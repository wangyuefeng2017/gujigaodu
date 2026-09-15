# -*- coding: utf-8 -*-
"""
Created on Tue Jul  2 22:05:36 2024

@author: wyf
"""

# -*- coding: utf-8 -*-
"""
Created on Wed May  8 00:44:51 2024

@author: wyf
"""

import cv2
import numpy as np
import math
from functools import lru_cache
import geopandas as gpd
from shapely.geometry import Point, LineString
from pyproj import Transformer, CRS
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="pyproj")

# GeoPandas 0.13 + Fiona 1.10 compatibility.  Importing the submodule restores
# ``fiona.path`` for older GeoPandas releases and is harmless on newer stacks.
try:
    import fiona.path  # noqa: F401
except (ImportError, AttributeError):
    pass


def _polygon_parts(geometry):
    """Yield Polygon parts from Polygon/MultiPolygon geometries."""
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type == "Polygon":
        yield geometry
    elif geometry.geom_type == "MultiPolygon":
        yield from geometry.geoms


def _metric_crs_for_camera(lon, lat):
    """Return the local UTM CRS used for metre-level distance calculations."""
    zone = max(1, min(60, int((float(lon) + 180.0) // 6.0) + 1))
    epsg = (32600 if float(lat) >= 0 else 32700) + zone
    return CRS.from_epsg(epsg)


@lru_cache(maxsize=8)
def _utm_transformer(epsg):
    return Transformer.from_crs(CRS.from_epsg(4326), CRS.from_epsg(epsg), always_xy=True)

def getfootprints(shp_file_path):
    shp_data = gpd.read_file(shp_file_path)

    # 过滤出建筑物数据（这里假设建筑物的类别是'building')
    buildings = shp_data[shp_data['building'] != '']

    # 遍历建筑物并提取角点坐标
    bldid = {}
    
    for index, row in buildings.iterrows():
        # 获取建筑物的几何形状
        coordset = []
        shape = row['geometry']
        print (index)
        exterior_coords = []
        for polygon in _polygon_parts(shape):
            exterior_coords.extend(list(polygon.exterior.coords))
        if not exterior_coords:
            continue
        for coord in exterior_coords:
            print('coord',coord)
            coordset.append(coord)
        bldid[index] = coordset
        # 转换坐标
        
    return bldid, exterior_coords

def select_footprint(shp_file_path, camera_geo, max_distance=20.0):
    """
    按论文 3.2.4 节筛选建筑角点：先限制观测距离，再进行视线遮挡检测。

    返回结构与原函数一致；超距或被其他建筑遮挡的角点进入
    ``invisible_points``，可用角点进入 ``visible_points``。
    """
    shp_data = gpd.read_file(shp_file_path)
    if "building" in shp_data.columns:
        building_value = shp_data["building"].fillna("").astype(str).str.strip()
        buildings = shp_data[building_value != ""].copy()
    else:
        buildings = shp_data.copy()

    # camera_geo 与 Shapefile 顶点都采用 (lon, lat, z) 顺序。
    lon, lat, _alt = camera_geo
    if buildings.crs is None:
        buildings = buildings.set_crs(CRS.from_epsg(4326))
    buildings_geo = buildings.to_crs(CRS.from_epsg(4326))
    metric_crs = _metric_crs_for_camera(lon, lat)
    buildings_metric = buildings_geo.to_crs(metric_crs)
    to_metric = Transformer.from_crs(CRS.from_epsg(4326), metric_crs, always_xy=True)
    camera_x, camera_y = to_metric.transform(lon, lat)
    camera_point = Point(camera_x, camera_y)

    visible_points = {str(idx): [] for idx in buildings_geo.index}
    invisible_points = {str(idx): [] for idx in buildings_geo.index}

    # 空间索引不可用时自动退化为遍历，不改变筛选语义。
    try:
        spatial_index = buildings_metric.sindex
    except Exception:
        spatial_index = None

    for idx in buildings_geo.index:
        geometry_geo = buildings_geo.at[idx, "geometry"]
        geometry_metric = buildings_metric.at[idx, "geometry"]
        geo_parts = list(_polygon_parts(geometry_geo))
        metric_parts = list(_polygon_parts(geometry_metric))

        for polygon_geo, polygon_metric in zip(geo_parts, metric_parts):
            geo_coords = list(polygon_geo.exterior.coords)
            metric_coords = list(polygon_metric.exterior.coords)
            # 外环的最后一个坐标与第一个坐标重复，避免重复候选高度。
            for point_geo, point_metric in zip(geo_coords[:-1], metric_coords[:-1]):
                point_lon, point_lat = point_geo[:2]
                target_point = Point(point_metric[:2])
                distance = camera_point.distance(target_point)

                if not np.isfinite(distance) or distance <= 0.0 or distance > max_distance:
                    invisible_points[str(idx)].append((point_lon, point_lat))
                    continue

                # 将射线终点缩短 2 cm，避免把目标角点或共边建筑的端点接触
                # 误判为前景遮挡。
                shrink = min(0.02 / distance, 0.25)
                ray_end = (
                    target_point.x + (camera_x - target_point.x) * shrink,
                    target_point.y + (camera_y - target_point.y) * shrink,
                )
                ray = LineString([(camera_x, camera_y), ray_end])

                if spatial_index is None:
                    candidate_positions = range(len(buildings_metric))
                else:
                    try:
                        candidate_positions = spatial_index.query(ray, predicate="intersects")
                    except (TypeError, NotImplementedError):
                        candidate_positions = list(spatial_index.intersection(ray.bounds))

                occluded = False
                for position in candidate_positions:
                    blocker = buildings_metric.geometry.iloc[int(position)]
                    intersection = ray.intersection(blocker)
                    # 单点相切通常不是有效遮挡；有长度的交集表示射线穿过建筑。
                    # 这里也检测目标建筑本身，以剔除被自身立面遮挡的背面角点。
                    if not intersection.is_empty and intersection.length > 0.02:
                        occluded = True
                        break

                destination = invisible_points if occluded else visible_points
                destination[str(idx)].append((point_lon, point_lat))

    return invisible_points, visible_points


def geo_to_utm(lon, lat, alt):
    """Convert a (longitude, latitude, altitude) point to the local UTM CRS."""
    epsg = _metric_crs_for_camera(lon, lat).to_epsg()
    transformer = _utm_transformer(epsg)
    x, y = transformer.transform(lon, lat)
    return x, y, alt
    
# def project_to_pano(x, y, z, pano_width, pano_height, north_rotation, camera_bearing):
#     # 计算偏航角phi和俯仰角theta
#     do = np.sqrt(x**2 + y**2)
#     phi = math.atan2(x, y) #经度
#     theta = math.atan2(z, np.sqrt(x**2 + y**2)) #纬度
    
#     # 摄影师朝向与北方向旋转角的差值调整phi

#     if np.pi-np.pi/8 > phi >= np.pi/8:
#         adjusted_phi = phi-np.pi/24 + (np.pi/24* (np.cos(theta)))
   
#     elif -np.pi + np.pi/8 < phi < -np.pi/8:
#         adjusted_phi = phi-np.pi/24 + (np.pi/24* (1/np.cos(theta)))
#     else:
#         adjusted_phi = phi
   
#     if adjusted_phi+np.radians(north_rotation)<0:
#         adjusted_phi = 2 * np.pi + (adjusted_phi + np.radians(north_rotation))
#         u = (adjusted_phi) / (2 * np.pi) * pano_width

#     else:
#         u = (adjusted_phi+np.radians(north_rotation)) / (2 * np.pi) * pano_width # + pano_width * (np.radians(north_rotation)/(2*np.pi))
#     v = (0.5 - theta  / np.pi) * pano_height# *(theta / np.sin(theta))  # 调整垂直位置
   
#     return int(u), int(v)


def project_to_pano_float(x, y, z, pano_width, pano_height,
                          north_rotation, camera_bearing=None):
    """
    按论文式 (1)-(4) 将相机坐标系中的点投影到等距柱状全景图。

    ``north_rotation`` 是 Street View Download 360 元数据给出的“北向在
    全景图中的旋转偏移”。它等价于论文中的 ``-psi_0``，所以这里与方位角
    相加。``camera_bearing`` 仅为兼容原调用保留。
    """
    if pano_width <= 0 or pano_height <= 0:
        raise ValueError("全景图宽度和高度必须为正数")

    horizontal_distance = math.hypot(x, y)
    phi = math.atan2(x, y)  # 以正北为 0，顺时针为正
    theta = math.atan2(z, horizontal_distance)

    relative_phi = (phi + math.radians(float(north_rotation))) % (2.0 * math.pi)
    u = relative_phi / (2.0 * math.pi) * float(pano_width)
    # 等距柱状投影的垂直角分辨率为常数：dv/dtheta = -H/pi。
    v = float(pano_height) / 2.0 - float(pano_height) * theta / math.pi
    return u, v


def project_to_pano(x, y, z, pano_width, pano_height,
                    north_rotation, camera_bearing=None):
    """整数像素兼容接口；精确计算请调用 ``project_to_pano_float``。"""
    u, v = project_to_pano_float(
        x, y, z, pano_width, pano_height, north_rotation, camera_bearing
    )
    u_int = int(round(u)) % int(pano_width)
    v_int = int(np.clip(round(v), 0, int(pano_height) - 1))
    return u_int, v_int

def getbldbound(image_path):
    # 定义建筑物顶部的颜色
    image_rgb = cv2.imread(image_path)
    print (image_path)
    building_top_color = np.array([70, 70, 70])
    
    # 创建掩码找到所有建筑物顶部的像素
    mask = np.all(image_rgb == building_top_color, axis=-1)
    # 获取图像的高度和宽度
    height, width, _ = image_rgb.shape
    
    # 创建白色图像 创建一个空白图像用于绘制边界
    color = (255, 255, 255)  # 白色（BGR格式）
    boundary_image = np.full((height, width, 3), color, dtype=np.uint8)
    # boundary_image = np.zeros_like(image_rgb)
    
    # 记录建筑物顶部轮廓的点
    top_boundary_points = []
    bottom_boundary_points = []
    
    # 找到每一列的第一个匹配点
    for x in range(width):
        y_coords = np.where(mask[:, x])[0]
        if len(y_coords) > 0:
            y = y_coords[0]
            ybottom = y_coords[-1]
        else:
            y = 0
            ybottom = 0
        boundary_image[y, x] = [255, 0, 0]  # 用蓝色标记顶部轮廓点
        boundary_image[ybottom, x] = [0, 0, 255]  # 用红色标记底部轮廓点
        top_boundary_points.append((x, y))
        bottom_boundary_points.append((x, ybottom))
        # cv2.circle(image_rgb, (x, y), 5, (255, 0, 0), -1)
    
    return top_boundary_points, bottom_boundary_points, boundary_image


def pp_main(pano_image_path, points_geo, camera_geo, pano_size, north_rotation, camera_bearing, optimal = None):
    # 加载全景图像
    pano_img = cv2.imread(pano_image_path)
    if pano_img is None:
        print("无法加载全景图像")
        return
    
    font = cv2.FONT_HERSHEY_SIMPLEX  # 字体类型
    pano_height, pano_width = pano_size
    camera_x, camera_y, camera_z = geo_to_utm(*camera_geo)
    for index in points_geo.keys():
        pointnum = 0
        for point in points_geo[index]:
            
            point = [point[0], point[1], 0]
            x, y, z = geo_to_utm(*point)
            x_relative, y_relative, z_relative = x - camera_x, y - camera_y, z - camera_z
            u, v = project_to_pano(x_relative, y_relative, z_relative, pano_width, pano_height, north_rotation, camera_bearing)
            print ('point1', pointnum, x, y, z , u, v)
            cv2.putText(pano_img, str(index), (u, v), font, 1, (255, 0, 0), 2, cv2.LINE_AA)
            cv2.circle(pano_img, (u, v), 5, (0, 0, 255), -1)
            
            point2 = [point[0], point[1], 18]
            x2, y2, z2 = geo_to_utm(*point2)
            x_relative2, y_relative2, z_relative2 = x2 - camera_x, y2 - camera_y, z2 - camera_z
            u2, v2 = project_to_pano(x_relative2, y_relative2, z_relative2, pano_width, pano_height, north_rotation, camera_bearing)
            print ('point2', pointnum, x2, y2, z2 , u2, v2)
            cv2.circle(pano_img, (u2, v2), 5, (255, 0, 0), -1)
            cv2.putText(pano_img, str(index), (u2, v2), font, 1, (255, 0, 0), 2, cv2.LINE_AA)
            cv2.line(pano_img,(int(u),int(v)),(int(u2),int(v2)), (255,0,0))
            pointnum+=1
    
    cv2.circle(pano_img, (2186, 527), 5, (255, 255, 0), -1)
        
    # 保存和显示结果图像
    if optimal:
        cv2.imwrite("image/pano_marked36142222.jpg", pano_img)
    # cv2.imshow("Marked Panorama", pano_img)
    # cv2.waitKey(0)
    # cv2.destroyAllWindows()

# 示例用法
if  __name__ == "__main__":
    pano_image_path =  r'H:/gujigaodu/gsi/Street View 3614.jpg'  # 全景图像路径
    
    output_path = 'output_image.jpg'  # 替换为输出图像的保存路径
    osmfile = r'H:\osm\building1.shp'
    # osmfile = r'visible_buildings.shp'
    # osmfile = r'H:\osm\paris\paris_area2bldt.shp'
    # camera_geo=[2.3551784,48.8606474,2.1]
    # camera_geo=[2.355206, 48.860654,2.5]
    # 48.860844, 2.355526
    camera_geo=[ 2.355178, 48.860648, 2.1]#3614
    # camera_geo=[ 2.355323, 48.860618, 1.7]#3613
    # camera_geo=[ 2.354996, 48.860522, 2.1]#3615
    camera_x, camera_y, camera_z = geo_to_utm(*camera_geo)
    pano_img=cv2.imread(pano_image_path)
    
    
    points_geo = select_footprint(osmfile, camera_geo)[1]

    pano_size = pano_img.shape[:2]  # 全景图像的尺寸（宽度，高度）
    north_rotation = 109  # 全景影像中地理北方向的位置（度）
    camera_bearing = 180#-north_rotation  # 摄影师相机的朝向（度）
    
    pp_main(pano_image_path, points_geo, camera_geo, pano_size, north_rotation, camera_bearing, optimal='1')
















