# -*- coding: utf-8 -*-
"""
新版本：使用反向解析求解建筑物高度（用于对比）
"""

import cv2
import numpy as np
import project_pano as p2pano
import time
import os

def iterheight_new(pano_image_path, points_geo, camera_geo, pano_size, north_rotation, camera_bearing, footheight, top_boundary_points, optimal = None):
    """新版本：通过反向解析直接计算高度"""
    pano_img = cv2.imread(pano_image_path)
    if pano_img is None:
        print("无法加载全景图像")
        return

    pano_height, pano_width = pano_size
    camera_x, camera_y, camera_z = p2pano.geo_to_utm(*camera_geo)
    
    bldheightset = {}
    skipped_count = 0
    
    for index in points_geo.keys():
        if index not in bldheightset.keys():
            height = []
            pointnum = 0
            facadebottom = []
            facadetop = []
            for point in points_geo[index]:
                # 地面 footprint 点正投影
                point_ground = [point[0], point[1], footheight]
                x, y, z = p2pano.geo_to_utm(*point_ground)
                x_relative, y_relative, z_relative = x - camera_x, y - camera_y, z - camera_z
                u, v = p2pano.project_to_pano(x_relative, y_relative, z_relative, pano_width, pano_height, north_rotation, camera_bearing)
                u = int(u) % pano_width
                
                # 从分割图获取该列的屋顶像素 y 坐标
                if u < 0 or u >= len(top_boundary_points):
                    skipped_count += 1
                    pointnum += 1
                    continue
                    
                v_roof = top_boundary_points[u][1]
                if v_roof == 0:
                    skipped_count += 1
                    pointnum += 1
                    continue
                
                if v_roof <= 2:
                    skipped_count += 1
                    pointnum += 1
                    continue
                
                # 反向求解高度
                h_estimated, phi_img, phi_ground = p2pano.inverse_project_height(
                    u, v_roof, [point[0], point[1]], camera_geo, pano_size, north_rotation, camera_bearing
                )
                
                # 验证投影
                point_est = [point[0], point[1], footheight + h_estimated]
                x2, y2, z2 = p2pano.geo_to_utm(*point_est)
                x_r2, y_r2, z_r2 = x2 - camera_x, y2 - camera_y, z2 - camera_z
                u2, v2 = p2pano.project_to_pano(x_r2, y_r2, z_r2, pano_width, pano_height, north_rotation, camera_bearing)
                
                height.append(h_estimated)
                cv2.circle(pano_img, (u, v), 5, (0, 0, 255), -1)
                cv2.circle(pano_img, (u2, v2), 5, (255, 0, 0), -1)
                cv2.line(pano_img, (int(u), int(v)), (int(u2), int(v2)), (255, 0, 0), 3)
                
                facadebottom.append([u, v])
                facadetop.append([u2, v2])
                pointnum += 1

            if len(height) > 0:
                bldheight = sum(height) / len(height)
            else:
                bldheight = 0
            
            bldheightset[index] = {'bldheight': bldheight, 'height': height}
    
    cv2.imwrite("image/marked222_new.jpg", pano_img)
    print(f"\n[NEW] 跳过点数: {skipped_count}")
    return bldheightset
                

if __name__ == "__main__":
    imgname = 'rectified_panoramaStreet View 3614.jpg'
    pano_image_path = 'svseginfor/' + imgname
    pano_seg = 'svseginfor/' + imgname
    osmfile = '../osm/paris/paris_area2bldt.shp'
    
    camera_geo = [2.355178, 48.860648, 1.6]
    pano_img = cv2.imread(pano_image_path)
    if pano_img is None:
        pano_image_path = 'svseginfor/Street View 3614.jpg'
        pano_img = cv2.imread(pano_image_path)
    
    points_geo = p2pano.select_footprint(osmfile, camera_geo)[1]
    pano_size = pano_img.shape[:2]
    north_rotation = 105
    camera_bearing = 180 - north_rotation
    footheight = 0
    top_boundary_points, bottom_boundary_points, boundary_image = p2pano.getbldbound(pano_seg)
    
    start_time = time.time()
    bldheightset = iterheight_new(pano_image_path, points_geo, camera_geo, pano_size, north_rotation, camera_bearing, footheight, top_boundary_points, optimal=None)
    elapsed = time.time() - start_time
    
    print(f"\n===== [NEW] 最终结果 | 耗时: {elapsed:.3f}s =====")
    for idx, data in bldheightset.items():
        print(f"建筑物 {idx}: 平均高度 = {data['bldheight']:.2f}m, 角点高度 = {[f'{h:.2f}' for h in data['height']]}")
