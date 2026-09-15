# Building Height Estimation from Google Street View Panoramas

Python code for estimating building heights from Google Street View panoramas and OpenStreetMap (OSM) building footprints, accompanying the manuscript submitted to ***GIScience & Remote Sensing*** (Taylor & Francis).

- **Code (this repository):** https://github.com/wangyuefeng2017/gujigaodu — archived on Zenodo: https://doi.org/[FILL-ZENODO-SOFTWARE-DOI] (MIT License)
- **Data (all measurement outputs, ablation results, reference heights, 505-viewpoint panorama-ID/coordinate index):** Zenodo, https://doi.org/[FILL-ZENODO-DATA-DOI] (CC BY 4.0)
- **Images:** the Google Street View panoramas are © Google and cannot be redistributed under the Google Maps/Google Earth Terms of Service. They can be re-obtained with the released panorama IDs and `paper_pipeline/panorama_rectification/step1_download_panoramas.py`; all image-derived products can then be regenerated with the released pipeline.

## Repository layout

- `Main6.py`, `Main6_old.py`, `Main6_new.py`, `project_pano.py` — refactored implementation (iterative search and closed-form inverse solvers) with unit tests and CI.
- [`paper_pipeline/`](paper_pipeline/) — the **exact experiment code used for the manuscript results**:
  - `height_estimation/v1_20m_distance_filter/` — variant v1 (20 m observation-distance filter);
  - `height_estimation/v2_yoso_iterative/` — proposed variant v2 (iterative refinement, non-binarized masks, YOSO segmentation);
  - `panorama_rectification/` — panorama acquisition and geometric rectification;
  - `visibility_analysis/` — footprint corner visibility and distance constraints (Figs. 3–4);
  - `THIRD_PARTY_CODE.md` — sources and licences of YOSO, SIHE and the upstream rectification project.
- `environment.yml`, `requirements.txt` — dependencies.

## Quick start

```bash
conda env create -f environment.yml
conda activate gujigaodu
python Main6_old.py   # iterative solver
python Main6_new.py   # closed-form inverse solver
```

Inputs (rectified panoramas, building masks, OSM footprints) are configured via paths inside the scripts; see `paper_pipeline/README.md` for the full reproduction workflow.

## Citation

Wang, Y.; Liu, Y.; *et al.* "[FILL: exact manuscript title]." *GIScience & Remote Sensing* (2026). Code: https://doi.org/[FILL-ZENODO-SOFTWARE-DOI] ; data: https://doi.org/[FILL-ZENODO-DATA-DOI].

## License

Code released by the authors is licensed under the MIT License (see [LICENSE](LICENSE)). Third-party components retain their own terms (see `paper_pipeline/THIRD_PARTY_CODE.md`).

---

# 基于 Google Street View 全景图的建筑物高度反演

从街景全景图（Google Street View）和 OSM 建筑物 footprint 反演建筑物高度。配套论文投稿于 *GIScience & Remote Sensing*（Taylor & Francis）。

- **代码（本仓库）：** https://github.com/wangyuefeng2017/gujigaodu ，Zenodo 归档：https://doi.org/[FILL-ZENODO-SOFTWARE-DOI]（MIT 许可）
- **数据（全部测量结果、消融实验、参考高度、505 个视点的 panoId/坐标索引）：** Zenodo，https://doi.org/[FILL-ZENODO-DATA-DOI]（CC BY 4.0）
- **影像说明：** Google 街景全景图版权归 Google，依其服务条款不能再分发；可用公开的 panoId 清单与 `paper_pipeline/panorama_rectification/step1_download_panoramas.py` 重新获取，并用公开流程重新生成全部影像产物。

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
- [`paper_pipeline/`](paper_pipeline/) — **论文实验所用的原始脚本**（两版方法、全景采集与纠正、可见性分析、消融实验），用于逐项复现论文数值

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

论文完整复现流程见 `paper_pipeline/README.md`。

## 方法对比

| 维度 | 迭代法 (Main6_old) | 反向解析法 (Main6_new) |
|------|-------------------|----------------------|
| 算法 | 离散搜索 h ∈ [5,100]m | 闭式解 `h = d·tan(θ) + z` |
| 速度 | 慢（132栋约 3.4s） | 快 30+ 倍（约 0.1s） |
| 精度 | 0.1m 步长离散 | 浮点级 |
| 异常数据鲁棒性 | 强（自带合理性约束） | 弱（无约束） |
| 典型应用场景 | 数据质量未知时 | 大规模批处理 |

## 许可

作者发布的代码采用 MIT 许可（见 [LICENSE](LICENSE)）；第三方组件（YOSO、SIHE、上游纠正项目）遵循其各自条款，见 `paper_pipeline/THIRD_PARTY_CODE.md`。
