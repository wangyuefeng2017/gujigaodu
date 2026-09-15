# -*- coding: utf-8 -*-
"""Visibility and distance filtering for building-footprint corner points.

The implementation follows Section 3.2.4:

* cast a segment from the camera to every footprint corner and reject the
  corner when another footprint is hit before the target;
* keep a visible corner for height inversion only when its horizontal distance
  is no greater than 20 m by default.

The input available to this project is a 2-D building-footprint Shapefile, so
the occlusion test is performed in footprint/model space.  The interface is
kept separate from the plotting code so the height-inversion scripts can use
exactly the same filter.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Iterable, Optional

import geopandas as gpd
import matplotlib

if os.environ.get("DISPLAY", "") == "":
    matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from matplotlib.ticker import FuncFormatter
import pandas as pd
from pyproj import Transformer
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.ops import transform as shapely_transform


DEFAULT_SHP = r"H:\osm\paris\paris_area2bldt.shp"
DEFAULT_CAMERA = (2.355526, 48.860844, 38.5)  # longitude, latitude, altitude
MAX_DISTANCE_M = 20.0
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "visibility_output"


def _polygon_parts(geometry: Any) -> list[Polygon]:
    if geometry is None or geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    if isinstance(geometry, MultiPolygon):
        return [part for part in geometry.geoms if not part.is_empty]
    if hasattr(geometry, "geoms"):
        parts: list[Polygon] = []
        for part in geometry.geoms:
            parts.extend(_polygon_parts(part))
        return parts
    return []


def _repair_geometry(geometry: Any) -> Any:
    if geometry is None or geometry.is_empty or geometry.is_valid:
        return geometry
    repaired = geometry.buffer(0)
    return repaired if not repaired.is_empty else geometry


def _intersection_distances(segment: LineString, geometry: Any) -> list[float]:
    """Return all intersection positions measured from the camera."""

    if geometry is None or geometry.is_empty:
        return []
    kind = geometry.geom_type
    if kind == "Point":
        return [segment.project(geometry)]
    if kind == "MultiPoint":
        return [segment.project(point) for point in geometry.geoms]
    if kind in {"LineString", "LinearRing"}:
        coords = list(geometry.coords)
        if not coords:
            return []
        return [segment.project(Point(coords[0])), segment.project(Point(coords[-1]))]
    if kind == "Polygon":
        return _intersection_distances(segment, geometry.boundary)
    if hasattr(geometry, "geoms"):
        distances: list[float] = []
        for part in geometry.geoms:
            distances.extend(_intersection_distances(segment, part))
        return distances
    return []


def is_corner_visible(
    camera: Point,
    target_corner: Point,
    target_building_id: str,
    building_geometries: Iterable[tuple[str, Any]],
    tolerance_m: float = 0.05,
) -> tuple[bool, Optional[str]]:
    """Return ``(visible, blocker_id)`` for one footprint corner.

    The target building is excluded explicitly.  Only an intersection strictly
    between the camera and target is a blocker, so an intersection at the
    target endpoint is not incorrectly classified as an obstruction.
    """

    target_distance = camera.distance(target_corner)
    if target_distance <= tolerance_m:
        return True, None

    segment = LineString([camera, target_corner])
    for building_id, geometry in building_geometries:
        if building_id == target_building_id or geometry is None or geometry.is_empty:
            continue
        intersections = geometry.boundary.intersection(segment)
        distances = _intersection_distances(segment, intersections)
        if any(
            tolerance_m < distance < target_distance - tolerance_m
            for distance in distances
        ):
            return False, building_id
    return True, None


def _metric_crs(buildings: gpd.GeoDataFrame):
    if buildings.crs is None:
        raise ValueError(
            "The input Shapefile has no CRS. Use --source-crs, e.g. EPSG:4326."
        )
    if buildings.crs.is_projected:
        return buildings.crs
    estimated = buildings.estimate_utm_crs()
    if estimated is None:
        raise ValueError("Could not estimate a local metric CRS for the input data.")
    return estimated


def _load_buildings(shp_path: str | Path, source_crs: Optional[str] = None):
    buildings = gpd.read_file(shp_path)
    if buildings.crs is None:
        if source_crs is None:
            raise ValueError(
                "The input Shapefile has no CRS. Pass --source-crs, e.g. EPSG:4326."
            )
        buildings = buildings.set_crs(source_crs)

    if "building" in buildings.columns:
        mask = buildings["building"].notna() & buildings["building"].astype(str).str.strip().ne("")
        if mask.any():
            buildings = buildings.loc[mask].copy()
    buildings = buildings.loc[~buildings.geometry.is_empty & buildings.geometry.notna()].copy()
    if buildings.empty:
        raise ValueError("No building footprints were found in the input file.")
    buildings["analysis_id"] = [str(index) for index in buildings.index]
    return buildings


def analyze_buildings(
    shp_path: str | Path = DEFAULT_SHP,
    camera_geo: tuple[float, float, float] = DEFAULT_CAMERA,
    max_distance_m: float = MAX_DISTANCE_M,
    source_crs: Optional[str] = None,
) -> dict[str, Any]:
    """Run visibility and horizontal-distance filtering."""

    if max_distance_m <= 0:
        raise ValueError("max_distance_m must be greater than zero.")

    source_buildings = _load_buildings(shp_path, source_crs=source_crs)
    metric_crs = _metric_crs(source_buildings)
    metric_buildings = source_buildings.to_crs(metric_crs)

    camera_lon, camera_lat, camera_alt = camera_geo
    camera_wgs = gpd.GeoDataFrame(
        {"altitude": [camera_alt]},
        geometry=[Point(camera_lon, camera_lat)],
        crs="EPSG:4326",
    )
    camera_metric = camera_wgs.to_crs(metric_crs).geometry.iloc[0]
    to_metric = Transformer.from_crs(
        source_buildings.crs, metric_crs, always_xy=True
    ).transform

    metric_geometries: list[tuple[str, Any]] = []
    for row in metric_buildings.itertuples():
        metric_geometries.append((str(row.analysis_id), _repair_geometry(row.geometry)))

    records: list[dict[str, Any]] = []
    visible_ids: set[str] = set()
    usable_ids: set[str] = set()

    for source_row, metric_row in zip(
        source_buildings.itertuples(), metric_buildings.itertuples()
    ):
        building_id = str(source_row.analysis_id)
        source_parts = _polygon_parts(source_row.geometry)
        metric_parts = _polygon_parts(metric_row.geometry)

        for part_index, source_part in enumerate(source_parts):
            if part_index < len(metric_parts):
                metric_part = _repair_geometry(metric_parts[part_index])
            else:
                metric_part = _repair_geometry(shapely_transform(to_metric, source_part))
            source_coords = list(source_part.exterior.coords)[:-1]
            if not source_coords:
                continue

            for corner_index, source_xy in enumerate(source_coords):
                target_metric = shapely_transform(
                    to_metric, Point(source_xy[0], source_xy[1])
                )
                visible, blocker_id = is_corner_visible(
                    camera_metric,
                    target_metric,
                    building_id,
                    metric_geometries,
                )
                distance_m = camera_metric.distance(target_metric)
                usable = visible and distance_m <= max_distance_m
                if visible:
                    visible_ids.add(building_id)
                if usable:
                    usable_ids.add(building_id)

                records.append(
                    {
                        "building_id": building_id,
                        "part_index": part_index,
                        "corner_index": corner_index,
                        "source_x": float(source_xy[0]),
                        "source_y": float(source_xy[1]),
                        "metric_x": float(target_metric.x),
                        "metric_y": float(target_metric.y),
                        "distance_m": float(distance_m),
                        "visible": bool(visible),
                        "usable": bool(usable),
                        "blocker_id": blocker_id or "",
                    }
                )

    annotated_source = source_buildings.copy()
    annotated_source["visible"] = annotated_source["analysis_id"].isin(visible_ids)
    annotated_source["usable"] = annotated_source["analysis_id"].isin(usable_ids)
    annotated_metric = metric_buildings.copy()
    annotated_metric["visible"] = annotated_metric["analysis_id"].isin(visible_ids)
    annotated_metric["usable"] = annotated_metric["analysis_id"].isin(usable_ids)

    columns = [
        "building_id", "part_index", "corner_index", "source_x", "source_y",
        "metric_x", "metric_y", "distance_m", "visible", "usable", "blocker_id",
    ]
    corners = pd.DataFrame.from_records(records, columns=columns)
    return {
        "source_path": Path(shp_path),
        "source_crs": source_buildings.crs,
        "metric_crs": metric_crs,
        "camera_geo": camera_geo,
        "camera_metric": camera_metric,
        "max_distance_m": float(max_distance_m),
        "buildings_source": annotated_source,
        "buildings_metric": annotated_metric,
        "corners": corners,
    }


def select_footprint(
    shp_file_path: str | Path,
    camera_geo: tuple[float, float, float],
    max_distance_m: float = MAX_DISTANCE_M,
):
    """Compatibility adapter for the height-inversion scripts.

    The return type remains ``(invisible_points, usable_points)``.  The second
    dictionary now contains only corners passing both filters.
    """

    result = analyze_buildings(shp_file_path, camera_geo, max_distance_m)
    invisible_points: dict[str, list[tuple[float, float]]] = {}
    usable_points: dict[str, list[tuple[float, float]]] = {}
    for row in result["corners"].itertuples(index=False):
        key = str(row.building_id)
        invisible_points.setdefault(key, [])
        usable_points.setdefault(key, [])
        point = (float(row.source_x), float(row.source_y))
        if not row.visible:
            invisible_points[key].append(point)
        if row.usable:
            usable_points[key].append(point)
    usable_points = {key: value for key, value in usable_points.items() if value}
    return invisible_points, usable_points


def save_analysis(result: dict[str, Any], output_dir: str | Path) -> Path:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    source = result["buildings_source"]
    metric = result["buildings_metric"]
    source[source["visible"]].to_file(output_path / "visible_buildings.shp")
    source[source["usable"]].to_file(output_path / "usable_buildings.shp")
    metric[metric["visible"]].to_file(output_path / "visible_buildings_metric.shp")
    metric[metric["usable"]].to_file(output_path / "usable_buildings_metric.shp")

    corners = result["corners"].copy()
    corners_source = gpd.GeoDataFrame(
        corners,
        geometry=[Point(x, y) for x, y in zip(corners.source_x, corners.source_y)],
        crs=result["source_crs"],
    )
    corners_metric = gpd.GeoDataFrame(
        corners,
        geometry=[Point(x, y) for x, y in zip(corners.metric_x, corners.metric_y)],
        crs=result["metric_crs"],
    )
    corners_source[corners_source["visible"]].to_file(output_path / "visible_corners.shp")
    corners_source[corners_source["usable"]].to_file(output_path / "usable_corners.shp")
    corners_metric.to_file(output_path / "corners_metric.shp")
    corners.to_csv(output_path / "corner_visibility.csv", index=False, encoding="utf-8-sig")
    return output_path


def _plot_geometry(ax, geometry: Any, **kwargs):
    """Plot polygon or line geometry without depending on GeoPandas plotting."""

    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type in {"LineString", "LinearRing"}:
        x, y = geometry.xy
        ax.plot(x, y, **kwargs)
        return
    if hasattr(geometry, "geoms") and geometry.geom_type not in {"Polygon", "MultiPolygon"}:
        for part in geometry.geoms:
            _plot_geometry(ax, part, **kwargs)
        return
    for polygon in _polygon_parts(geometry):
        x, y = polygon.exterior.xy
        ax.plot(x, y, **kwargs)


def plot_analysis(result: dict[str, Any], output_path: str | Path, show: bool = False) -> Path:
    """Create a map-style figure close to the supplied reference image."""

    buildings = result["buildings_metric"]
    corners = result["corners"]
    camera = result["camera_metric"]
    max_distance_m = result["max_distance_m"]
    fig, ax = plt.subplots(figsize=(12, 8), dpi=180)

    for row in buildings.itertuples():
        _plot_geometry(ax, row.geometry, color="#a6a6a6", linewidth=0.55, zorder=1)
        if row.visible:
            _plot_geometry(ax, row.geometry, color="#e3342f", linewidth=1.8, zorder=2)
        if row.usable:
            _plot_geometry(ax, row.geometry, color="#1769aa", linewidth=1.8, zorder=3)

    visible = corners[corners["visible"]]
    usable = corners[corners["usable"]]
    ax.scatter(visible["metric_x"], visible["metric_y"], s=13, color="#d62728", zorder=4)
    ax.scatter(
        usable["metric_x"], usable["metric_y"], s=22, color="#54a8d8",
        edgecolor="white", linewidth=0.25, zorder=5,
    )
    _plot_geometry(
        ax, camera.buffer(max_distance_m).boundary,
        color="#202020", linestyle="--", linewidth=1.4, zorder=6,
    )
    ax.scatter(
        [camera.x], [camera.y], marker="*", s=230, color="#b22222",
        edgecolor="black", linewidth=0.7, zorder=7,
    )

    ax.set_aspect("equal", adjustable="datalim")
    ax.xaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:.2f}"))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value / 1000:.2f}"))
    ax.set_xlabel("Easting (km)")
    ax.set_ylabel("Northing (km)")
    ax.set_title("Visibility Analysis", fontsize=16, pad=12)
    handles = [
        Patch(facecolor="#d9d9d9", edgecolor="#a6a6a6", label="All buildings"),
        Line2D([0], [0], color="#e3342f", linewidth=2, label="Z-buffer visible buildings"),
        Line2D([0], [0], color="#1769aa", linewidth=2, label="Usable buildings within distance threshold"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#d62728", markersize=6, label="Z-buffer visible corners"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#54a8d8", markersize=7, label=f"Usable corners (≤ {max_distance_m:g} m)"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#b22222", markeredgecolor="black", markersize=12, label="Observer"),
        Line2D([0], [0], color="#202020", linestyle="--", label="Panorama analysis range"),
    ]
    ax.legend(handles=handles, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    fig.text(
        0.01, 0.01,
        f"Visible corners: {len(visible)} | Usable corners: {len(usable)} | "
        f"Distance threshold: {max_distance_m:g} m",
        fontsize=9,
    )
    fig.tight_layout(rect=(0, 0.03, 0.80, 1))
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, bbox_inches="tight")
    if show:
        plt.show()
    else:
        plt.close(fig)
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Filter footprint corners by visibility and distance.")
    parser.add_argument("--shp", default=DEFAULT_SHP, help="Building footprint Shapefile")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--camera-lon", type=float, default=DEFAULT_CAMERA[0])
    parser.add_argument("--camera-lat", type=float, default=DEFAULT_CAMERA[1])
    parser.add_argument("--camera-alt", type=float, default=DEFAULT_CAMERA[2])
    parser.add_argument("--max-distance-m", type=float, default=MAX_DISTANCE_M)
    parser.add_argument("--source-crs", default=None, help="CRS if the input has no CRS metadata")
    parser.add_argument("--show", action="store_true", help="Show the saved figure")
    return parser


def main(argv: Optional[list[str]] = None) -> None:
    args = build_parser().parse_args(argv)
    result = analyze_buildings(
        shp_path=args.shp,
        camera_geo=(args.camera_lon, args.camera_lat, args.camera_alt),
        max_distance_m=args.max_distance_m,
        source_crs=args.source_crs,
    )
    output_dir = save_analysis(result, args.output_dir)
    figure_path = plot_analysis(result, output_dir / "visibility_analysis.png", show=args.show)
    corners = result["corners"]
    print(f"Input: {result['source_path']}")
    print(f"Metric CRS: {result['metric_crs']}")
    print(f"Distance threshold: {result['max_distance_m']:.1f} m")
    print(f"Visible corners: {int(corners['visible'].sum())}")
    print(f"Usable corners: {int(corners['usable'].sum())}")
    print(f"Outputs: {output_dir}")
    print(f"Figure: {figure_path}")


if __name__ == "__main__":
    main()
