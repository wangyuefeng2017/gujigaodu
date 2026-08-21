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
from pyproj import Proj, transform
# from pyproj import Transformer
import geopandas as gpd
from shapely.geometry import Point, Polygon, LineString
from pyproj import Transformer, CRS
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="pyproj")

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
        # 如果是多边形，获取外环的坐标
        if shape.type == 'Polygon':
            exterior_coords = shape.exterior.coords
        elif shape.type == 'MultiPolygon':
            exterior_coords = shape.exteriors[0].coords  # 取第一个外环
        else:
            continue  # 不是Polygon或MultiPolygon，跳过
        for coord in exterior_coords:
            print('coord',coord) 
            coordset.append(coord)
        bldid[index] = coordset
        # 转换坐标
        
    return bldid, exterior_coords

def select_footprint(shp_file_path, camera_geo):
    # 提取building几何信息
    shp_data = gpd.read_file(shp_file_path)
    buildings = shp_data[shp_data['building'] != '']
    # 创建观测点
    lat, lon, alt = camera_geo
    observation_point = Point(lat, lon)
    
    visible_points = {}
    invisible_points = {}
    for idx, building in buildings.iterrows():
        visible_points[str(idx)] = []
        invisible_points[str(idx)] = []
        # building_polygon = Polygon(building.geometry.exterior)
        for point in building.geometry.exterior.coords:
            point_shapely = Point(point)
            line = LineString([observation_point, point_shapely])
            
            # 检查是否与其他建筑物相交
            intersects = False
            for other_idx, other_building in buildings.iterrows():
                #if idx != other_idx:  # 不检查自身
                other_polygon = Polygon(other_building.geometry.exterior)
                if line.crosses(other_polygon):
                    intersects = True
                    break
            if intersects:
                invisible_points[str(idx)].append((point_shapely.x, point_shapely.y))
            else:
                visible_points[str(idx)].append((point_shapely.x, point_shapely.y))
            # break
    return invisible_points, visible_points


def geo_to_utm(lat, lon, alt):
    # 定义坐标系
    wgs84 = CRS.from_epsg(4326)
    utm_zone_31n = CRS.from_epsg(32631)
    
    # 创建Transformer对象
    transformer = Transformer.from_crs(wgs84, utm_zone_31n)
    
    # 进行坐标转换
    x, y = transformer.transform(lon, lat)
    return x, y, alt
    
# def project_to_pano(x, y, z, pano_width, pano_height, north_rotation, camera_bearing):
#     # 计算偏航角phi和俯仰角theta
#     do = np.sqrt(x**2 + y**2)
#     phi = math.atan2(x, y) #经度
#     theta = math.atan2(z, np.sqrt(x**2 + y**2)) #纬度
#     
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


def project_to_pano(x, y, z, pano_width, pano_height, north_rotation, camera_bearing):
    # 计算偏航角phi和俯仰角theta
    # k = 1
    # r = np.sqrt(x**2 + y**2 + z**2)
    # phi = np.arctan2(x, y) + k * np.arctan2(np.sqrt(x**2 + y**2), r) #(1 + k * (np.sqrt(x**2 + y**2) / r)), x * (1 + k * (np.sqrt(x**2 + y**2) / r)))
    phi = math.atan2(x, y) #经度
    theta = math.atan2(z, np.sqrt(x**2 + y**2)) #纬度
    
    # theta2 = math.asin(z/np.sqrt(x**2 + y**2 + z**2))
    # print (' ')
    # print ('theta0',phi/np.pi * 180, theta/np.pi * 180, np.sqrt(x**2 + y**2))
   
    # phi = phi - np.radians(camera_bearing - north_rotation)
    # print ('theta0',phi/np.pi * 180, theta/np.pi * 180, (1/np.cos(theta)))
    # 调整phi以考虑全景影像的水平旋转角和摄影师的朝向
    # 摄影师朝向与北方向旋转角的差值调整phi
    # trans_phi = phi % (np.pi/4) - (np.pi/8)
    # if theta>=0:
    # if phi>0:
    #     trans_phi = phi % (np.pi/2) - (np.pi/4)
    # else:
    #     trans_phi = phi % (-np.pi/2) + (np.pi/4)
        

    # if np.pi-np.pi/8 > phi >= np.pi/8:
    #     adjusted_phi = phi-np.pi/24 + (np.pi/24* (np.cos(theta)))

    # elif -np.pi + np.pi/8 < phi < -np.pi/8:
    #     adjusted_phi = phi-np.pi/24 + (np.pi/24* (1/np.cos(theta)))
    # else:
    #     adjusted_phi = phi
    adjusted_phi = phi
    # print ('adjusted_phi',(phi-trans_phi)/np.pi * 180, adjusted_phi/np.pi * 180, trans_phi/np.pi * 180)
    # 确保adjusted_phi在-π到π范围内
    # adjusted_phi = (adjusted_phi + np.pi) % (2 * np.pi) - np.pi 
    if adjusted_phi+np.radians(north_rotation)<0:
        adjusted_phi = 2 * np.pi + (adjusted_phi + np.radians(north_rotation))
        u = (adjusted_phi) / (2 * np.pi) * pano_width

    else:
        u = (adjusted_phi+np.radians(north_rotation)) / (2 * np.pi) * pano_width# + pano_width * (np.radians(north_rotation)/(2*np.pi))
    # v = (0.5 - theta  / np.pi) * pano_height *(theta / np.sin(theta))  # 调整垂直位置
    v = pano_height/2 - (np.sin(theta) * (pano_height/2))
    # print ('u2', adjusted_phi/np.pi * 180, u)

    return int(u), int(v)

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
        boundary_image[y, x] = [255, 0, 0]  # 用红色标记轮廓点
        boundary_image[ybottom, x] = [0, 0, 255]  # 用红色标记轮廓点
        top_boundary_points.append((x, y))
        bottom_boundary_points.append((x, ybottom))
        # cv2.circle(image_rgb, (x, y), 5, (255, 0, 0), -1)
    
    return top_boundary_points, bottom_boundary_points, boundary_image


def pano_to_angles(u, v, pano_width, pano_height, north_rotation):
    """
    从全景影像像素坐标反求方位角 phi 和俯仰角 theta
    
    Parameters:
        u, v: 影像像素坐标
        pano_width, pano_height: 影像尺寸
        north_rotation: 北方向旋转角（度）
    
    Returns:
        phi: 方位角（弧度），theta: 俯仰角（弧度）
    """
    # 从 u 反求 adjusted_phi
    adjusted_phi = u * (2 * np.pi) / pano_width - np.radians(north_rotation)
    
    # 规范化到 [-pi, pi] 范围
    if adjusted_phi > np.pi:
        adjusted_phi -= 2 * np.pi
    elif adjusted_phi < -np.pi:
        adjusted_phi += 2 * np.pi
    
    phi = adjusted_phi
    
    # 从 v 反求 theta
    # v = pano_height/2 - (np.sin(theta) * (pano_height/2))
    sin_theta = (pano_height / 2 - v) / (pano_height / 2)
    
    # 限制范围防止数值误差
    sin_theta = np.clip(sin_theta, -1.0, 1.0)
    theta = math.asin(sin_theta)
    
    return phi, theta


def inverse_project_height(u, v, point_geo, camera_geo, pano_size, north_rotation, camera_bearing):
    """
    通过影像中屋顶像点坐标反求建筑物高度
    
    Parameters:
        u, v: 屋顶在全景影像上的像素坐标
        point_geo: 地面 footprint 点的地理坐标 [lat, lon]（高度为0）
        camera_geo: 相机位置 [lat, lon, alt]
        pano_size: 影像尺寸 (height, width)
        north_rotation: 北方向旋转角（度）
        camera_bearing: 相机朝向（度）
    
    Returns:
        height: 反求得到的高度值（米）
        phi_img: 影像对应的方位角
        phi_ground: 地面点对应的方位角（用于验证）
    """
    pano_height, pano_width = pano_size
    
    # 1. 从影像坐标反求角度
    phi_img, theta = pano_to_angles(u, v, pano_width, pano_height, north_rotation)
    
    # 2. 获取相机和地面点的 UTM 坐标
    camera_x, camera_y, camera_z = geo_to_utm(*camera_geo)
    point = [point_geo[0], point_geo[1], 0]
    x, y, z = geo_to_utm(*point)
    x_relative = x - camera_x
    y_relative = y - camera_y
    
    # 3. 计算地面点相对于相机的方位角（用于验证像素点是否对应此 footprint 点）
    phi_ground = math.atan2(x_relative, y_relative)
    
    # 4. 计算水平距离
    d_horizontal = np.sqrt(x_relative**2 + y_relative**2)
    
    # 5. 从俯仰角 theta 反求高度
    # theta = atan2(z_relative, sqrt(x^2 + y^2))
    # => z_relative = d_horizontal * tan(theta)
    # 加上相机高度得到绝对高度
    height_relative = d_horizontal * math.tan(theta)
    height_absolute = height_relative + camera_z
    
    return height_absolute, phi_img, phi_ground
    # theta = atan2(z, sqrt(x^2 + y^2))
    # => z = d_horizontal * tan(theta)
    height = d_horizontal * math.tan(theta)
    
    return height, phi_img, phi_ground


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
            
            # ===== 新方法：通过屋顶像点坐标反求高度 =====
            # 先使用固定高度18获取屋顶像素坐标（模拟从影像中检测到的屋顶点）
            point2 = [point[0], point[1], 18]
            x2, y2, z2 = geo_to_utm(*point2)
            x_relative2, y_relative2, z_relative2 = x2 - camera_x, y2 - camera_y, z2 - camera_z
            u2, v2 = project_to_pano(x_relative2, y_relative2, z_relative2, pano_width, pano_height, north_rotation, camera_bearing)
            
            # 用反向求解从屋顶像素 (u2, v2) 反求高度
            height_estimated, phi_img, phi_ground = inverse_project_height(
                u2, v2, point[:2], camera_geo, pano_size, north_rotation, camera_bearing
            )
            
            print(f'  -> 反向求解高度: {height_estimated:.2f}m (理论高度: 18m)')
            print(f'  -> 影像方位角 phi_img: {phi_img/np.pi*180:.2f}°, 地面点方位角 phi_ground: {phi_ground/np.pi*180:.2f}°')
            
            # 使用反求得到的高度重新投影验证
            point_est = [point[0], point[1], height_estimated]
            xe, ye, ze = geo_to_utm(*point_est)
            x_re, y_re, z_re = xe - camera_x, ye - camera_y, ze - camera_z
            ue, ve = project_to_pano(x_re, y_re, z_re, pano_width, pano_height, north_rotation, camera_bearing)
            print(f'  -> 验证投影: ({ue}, {ve}), 原屋顶像素: ({u2}, {v2})')
            
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
