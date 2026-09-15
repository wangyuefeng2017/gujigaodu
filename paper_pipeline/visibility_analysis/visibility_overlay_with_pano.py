# -*- coding: utf-8 -*-
"""Visibility-analysis map with a panorama inset and separate legend.

Outputs:
1. ``OUT_MAP``: map, panorama inset, connector line, and right-side legend.
2. ``OUT_LEGEND``: legend-only image for paper layout reuse.

The footprint visibility calculation follows Section 3.2.4 through the shared
``visiblefootprint1.analyze_buildings`` implementation.  The supplied
panorama is placed in a rounded panel at the upper right, with a light dashed
connector from the observer to the panel.
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

# GeoPandas 0.13 expects ``fiona.path``; Fiona 1.10 moved this class to
# ``fiona._ParsedPath``.  Keep the script usable in that common mixed setup.
try:
    import fiona

    if not hasattr(fiona, "path") and hasattr(fiona, "_ParsedPath"):
        class _FionaPathCompat:
            ParsedPath = fiona._ParsedPath

        fiona.path = _FionaPathCompat()
except ImportError:
    pass

if os.environ.get("DISPLAY", "") == "":
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.ticker as mticker
from matplotlib.lines import Line2D
from matplotlib.patches import ConnectionPatch, FancyBboxPatch
from visiblefootprint1 import analyze_buildings


# =========================
# USER PARAMS
# =========================
DIST_THRESH_M = 20.0
PANORAMA_CIRCLE_RADIUS_M = 20.0
SHOW_INVISIBLE_POINTS = False

SHP_PATH = r"F:\gsv3d\osm\parisosmarea\paris_area2bldt.shp"
PANO_IMG_PATH = r"C:\Users\lyx\Desktop\对比方法图\C12.jpg"

OUT_MAP = str(Path(__file__).resolve().parent / "overlay_map.png")
OUT_LEGEND = str(Path(__file__).resolve().parent / "overlay_legend.png")
SAVE_DPI = 600

OBSERVERS_WGS84 = [
    (2.355142014639097, 48.8606812628369, 36.72265625),
]

# =========================
# Style
# =========================
COL_ALL = "#b7b7b7"
COL_ZVIS = "#e3342f"
COL_USABLE = "#1769aa"
COL_USABLE_POINT = "#54a8d8"
COL_PANEL = "#f1f1f1"

LW_ALL = 1.0
LW_ZVIS = 2.4
LW_USABLE = 2.6
LW_CIRCLE = 1.8
S_ZVIS = 25
S_USABLE = 34
S_OBS = 220

FIG_W = 12.0
FIG_H = 8.0
LEGEND_FIG_W = 4.8
LEGEND_FIG_H = 3.6

plt.rcParams.update(
    {
        "font.family": "Times New Roman",
        "font.size": 13,
        "axes.titlesize": 17,
        "axes.titleweight": "bold",
        "axes.labelsize": 15,
        "axes.labelweight": "bold",
        "xtick.labelsize": 12,
        "ytick.labelsize": 12,
        "legend.fontsize": 12,
    }
)


def add_range_circle(ax, center_xy, radius_m):
    cx, cy = center_xy
    ax.add_patch(
        patches.Circle(
            (cx, cy),
            radius_m,
            fill=False,
            edgecolor="black",
            linestyle="--",
            linewidth=LW_CIRCLE,
            zorder=6,
        )
    )


def format_axes_km(ax):
    ax.ticklabel_format(style="plain", useOffset=False, axis="both")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x / 1000:.2f}"))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda y, _: f"{y / 1000:.2f}"))
    ax.set_aspect("equal", adjustable="box")
    for spine in ax.spines.values():
        spine.set_linewidth(1.2)
    ax.set_xlabel("Easting (km)")
    ax.set_ylabel("Northing (km)")


def legend_handles():
    return [
        Line2D([0], [0], color=COL_ALL, lw=LW_ALL + 0.5, label="All buildings"),
        Line2D([0], [0], color=COL_ZVIS, lw=LW_ZVIS, label="Z-buffer visible buildings"),
        Line2D([0], [0], color=COL_USABLE, lw=LW_USABLE,
               label="Usable buildings within\ndistance threshold"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COL_ZVIS,
               markeredgecolor=COL_ZVIS, markersize=7, label="Z-buffer visible corners"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=COL_USABLE_POINT,
               markeredgecolor=COL_USABLE_POINT, markersize=8,
               label=f"Usable corners (≤ {DIST_THRESH_M:g} m)"),
        Line2D([0], [0], marker="*", color="none", markerfacecolor=COL_ZVIS,
               markeredgecolor="black", markersize=13, label="Observer"),
        Line2D([0], [0], color="black", lw=LW_CIRCLE, linestyle="--",
               label="Panorama analysis range"),
    ]


def add_panorama_panel(fig, pano_path, connector_start, map_ax):
    """Add the rounded panorama panel and its map-to-image connector."""

    pano_path = Path(pano_path)
    if not pano_path.exists():
        raise FileNotFoundError(f"Panorama image not found: {pano_path}")

    # Coordinates are figure fractions.  The panel intentionally overlaps the
    # upper-right part of the map, as in the reference image.
    panel = (0.545, 0.685, 0.385, 0.285)
    image_box = (0.580, 0.735, 0.315, 0.180)

    fig.patches.append(
        FancyBboxPatch(
            (panel[0], panel[1]),
            panel[2],
            panel[3],
            boxstyle="round,pad=0.012,rounding_size=0.018",
            transform=fig.transFigure,
            facecolor=COL_PANEL,
            edgecolor="#b8b8b8",
            linewidth=1.2,
            zorder=20,
        )
    )
    fig.text(
        panel[0] + panel[2] / 2,
        panel[1] + panel[3] - 0.025,
        "360° LOCATION PANORAMA",
        ha="center",
        va="center",
        fontsize=13,
        zorder=23,
    )

    pano_ax = fig.add_axes(image_box, zorder=22)
    pano_ax.imshow(plt.imread(pano_path), aspect="auto")
    pano_ax.set_axis_off()
    for spine in pano_ax.spines.values():
        spine.set_visible(True)
        spine.set_edgecolor("#c0c0c0")
        spine.set_linewidth(0.8)

    # Draw after the map so the dashed line remains visible above the map but
    # below the panorama panel.
    connector = ConnectionPatch(
        xyA=connector_start,
        coordsA=map_ax.transData,
        xyB=(panel[0] + 0.20, panel[1]),
        coordsB=fig.transFigure,
        color="#b6c2ce",
        linewidth=1.2,
        linestyle="--",
        zorder=18,
    )
    fig.add_artist(connector)


def main():
    if len(OBSERVERS_WGS84) != 1:
        raise ValueError("当前示例图布局只支持一个 observer")

    # Section 3.2.4 filtering is performed in visiblefootprint1.py:
    # finite ray from camera to each corner, target building excluded, and
    # usable = visible AND horizontal distance <= 20 m.
    analysis = analyze_buildings(
        shp_path=SHP_PATH,
        camera_geo=OBSERVERS_WGS84[0],
        max_distance_m=DIST_THRESH_M,
    )
    buildings_poly = analysis["buildings_metric"]
    corners = analysis["corners"]
    observation_point = analysis["camera_metric"]
    zvis_buildings = buildings_poly[buildings_poly["visible"]]
    usable_buildings = buildings_poly[buildings_poly["usable"]]
    zvis_corners = corners[corners["visible"]]
    usable_corners = corners[corners["usable"]]

    minx, miny, maxx, maxy = buildings_poly.total_bounds
    pad = 40.0
    common_xlim = (minx - pad, maxx + pad)
    common_ylim = (miny - pad, maxy + pad)

    # Leave enough right/top margin for the legend and panorama panel.
    fig = plt.figure(figsize=(FIG_W, FIG_H), facecolor="white")
    map_ax = fig.add_axes([0.075, 0.125, 0.685, 0.745])
    legend_ax = fig.add_axes([0.775, 0.165, 0.215, 0.640])
    legend_ax.set_facecolor("#eeeeee")
    for spine in legend_ax.spines.values():
        spine.set_visible(True)
        spine.set_edgecolor("#e0e0e0")
        spine.set_linewidth(0.8)
    legend_ax.set_xticks([])
    legend_ax.set_yticks([])
    legend_ax.legend(
        handles=legend_handles(),
        loc="center",
        frameon=False,
        fontsize=10.5,
        handlelength=2.6,
        handletextpad=0.8,
        labelspacing=1.0,
        borderpad=0.2,
    )

    buildings_poly.boundary.plot(ax=map_ax, linewidth=LW_ALL, color=COL_ALL, zorder=1)
    if len(zvis_buildings) > 0:
        zvis_buildings.boundary.plot(ax=map_ax, linewidth=LW_ZVIS, color=COL_ZVIS, zorder=2)
    if len(usable_buildings) > 0:
        usable_buildings.boundary.plot(ax=map_ax, linewidth=LW_USABLE, color=COL_USABLE, zorder=3)

    if not zvis_corners.empty:
        map_ax.scatter(
            zvis_corners["metric_x"],
            zvis_corners["metric_y"],
            s=S_ZVIS,
            c=COL_ZVIS,
            edgecolors="none",
            zorder=4,
        )
    if not usable_corners.empty:
        map_ax.scatter(
            usable_corners["metric_x"],
            usable_corners["metric_y"],
            s=S_USABLE,
            c=COL_USABLE_POINT,
            edgecolors="none",
            zorder=5,
        )

    map_ax.scatter(
        [observation_point.x], [observation_point.y], s=S_OBS, c=COL_ZVIS,
        marker="*", edgecolors="black", linewidths=0.5, zorder=8,
    )
    add_range_circle(
        map_ax,
        (observation_point.x, observation_point.y),
        PANORAMA_CIRCLE_RADIUS_M,
    )

    map_ax.set_xlim(*common_xlim)
    map_ax.set_ylim(*common_ylim)
    map_ax.set_title("Visibility Analysis", pad=14)
    format_axes_km(map_ax)
    add_panorama_panel(
        fig,
        PANO_IMG_PATH,
        (observation_point.x, observation_point.y),
        map_ax,
    )

    out_map = Path(OUT_MAP)
    out_map.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_map, dpi=SAVE_DPI, facecolor="white")
    plt.close(fig)

    # Preserve the separate legend output requested by the original script.
    fig_leg, ax_leg = plt.subplots(figsize=(LEGEND_FIG_W, LEGEND_FIG_H))
    ax_leg.axis("off")
    ax_leg.legend(
        handles=legend_handles(),
        loc="center",
        frameon=False,
        handlelength=2.8,
        handletextpad=0.8,
        labelspacing=0.9,
        borderpad=0.2,
    )
    out_legend = Path(OUT_LEGEND)
    out_legend.parent.mkdir(parents=True, exist_ok=True)
    fig_leg.savefig(out_legend, dpi=SAVE_DPI, bbox_inches="tight", transparent=True)
    plt.close(fig_leg)

    print("主图已保存：", out_map)
    print("图例已保存：", out_legend)
    print("PANO_IMG_PATH：", PANO_IMG_PATH)
    print("可见角点数：", len(zvis_corners))
    print("可用角点数：", len(usable_corners))


if __name__ == "__main__":
    main()
