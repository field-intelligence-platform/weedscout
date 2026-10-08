"""Command line: weedscout --boundary fields.geojson --start 2024-04-01 --end 2024-07-31"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from .anomaly import Settings
from .boundary import BoundaryError, read_fields
from .pipeline import run_field


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="weedscout",
        description="Within-field low-vigour scouting map from Sentinel-2 for each field in a boundary file.",
    )
    p.add_argument("--boundary", required=True, help="Shapefile (.shp/.zip), GeoJSON, KML, GPX or GeoPackage")
    when = p.add_mutually_exclusive_group(required=True)
    when.add_argument("--year", type=int, help="whole growing season of that year (1 March - 31 October); "
                      "each crop is scored in its own growing period. Recommended")
    when.add_argument("--start", help="custom window start, YYYY-MM-DD (needs --end)")
    p.add_argument("--end", help="custom window end, YYYY-MM-DD")
    p.add_argument("--out", default="outputs", help="output folder (one sub-folder per field)")
    p.add_argument("--id-column", help="attribute holding the field id")
    p.add_argument("--max-tile-cloud", type=float, default=80.0,
                   help="loose tile-level cloud pre-filter; the field itself is checked pixel by pixel")
    p.add_argument("--min-zone-ha", type=float, default=Settings.min_zone_ha)
    p.add_argument("--edge-buffer-m", type=float, default=Settings.edge_buffer_m)
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)
    if args.year:
        args.start, args.end = f"{args.year}-03-01", f"{args.year}-10-31"
    elif not args.end:
        p.error("--start needs --end")

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("pyogrio").setLevel(logging.WARNING)
    try:
        fields = read_fields(args.boundary, args.id_column)
    except BoundaryError as e:
        logging.error("%s", e)
        return 2

    settings = Settings(min_zone_ha=args.min_zone_ha, edge_buffer_m=args.edge_buffer_m)
    failed = 0
    for field in fields:
        for w in field.warnings:
            logging.warning("%s: %s", field.field_id, w)
        report = run_field(field, args.start, args.end, Path(args.out), settings, args.max_tile_cloud)
        failed += report["status"] != "ok"
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
