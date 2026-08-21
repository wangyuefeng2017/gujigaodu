# 基于 Google Street View 全景图的建筑物高度反演

从街景全景图（Google Street View）和 OSM 建筑物 footprint 反演建筑物高度。

## 核心功能

- `project_pano.py` — 全景图投影核心模块
  - `geo_to_utm()`：地理坐标 ↔ UTM 转换
  - `select_footprint()`：基于可见性筛选建筑物角点
  - `project_to_pano()`：3D 地理坐标 → 全景像素正向投影
  - `pano_to_angles()`：全景像素 → 方位角/天顶角
  - `inverse_project_height()`：全景像素 → 建筑物高度（反向解析）
  - `getbldbound()`：从分割图提取屋顶/地面边界

- `Main6.py` — 完整工作流（含 Excel 输出）
- `Main6_old.py` — 迭代法：通过假设高度正向投影匹配屋顶边界（5~100m，步长 0.1m）
- `Main6_new.py` — 反向解析法：由屋顶像素直接反解高度公式 `h = d·tan(θ) + z_camera`

## 环境安装

```bash
conda env create -f environment.yml
conda activate gujigaodu
```

或手动安装：

```bash
conda install -c conda-forge numpy pandas shapely pyproj geopandas opencv openpyxl
```

## 使用方法

```bash
# 迭代法（稳健，自带 5~100m 高度合理性约束）
python Main6_old.py

# 反向解析法（快 30+ 倍，需配合分割质量较好的数据）
python Main6_new.py

# 完整工作流（输出 Excel）
python Main6.py
```

运行前需准备：
- `svseginfor/` 目录下的全景图与分割图
- `../osm/paris/` 目录下的建筑物 shapefile

## 方法对比

| 维度 | 迭代法 (Main6_old) | 反向解析法 (Main6_new) |
|------|-------------------|----------------------|
| 算法 | 离散搜索 h ∈ [5,100]m | 闭式解 `h = d·tan(θ) + z` |
| 速度 | 慢（132栋约 3.4s） | 快 30+ 倍（约 0.1s） |
| 精度 | 0.1m 步长离散 | 浮点级 |
| 异常数据鲁棒性 | 强（自带合理性约束） | 弱（无约束） |
| 典型应用场景 | 数据质量未知时 | 大规模批处理 |

## 项目结构

```
.
├── project_pano.py        # 全景投影核心模块
├── Main6.py               # 完整工作流
├── Main6_old.py           # 迭代法
├── Main6_new.py           # 反向解析法
├── environment.yml        # conda 环境定义
├── requirements.txt       # pip 依赖
└── README.md
```
