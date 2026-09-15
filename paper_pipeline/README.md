# Paper pipeline — exact code used for the manuscript experiments

This folder contains the **exact scripts that produced the results** in the manuscript submitted to *GIScience & Remote Sensing*. The refactored implementation lives at the repository root (`Main6.py`, `Main6_old.py`, `Main6_new.py`, `project_pano.py`); the scripts here are the experiment versions used for the reported numbers and are kept for one-to-one reproducibility.

## Layout

```
paper_pipeline/
├── height_estimation/
│   ├── v1_20m_distance_filter/   # variant v1: updated implementation, 20 m observation-distance filter
│   │   ├── Main6.py
│   │   └── project_pano.py
│   └── v2_yoso_iterative/        # variant v2 (proposed): iterative height refinement,
│       ├── Main6.py              #                  non-binarized masks, YOSO segmentation
│       └── project_pano.py
├── panorama_rectification/       # panorama acquisition & geometric rectification
│   ├── step1_download_panoramas.py
│   ├── step2_rectify_and_project_panoramas.py
│   ├── step3_detect_facades_from_rendering.py
│   ├── step4_detect_assets_from_facades.py
│   └── simple_rectify.py … simple_rectify_v5.py
├── visibility_analysis/          # footprint corner visibility & distance constraints (Figs. 3–4)
│   ├── visiblefootprint1.py
│   ├── visiblefootprint2.py
│   └── visibility_overlay_with_pano.py
├── requirements.txt
└── THIRD_PARTY_CODE.md           # YOSO / SIHE / upstream rectification project sources & licences
```

## Key parameters (`height_estimation/*/Main6.py`)

- Camera height: 2.5 m (fixed)
- Maximum observation distance: 20.0 m
- Plausible building-height bounds: 5–100 m
- Boundary snapping tolerance: 8 px

## Relation to root scripts

The root `Main6_old.py` (iterative discrete search) and `Main6_new.py` (closed-form inverse solution) are cleaned re-implementations of the two solver ideas; the complete experiment workflow (mask-boundary extraction, PCHIP bottom-boundary correction, per-viewpoint Excel output) is in `height_estimation/v2_yoso_iterative/Main6.py`.

## Inputs / outputs

Inputs are paths configured inside each script (rectified panoramas, YOSO building masks, OSM building footprints); outputs are the per-viewpoint workbooks (`bldheightset21_rectified_panorama_Street View *.xlsx`) used to build the released dataset.

All measurement outputs, the 505-viewpoint metadata index (panorama IDs, coordinates, dates), and the reference heights are archived in the companion Zenodo dataset: https://doi.org/10.5281/zenodo.22775001 . The Google Street View panoramas themselves are © Google and are not redistributed; re-acquire them with the panorama IDs and `step1_download_panoramas.py`.
