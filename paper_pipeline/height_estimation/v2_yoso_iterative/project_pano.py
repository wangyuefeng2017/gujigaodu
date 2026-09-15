# -*- coding: utf-8 -*-
"""全景投影、足迹可见性和按投影列分配建筑实例。

这个模块不读取二值建筑掩膜。``select_footprint`` 仍保持旧版的返回结构，
同时 ``project_building_owner_columns`` 用建筑足迹在相机射线上的第一交点，
为每个全景列分配一个建筑 ID。这样相邻建筑虽然在 YOSO 语义图中都是同一
种灰色，也不会再把整张建筑区域当作一个建筑来提屋顶。
"""

import math
import os
import warnings
from functools import lru_cache

import cv2
import geopandas as gpd
import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import LineString, Point

warnings.filterwarnings("ignore", category=FutureWarning, module="pyproj")

try:
    import fiona.path  # noqa: F401
except (ImportError, AttributeError):
    pass


def _polygon_parts(geometry):
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        yield geometry
    elif geometry.geom_type == "MultiPolygon":
        yield from geometry.geoms


def _metric_crs_for_camera(lon, lat):
    zone = max(1, min(60, int((float(lon) + 180.0) // 6.0) + 1))
    epsg = (32600 if float(lat) >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


@lru_cache(maxsize=8)
def _utm_transformer(epsg):
    return Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(epsg), always_xy=True)


def _read_buildings(shp_file_path, camera_geo):
    """Read building polygons once and convert them to a local metric CRS."""
    data = gpd.read_file(shp_file_path)
    if "building" in data.columns:
        values = data["building"].fillna("").astype(str).str.strip()
        data = data[values != ""].copy()
    if data.crs is None:
        data = data.set_crs(CRS.from_epsg(4326))
    data_geo = data.to_crs(CRS.from_epsg(4326))
    lon, lat, _ = camera_geo
    metric_crs = _metric_crs_for_camera(lon, lat)
    data_metric = data_geo.to_crs(metric_crs)
    to_metric = Transformer.from_crs(CRS.from_epsg(4326), metric_crs, always_xy=True)
    camera_x, camera_y = to_metric.transform(float(lon), float(lat))
    scene = []
    for idx in data_geo.index:
        geo = data_geo.at[idx, "geometry"]
        metric = data_metric.at[idx, "geometry"]
        if geo is None or geo.is_empty or metric is None or metric.is_empty:
            continue
        for part_no, (geo_part, metric_part) in enumerate(
                zip(_polygon_parts(geo), _polygon_parts(metric))):
            scene.append({
                "id": str(idx),
                "part": part_no,
                "geo": geo_part,
                "metric": metric_part,
            })
    return scene, metric_crs, (float(camera_x), float(camera_y))


def getfootprints(shp_file_path):
    """Legacy footprint reader; returns the same two values as the old code."""
    data = gpd.read_file(shp_file_path)
    if "building" in data.columns:
        values = data["building"].fillna("").astype(str).str.strip()
        data = data[values != ""]
    bldid = {}
    last_coords = []
    for index, row in data.iterrows():
        coords = []
        for polygon in _polygon_parts(row.geometry):
            coords.extend(list(polygon.exterior.coords))
        if coords:
            bldid[index] = coords
            last_coords = coords
    return bldid, last_coords


def _ray_intersects_interior(ray, polygon):
    """Return the closest positive distance at which a ray enters a polygon."""
    hit = ray.intersection(polygon)
    if hit.is_empty:
        return None
    points = []
    if hit.geom_type == "Point":
        points = [hit]
    elif hit.geom_type == "MultiPoint":
        points = list(hit.geoms)
    elif hit.geom_type in ("LineString", "LinearRing"):
        points = [Point(hit.coords[0]), Point(hit.coords[-1])]
    elif hasattr(hit, "geoms"):
        for item in hit.geoms:
            if item.geom_type == "Point":
                points.append(item)
            elif hasattr(item, "coords"):
                points.extend([Point(item.coords[0]), Point(item.coords[-1])])
    if not points:
        try:
            points = [hit.representative_point()]
        except Exception:
            return None
    return min(float(ray.project(point)) for point in points)


def _visible_points(scene, camera_xy, max_distance=None):
    camera_x, camera_y = camera_xy
    camera_point = Point(camera_x, camera_y)
    visible = {}
    invisible = {}
    for item in scene:
        visible.setdefault(item["id"], [])
        invisible.setdefault(item["id"], [])
    for item in scene:
        building_id = item["id"]
        geo_part = item["geo"]
        metric_part = item["metric"]
        for point_geo, point_metric in zip(
                list(geo_part.exterior.coords)[:-1],
                list(metric_part.exterior.coords)[:-1]):
            target = Point(point_metric[:2])
            distance = camera_point.distance(target)
            too_far = (max_distance is not None and distance > float(max_distance))
            if not np.isfinite(distance) or distance <= 0.0 or too_far:
                invisible[building_id].append(tuple(point_geo[:2]))
                continue
            shrink = min(0.02 / distance, 0.25)
            ray_end = (
                target.x + (camera_x - target.x) * shrink,
                target.y + (camera_y - target.y) * shrink,
            )
            ray = LineString([(camera_x, camera_y), ray_end])
            target_hit = ray.length
            occluded = False
            for blocker in scene:
                hit_distance = _ray_intersects_interior(ray, blocker["metric"])
                if hit_distance is None:
                    continue
                if blocker["id"] == building_id and abs(hit_distance - target_hit) < 0.05:
                    continue
                if hit_distance < target_hit - 0.02:
                    occluded = True
                    break
            (invisible if occluded else visible)[building_id].append(tuple(point_geo[:2]))
    return invisible, visible


def select_footprint(shp_file_path, camera_geo, max_distance=None):
    """筛选可见角点；``max_distance=None`` 表示关闭距离筛选。"""
    scene, _metric_crs, camera_xy = _read_buildings(shp_file_path, camera_geo)
    return _visible_points(scene, camera_xy, max_distance=max_distance)


def geo_to_utm(lon, lat, alt):
    epsg = _metric_crs_for_camera(lon, lat).to_epsg()
    x, y = _utm_transformer(epsg).transform(float(lon), float(lat))
    return x, y, float(alt)


def project_to_pano_float(x, y, z, pano_width, pano_height,
                          north_rotation, camera_bearing=None):
    """Project a local ENU point into an equirectangular panorama."""
    if pano_width <= 0 or pano_height <= 0:
        raise ValueError("全景图宽度和高度必须为正数")
    horizontal_distance = math.hypot(float(x), float(y))
    phi = math.atan2(float(x), float(y))
    theta = math.atan2(float(z), horizontal_distance)
    relative_phi = (phi + math.radians(float(north_rotation))) % (2.0 * math.pi)
    u = relative_phi / (2.0 * math.pi) * float(pano_width)
    v = float(pano_height) / 2.0 - float(pano_height) * theta / math.pi
    return u, v


def project_to_pano(x, y, z, pano_width, pano_height,
                    north_rotation, camera_bearing=None):
    u, v = project_to_pano_float(
        x, y, z, pano_width, pano_height, north_rotation, camera_bearing
    )
    return int(round(u)) % int(pano_width), int(np.clip(round(v), 0, pano_height - 1))


def project_building_owner_columns(shp_file_path, camera_geo, pano_width,
                                   north_rotation, max_range_m=2000.0):
    """为每个全景列分配最近足迹建筑 ID和地面交点距离。

    这是 YOSO 只有语义建筑颜色时的几何实例分配；它不会把 JPG 的灰色
    像素冒充 YOSO 的真实实例 ID。若存在真实实例 PNG，Main6 会优先使用它。
    """
    scene, _metric_crs, camera_xy = _read_buildings(shp_file_path, camera_geo)
    camera_x, camera_y = camera_xy
    owner = np.full(int(pano_width), "", dtype=object)
    distance = np.full(int(pano_width), np.nan, dtype=float)
    try:
        geometries = [item["metric"] for item in scene]
        index = gpd.GeoSeries(geometries).sindex
    except Exception:
        index = None
    rot = math.radians(float(north_rotation))
    for u in range(int(pano_width)):
        phi = (2.0 * math.pi * (u + 0.5) / float(pano_width) - rot) % (2.0 * math.pi)
        end = (camera_x + max_range_m * math.sin(phi),
               camera_y + max_range_m * math.cos(phi))
        ray = LineString([(camera_x, camera_y), end])
        if index is None:
            candidate_positions = range(len(scene))
        else:
            try:
                candidate_positions = index.query(ray, predicate="intersects")
            except (TypeError, NotImplementedError):
                candidate_positions = index.intersection(ray.bounds)
        best = None
        for pos in candidate_positions:
            item = scene[int(pos)]
            hit_distance = _ray_intersects_interior(ray, item["metric"])
            if hit_distance is None or hit_distance <= 0.02:
                continue
            if best is None or hit_distance < best[0]:
                best = (hit_distance, item["id"])
        if best is not None:
            distance[u] = best[0]
            owner[u] = best[1]
    return owner, distance


def getbldbound(image_path):
    """Legacy color-boundary helper; new code uses Main6 YOSO boundaries."""
    image = cv2.imread(image_path)
    if image is None:
        raise FileNotFoundError(image_path)
    mask = np.all(np.abs(image.astype(np.int16) - 70) <= 8, axis=2)
    h, w = mask.shape
    boundary_image = np.full((h, w, 3), 255, dtype=np.uint8)
    top, bottom = [], []
    for x in range(w):
        ys = np.where(mask[:, x])[0]
        yt, yb = (int(ys[0]), int(ys[-1])) if len(ys) else (0, 0)
        if yt > 0:
            boundary_image[yt, x] = (0, 0, 255)
        if yb > 0:
            boundary_image[yb, x] = (255, 0, 0)
        top.append((x, yt))
        bottom.append((x, yb))
    return top, bottom, boundary_image


def pp_main(pano_image_path, points_geo, camera_geo, pano_size,
            north_rotation, camera_bearing, optimal=None):
    """Legacy point-marking helper retained for callers outside Main6."""
    pano_img = cv2.imread(pano_image_path)
    if pano_img is None:
        print("无法加载全景图像")
        return
    h, w = pano_size
    camera_x, camera_y, camera_z = geo_to_utm(*camera_geo)
    font = cv2.FONT_HERSHEY_SIMPLEX
    for index, points in points_geo.items():
        for point in points:
            x, y, z = geo_to_utm(point[0], point[1], 0.0)
            u, v = project_to_pano(x - camera_x, y - camera_y, z - camera_z,
                                   w, h, north_rotation, camera_bearing)
            x2, y2, z2 = geo_to_utm(point[0], point[1], 18.0)
            u2, v2 = project_to_pano(x2 - camera_x, y2 - camera_y, z2 - camera_z,
                                     w, h, north_rotation, camera_bearing)
            cv2.putText(pano_img, str(index), (u, v), font, 1, (255, 0, 0), 2, cv2.LINE_AA)
            cv2.circle(pano_img, (u, v), 5, (0, 0, 255), -1)
            cv2.circle(pano_img, (u2, v2), 5, (255, 0, 0), -1)
            cv2.putText(pano_img, str(index), (u2, v2), font, 1, (255, 0, 0), 2, cv2.LINE_AA)
            cv2.line(pano_img, (u, v), (u2, v2), (255, 0, 0), 1)
    if optimal:
        os.makedirs("image", exist_ok=True)
        cv2.imwrite("image/pano_marked36142222.jpg", pano_img)
    return pano_img
