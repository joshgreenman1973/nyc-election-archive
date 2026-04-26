"""Join per-ED results to ED shapefile and emit one GeoJSON per year (compact, web-ready).

Each feature.properties contains:
  ed, ballots,
  first_winner, first_winner_pct,
  final_winner, final_winner_pct,
  fc_<slug>: first-choice pct for major candidate (e.g. fc_mamdani)
  fr_<slug>: final-round pct for major candidate (e.g. fr_mamdani)

Frontend chooses property to colorize from; this keeps GeoJSON small (one file per year)
and avoids a per-candidate fetch.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
NORM = ROOT / "data" / "normalized"
SITE = ROOT / "docs"
SITE.mkdir(parents=True, exist_ok=True)
TILES = SITE  # write geojsons directly to site/ — they're deployment artifacts

YEARS = ["2021", "2025"]
SHAPEFILE_FOR_YEAR = {
    "2021": "ed_shapefile_2021.geojson",  # DCP nyed_21a (Feb 2021), 5,839 EDs
    "2025": "ed_shapefile.geojson",       # DCP current vintage, 4,247 EDs
}


def slug(name: str) -> str:
    s = name.lower()
    parts = re.findall(r"[a-z]+", s)
    if not parts:
        return "unk"
    last = parts[-1]
    common = {"jr", "sr", "ii", "iii"}
    if last in common and len(parts) > 1:
        last = parts[-2]
    return last[:14]


def build_year(year: str) -> dict:
    summary = pd.read_csv(NORM / f"{year}_ed_summary.csv")
    results = pd.read_csv(NORM / f"{year}_ed_results.csv")
    majors = (
        results.loc[results["is_major"], ["candidacy_id", "name"]]
        .drop_duplicates()
        .sort_values("candidacy_id")
        .to_dict("records")
    )
    slug_for: dict[int, str] = {}
    used: set[str] = set()
    for m in majors:
        s = slug(m["name"])
        base = s
        n = 2
        while s in used:
            s = f"{base}{n}"
            n += 1
        slug_for[int(m["candidacy_id"])] = s
        used.add(s)
        m["slug"] = s

    def s(v):  # NaN/empty → "" (string fields)
        return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)

    def n(v):  # NaN → 0 (numeric fields)
        return 0 if v is None or (isinstance(v, float) and pd.isna(v)) else round(float(v), 1)

    ed_props: dict[int, dict] = {}
    for row in summary.itertuples(index=False):
        ed_props[int(row.ed)] = {
            "ed": int(row.ed),
            "ballots": int(row.ballots),
            "fc_total": int(row.first_choice_total),
            "fr_active": int(row.final_round_active),
            "first_winner": s(row.first_winner),
            "first_winner_pct": n(row.first_winner_pct),
            "final_winner": s(row.final_winner),
            "final_winner_pct": n(row.final_winner_pct),
        }
    for row in results.itertuples(index=False):
        if not row.is_major:
            continue
        ed = int(row.ed)
        if ed not in ed_props:
            continue
        s = slug_for[int(row.candidacy_id)]
        fc_total = ed_props[ed]["fc_total"] or 1
        fr_active = ed_props[ed]["fr_active"] or 1
        ed_props[ed][f"fc_{s}"] = round(int(row.first_choice) / fc_total * 100, 1)
        ed_props[ed][f"fr_{s}"] = round(int(row.final_round) / fr_active * 100, 1)
        ed_props[ed][f"v_{s}"] = int(row.first_choice)

    shapes = json.load(open(RAW / SHAPEFILE_FOR_YEAR[year]))
    out_features = []
    matched = unmatched = 0
    for feat in shapes["features"]:
        ed = feat["properties"].get("ElectDist")
        if ed is None or ed not in ed_props:
            unmatched += 1
            continue
        out_features.append({
            "type": "Feature",
            "geometry": feat["geometry"],
            "properties": ed_props[ed],
        })
        matched += 1
    print(f"  {year}: matched {matched}, unmatched {unmatched}, no-result EDs {len(ed_props) - matched}")

    fc = {"type": "FeatureCollection", "features": out_features}
    out_path = TILES / f"results_{year}.geojson"
    # allow_nan=False catches any leftover NaN — fail loud rather than write invalid JSON
    out_path.write_text(json.dumps(fc, separators=(",", ":"), allow_nan=False))
    print(f"  -> {out_path} ({out_path.stat().st_size:,} bytes)")
    return {"year": year, "majors": majors, "matched": matched}


def main() -> None:
    manifest = {"elections": []}
    for y in YEARS:
        manifest["elections"].append(build_year(y))
    SITE.mkdir(parents=True, exist_ok=True)
    (SITE / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\n-> {SITE/'manifest.json'}")


if __name__ == "__main__":
    main()
