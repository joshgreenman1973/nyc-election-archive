"""Normalize NYC BOE Cast Vote Records to per-ED, per-ballot Mayor primary results.

Inputs:  data/raw/cvr_{year}/**/*.xlsx
Outputs: data/normalized/{year}_dem_mayor_ballots.parquet
         data/normalized/{year}_candidate_map.parquet

Each ballot row keeps: ed (int, AD*1000+ED), choice_1..choice_5 (candidacy id or None).
"""
from __future__ import annotations

import re
import sys
import warnings
from pathlib import Path

import pandas as pd

warnings.filterwarnings("ignore")

ROOT = Path(__file__).parent.parent
RAW = ROOT / "data" / "raw"
OUT = ROOT / "data" / "normalized"
OUT.mkdir(parents=True, exist_ok=True)

YEARS = {
    "2021": {
        "glob": "cvr_2021/PE2021_CVR_Final/*.xlsx",
        "candidacy_map": "cvr_2021/PE2021_CVR_Final/2021P_CandidacyID_To_Name.xlsx",
        "exclude": ["CandidacyID_To_Name"],
    },
    "2025": {
        "glob": "cvr_2025/*.xlsx",
        "candidacy_map": "cvr_2025/Primary Election 2025 - 06-24-2025_CandidacyID_To_Name.xlsx",
        "exclude": ["CandidacyID_To_Name"],
    },
}

PRECINCT_RE = re.compile(r"AD:\s*(\d+)\s*ED:\s*(\d+)")
MAYOR_RE = re.compile(r"DEM Mayor Choice (\d) of 5 Citywide", re.IGNORECASE)


def parse_ed(precinct: str) -> int | None:
    if not isinstance(precinct, str):
        return None
    m = PRECINCT_RE.search(precinct)
    if not m:
        return None
    return int(m.group(1)) * 1000 + int(m.group(2))


def normalize_cell(v):
    """Return candidacy id (int) or None for undervote/overvote/write-in/blank."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"undervote", "overvote", "write-in"} or s.startswith("write"):
            return None
        try:
            return int(s)
        except ValueError:
            return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def process_file(path: Path) -> pd.DataFrame:
    """Read one CVR xlsx, extract precinct + DEM mayor choices."""
    head = pd.read_excel(path, nrows=0)
    mayor_cols = {}
    for col in head.columns:
        m = MAYOR_RE.search(str(col))
        if m:
            mayor_cols[int(m.group(1))] = col
    if not mayor_cols:
        return pd.DataFrame(columns=["ed", "choice_1", "choice_2", "choice_3", "choice_4", "choice_5"])
    use = ["Precinct"] + [mayor_cols[i] for i in sorted(mayor_cols)]
    df = pd.read_excel(path, usecols=use, dtype=str)
    df["ed"] = df["Precinct"].map(parse_ed)
    out = pd.DataFrame({"ed": df["ed"]})
    for i in range(1, 6):
        col = mayor_cols.get(i)
        out[f"choice_{i}"] = df[col].map(normalize_cell) if col else None
    out = out.dropna(subset=["ed"])
    out["ed"] = out["ed"].astype("int32")
    has_any = out[[f"choice_{i}" for i in range(1, 6)]].notna().any(axis=1)
    return out.loc[has_any].reset_index(drop=True)


def process_year(year: str, cfg: dict) -> None:
    files = sorted(RAW.glob(cfg["glob"]))
    files = [f for f in files if not any(ex in f.name for ex in cfg["exclude"])]
    print(f"\n=== {year}: {len(files)} files ===")
    parts = []
    for i, f in enumerate(files, 1):
        df = process_file(f)
        parts.append(df)
        print(f"  [{i}/{len(files)}] {f.name}: {len(df):,} ballots with DEM Mayor vote")
    all_ballots = pd.concat(parts, ignore_index=True)
    for col in [f"choice_{i}" for i in range(1, 6)]:
        all_ballots[col] = all_ballots[col].astype("Int64")
    out_path = OUT / f"{year}_dem_mayor_ballots.csv.gz"
    all_ballots.to_csv(out_path, index=False, compression="gzip")
    print(f"  -> {out_path}: {len(all_ballots):,} total ballots, {all_ballots['ed'].nunique()} EDs")

    cmap = pd.read_excel(RAW / cfg["candidacy_map"])
    cmap.columns = [c.strip() for c in cmap.columns]
    cmap = cmap.rename(columns={"CandidacyID": "candidacy_id", "DefaultBallotName": "name"})
    cmap["candidacy_id"] = cmap["candidacy_id"].astype("Int64")
    cmap.to_csv(OUT / f"{year}_candidate_map.csv", index=False)
    print(f"  -> candidate map: {len(cmap):,} candidacies")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for year, cfg in YEARS.items():
        if only and year != only:
            continue
        process_year(year, cfg)
