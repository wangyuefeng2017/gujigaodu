# -*- coding: utf-8 -*-
"""
Main6 - 从全景图 + 建筑掩膜估计建筑高度

修改要点：
1）使用 svgdata 下的 building_mask_Street View XX.jpg 作为二值建筑掩膜
2）在本文件内实现 getbldbound()，从二值掩膜提取建筑顶部/底部边界
3）iterheight() 中：
    - 相机高度固定为 2.5 m
    - 底部点吸附到底部边界（红点）
    - 顶部搜索到达顶部边界（蓝点）
4）按输入文件名保存可视化结果，不再覆盖
"""

import cv2
import numpy as np
import project_pano as p2pano
import pandas as pd
from openpyxl import load_workbook
import os
import json
import math

try:
    # PCHIP 是保持形状的分段三次插值，可避免普通三次样条在建筑间隙处振荡。
    from scipy.interpolate import PchipInterpolator
except ImportError:
    PchipInterpolator = None


MAX_OBSERVATION_DISTANCE_M = 20.0
MIN_BUILDING_HEIGHT_M = 5.0
MAX_BUILDING_HEIGHT_M = 100.0
BOUNDARY_ERROR_PIXELS = 8


def _contiguous_runs(indices):
    """Split sorted integer indices into contiguous runs."""
    if len(indices) == 0:
        return []
    split_at = np.where(np.diff(indices) > 1)[0] + 1
    return np.split(indices, split_at)


def _correct_bottom_boundary(raw_bottom, valid_columns, image_height,
                             neighborhood=21):
    """
    按论文式 (9)-(10) 从局部最低点构建底边锚点并作分段三次插值。

    插值只在连续建筑区间内进行，避免跨越天空/街巷空隙连接不同建筑。
    """
    corrected = raw_bottom.astype(float).copy()
    valid_indices = np.flatnonzero(valid_columns)
    if len(valid_indices) == 0:
        return corrected

    neighborhood = max(5, int(neighborhood) | 1)
    stride = max(2, neighborhood // 2)

    for run in _contiguous_runs(valid_indices):
        if len(run) < 3:
            continue

        anchor_x = []
        anchor_y = []
        start = int(run[0])
        stop = int(run[-1]) + 1
        for left in range(start, stop, stride):
            right = min(stop, left + neighborhood)
            window_x = np.arange(left, right)
            window_x = window_x[valid_columns[window_x]]
            if len(window_x) == 0:
                continue
            # 取局部最大行号，即图像中最低的可靠地面接触点。
            local_y = raw_bottom[window_x]
            anchor_pos = int(np.argmax(local_y))
            anchor_x.append(int(window_x[anchor_pos]))
            anchor_y.append(float(local_y[anchor_pos]))

        if not anchor_x:
            continue
        # 保证区间端点被约束，且去除重复锚点。
        anchor_x.extend([start, stop - 1])
        anchor_y.extend([float(raw_bottom[start]), float(raw_bottom[stop - 1])])
        anchor_map = {}
        for x, y in zip(anchor_x, anchor_y):
            anchor_map[x] = max(y, anchor_map.get(x, -np.inf))
        anchor_x = np.array(sorted(anchor_map), dtype=float)
        anchor_y = np.array([anchor_map[int(x)] for x in anchor_x], dtype=float)

        target_x = run.astype(float)
        if len(anchor_x) >= 3 and PchipInterpolator is not None:
            values = PchipInterpolator(anchor_x, anchor_y, extrapolate=False)(target_x)
        else:
            values = np.interp(target_x, anchor_x, anchor_y)

        # 拒绝数值振荡和越界；同时保持校正只向图像下方移动。
        values = np.nan_to_num(values, nan=raw_bottom[run].astype(float))
        values = np.maximum(values, raw_bottom[run])
        corrected[run] = np.clip(values, 0, image_height - 1)

    return corrected


def _sample_boundary(boundary_points, u, radius=2):
    """At a sub-pixel column, return a local robust boundary row or None."""
    width = len(boundary_points)
    if width == 0 or not np.isfinite(u):
        return None
    center = int(round(u)) % width
    columns = [(center + offset) % width for offset in range(-radius, radius + 1)]
    values = [float(boundary_points[column][1]) for column in columns
              if boundary_points[column][1] > 0]
    if not values:
        return None
    return float(np.median(values))


def _weighted_median(values, weights):
    """Robust median extended with inverse-uncertainty observation weights."""
    values = np.asarray(values, dtype=float)
    weights = np.asarray(weights, dtype=float)
    if len(values) == 0:
        return 0.0
    if len(values) != len(weights) or np.any(weights < 0) or not np.any(weights > 0):
        return float(np.median(values))
    order = np.argsort(values)
    sorted_values = values[order]
    sorted_weights = weights[order]
    cutoff = 0.5 * float(np.sum(sorted_weights))
    position = int(np.searchsorted(np.cumsum(sorted_weights), cutoff, side="left"))
    return float(sorted_values[min(position, len(sorted_values) - 1)])


def fuse_multiview_results(result_sets):
    """
    按论文式 (11) 汇集所有全景站点的有效角点候选，并回填最终建筑高度。

    每个结果仍只保留原有 ``bldheight`` 和 ``height`` 字段；未在某张图中形成
    候选值的建筑继续保持 0，避免改变原输出语义。
    """
    pooled = {}
    for result in result_sets:
        for index, values in result.items():
            candidates = [
                float(value) for value in values.get('height', []) if np.isfinite(value)
            ]
            pooled.setdefault(index, []).extend(candidates)

    fused = {
        index: float(np.median(candidates))
        for index, candidates in pooled.items() if candidates
    }
    for result in result_sets:
        for index, values in result.items():
            if values.get('height') and index in fused:
                values['bldheight'] = fused[index]
    return fused


# ==============================
# 1. Excel 结果追加函数
# ==============================
def append_nested_dict_to_excel(file_path, sheet_name, nested_dict):
    """
    将嵌套字典追加/写入到 Excel：
    nested_dict 结构类似：
        {
            idx1: {'bldheight': 12.3, 'height': [xx, xx, ...]},
            idx2: {...}
        }
    """
    # 将嵌套字典转换为 DataFrame
    rows = []
    for key, value in nested_dict.items():
        row = {'Index': key}
        row.update(value)
        rows.append(row)

    df_new = pd.DataFrame(rows)
    df_new = df_new.set_index('Index')

    # 检查文件是否存在
    if not os.path.exists(file_path):
        # 如果文件不存在，则创建新的 Excel 文件并写入数据
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df_new.to_excel(writer, sheet_name=sheet_name, index=True)
    else:
        # 如果文件存在，则加载 Excel 文件
        book = load_workbook(file_path)
        if sheet_name in book.sheetnames:
            # 读取现有的表格
            df_existing = pd.read_excel(file_path, sheet_name=sheet_name, index_col=0)
            # 合并现有数据和新数据（按列拼接）
            df_combined = pd.concat([df_existing, df_new], axis=1)
        else:
            df_combined = df_new

        # 写回 Excel 文件（覆盖原文件）
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df_combined.to_excel(writer, sheet_name=sheet_name, index=True)


# ==============================
# 2. 从二值建筑掩膜提取上下边界
# ==============================
def getbldbound(mask_path, target_size=None):
    """
    输入：
        mask_path : 二值建筑掩膜图路径（白=建筑，黑=非建筑）
    输出：
        top_boundary_points[u]    = [u, v_top]
        bottom_boundary_points[u] = [u, v_bottom]
        vis_img                   = 可视化图像（顶部红点，底部蓝点）
    """
    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise FileNotFoundError(f"无法读取建筑 mask：{mask_path}")

    if target_size is not None:
        target_width, target_height = target_size
        if mask.shape != (target_height, target_width):
            mask = cv2.resize(
                mask, (target_width, target_height), interpolation=cv2.INTER_NEAREST
            )

    # JPEG 二值掩膜会在黑色背景中产生低灰度压缩噪声，Otsu 阈值比 >0 稳定。
    _, mask_binary = cv2.threshold(
        mask, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )

    # 开运算去除孤立噪声，闭运算连接边界小缺口（论文 Fig. 1 的形态学闭运算）。
    kernel = np.ones((3, 3), np.uint8)
    mask_clean = cv2.morphologyEx(mask_binary, cv2.MORPH_OPEN, kernel)
    mask_clean = cv2.morphologyEx(mask_clean, cv2.MORPH_CLOSE, kernel)

    h, w = mask_clean.shape

    # 移除很小的压缩/分割碎片，保留所有有意义的建筑连通域。
    component_count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask_clean, connectivity=8
    )
    min_component_area = max(32, int(round(h * w * 0.00005)))
    filtered = np.zeros_like(mask_clean)
    for label in range(1, component_count):
        if stats[label, cv2.CC_STAT_AREA] >= min_component_area:
            filtered[labels == label] = 255
    mask_clean = filtered

    top_boundary_points = np.zeros((w, 2), dtype=int)
    bottom_boundary_points = np.zeros((w, 2), dtype=int)

    raw_top = np.zeros(w, dtype=int)
    raw_bottom = np.zeros(w, dtype=int)
    valid_columns = np.zeros(w, dtype=bool)

    for u in range(w):
        column = mask_clean[:, u]
        ys = np.where(column > 0)[0]   # 建筑像素的位置

        if len(ys) > 0:
            valid_columns[u] = True
            raw_top[u] = int(ys[0])       # 最上面的建筑像素
            raw_bottom[u] = int(ys[-1])   # 初始底边

    neighborhood = max(9, int(round(w * 0.01)) | 1)
    corrected_bottom = _correct_bottom_boundary(
        raw_bottom, valid_columns, h, neighborhood=neighborhood
    )

    top_boundary_points[:, 0] = np.arange(w)
    bottom_boundary_points[:, 0] = np.arange(w)
    top_boundary_points[:, 1] = raw_top
    bottom_boundary_points[:, 1] = np.rint(corrected_bottom).astype(int)
    bottom_boundary_points[~valid_columns, 1] = 0

    # 可视化检查图：顶部红，底部蓝
    vis_img = cv2.cvtColor(mask_clean, cv2.COLOR_GRAY2BGR)
    for u in range(w):
        vt = top_boundary_points[u][1]
        vb = bottom_boundary_points[u][1]
        if vt > 0:
            vis_img[vt, u] = (0, 0, 255)   # red
        if vb > 0:
            vis_img[vb, u] = (255, 0, 0)   # blue

    return top_boundary_points, bottom_boundary_points, vis_img


# ==============================
# 3. 高度迭代函数
# ==============================
def iterheight(pano_image_path, points_geo, camera_geo, pano_size,
               north_rotation, camera_bearing, footheight,
               top_boundary_points, bottom_boundary_points,
               optimal=None):
    """
    根据论文式 (5)-(7) 由同一列的屋顶/底边仰角差闭式反演高度。

    保留原函数名、参数和返回结构，以避免改变调用端及 Excel 输出内容。
    """
    # 加载全景图像
    pano_img = cv2.imread(pano_image_path)
    if pano_img is None:
        print("无法加载全景图像：", pano_image_path)
        return {}

    pano_height, pano_width = pano_size
    if pano_img.shape[:2] != (pano_height, pano_width):
        pano_height, pano_width = pano_img.shape[:2]
    camera_x, camera_y, _camera_z = p2pano.geo_to_utm(*camera_geo)

    if len(top_boundary_points) != pano_width or len(bottom_boundary_points) != pano_width:
        raise ValueError("建筑边界宽度与全景图宽度不一致")

    bldheightset = {}
    for index in points_geo.keys():
        height = []
        reliability_weights = []

        for point in points_geo[index]:
            point_base = [point[0], point[1], footheight]
            x, y, _z = p2pano.geo_to_utm(*point_base)
            x_relative = x - camera_x
            y_relative = y - camera_y
            horizontal_distance = math.hypot(x_relative, y_relative)

            # 论文在 1024 像素高、边界误差约 8 像素时采用 20 m 阈值。
            if (not np.isfinite(horizontal_distance)
                    or horizontal_distance <= 0.0
                    or horizontal_distance > MAX_OBSERVATION_DISTANCE_M):
                continue

            # 垂直建筑边在整列上具有相同 u，仅需投影一次平面角点。
            u, _ = p2pano.project_to_pano_float(
                x_relative, y_relative, 0.0,
                pano_width, pano_height,
                north_rotation, camera_bearing
            )
            top_v = _sample_boundary(top_boundary_points, u)
            bottom_v = _sample_boundary(bottom_boundary_points, u)
            if top_v is None or bottom_v is None or bottom_v <= top_v:
                continue

            # 靠近天顶/天底时 tan(theta) 条件数急剧增大，按论文剔除。
            if (top_v <= BOUNDARY_ERROR_PIXELS
                    or bottom_v >= pano_height - BOUNDARY_ERROR_PIXELS):
                continue

            theta_top = math.pi * (0.5 - top_v / float(pano_height))
            theta_bottom = math.pi * (0.5 - bottom_v / float(pano_height))
            if abs(math.cos(theta_top)) < 1e-6 or abs(math.cos(theta_bottom)) < 1e-6:
                continue

            candidate_height = horizontal_distance * (
                math.tan(theta_top) - math.tan(theta_bottom)
            )
            if (not np.isfinite(candidate_height)
                    or candidate_height < MIN_BUILDING_HEIGHT_M
                    or candidate_height > MAX_BUILDING_HEIGHT_M):
                continue

            height.append(float(candidate_height))
            predicted_boundary_error = horizontal_distance * math.tan(
                BOUNDARY_ERROR_PIXELS * math.pi / float(pano_height)
            )
            reliability_weights.append(1.0 / max(predicted_boundary_error, 0.05))

            # 可视化内容保持原样：底部红点、顶部蓝点和蓝色连线。
            u_idx = int(round(u)) % pano_width
            top_y = int(round(top_v))
            bottom_y = int(round(bottom_v))
            cv2.circle(pano_img, (u_idx, bottom_y), 5, (0, 0, 255), -1)
            cv2.circle(pano_img, (u_idx, top_y), 5, (255, 0, 0), -1)
            cv2.line(pano_img, (u_idx, bottom_y), (u_idx, top_y), (255, 0, 0), 3)

        # 论文式 (11) 的中位数融合，并按论文误差传播关系 Δh∝D 对候选值
        # 进行逆不确定度加权；返回字段仍保持 bldheight / height 不变。
        bldheight = _weighted_median(height, reliability_weights) if height else 0
        bldheightset[index] = {'bldheight': bldheight, 'height': height}

    # 保存可视化图像（根据输入全景图文件名生成）
    os.makedirs("image", exist_ok=True)
    base_name = os.path.splitext(os.path.basename(pano_image_path))[0]
    out_vis = os.path.join("image", f"marked_iterheight_{base_name}.jpg")
    cv2.imwrite(out_vis, pano_img)
    print("✔ 已保存可视化图片：", out_vis)

    return bldheightset


# ==============================
# 4. 批量匹配 raw / rect / mask
# ==============================
def read_files_from_folders(base_folder):
    """
    在 base_folder 下自动匹配：
        rawdata/Street View XX.jpg
        rectdata/rectified_panorama_Street View XX.jpg
        svgdata/building_mask_Street View XX.jpg
    返回三个等长列表
    """
    rawdata_folder = os.path.join(base_folder, 'rawdata')
    rectdata_folder = os.path.join(base_folder, 'rectdata')
    svgdata_folder = os.path.join(base_folder, 'svgdata')  # 存 building_mask_*.jpg

    rawdata_files = set(os.listdir(rawdata_folder))
    rectdata_files = set(os.listdir(rectdata_folder))
    svgdata_files = set(os.listdir(svgdata_folder))

    RawDataFile, RectDataFile, SVGDataFile = [], [], []

    # 固定遍历顺序，保证相同输入每次生成相同的处理/输出顺序。
    for raw_file in sorted(rawdata_files):
        base_name = os.path.splitext(raw_file)[0]  # Street View XX
        ext = os.path.splitext(raw_file)[1]        # .jpg

        rect_file = f"rectified_panorama_{base_name}{ext}"
        svg_file = f"building_mask_{base_name}{ext}"  # 注意这里用 building_mask

        if rect_file in rectdata_files and svg_file in svgdata_files:
            print(f"Raw Data File: {os.path.join(rawdata_folder, raw_file)}")
            print(f"Rect Data File: {os.path.join(rectdata_folder, rect_file)}")
            print(f"SVG/Mask Data File: {os.path.join(svgdata_folder, svg_file)}")
            print("-" * 40)
            RawDataFile.append(os.path.join(rawdata_folder, raw_file))
            RectDataFile.append(os.path.join(rectdata_folder, rect_file))
            SVGDataFile.append(os.path.join(svgdata_folder, svg_file))

    return RawDataFile, RectDataFile, SVGDataFile


# ==============================
# 5. 读取 metadata json
# ==============================
def load_metadata_jsons(json_folder):
    """
    自动读取 360json 目录下所有 *.metadata.json
    以图片编号（例如 19）为 key 存储：
        meta_dict["19"] = {lat, lng, elevation, rotation}
    """
    meta_dict = {}

    if not os.path.exists(json_folder):
        print("⚠ metadata 目录不存在：", json_folder)
        return meta_dict

    for file in os.listdir(json_folder):
        if file.endswith(".metadata.json"):
            num = ''.join(filter(str.isdigit, file))
            if not num:
                continue

            json_path = os.path.join(json_folder, file)
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            meta_dict[num] = {
                "lat": data["lat"],
                "lng": data["lng"],
                "elevation": data.get("elevation", 1.7),
                "rotation": data.get("rotation", 0.0)
            }

    print("✔ 已读取 metadata 数量：", len(meta_dict))
    return meta_dict


# ==============================
# 6. 主程序
# ==============================
if __name__ == "__main__":

    # ===== 1. 基础路径设置 =====
    basefolder = r"F:/gsvosmd/gsi/area4"
    json_folder = os.path.join(basefolder, "360json")
    osmfile = r"C:\Users\lyx\Desktop\boss\gsv3d2\gsv3d\osm - 副本 (5) - 副本\纠正后的footprint\paris_area2bldt.shp"
    #osmfile=r"F:\gsv3d\osm\parisosmarea\paris_area2bldt.shp"

    # ===== 2. 读取 metadata（相机坐标 & 朝向） =====
    meta_dict = load_metadata_jsons(json_folder)

    # ===== 3. 读取 raw / rect / mask 文件列表 =====
    RawDataFile, RectDataFile, SVGDataFile = read_files_from_folders(basefolder)

    # ===== 4. 批量处理每一张 rect 全景 =====
    pending_outputs = []
    for ind in range(len(RectDataFile)):

        rectd = RectDataFile[ind]
        maskd = SVGDataFile[ind]     # 这里实际上是 building_mask 路径

        rect_filename = os.path.basename(rectd)
        rect_name_no_ext = os.path.splitext(rect_filename)[0]

        # 从文件名中提取数字编号（例如 19）
        rect_num = ''.join(filter(str.isdigit, rect_filename))

        if not rect_num:
            print("⚠ 无法从文件名中提取编号，跳过：", rect_filename)
            continue

        # ===== 自动匹配对应的 metadata =====
        if rect_num not in meta_dict:
            print("❌ metadata 中找不到编号：", rect_num, " 文件：", rect_filename)
            continue

        cam = meta_dict[rect_num]

        # 固定相机高度为 2.5 m
        camera_geo = [cam["lng"], cam["lat"], 2.5]
        north_rotation = cam["rotation"]
        camera_bearing = 180 - north_rotation

        # 读取 rect 全景，获取尺寸
        pano_img = cv2.imread(rectd)
        if pano_img is None:
            print("❌ 无法读取 rect 图像：", rectd)
            continue

        pano_size = pano_img.shape[:2]  # (height, width)

        # 按论文 3.2.4 节执行遮挡射线和 20 m 距离筛选。
        points_geo = p2pano.select_footprint(
            osmfile, camera_geo, max_distance=MAX_OBSERVATION_DISTANCE_M
        )[1]

        # 读取建筑掩膜的顶部/底部边界
        top_boundary_points, bottom_boundary_points, boundary_image = getbldbound(
            maskd, target_size=(pano_size[1], pano_size[0])
        )

        # ===== 高度迭代估计 =====
        bldheightset = iterheight(
            rectd, points_geo, camera_geo, pano_size,
            north_rotation, camera_bearing,
            footheight=0,
            top_boundary_points=top_boundary_points,
            bottom_boundary_points=bottom_boundary_points,
            optimal=None
        )

        if not bldheightset:
            print("⚠ 没有得到高度结果，跳过保存：", rect_filename)
            continue

        # ===== 输出 Excel，高度结果按每张图单独一个文件 =====
        out_excel_name = f"bldheightset21_{rect_name_no_ext}.xlsx"
        out_excel_path = os.path.join(basefolder, out_excel_name)
        pending_outputs.append((out_excel_path, rect_filename, bldheightset))

    # ===== 5. 汇集所有站点候选后，再保持原文件名/字段写出结果 =====
    fuse_multiview_results([item[2] for item in pending_outputs])
    for out_excel_path, rect_filename, bldheightset in pending_outputs:
        append_nested_dict_to_excel(out_excel_path, "Sheet1", bldheightset)
        print("✔ 已保存高度结果：", out_excel_path)
