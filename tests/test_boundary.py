import json
import shutil

import geopandas as gpd
import pytest
from shapely.geometry import Polygon, box

from weedscout.boundary import BoundaryError, inspect_fields, read_fields, utm_crs_for

# ~16 ha square near Goettingen, lon/lat
LON0, LAT0 = 9.93, 51.53
SQUARE = box(LON0, LAT0, LON0 + 0.0058, LAT0 + 0.0036)


def _gdf(geoms, **cols):
    return gpd.GeoDataFrame(cols, geometry=geoms, crs=4326)


def test_utm_zone_comes_from_the_field():
    assert utm_crs_for(9.93, 51.53).to_epsg() == 32632  # Goettingen
    assert utm_crs_for(-114.3, 38.3).to_epsg() == 32611  # the v0 Nevada AOI was not zone 32
    assert utm_crs_for(151.2, -33.9).to_epsg() == 32756


def test_geojson_multiple_fields_with_ids(tmp_path):
    p = tmp_path / "f.geojson"
    shifted = box(LON0 + 0.01, LAT0, LON0 + 0.0158, LAT0 + 0.0036)
    _gdf([SQUARE, shifted], field_id=["north", "south"]).to_file(p)
    fields = read_fields(p)
    assert [f.field_id for f in fields] == ["north", "south"]
    assert fields[0].crs.to_epsg() == 32632
    assert 14 < fields[0].area_ha < 18


def test_zipped_shapefile(tmp_path):
    d = tmp_path / "shp"
    d.mkdir()
    _gdf([SQUARE], name=["Acker 1"]).to_crs(25832).to_file(d / "field.shp")
    zipped = shutil.make_archive(str(tmp_path / "field"), "zip", d)
    (f,) = read_fields(zipped)
    assert f.field_id == "Acker 1" and 14 < f.area_ha < 18


def test_kml(tmp_path):
    coords = " ".join(f"{x},{y},0" for x, y in SQUARE.exterior.coords)
    p = tmp_path / "field.kml"
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f"<Placemark><name>Schlag 7</name><Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}"
        "</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>"
    )
    (f,) = read_fields(p)
    assert 14 < f.area_ha < 18


def test_kml_placemark_name_wins_over_technical_id(tmp_path):
    coords = " ".join(f"{x},{y},0" for x, y in SQUARE.exterior.coords)
    p = tmp_path / "export.kml"
    p.write_text(
        '<?xml version="1.0" encoding="UTF-8"?><kml xmlns="http://www.opengis.net/kml/2.2"><Document>'
        f'<Placemark id="export.1"><name>Lössacker Nord</name><Polygon><outerBoundaryIs><LinearRing><coordinates>{coords}'
        "</coordinates></LinearRing></outerBoundaryIs></Polygon></Placemark></Document></kml>", encoding="utf-8"
    )
    (c,) = inspect_fields(p)
    assert c.name == "Lössacker Nord"


def test_gpx_track_walked_around_field(tmp_path):
    pts = "".join(f'<trkpt lat="{y}" lon="{x}"></trkpt>' for x, y in SQUARE.exterior.coords)
    p = tmp_path / "walk.gpx"
    p.write_text(
        '<?xml version="1.0"?><gpx version="1.1" creator="test" xmlns="http://www.topografix.com/GPX/1/1">'
        f"<trk><name>boundary</name><trkseg>{pts}</trkseg></trk></gpx>"
    )
    (f,) = read_fields(p)
    assert 14 < f.area_ha < 18


def test_self_intersecting_polygon_is_repaired(tmp_path):
    bowtie = Polygon([(LON0, LAT0), (LON0 + 0.006, LAT0 + 0.004), (LON0 + 0.006, LAT0), (LON0, LAT0 + 0.004)])
    p = tmp_path / "bowtie.geojson"
    _gdf([bowtie]).to_file(p)
    (f,) = read_fields(p)
    assert f.geometry.is_valid and f.area_ha > 5


def test_rejects_area_that_is_not_a_field(tmp_path):
    """The v0 AOI: an ~8,000 ha quadrilateral in the Nevada desert."""
    nevada = Polygon([(-114.2685, 38.3455), (-114.3784, 38.3462), (-114.3280, 38.2634), (-114.2266, 38.2796)])
    p = tmp_path / "v0_aoi.geojson"
    _gdf([nevada]).to_file(p)
    with pytest.raises(BoundaryError, match="not a single field"):
        read_fields(p)


def test_rejects_tiny_polygon(tmp_path):
    p = tmp_path / "tiny.geojson"
    _gdf([box(LON0, LAT0, LON0 + 0.0005, LAT0 + 0.0005)]).to_file(p)
    with pytest.raises(BoundaryError, match="too small"):
        read_fields(p)


def test_unsupported_file_gives_plain_error(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("not a boundary")
    with pytest.raises(BoundaryError, match="not a boundary file"):
        read_fields(p)


def test_shapefile_without_prj_is_rejected(tmp_path):
    _gdf([SQUARE]).to_file(tmp_path / "f.shp")
    (tmp_path / "f.prj").unlink()
    with pytest.raises(BoundaryError, match="coordinate system"):
        read_fields(tmp_path / "f.shp")


def test_example_fields_file_is_valid():
    from pathlib import Path

    p = Path(__file__).parents[1] / "data" / "fields" / "goettingen_example_fields.geojson"
    fields = read_fields(p)
    assert len(fields) == 3
    official = {ft["properties"]["field_id"]: ft["properties"]["area_ha_official"]
                for ft in json.loads(p.read_text())["features"]}
    for f in fields:
        assert abs(f.area_ha - official[f.field_id]) / official[f.field_id] < 0.01


def test_inspect_reports_every_field_without_raising(tmp_path):
    from weedscout.boundary import inspect_fields

    bowtie = Polygon([(LON0, LAT0), (LON0 + 0.006, LAT0 + 0.004), (LON0 + 0.006, LAT0), (LON0, LAT0 + 0.004)])
    huge = box(LON0, LAT0, LON0 + 0.6, LAT0 + 0.4)
    tiny = box(LON0, LAT0, LON0 + 0.0005, LAT0 + 0.0005)
    p = tmp_path / "mixed.geojson"
    _gdf([SQUARE, bowtie, huge, tiny], name=["Nordacker", "Kreuz", "Gemarkung", "Ecke"]).to_file(p)
    checks = inspect_fields(p)
    assert [c.status for c in checks] == ["ok", "ok", "too_large", "too_small"]
    assert [c.name for c in checks] == ["Nordacker", "Kreuz", "Gemarkung", "Ecke"]
    assert checks[1].repaired and not checks[0].repaired
    assert 14 < checks[0].area_ha < 18 and checks[0].geometry_wgs84.is_valid


def test_file_level_errors_have_codes(tmp_path):
    p = tmp_path / "notes.txt"
    p.write_text("x")
    with pytest.raises(BoundaryError) as e:
        read_fields(p)
    assert e.value.code == "unreadable"
