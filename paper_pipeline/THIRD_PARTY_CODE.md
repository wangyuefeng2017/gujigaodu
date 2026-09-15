# Third-Party Components — Sources and Licences

The following components are used by the pipeline but are **not redistributed** in this dataset because they are maintained by third parties under their own licences (and, in the case of the SIHE repository, no licence file is present, so default "all rights reserved" applies). Please obtain them from the sources below.

## 1. YOSO — panoptic segmentation (building masks)

- Used to produce the building masks (`svgdata/building_mask_*.jpg`) in the `v2_yoso_iterative` variant.
- Project: YOSO — *You Only Segment Once: Panoptic Segmentation* (NeurIPS 2021).
- Source: https://github.com/hustvl/YOSO  **[VERIFY the exact URL/commit used in your study]**
- Action: clone upstream, note the commit hash in your manuscript/repository, and follow its licence.

## 2. SIHE — comparison method (Fig. 8, "DNN-based" results)

- Yan, Y., Huang, B. (2022). "Estimation of building height using a single street view image via deep neural networks." *ISPRS Journal of Photogrammetry and Remote Sensing*, 192, 83–98. https://doi.org/10.1016/j.isprsjprs.2022.08.006
- Code: the `SIHE-main` folder you used locally (the README's clone URL is truncated). **[FILL: actual GitHub repository URL]**
- The upstream repository ships **without a LICENSE file**; under GitHub's default rules the authors retain all rights. Do not re-publish the SIHE code or its model weight `190418-201834-f8934c6-lr4d10-312k.pth`; link to the upstream repository instead, and consider asking the SIHE authors for redistribution permission. The bundled `lcnn/` component carries its own licence — consult upstream.
- SIHE outputs in the manuscript are reproduced by running the unmodified upstream code on the re-obtained panoramas.

## 3. External panorama-rectification project (`Panorama_Rectification/`, "Simon-py")

- The scripts `simple_rectify.py` … `simple_rectify_v5.py` are simplified derivatives based on the A-Contrario horizon-first vanishing-point detection project you started from.
- **[FILL: original repository URL and authors]** and **[FILL: its licence]** — please verify and record both; only your own modified scripts are released under MIT here.
- Contains compiled helpers (`libmnf_modes.so` / `_linux.so`) and C sources that are not part of this release.

## 4. Panorama download helper

- `step1_download_panoramas.py` uses the third-party `streetview` Python package: https://pypi.org/project/streetview/ (source: https://github.com/robolyst/streetview) **[VERIFY]**.
- Downloading Street View content requires a Google account / API key and remains subject to the Google Maps Platform Terms of Service (https://cloud.google.com/maps-platform/terms) and the Google Maps/Google Earth Permissions Guidelines (https://google.com/permissions/geoguidelines/).

## 5. OpenStreetMap building footprints

- The 132 building footprints (FIDs) come from OpenStreetMap, © OpenStreetMap contributors, ODbL licence: https://www.openstreetmap.org/copyright.

## 6. Google Earth Pro reference measurements

- Reference heights were measured in Google Earth Pro; Google Earth Pro content may be used under its permitted-use guidelines (https://google.com/permissions/geoguidelines/). Only the resulting numeric measurements are shared here, not Google imagery.
