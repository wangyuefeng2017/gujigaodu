# -*- coding: utf-8 -*-
"""基于 YOSO 全景语义图和建筑足迹的建筑高度估计。

关键改动
---------
* 默认关闭 20 m 距离筛选；``--max-distance`` 只有显式传值时才启用。
* 直接保留 YOSO 的彩色建筑语义图，不再读取或生成二值建筑掩膜。
* 用足迹投影射线为每个全景列分配最近建筑实例，再在该实例的建筑像素
  内提取屋顶/底边。相邻建筑的同色语义区域不会被合并成一个屋顶。
* 如果提供 16 位 ``*_instance.png``/``*_panoptic.png``，优先用其真实
  实例 ID；只有 JPG 语义图时，明确使用“足迹几何实例分配”作为回退。

Excel 字段 ``bldheight``、``height`` 和可视化文件名保持旧程序不变。
"""

import argparse
import json
import math
import os
import re

import cv2
import numpy as np
import pandas as pd
from openpyxl import load_workbook

import project_pano as p2pano

try:
    from scipy.interpolate import PchipInterpolator
except ImportError:  # pragma: no cover - the fallback is tested too
    PchipInterpolator = None


# None means disabled. Kept as a named constant for old callers/imports.
MAX_OBSERVATION_DISTANCE_M = None
MIN_BUILDING_HEIGHT_M = 5.0
MAX_BUILDING_HEIGHT_M = 100.0
BOUNDARY_ERROR_PIXELS = 8
YOSO_BUILDING_RGB = np.array([70, 70, 70], dtype=np.int16)

# Common Cityscapes/YOSO palette colors. Nearest-color matching handles JPEG
# compression without treating a grayscale wall/road color as building.
_YOSO_PALETTE_RGB = np.array([
    [70, 70, 70], [70, 130, 180], [128, 64, 128], [107, 142, 35],
    [70, 70, 70], [102, 102, 156], [190, 153, 153], [152, 251, 152],
    [220, 20, 60], [255, 0, 0], [0, 0, 142], [0, 0, 70], [0, 60, 100],
    [0, 80, 100], [0, 0, 230], [119, 11, 32], [244, 35, 232],
    [153, 153, 153], [220, 220, 0],
], dtype=np.int16)


def _contiguous_runs(indices):
    if len(indices) == 0:
        return []
    return np.split(indices, np.where(np.diff(indices) > 1)[0] + 1)


def _correct_bottom_boundary(raw_bottom, valid_columns, image_height, neighborhood=21):
    """Only interpolate within one selected instance; never across an owner gap."""
    corrected = raw_bottom.astype(float).copy()
    valid_indices = np.flatnonzero(valid_columns)
    if len(valid_indices) == 0:
        return corrected
    neighborhood = max(5, int(neighborhood) | 1)
    stride = max(2, neighborhood // 2)
    for run in _contiguous_runs(valid_indices):
        if len(run) < 3:
            continue
        start, stop = int(run[0]), int(run[-1]) + 1
        anchor_x, anchor_y = [], []
        for left in range(start, stop, stride):
            right = min(stop, left + neighborhood)
            xs = np.arange(left, right)
            xs = xs[valid_columns[xs]]
            if len(xs):
                x = int(xs[np.argmax(raw_bottom[xs])])
                anchor_x.append(x)
                anchor_y.append(float(raw_bottom[x]))
        anchor_x += [start, stop - 1]
        anchor_y += [float(raw_bottom[start]), float(raw_bottom[stop - 1])]
        anchors = {}
        for x, y in zip(anchor_x, anchor_y):
            anchors[x] = max(y, anchors.get(x, -np.inf))
        ax = np.array(sorted(anchors), dtype=float)
        ay = np.array([anchors[int(x)] for x in ax], dtype=float)
        tx = run.astype(float)
        if len(ax) >= 3 and PchipInterpolator is not None:
            values = PchipInterpolator(ax, ay, extrapolate=False)(tx)
        else:
            values = np.interp(tx, ax, ay)
        values = np.nan_to_num(values, nan=raw_bottom[run].astype(float))
        corrected[run] = np.clip(np.maximum(values, raw_bottom[run]), 0, image_height - 1)
    return corrected


def _sample_boundary(boundary, u, radius=1):
    """Robust subpixel sample, restricted to the selected instance array."""
    if boundary is None or len(boundary) == 0 or not np.isfinite(u):
        return None
    center = int(round(u)) % len(boundary)
    values = []
    for offset in range(-radius, radius + 1):
        value = float(boundary[(center + offset) % len(boundary)])
        if value > 0:
            values.append(value)
    return float(np.median(values)) if values else None


def _weighted_median(values, weights):
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if len(values) == 0:
        return 0.0
    if len(values) != len(weights) or np.any(weights < 0) or not np.any(weights > 0):
        return float(np.median(values))
    order = np.argsort(values)
    sv, sw = values[order], weights[order]
    pos = int(np.searchsorted(np.cumsum(sw), 0.5 * float(np.sum(sw)), side="left"))
    return float(sv[min(pos, len(sv) - 1)])


def fuse_multiview_results(result_sets):
    pooled = {}
    for result in result_sets:
        for index, values in result.items():
            pooled.setdefault(index, []).extend(
                float(value) for value in values.get("height", []) if np.isfinite(value)
            )
    fused = {index: float(np.median(values)) for index, values in pooled.items() if values}
    for result in result_sets:
        for index, values in result.items():
            if values.get("height") and index in fused:
                values["bldheight"] = fused[index]
    return fused


def append_nested_dict_to_excel(file_path, sheet_name, nested_dict):
    rows = []
    for key, value in nested_dict.items():
        row = {"Index": key}
        row.update(value)
        rows.append(row)
    df_new = pd.DataFrame(rows).set_index("Index")
    os.makedirs(os.path.dirname(os.path.abspath(file_path)), exist_ok=True)
    if not os.path.exists(file_path):
        with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
            df_new.to_excel(writer, sheet_name=sheet_name, index=True)
        return
    book = load_workbook(file_path)
    if sheet_name in book.sheetnames:
        df_old = pd.read_excel(file_path, sheet_name=sheet_name, index_col=0)
        # Keep the original output columns but update the same building rows.
        df_combined = df_old.copy()
        for column in df_new.columns:
            df_combined[column] = df_new[column]
        df_combined = df_combined.combine_first(df_new)
    else:
        df_combined = df_new
    with pd.ExcelWriter(file_path, engine="openpyxl") as writer:
        df_combined.to_excel(writer, sheet_name=sheet_name, index=True)


def _read_yoso_rgb(segmentation_path, target_size=None):
    image_bgr = cv2.imread(segmentation_path, cv2.IMREAD_COLOR)
    if image_bgr is None:
        raise FileNotFoundError(f"无法读取 YOSO 全景分割图：{segmentation_path}")
    if target_size is not None:
        width, height = target_size
        if image_bgr.shape[:2] != (height, width):
            image_bgr = cv2.resize(image_bgr, (width, height), interpolation=cv2.INTER_NEAREST)
    return cv2.cvtColor(image_bgr, cv2.COLOR_BGR2RGB)


def yoso_building_mask(segmentation_path, target_size=None):
    """读取 YOSO 彩色语义图；输出的是语义类别，不是二值掩膜文件。"""
    rgb = _read_yoso_rgb(segmentation_path, target_size)
    # int16 multiplication overflows at 255^2 and can silently turn building
    # pixels into another class. Use int32 for the nearest-color distance.
    pixels = rgb.astype(np.int32).reshape(-1, 3)
    palette = _YOSO_PALETTE_RGB.astype(np.int32)
    distances = ((pixels[:, None, :] - palette[None, :, :]) ** 2).sum(axis=2)
    nearest = np.argmin(distances, axis=1)
    building = (nearest == 0) & (distances[np.arange(len(pixels)), nearest] <= 55 ** 2)
    return rgb, building.reshape(rgb.shape[:2])


def _read_instance_raster(instance_path, target_size=None):
    """Read an optional integer PNG. JPG semantic maps are deliberately rejected."""
    if not instance_path or not os.path.exists(instance_path):
        return None
    if os.path.splitext(instance_path)[1].lower() in (".jpg", ".jpeg"):
        raise ValueError("实例图必须是 PNG/NPY 等整数标签图，不能把 YOSO JPG 当作实例 ID")
    image = cv2.imread(instance_path, cv2.IMREAD_UNCHANGED)
    if image is None:
        raise ValueError(f"无法读取实例标签图：{instance_path}")
    if image.ndim == 3:
        # RGB 24-bit panoptic IDs are common; preserve all three bytes.
        image = (image[:, :, 0].astype(np.int64)
                 + (image[:, :, 1].astype(np.int64) << 8)
                 + (image[:, :, 2].astype(np.int64) << 16))
    if image.dtype.kind not in "ui":
        raise ValueError("实例标签图必须是无符号/有符号整数类型")
    if target_size is not None:
        width, height = target_size
        if image.shape[:2] != (height, width):
            image = cv2.resize(image, (width, height), interpolation=cv2.INTER_NEAREST)
    return image.astype(np.int64)


def find_instance_raster(segmentation_path, instance_dir=None):
    """Find a sidecar true-instance PNG without confusing the semantic JPG."""
    folder = instance_dir or os.path.dirname(segmentation_path)
    stem = os.path.splitext(os.path.basename(segmentation_path))[0]
    stems = [stem, stem.replace("svg_", ""), stem.replace("svg_", "instance_"),
             stem.replace("svg_", "panoptic_")]
    candidates = []
    for name in stems:
        for suffix in ("_instance.png", "_panoptic.png", ".instance.png", ".panoptic.png", ".png"):
            candidates.append(os.path.join(folder, name + suffix))
    for path in candidates:
        if os.path.isfile(path) and os.path.normcase(path) != os.path.normcase(segmentation_path):
            return path
    return None


def _instance_for_footprint(instance_labels, semantic, owner_columns, building_id):
    if instance_labels is None:
        return None
    columns = np.flatnonzero(owner_columns == str(building_id))
    if len(columns) == 0:
        return None
    labels = instance_labels[:, columns][semantic[:, columns]]
    labels = labels[(labels > 0) & np.isfinite(labels)]
    if len(labels) == 0:
        return None
    values, counts = np.unique(labels, return_counts=True)
    return int(values[np.argmax(counts)])


def build_instance_boundaries(segmentation_path, target_size, building_ids,
                              owner_columns, instance_labels=None):
    """Extract top/bottom arrays separately for every selected footprint ID."""
    _rgb, semantic = yoso_building_mask(segmentation_path, target_size)
    height, width = semantic.shape
    boundary_by_id = {}
    visual = cv2.cvtColor(_rgb, cv2.COLOR_RGB2BGR)
    for building_id in building_ids:
        building_id = str(building_id)
        selected_instance = _instance_for_footprint(
            instance_labels, semantic, owner_columns, building_id
        )
        if selected_instance is not None:
            selected = semantic & (instance_labels == selected_instance)
        else:
            # Geometric instance fallback: the column belongs only to the
            # nearest footprint hit, never to all gray pixels globally.
            selected = semantic & (owner_columns[None, :] == building_id)
        raw_top = np.zeros(width, dtype=int)
        raw_bottom = np.zeros(width, dtype=int)
        valid = np.zeros(width, dtype=bool)
        for u in np.flatnonzero(np.any(selected, axis=0)):
            ys = np.flatnonzero(selected[:, u])
            if len(ys) == 0:
                continue
            # If compression/occlusion creates multiple runs, use the run with
            # the lowest visible base; this is the surface hit by the footprint ray.
            runs = _contiguous_runs(ys)
            run = max(runs, key=lambda item: (int(item[-1]) - int(item[0]) + 1, int(item[-1])))
            raw_top[u] = int(run[0])
            raw_bottom[u] = int(run[-1])
            valid[u] = True
        corrected = _correct_bottom_boundary(
            raw_bottom, valid, height, neighborhood=max(9, int(round(width * 0.01)) | 1)
        )
        boundary_by_id[building_id] = {
            "top": raw_top,
            "bottom": np.rint(corrected).astype(int),
            "valid": valid,
            "instance_id": selected_instance,
        }
        for u in np.flatnonzero(valid):
            cv2.circle(visual, (int(u), int(raw_top[u])), 1, (0, 0, 255), -1)
            cv2.circle(visual, (int(u), int(corrected[u])), 1, (255, 0, 0), -1)
    return boundary_by_id, visual


def getbldbound(mask_path, target_size=None):
    """Compatibility API: returns the global YOSO semantic boundary.

    New batch processing calls ``build_instance_boundaries`` instead, so this
    function never creates/reads ``building_mask_*.jpg``.
    """
    _rgb, semantic = yoso_building_mask(mask_path, target_size)
    height, width = semantic.shape
    top = np.zeros((width, 2), dtype=int)
    bottom = np.zeros((width, 2), dtype=int)
    raw_bottom = np.zeros(width, dtype=int)
    valid = np.any(semantic, axis=0)
    for u in np.flatnonzero(valid):
        ys = np.flatnonzero(semantic[:, u])
        top[u] = (u, int(ys[0]))
        raw_bottom[u] = int(ys[-1])
        bottom[u, 0] = u
    bottom[:, 1] = np.rint(_correct_bottom_boundary(raw_bottom, valid, height)).astype(int)
    bottom[~valid, 1] = 0
    vis = cv2.cvtColor(_rgb, cv2.COLOR_RGB2BGR)
    for u in np.flatnonzero(valid):
        vis[top[u, 1], u] = (0, 0, 255)
        vis[bottom[u, 1], u] = (255, 0, 0)
    return top, bottom, vis


def iterheight(pano_image_path, points_geo, camera_geo, pano_size,
               north_rotation, camera_bearing, footheight,
               top_boundary_points, bottom_boundary_points,
               optimal=None, owner_columns=None, output_dir=None,
               max_observation_distance=None):
    """Estimate heights from per-instance roof/base boundaries.

    The old positional parameters and returned dictionary are unchanged.
    ``max_observation_distance`` is intentionally ``None`` by default.
    """
    pano_img = cv2.imread(pano_image_path)
    if pano_img is None:
        print("无法加载全景图像：", pano_image_path)
        return {}
    pano_height, pano_width = pano_size
    if pano_img.shape[:2] != (pano_height, pano_width):
        pano_height, pano_width = pano_img.shape[:2]
    camera_x, camera_y, _ = p2pano.geo_to_utm(*camera_geo)
    result = {}
    for index in points_geo.keys():
        index = str(index)
        if isinstance(top_boundary_points, dict):
            bounds = top_boundary_points.get(index)
            top_array = bounds["top"] if bounds else None
            bottom_array = bounds["bottom"] if bounds else None
            valid_array = bounds["valid"] if bounds else None
        else:
            top_array = np.asarray(top_boundary_points)[:, 1]
            bottom_array = np.asarray(bottom_boundary_points)[:, 1]
            valid_array = top_array > 0
        heights, weights = [], []
        for point in points_geo[index]:
            x, y, _ = p2pano.geo_to_utm(point[0], point[1], footheight)
            dx, dy = x - camera_x, y - camera_y
            distance = math.hypot(dx, dy)
            if (not np.isfinite(distance) or distance <= 0.0
                    or (max_observation_distance is not None
                        and distance > float(max_observation_distance))):
                continue
            u, _ = p2pano.project_to_pano_float(
                dx, dy, 0.0, pano_width, pano_height, north_rotation, camera_bearing
            )
            if owner_columns is not None:
                owner_values = [owner_columns[(int(round(u)) + offset) % pano_width]
                                for offset in (-1, 0, 1)]
                if not any(str(value) == index for value in owner_values):
                    continue
            if top_array is None or bottom_array is None:
                continue
            top_v = _sample_boundary(top_array, u)
            bottom_v = _sample_boundary(bottom_array, u)
            if top_v is None or bottom_v is None or bottom_v <= top_v:
                continue
            if valid_array is not None and not np.any([
                    bool(valid_array[(int(round(u)) + offset) % pano_width])
                    for offset in (-1, 0, 1)]):
                continue
            if top_v <= BOUNDARY_ERROR_PIXELS or bottom_v >= pano_height - BOUNDARY_ERROR_PIXELS:
                continue
            theta_top = math.pi * (0.5 - top_v / float(pano_height))
            theta_bottom = math.pi * (0.5 - bottom_v / float(pano_height))
            if abs(math.cos(theta_top)) < 1e-6 or abs(math.cos(theta_bottom)) < 1e-6:
                continue
            candidate = distance * (math.tan(theta_top) - math.tan(theta_bottom))
            if not np.isfinite(candidate) or candidate < MIN_BUILDING_HEIGHT_M \
                    or candidate > MAX_BUILDING_HEIGHT_M:
                continue
            heights.append(float(candidate))
            error_m = distance * math.tan(
                BOUNDARY_ERROR_PIXELS * math.pi / float(pano_height)
            )
            weights.append(1.0 / max(error_m, 0.05))
            ui = int(round(u)) % pano_width
            cv2.circle(pano_img, (ui, int(round(bottom_v))), 5, (0, 0, 255), -1)
            cv2.circle(pano_img, (ui, int(round(top_v))), 5, (255, 0, 0), -1)
            cv2.line(pano_img, (ui, int(round(bottom_v))),
                     (ui, int(round(top_v))), (255, 0, 0), 3)
        result[index] = {
            "bldheight": _weighted_median(heights, weights) if heights else 0,
            "height": heights,
        }
    image_dir = os.path.join(output_dir or os.getcwd(), "image")
    os.makedirs(image_dir, exist_ok=True)
    base_name = os.path.splitext(os.path.basename(pano_image_path))[0]
    out_vis = os.path.join(image_dir, f"marked_iterheight_{base_name}.jpg")
    cv2.imwrite(out_vis, pano_img)
    print("✔ 已保存可视化图片：", out_vis)
    return result


def read_files_from_folders(base_folder, pano_id=None):
    """Match raw, rectified panorama and YOSO semantic ``svg_*.jpg`` files."""
    raw_dir = os.path.join(base_folder, "rawdata")
    rect_dir = os.path.join(base_folder, "rectdata")
    svg_dir = os.path.join(base_folder, "svgdata")
    raw_files = sorted(os.listdir(raw_dir)) if os.path.isdir(raw_dir) else []
    rect_files = set(os.listdir(rect_dir)) if os.path.isdir(rect_dir) else set()
    svg_files = set(os.listdir(svg_dir)) if os.path.isdir(svg_dir) else set()
    raw_out, rect_out, svg_out = [], [], []
    for raw_file in raw_files:
        stem, ext = os.path.splitext(raw_file)
        if pano_id is not None and _number_from_name(raw_file) != str(pano_id):
            continue
        rect_name = f"rectified_panorama_{stem}{ext}"
        svg_name = f"svg_{stem}{ext}"
        if rect_name not in rect_files or svg_name not in svg_files:
            continue
        raw_out.append(os.path.join(raw_dir, raw_file))
        rect_out.append(os.path.join(rect_dir, rect_name))
        svg_out.append(os.path.join(svg_dir, svg_name))
        print("Raw Data File:", raw_out[-1])
        print("Rect Data File:", rect_out[-1])
        print("YOSO Semantic File:", svg_out[-1])
        print("-" * 40)
    return raw_out, rect_out, svg_out


def load_metadata_jsons(json_folder):
    meta = {}
    if not os.path.isdir(json_folder):
        print("⚠ metadata 目录不存在：", json_folder)
        return meta
    for filename in sorted(os.listdir(json_folder)):
        if not filename.endswith(".metadata.json"):
            continue
        match = re.search(r"(\d+)(?=\.metadata\.json$)", filename)
        if not match:
            continue
        with open(os.path.join(json_folder, filename), "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if "lat" not in data or "lng" not in data:
            continue
        meta[match.group(1)] = {
            "lat": data["lat"], "lng": data["lng"],
            "elevation": data.get("elevation", 1.7),
            "rotation": data.get("rotation", 0.0),
        }
    print("✔ 已读取 metadata 数量：", len(meta))
    return meta


def _number_from_name(path):
    match = re.search(r"(\d+)(?=\.[^.]+$)", os.path.basename(path))
    return match.group(1) if match else ""


def run_batch(base_folder, osmfile, instance_dir=None, output_dir=None,
              pano_id=None, max_distance=None):
    output_dir = output_dir or base_folder
    meta = load_metadata_jsons(os.path.join(base_folder, "360json"))
    _raw, rect_files, semantic_files = read_files_from_folders(base_folder, pano_id=pano_id)
    pending = []
    for rect_path, semantic_path in zip(rect_files, semantic_files):
        number = _number_from_name(rect_path)
        if pano_id is not None and str(number) != str(pano_id):
            continue
        if number not in meta:
            print("❌ metadata 中找不到编号：", number, os.path.basename(rect_path))
            continue
        pano = cv2.imread(rect_path)
        if pano is None:
            print("❌ 无法读取 rect 图像：", rect_path)
            continue
        height, width = pano.shape[:2]
        cam = meta[number]
        camera_geo = [cam["lng"], cam["lat"], 2.5]
        north_rotation = cam["rotation"]
        camera_bearing = 180.0 - north_rotation
        # None is intentional: no 20 m rejection.
        points_geo = p2pano.select_footprint(
            osmfile, camera_geo, max_distance=max_distance
        )[1]
        owner_columns, owner_distance = p2pano.project_building_owner_columns(
            osmfile, camera_geo, width, north_rotation
        )
        instance_path = find_instance_raster(semantic_path, instance_dir)
        instance_labels = _read_instance_raster(instance_path, (width, height)) \
            if instance_path else None
        if instance_path:
            print("✓ 使用 YOSO/全景实例标签：", instance_path)
        else:
            print("ℹ 未发现实例 PNG：使用建筑足迹进行几何实例分配")
        building_ids = list(points_geo.keys())
        boundaries, _boundary_vis = build_instance_boundaries(
            semantic_path, (width, height), building_ids,
            owner_columns, instance_labels=instance_labels
        )
        result = iterheight(
            rect_path, points_geo, camera_geo, (height, width),
            north_rotation, camera_bearing, 0,
            boundaries, boundaries, optimal=None,
            owner_columns=owner_columns, output_dir=output_dir,
            max_observation_distance=max_distance,
        )
        if result:
            output_name = f"bldheightset21_{os.path.splitext(os.path.basename(rect_path))[0]}.xlsx"
            pending.append((os.path.join(output_dir, output_name), os.path.basename(rect_path), result))
    fuse_multiview_results([item[2] for item in pending])
    for excel_path, filename, result in pending:
        append_nested_dict_to_excel(excel_path, "Sheet1", result)
        print("✔ 已保存高度结果：", excel_path)
    return pending


def main():
    parser = argparse.ArgumentParser(description="YOSO 语义图 + 足迹实例化建筑高度估计")
    parser.add_argument("--base-folder", default=r"F:/gsvosmd/gsi/area4")
    parser.add_argument("--osm-file", default=r"F:\1数据整理\图 3 建筑轮廓平面校正与配准精度评估\纠正后的footprint\paris_area2bldt.shp")
    parser.add_argument("--instance-dir", default=None,
                        help="可选真实实例 PNG 目录；不提供则按足迹投影分配")
    parser.add_argument("--output-dir", default=None,
                        help="结果目录；默认写回 base-folder（字段和文件名不变）")
    parser.add_argument("--pano-id", default=None, help="只处理一个编号，例如 396")
    parser.add_argument("--max-distance", type=float, default=None,
                        help="仅显式设置时启用距离筛选；默认关闭 20 m 筛选")
    args = parser.parse_args()
    run_batch(args.base_folder, args.osm_file, args.instance_dir,
              args.output_dir, args.pano_id, args.max_distance)


if __name__ == "__main__":
    main()
