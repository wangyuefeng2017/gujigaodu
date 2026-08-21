# -*- coding: utf-8 -*-
"""
Created on Sun Jun 16 22:13:45 2024

@author: wyf
"""

import cv2
import numpy as np
import project_pano as p2pano
import pandas as pd
from openpyxl import load_workbook
import os

def append_nested_dict_to_excel(file_path, sheet_name, nested_dict):
    # 将嵌套字典转换为DataFrame
    rows = []
    for key, value in nested_dict.items():
        row = {'Index': key}
        row.update(value)
        rows.append(row)
    
    df_new = pd.DataFrame(rows)
    df_new = df_new.set_index('Index')
    
    # 检查文件是否存在
    if not os.path.exists(file_path):
        # 如果文件不存在，则创建新的Excel文件并写入数据
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df_new.to_excel(writer, sheet_name=sheet_name, index=True)
    else:
        # 如果文件存在，则加载Excel文件
        book = load_workbook(file_path)
        if sheet_name in book.sheetnames:
            # 读取现有的表格
            df_existing = pd.read_excel(file_path, sheet_name=sheet_name, index_col=0)
            # 合并现有数据和新数据
            df_combined = pd.concat([df_existing, df_new], axis=1)
        else:
            df_combined = df_new
        
        # 写回Excel文件
        with pd.ExcelWriter(file_path, engine='openpyxl') as writer:
            df_combined.to_excel(writer, sheet_name=sheet_name, index=True)


def iterheight(pano_image_path, points_geo, camera_geo, pano_size, north_rotation, camera_bearing, footheight, top_boundary_points, optimal = None):
    # 加载全景图像
    pano_img = cv2.imread(pano_image_path)
    if pano_img is None:
        print("无法加载全景图像")
        return

    pano_height, pano_width = pano_size
    camera_x, camera_y, camera_z = p2pano.geo_to_utm(*camera_geo)
    
    bldheightset = {}
    for index in points_geo.keys():
        if index not in bldheightset.keys():
            height = []
            pointnum = 0
            facadebottom = []
            facadetop = []
            for point in points_geo[index]:
                # ===== 步骤1：地面 footprint 点正投影 =====
                point_ground = [point[0], point[1], footheight]
                x, y, z = p2pano.geo_to_utm(*point_ground)
                x_relative, y_relative, z_relative = x - camera_x, y - camera_y, z - camera_z
                u, v = p2pano.project_to_pano(x_relative, y_relative, z_relative, pano_width, pano_height, north_rotation, camera_bearing)
                
                # 处理全景图循环（u 超出宽度时取模）
                u = int(u) % pano_width
                
                # ===== 步骤2：从分割图获取该列的屋顶像素 y 坐标 =====
                if u < 0 or u >= len(top_boundary_points):
                    print(f'building {index}, point {pointnum}: u={u} 超出边界，跳过')
                    pointnum += 1
                    continue
                    
                v_roof = top_boundary_points[u][1]
                if v_roof == 0:
                    print(f'building {index}, point {pointnum}: u={u} 处无屋顶，跳过')
                    pointnum += 1
                    continue
                
                # 边界保护：当屋顶像素接近图像顶部时（v <= 2），tan(theta) 会趋向无穷大，产生极大误差
                if v_roof <= 2:
                    print(f'building {index}, point {pointnum}: u={u}, v_roof={v_roof} 接近图像顶部，跳过')
                    pointnum += 1
                    continue
                
                # ===== 步骤3：反向求解高度（核心修改：替代原来的迭代h）=====
                h_estimated, phi_img, phi_ground = p2pano.inverse_project_height(
                    u, v_roof, [point[0], point[1]], camera_geo, pano_size, north_rotation, camera_bearing
                )
                
                # 方位角一致性验证（差值在30°以内认为匹配，容忍分割图误差）
                phi_diff = abs(phi_img - phi_ground)
                if phi_diff > np.pi:
                    phi_diff = 2 * np.pi - phi_diff
                
                print(f'building {index}, point {pointnum}: footprint投影 u={u}, v={v}, 屋顶像素 v_roof={v_roof}')
                print(f'  -> 反向求解高度: {h_estimated:.2f}m')
                print(f'  -> phi_img={phi_img/np.pi*180:.2f}°, phi_ground={phi_ground/np.pi*180:.2f}°, diff={phi_diff/np.pi*180:.2f}°')
                
                # ===== 步骤4：用求得的高度重新正投影验证 =====
                point_est = [point[0], point[1], footheight + h_estimated]
                x2, y2, z2 = p2pano.geo_to_utm(*point_est)
                x_r2, y_r2, z_r2 = x2 - camera_x, y2 - camera_y, z2 - camera_z
                u2, v2 = p2pano.project_to_pano(x_r2, y_r2, z_r2, pano_width, pano_height, north_rotation, camera_bearing)
                print(f'  -> 验证投影: ({u2}, {v2}), 原屋顶像素: ({u}, {v_roof})')
                
                # 绘制可视化
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
            print(f'building {index} 平均高度: {bldheight:.2f}m')
    
    cv2.imwrite("image/marked222.jpg", pano_img)
    return bldheightset
                

if  __name__ == "__main__":
    imgname = 'rectified_panoramaStreet View 3614.jpg'
    # 使用当前目录下的文件路径（替代Windows绝对路径）
    pano_image_path =  'svseginfor/' + imgname  # 全景图像路径
    
    pano_seg = 'svseginfor/'  + imgname
    
    # 使用真实巴黎建筑物shp文件
    osmfile = '/Users/wangyuefeng/学生指导/硕士研究生/2024硕士/刘乙萱/gujigaodu/osm/paris/building_paris_4.shp'
    osmfile = 'test_data/paris_area2bldt.shp'
    
    camera_geo=[2.355178, 48.860648, 1.6]
    pano_img=cv2.imread(pano_image_path)
    if pano_img is None:
        print(f"无法加载全景图像: {pano_image_path}")
        # 尝试使用分割图作为全景图（如果分割图本身包含全景图内容）
        pano_image_path = 'svseginfor/Street View 3614.jpg'
        pano_img = cv2.imread(pano_image_path)
        if pano_img is None:
            print(f"备用路径也无法加载: {pano_image_path}")
            exit(1)
    
    points_geo = p2pano.select_footprint(osmfile, camera_geo)[1]
    pano_size = pano_img.shape[:2]  # 全景图像的尺寸（宽度，高度）
    north_rotation = 105  # 全景影像中地理北方向的位置（度）
    camera_bearing = 180-north_rotation  # 摄影师相机的朝向（度）
    # p2pano.pp_main(pano_image_path, points_geo, camera_geo, pano_size, north_rotation, camera_bearing)
    footheight = 0
    top_boundary_points, bottom_boundary_points, boundary_image = p2pano.getbldbound(pano_seg)
    
    bldheightset = iterheight(pano_image_path, points_geo, camera_geo, pano_size, north_rotation, camera_bearing, footheight, top_boundary_points, optimal = None)
    
    file_path = 'bldheightset21'+'_'+ imgname+ '.xlsx'
    sheet_name = 'Sheet1'  
    # append_nested_dict_to_excel(file_path, sheet_name, bldheightset)
    
    print("\n===== 最终结果 =====")
    for idx, data in bldheightset.items():
        print(f"建筑物 {idx}: 平均高度 = {data['bldheight']:.2f}m, 角点高度 = {[f'{h:.2f}' for h in data['height']]}")
