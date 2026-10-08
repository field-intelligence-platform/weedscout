"""Read the field-boundary files farmers already have.

Supported: Shapefile (.shp or zipped .zip), GeoJSON, KML, GPX (tracks or
routes walked around the field), GeoPackage. Every feature in the file is
treated as one field.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pyogrio
import shapely
from pyproj import CRS
from shapely.geometry import MultiPolygon, Polygon
from shapely.validation import make_valid

# A boundary larger than this is almost certainly not a single field
# (the v0 AOI was an 8,000 ha desert quadrilateral).
MAX_FIELD_HA = 1000.0
WARN_FIELD_HA = 250.0
# Below this there are too few interior 10 m pixels for field statistics.
MIN_FIELD_HA = 1.0

ID_COLUMNS = ("field_id", "id", "flik", "name", "Name", "NAME")
# Formats whose coordinates are WGS84 by specification.
WGS84_FORMATS = {".geojson", ".json", ".kml", ".kmz", ".gpx"}


class BoundaryError(ValueError):
    """The boundary file cannot be used as a field boundary.

    `code` is a stable machine-readable reason (e.g. "no_crs") that apps can translate."""

    def __init__(self, message: str, code: str = "invalid"):
        super().__init__(message)
        self.code = code


@dataclass
class Field:
    field_id: str
    geometry: Polygon | MultiPolygon  # in `crs`
    crs: CRS  # metric UTM CRS used for all processing
    area_ha: float
    warnings: list[str] = field(default_factory=list)

    @property
    def geometry_wgs84(self):
        return gpd.GeoSeries([self.geometry], crs=self.crs).to_crs(4326).iloc[0]


def utm_crs_for(lon: float, lat: float) -> CRS:
    """WGS84 / UTM zone containing a lon/lat point."""
    zone = int((lon + 180) // 6) % 60 + 1
    return CRS.from_epsg((32600 if lat >= 0 else 32700) + zone)


def _polygonal(geom):
    """Valid polygonal part of a geometry; closes GPX/KML lines into rings."""
    geom = shapely.force_2d(geom)
    if geom.geom_type in ("LineString", "MultiLineString"):
        lines = [geom] if geom.geom_type == "LineString" else list(geom.geoms)
        rings = [Polygon(line.coords) for line in lines if len(line.coords) >= 3]
        geom = MultiPolygon(rings) if len(rings) > 1 else (rings[0] if rings else None)
    if geom is None or geom.is_empty:
        return None
    geom = make_valid(geom)
    if geom.geom_type == "GeometryCollection":
        parts = [g for g in geom.geoms if g.geom_type in ("Polygon", "MultiPolygon")]
        geom = shapely.union_all(parts) if parts else None
    if geom is None or geom.geom_type not in ("Polygon", "MultiPolygon") or geom.area == 0:
        return None
    return geom


def _read_layers(path: Path) -> gpd.GeoDataFrame:
    try:
        if path.suffix.lower() == ".gpx":
            layers = ["tracks", "routes"]
        else:
            layers = [name for name, _ in pyogrio.list_layers(path)]
    except pyogrio.errors.DataSourceError:
        raise BoundaryError(
            f"{path.name} is not a boundary file this tool can read "
            "(use Shapefile, zipped Shapefile, GeoJSON, KML, GPX or GeoPackage)", "unreadable"
        ) from None
    frames = []
    for layer in layers:
        gdf = gpd.read_file(path, layer=layer)
        if len(gdf) and gdf.geometry.notna().any():
            frames.append(gdf)
    if not frames:
        raise BoundaryError(f"{path.name}: no features found", "no_features")
    crs = frames[0].crs
    return gpd.GeoDataFrame(
        pd.concat([f.to_crs(crs) if f.crs and crs else f for f in frames], ignore_index=True),
        crs=crs,
    )


@dataclass
class FieldCheck:
    """One feature of a boundary file, checked on its own (nothing is raised per feature)."""

    index: int  # position in the file, from 0
    name: str
    status: str  # ok | too_large | too_small | not_polygon
    area_ha: float | None
    repaired: bool  # geometry was invalid and fixed, or a track was closed into a polygon
    geometry_wgs84: Polygon | MultiPolygon | None
    warnings: list[str] = field(default_factory=list)


def _open(path: str | Path):
    path = Path(path)
    if not path.exists():
        raise BoundaryError(f"{path} does not exist", "not_found")
    try:
        gdf = _read_layers(path)
    except BoundaryError:
        raise
    except Exception as e:  # unreadable or unsupported file
        raise BoundaryError(f"{path.name} cannot be read as a boundary file ({e.__class__.__name__})", "unreadable") from e
    if gdf.crs is None:
        if path.suffix.lower() in WGS84_FORMATS:
            gdf = gdf.set_crs(4326)
        else:
            raise BoundaryError(f"{path.name} has no coordinate system (a Shapefile needs its .prj file)", "no_crs")
    return path, gdf


def inspect_fields(path: str | Path, id_column: str | None = None) -> list[FieldCheck]:
    """Check every feature in a boundary file separately, so an app can show which fields are
    usable and why the others are not. Only file-level problems raise BoundaryError."""
    path, gdf = _open(path)
    if id_column is None:
        id_column = next((c for c in ID_COLUMNS if c in gdf.columns), None)
    elif id_column not in gdf.columns:
        raise BoundaryError(f"column '{id_column}' not in {path.name}: {list(gdf.columns)}", "bad_id_column")

    wgs = gdf.to_crs(4326)
    checks: list[FieldCheck] = []
    for i, (row, geom_wgs) in enumerate(zip(gdf.itertuples(), wgs.geometry)):
        raw_id = getattr(row, id_column) if id_column else None
        name = str(raw_id) if raw_id not in (None, "") and str(raw_id) != "nan" else f"field_{i + 1}"
        geom = _polygonal(geom_wgs) if geom_wgs is not None else None
        if geom is None:
            checks.append(FieldCheck(i, name, "not_polygon", None, False, None))
            continue
        repaired = bool(geom_wgs.geom_type.endswith("LineString") or not geom_wgs.is_valid)
        centroid = geom.centroid
        area_ha = gpd.GeoSeries([geom], crs=4326).to_crs(utm_crs_for(centroid.x, centroid.y)).area.iloc[0] / 1e4
        status = "too_large" if area_ha > MAX_FIELD_HA else "too_small" if area_ha < MIN_FIELD_HA else "ok"
        warnings = []
        if status == "ok" and area_ha > WARN_FIELD_HA:
            warnings.append(f"{area_ha:,.0f} ha is unusually large for one field; zones are relative "
                            "to the whole boundary, so mixed crops will show up as anomalies")
        checks.append(FieldCheck(i, name, status, float(area_ha), repaired, geom, warnings))
    return checks


def read_fields(path: str | Path, id_column: str | None = None) -> list[Field]:
    """Read every field in a boundary file, validated and projected to UTM.
    Raises BoundaryError on the first field that cannot be used."""
    checks = inspect_fields(path, id_column)
    name = Path(path).name
    fields: list[Field] = []
    for c in checks:
        if c.status == "not_polygon":
            raise BoundaryError(f"{c.name}: not a polygon (or a closed track) after repair", "not_polygon")
        if c.status == "too_large":
            raise BoundaryError(f"{c.name}: {c.area_ha:,.0f} ha is not a single field "
                                f"(limit {MAX_FIELD_HA:,.0f} ha). Split it into individual fields.", "too_large")
        if c.status == "too_small":
            raise BoundaryError(f"{c.name}: {c.area_ha:.2f} ha is too small for 10 m satellite pixels "
                                f"(minimum {MIN_FIELD_HA} ha)", "too_small")
        centroid = c.geometry_wgs84.centroid
        crs = utm_crs_for(centroid.x, centroid.y)
        geom_utm = gpd.GeoSeries([c.geometry_wgs84], crs=4326).to_crs(crs).iloc[0]
        fields.append(Field(c.name, geom_utm, crs, geom_utm.area / 1e4, list(c.warnings)))
    ids = [f.field_id for f in fields]
    if len(set(ids)) != len(ids):
        raise BoundaryError(f"duplicate field ids in {name}; pass --id-column", "duplicate_ids")
    return fields
