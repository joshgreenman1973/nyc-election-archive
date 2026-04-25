"""Fetch NYC election district shapefile from DCP ArcGIS REST in batches."""
import json
import urllib.request
from pathlib import Path

BASE = "https://services5.arcgis.com/GfwWNkhOj9bNBqoJ/ArcGIS/rest/services/NYC_Election_Districts/FeatureServer/0/query"
PAGE = 1000
OUT = Path(__file__).parent.parent / "data" / "raw" / "ed_shapefile.geojson"


def fetch_page(offset: int) -> dict:
    qs = (
        f"where=1%3D1&outFields=ElectDist&outSR=4326&f=geojson"
        f"&resultOffset={offset}&resultRecordCount={PAGE}"
        f"&orderByFields=OBJECTID"
    )
    with urllib.request.urlopen(f"{BASE}?{qs}") as r:
        return json.loads(r.read())


def main() -> None:
    features = []
    offset = 0
    while True:
        page = fetch_page(offset)
        chunk = page.get("features", [])
        features.extend(chunk)
        print(f"offset={offset} got={len(chunk)} total={len(features)}")
        if not page.get("properties", {}).get("exceededTransferLimit") and len(chunk) < PAGE:
            break
        offset += PAGE
    fc = {"type": "FeatureCollection", "features": features}
    OUT.write_text(json.dumps(fc))
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes, {len(features)} features)")


if __name__ == "__main__":
    main()
