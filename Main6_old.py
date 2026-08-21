# -*- coding: utf-8 -*-
"""
旧版本：使用迭代h的方法求解建筑物高度（用于对比）
"""

import cv2
import numpy as np
import project_pano as p2pano
import time
import os


class Timer:
    """分阶段计时器：支持累计计时、单次计时和汇总报告"""

    def __init__(self):
        self.stages = {}          # 各阶段累计耗时 {stage_name: seconds}
        self._current = None      # 当前正在计时的阶段名
        self._t0 = None           # 当前阶段开始时间戳

    def start(self, stage_name):
        """开始某个阶段的计时（会自动停止上一个阶段）"""
        if self._current is not None:
            self.stop()
        self._current = stage_name
        self._t0 = time.time()

    def stop(self):
        """停止当前阶段计时并累计"""
        if self._current is None:
            return
        elapsed = time.time() - self._t0
        self.stages[self._current] = self.stages.get(self._current, 0.0) + elapsed
        self._current = None
        self._t0 = None

    @staticmethod
    def elapsed_since(t0):
        """便捷函数：返回从 t0 到现在的耗时"""
        return time.time() - t0

    def summary(self, title="时间统计"):
        """输出各阶段耗时汇总表，返回总耗时"""
        if self._current is not None:
            self.stop()
        total = sum(self.stages.values())
        print(f"\n===== {title} =====")
        print(f"{'阶段':<20s}{'耗时(s)':<12s}{'占比':<10s}")
        print("-" * 42)
        for stage, t in sorted(self.stages.items(), key=lambda x: -x[1]):
            pct = (t / total * 100) if total > 0 else 0
            print(f"{stage:<20s}{t:<12.4f}{pct:<10.1f}")
        print("-" * 42)
        print(f"{'总计':<20s}{total:<12.4f}{100.0:<10.1f}")
        return total


def iterheight_old(pano_image_path, points_geo, camera_geo, pano_size, north_rotation, camera_bearing, footheight, top_boundary_points, optimal = None, timer=None):
    """旧版本：通过迭代h（5~100m，步长0.1m）来找到匹配屋顶边界的高度"""
    pano_img = cv2.imread(pano_image_path)
    if pano_img is None:
        print("无法加载全景图像")
        return

    pano_height, pano_width = pano_size
    camera_x, camera_y, camera_z = p2pano.geo_to_utm(*camera_geo)
    
    bldheightset = {}
    total_iterations = 0
    per_bld_times = []   # 记录每栋建筑的耗时和迭代次数
    
    for index in points_geo.keys():
        if index not in bldheightset.keys():
            height = []
            pointnum = 0
            facadebottom = []
            facadetop = []
            bld_iter = 0
            bld_t0 = time.time()
            for point in points_geo[index]:
                for h in range(50, 1000, 1):
                    total_iterations += 1
                    bld_iter += 1
                    point_ground = [point[0], point[1], footheight]
                    x, y, z = p2pano.geo_to_utm(*point_ground)
                    x_relative, y_relative, z_relative = x - camera_x, y - camera_y, z - camera_z
                    u, v = p2pano.project_to_pano(x_relative, y_relative, z_relative, pano_width, pano_height, north_rotation, camera_bearing)
                    cv2.circle(pano_img, (u, v), 5, (0, 0, 255), -1)
                    
                    point2 = [point[0], point[1], footheight + h * 0.1]
                    x2, y2, z2 = p2pano.geo_to_utm(*point2)
                    x_relative2, y_relative2, z_relative2 = x2 - camera_x, y2 - camera_y, z2 - camera_z
                    u2, v2 = p2pano.project_to_pano(x_relative2, y_relative2, z_relative2, pano_width, pano_height, north_rotation, camera_bearing)
                    
                    if v2 <= top_boundary_points[u2][1]:
                        height.append(h * 0.1)
                        print(f'[OLD] building {index}, point {pointnum}: h={h*0.1:.1f}m, u={u}, v={v}, u2={u2}, v2={v2}, roof_y={top_boundary_points[u2][1]}')
                        cv2.circle(pano_img, (u2, v2), 5, (255, 0, 0), -1)
                        cv2.line(pano_img, (int(u), int(v)), (int(u2), int(v2)), (255, 0, 0), 3)
                        break
                    elif top_boundary_points[u2][1] == 0:
                        break
                
                facadebottom.append([u, v])
                facadetop.append([u2, v2])
                pointnum += 1

            if len(height) > 0:
                bldheight = sum(height) / len(height)
            else:
                bldheight = 0
            
            bldheightset[index] = {'bldheight': bldheight, 'height': height}
            bld_elapsed = time.time() - bld_t0
            per_bld_times.append((index, bld_elapsed, bld_iter, len(height)))
            print(f'[OLD] building {index} 平均高度: {bldheight:.2f}m | 耗时: {bld_elapsed*1000:.1f}ms | 迭代: {bld_iter}次')
    
    if timer is not None:
        timer.start("图像保存")
    cv2.imwrite("image/marked222_old.jpg", pano_img)
    if timer is not None:
        timer.stop()
    print(f"\n[OLD] 总迭代次数: {total_iterations}")

    # 输出每栋建筑耗时统计
    if per_bld_times:
        print(f"\n----- 每栋建筑耗时 Top10 -----")
        print(f"{'建筑ID':<10s}{'耗时(ms)':<12s}{'迭代次数':<10s}{'有效角点':<10s}")
        sorted_bld = sorted(per_bld_times, key=lambda x: -x[1])[:10]
        for bid, t, it, nh in sorted_bld:
            print(f"{bid:<10s}{t*1000:<12.1f}{it:<10d}{nh:<10d}")
        avg_bld_t = sum(x[1] for x in per_bld_times) / len(per_bld_times)
        print(f"平均每栋建筑耗时: {avg_bld_t*1000:.1f}ms (共{len(per_bld_times)}栋)")

    return bldheightset
                

if __name__ == "__main__":
    timer = Timer()

    imgname = 'rectified_panoramaStreet View 3614.jpg'
    pano_image_path = 'svseginfor/' + imgname
    pano_seg = 'svseginfor/' + imgname
    osmfile = '../osm/paris/paris_area2bldt.shp'
    
    camera_geo = [2.355178, 48.860648, 1.6]

    timer.start("加载全景图像")
    pano_img = cv2.imread(pano_image_path)
    if pano_img is None:
        pano_image_path = 'svseginfor/Street View 3614.jpg'
        pano_img = cv2.imread(pano_image_path)
    timer.stop()

    timer.start("select_footprint")
    points_geo = p2pano.select_footprint(osmfile, camera_geo)[1]
    timer.stop()

    pano_size = pano_img.shape[:2]
    north_rotation = 105
    camera_bearing = 180 - north_rotation
    footheight = 0

    timer.start("getbldbound(屋顶边界提取)")
    top_boundary_points, bottom_boundary_points, boundary_image = p2pano.getbldbound(pano_seg)
    timer.stop()
    
    timer.start("iterheight_old(迭代解算)")
    bldheightset = iterheight_old(pano_image_path, points_geo, camera_geo, pano_size, north_rotation, camera_bearing, footheight, top_boundary_points, optimal=None, timer=timer)
    timer.stop()
    
    total_time = timer.summary("[OLD] 分阶段时间统计")
    
    print(f"\n===== [OLD] 最终结果 | 总耗时: {total_time:.3f}s =====")
    for idx, data in bldheightset.items():
        print(f"建筑物 {idx}: 平均高度 = {data['bldheight']:.2f}m, 角点高度 = {[f'{h:.2f}' for h in data['height']]})")
