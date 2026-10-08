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
    """The boundary file cannot be used as a field boundary."""


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
            "(use Shapefile, zipped Shapefile, GeoJSON, KML, GPX or GeoPackage)"
        ) from None
    frames = []
    for layer in layers:
        gdf = gpd.read_file(path, layer=layer)
        if len(gdf) and gdf.geometry.notna().any():
            frames.append(gdf)
    if not frames:
        raise BoundaryError(f"{path.name}: no features found")
    crs = frames[0].crs
    return gpd.GeoDataFrame(
        pd.concat([f.to_crs(crs) if f.crs and crs else f for f in frames], ignore_index=True),
        crs=crs,
    )


def read_fields(path: str | Path, id_column: str | None = None) -> list[Field]:
    """Read every field in a boundary file, validated and projected to UTM."""
    path = Path(path)
    if not path.exists():
        raise BoundaryError(f"{path} does not exist")
    gdf = _read_layers(path)

    if gdf.crs is None:
        if path.suffix.lower() in WGS84_FORMATS:
            gdf = gdf.set_crs(4326)
        else:
            raise BoundaryError(
                f"{path.name} has no coordinate system (a Shapefile needs its .prj file)"
            )

    if id_column is None:
        id_column = next((c for c in ID_COLUMNS if c in gdf.columns), None)
    elif id_column not in gdf.columns:
        raise BoundaryError(f"column '{id_column}' not in {path.name}: {list(gdf.columns)}")

    wgs = gdf.to_crs(4326)
    fields: list[Field] = []
    for i, (row, geom_wgs) in enumerate(zip(gdf.itertuples(), wgs.geometry)):
        raw_id = getattr(row, id_column) if id_column else None
        field_id = str(raw_id) if raw_id not in (None, "") else f"field_{i + 1}"
        geom = _polygonal(geom_wgs) if geom_wgs is not None else None
        if geom is None:
            raise BoundaryError(f"{field_id}: not a polygon (or a closed track) after repair")

        centroid = geom.centroid
        crs = utm_crs_for(centroid.x, centroid.y)
        geom_utm = gpd.GeoSeries([geom], crs=4326).to_crs(crs).iloc[0]
        area_ha = geom_utm.area / 1e4

        if area_ha > MAX_FIELD_HA:
            raise BoundaryError(
                f"{field_id}: {area_ha:,.0f} ha is not a single field "
                f"(limit {MAX_FIELD_HA:,.0f} ha). Split it into individual fields."
            )
        if area_ha < MIN_FIELD_HA:
            raise BoundaryError(
                f"{field_id}: {area_ha:.2f} ha is too small for 10 m satellite pixels "
                f"(minimum {MIN_FIELD_HA} ha)"
            )
        warnings = []
        if area_ha > WARN_FIELD_HA:
            warnings.append(
                f"{area_ha:,.0f} ha is unusually large for one field; zones are relative "
                "to the whole boundary, so mixed crops will show up as anomalies"
            )
        fields.append(Field(field_id, geom_utm, crs, area_ha, warnings))

    ids = [f.field_id for f in fields]
    if len(set(ids)) != len(ids):
        raise BoundaryError(f"duplicate field ids in {path.name}; pass --id-column")
    return fields
