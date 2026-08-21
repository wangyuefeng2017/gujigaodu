# -*- coding: utf-8 -*-
"""
project_pano 核心函数单元测试

测试内容:
- geo_to_utm: 地理坐标 ↔ UTM 转换
- project_to_pano: 3D 坐标 → 全景像素正向投影
- inverse_project_height: 全景像素 → 建筑高度反向解析
- 正向/反向投影的互逆性
"""

import math
import pytest
import project_pano as p2pano

# 测试参数（来自 Main6_old.py / Main6_new.py 的真实配置）
CAMERA_GEO = [2.355178, 48.860648, 1.6]   # 巴黎街景相机位置
PANO_WIDTH = 2048
PANO_HEIGHT = 1024
NORTH_ROTATION = 105
CAMERA_BEARING = 75                        # 180 - north_rotation


class TestGeoToUtm:
    """geo_to_utm 坐标转换测试"""

    def test_nearby_point_utm_distance(self):
        """相近两点的 UTM 距离应与地理距离一致(项目用相对坐标，不依赖绝对值)"""
        x1, y1, _ = p2pano.geo_to_utm(2.355178, 48.860648, 0)
        # 向北约0.0009°(≈100m)，经度相同
        x2, y2, _ = p2pano.geo_to_utm(2.355178, 48.861548, 0)
        dist = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        assert 90 < dist < 110, f"两点距离 {dist:.1f}m 偏离预期 100m"

    def test_altitude_passthrough(self):
        """高度应原样返回"""
        _, _, z = p2pano.geo_to_utm(2.355178, 48.860648, 100.0)
        assert z == 100.0


class TestProjectToPano:
    """project_to_pano 正向投影测试"""

    def test_ground_point_at_horizon(self):
        """与相机同高(z_rel=0)的点应投影到地平线 v=pano_height/2"""
        u, v = p2pano.project_to_pano(0.0, 10.0, 0.0, PANO_WIDTH, PANO_HEIGHT,
                                      NORTH_ROTATION, CAMERA_BEARING)
        assert v == PANO_HEIGHT // 2

    def test_pixel_in_image_range(self):
        """投影结果应在图像范围内"""
        u, v = p2pano.project_to_pano(5.0, 10.0, 3.0, PANO_WIDTH, PANO_HEIGHT,
                                      NORTH_ROTATION, CAMERA_BEARING)
        assert 0 <= u < PANO_WIDTH
        assert 0 <= v < PANO_HEIGHT

    def test_higher_point_projects_above(self):
        """更高的点应投影到更小的 v（图像上方）"""
        _, v_low = p2pano.project_to_pano(0, 10, 1, PANO_WIDTH, PANO_HEIGHT,
                                          NORTH_ROTATION, CAMERA_BEARING)
        _, v_high = p2pano.project_to_pano(0, 10, 5, PANO_WIDTH, PANO_HEIGHT,
                                           NORTH_ROTATION, CAMERA_BEARING)
        assert v_high < v_low, "更高的点应在图像上方(v更小)"


class TestInverseProjection:
    """正向投影与反向解析的互逆性测试"""

    @pytest.mark.parametrize("h_true", [3.0, 5.0, 10.0, 20.0])
    def test_height_inversion_consistency(self, h_true):
        """给定高度正向投影后再反解，高度应一致(误差<1m，因int取整)"""
        cam_x, cam_y, cam_z = p2pano.geo_to_utm(*CAMERA_GEO)
        # 地面点（相机正北约6米，经度相同）
        point_geo = [2.355178, 48.860700]
        px, py, _ = p2pano.geo_to_utm(point_geo[0], point_geo[1], 0)
        x_rel = px - cam_x
        y_rel = py - cam_y
        z_rel = h_true - cam_z   # 屋顶相对相机高度

        # 正向投影得到屋顶像素
        u, v = p2pano.project_to_pano(x_rel, y_rel, z_rel, PANO_WIDTH, PANO_HEIGHT,
                                     NORTH_ROTATION, CAMERA_BEARING)
        # 反向解析高度
        h_est, _, _ = p2pano.inverse_project_height(
            u, v, point_geo, CAMERA_GEO,
            (PANO_HEIGHT, PANO_WIDTH), NORTH_ROTATION, CAMERA_BEARING)

        assert abs(h_est - h_true) < 1.0, \
            f"高度{h_true}m 反解为 {h_est:.2f}m，误差 {abs(h_est - h_true):.2f}m 过大"

    def test_azimuth_consistency(self):
        """影像方位角 phi_img 应与地面点方位角 phi_ground 接近(<1°)"""
        point_geo = [2.355178, 48.860700]
        cam_x, cam_y, _ = p2pano.geo_to_utm(*CAMERA_GEO)
        px, py, _ = p2pano.geo_to_utm(point_geo[0], point_geo[1], 0)
        x_rel, y_rel = px - cam_x, py - cam_y
        u, v = p2pano.project_to_pano(x_rel, y_rel, 3.4, PANO_WIDTH, PANO_HEIGHT,
                                     NORTH_ROTATION, CAMERA_BEARING)
        _, phi_img, phi_ground = p2pano.inverse_project_height(
            u, v, point_geo, CAMERA_GEO,
            (PANO_HEIGHT, PANO_WIDTH), NORTH_ROTATION, CAMERA_BEARING)
        angle_diff = math.degrees(abs(phi_img - phi_ground))
        assert angle_diff < 1.0, f"方位角差异 {angle_diff:.2f}° 过大"
