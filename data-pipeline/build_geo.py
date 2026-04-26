"""Join per-ED results to ED shapefile and emit one GeoJSON per election (compact, web-ready).

Each feature.properties contains:
  ed, ballots,
  first_winner, first_winner_pct,
  final_winner, final_winner_pct,
  fc_<slug>: first-choice pct for major candidate (e.g. fc_mamdani)
  fr_<slug>: final-round (or final-tally for non-RCV) pct
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

# Master election registry. Each entry → one results_<id>.geojson + one manifest entry.
# label is what shows in the dropdown. shapefile is the vintage GeoJSON in data/raw/.
# rcv=True means the round toggle is meaningful (separate first-choice vs RCV final).
ELECTIONS = [
    {
        "id": "2017_general_mayor",
        "label": "2017 general — Mayor",
        "year": 2017,
        "type": "general",
        "shapefile": "ed_shapefile_2017.geojson",
        "rcv": False,
    },
    {
        "id": "2021",
        "label": "2021 Democratic primary — Mayor",
        "year": 2021,
        "type": "primary",
        "shapefile": "ed_shapefile_2021.geojson",
        "rcv": True,
    },
    {
        "id": "2021_general_mayor",
        "label": "2021 general — Mayor",
        "year": 2021,
        "type": "general",
        "shapefile": "ed_shapefile_2021.geojson",
        "rcv": False,
    },
    {
        "id": "2025",
        "label": "2025 Democratic primary — Mayor",
        "year": 2025,
        "type": "primary",
        "shapefile": "ed_shapefile.geojson",
        "rcv": True,
    },
    {
        "id": "2025_general_mayor",
        "label": "2025 general — Mayor",
        "year": 2025,
        "type": "general",
        "shapefile": "ed_shapefile.geojson",
        "rcv": False,
    },
]


def slug(name: str) -> str:
    parts = re.findall(r"[a-z]+", name.lower())
    if not parts:
        return "unk"
    last = parts[-1]
    if last in {"jr", "sr", "ii", "iii"} and len(parts) > 1:
        last = parts[-2]
    return last[:14]


def safe_str(v):
    return "" if v is None or (isinstance(v, float) and pd.isna(v)) else str(v)


def safe_num(v):
    return 0 if v is None or (isinstance(v, float) and pd.isna(v)) else round(float(v), 1)


def build_election(spec: dict) -> dict:
    eid = spec["id"]
    print(f"\n=== {eid} ({spec['label']}) ===")
    summary = pd.read_csv(NORM / f"{eid}_ed_summary.csv")
    results = pd.read_csv(NORM / f"{eid}_ed_results.csv")
    majors = (
        results.loc[results["is_major"], ["candidacy_id", "name"]]
        .drop_duplicates()
        .sort_values("name")
        .to_dict("records")
    )
    slug_for: dict[int, str] = {}
    used: set[str] = set()
    for m in majors:
        s = slug(m["name"])
        base, n = s, 2
        while s in used:
            s = f"{base}{n}"
            n += 1
        slug_for[int(m["candidacy_id"])] = s
        used.add(s)
        m["slug"] = s

    ed_props: dict[int, dict] = {}
    for row in summary.itertuples(index=False):
        ed_props[int(row.ed)] = {
            "ed": int(row.ed),
            "ballots": int(row.ballots),
            "fc_total": int(row.first_choice_total),
            "fr_active": int(row.final_round_active),
            "first_winner": safe_str(row.first_winner),
            "first_winner_pct": safe_num(row.first_winner_pct),
            "final_winner": safe_str(row.final_winner),
            "final_winner_pct": safe_num(row.final_winner_pct),
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

    shapes = json.load(open(RAW / spec["shapefile"]))
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
    print(f"  matched {matched} / unmatched {unmatched} / no-shape {len(ed_props) - matched}")

    fc = {"type": "FeatureCollection", "features": out_features}
    out_path = SITE / f"results_{eid}.geojson"
    out_path.write_text(json.dumps(fc, separators=(",", ":"), allow_nan=False))
    print(f"  -> {out_path.name} ({out_path.stat().st_size:,} bytes)")

    return {
        "id": eid,
        "year": spec["year"],
        "label": spec["label"],
        "type": spec["type"],
        "rcv": spec["rcv"],
        "majors": majors,
        "matched": matched,
    }


def main() -> None:
    manifest = {"elections": [build_election(e) for e in ELECTIONS]}
    (SITE / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"\n-> {SITE/'manifest.json'}")


if __name__ == "__main__":
    main()
