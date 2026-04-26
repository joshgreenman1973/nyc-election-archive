"""Normalize a BOE 'EDLevel' CSV (long format, one row per ED + ballot-channel + party-line)
into the same per-ED summary + results CSVs that build_geo.py consumes.

Used for non-RCV races (general elections, pre-2021 primaries). Multi-party-line
candidates (e.g. "Bill de Blasio (Democratic)" + "Bill de Blasio (Working Families)")
are summed under a single canonical name.

For non-RCV races, first_choice == final_round; the frontend round toggle is harmless
but inert.

Usage:
    python normalize_edlevel.py <election_id> <path_to_edlevel.csv>

election_id is a short slug used as filename prefix, e.g. "2017_general_mayor".
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
NORM = ROOT / "data" / "normalized"
NORM.mkdir(parents=True, exist_ok=True)

CHANNEL_NAMES = {
    "Public Counter",
    "Manually Counted Emergency",
    "Absentee / Military",
    "Affidavit",
    "Federal",
    "Special Presidential",
    "Special Federal",
    "Election Day",
    "Early Voting",
}
NOISE_NAMES = {"Scattered", "Unattributed Write-In", "Write-in", ""}
NAME_PARTY_RE = re.compile(r"^(.+?)\s*\(([^()]+)\)\s*$")


def parse_unit(unit: str) -> tuple[str, str | None]:
    """Return (canonical_name, party) or (channel, None) for ballot-channel rows."""
    if not isinstance(unit, str):
        return ("", None)
    s = unit.strip()
    if s in CHANNEL_NAMES:
        return (s, None)
    m = NAME_PARTY_RE.match(s)
    if m:
        return (m.group(1).strip(), m.group(2).strip())
    return (s, None)


def slug(name: str) -> str:
    parts = re.findall(r"[a-z]+", name.lower())
    if not parts:
        return "unk"
    last = parts[-1]
    if last in {"jr", "sr", "ii", "iii"} and len(parts) > 1:
        last = parts[-2]
    return last[:14]


MAJOR_THRESHOLD = 0.005  # 0.5% citywide for general (lower bar than primaries)


EXPECTED_COLS = ["AD", "ED", "County", "EDAD Status", "Event", "Party/Independent Body",
                 "Office/Position Title", "District Key", "VoteFor", "Unit Name", "Tally"]


def read_edlevel_csv(csv_path: Path) -> pd.DataFrame:
    """Robust reader for BOE EDLevel CSVs.

    Some years (2017) have a normal CSV with one header row.
    Others (2021, 2025) have a broken export where the header is concatenated
    into every data row, producing 22 columns where the first 11 repeat the
    header text and the last 11 are the actual values.
    """
    raw = pd.read_csv(csv_path, header=None, dtype=str, keep_default_na=False)
    if raw.shape[1] == len(EXPECTED_COLS):
        df = raw.iloc[1:].copy()
        df.columns = raw.iloc[0].tolist()
    elif raw.shape[1] == 2 * len(EXPECTED_COLS):
        df = raw.iloc[:, len(EXPECTED_COLS):].copy()
        df.columns = EXPECTED_COLS
    else:
        raise SystemExit(f"Unexpected EDLevel CSV shape: {raw.shape} in {csv_path}")
    return df.reset_index(drop=True)


def process(election_id: str, csv_path: Path) -> None:
    df = read_edlevel_csv(csv_path)
    df = df[df["Office/Position Title"].astype(str).str.strip() == "Mayor"]
    df["ed"] = df["AD"].astype(int) * 1000 + df["ED"].astype(int)
    df["Tally"] = pd.to_numeric(df["Tally"], errors="coerce").fillna(0).astype(int)

    parsed = df["Unit Name"].map(parse_unit)
    df["unit_name"] = parsed.map(lambda x: x[0])
    df["unit_party"] = parsed.map(lambda x: x[1])

    # candidate rows have a party in parens
    cand = df[df["unit_party"].notna()].copy()
    if cand.empty:
        raise SystemExit(f"No candidate rows in {csv_path}")
    # sum across party lines per (ed, candidate)
    by_ed_cand = cand.groupby(["ed", "unit_name"], as_index=False)["Tally"].sum()
    by_ed_cand = by_ed_cand.rename(columns={"unit_name": "name", "Tally": "votes"})

    # determine majors (>= MAJOR_THRESHOLD of citywide)
    citywide = by_ed_cand.groupby("name", as_index=False)["votes"].sum()
    citywide_total = citywide["votes"].sum()
    majors = citywide[citywide["votes"] >= MAJOR_THRESHOLD * citywide_total]["name"].tolist()
    print(f"  major candidates ({len(majors)}):", majors)
    print(f"  total citywide votes (all candidates): {citywide_total:,}")

    # ed_summary: total per ED + winner
    summary = by_ed_cand.groupby("ed").apply(
        lambda g: pd.Series({
            "ballots": int(g["votes"].sum()),
            "first_choice_total": int(g["votes"].sum()),
            "final_round_active": int(g["votes"].sum()),
            "first_winner_id": int(0),
            "first_winner": g.loc[g["votes"].idxmax(), "name"] if g["votes"].sum() else "",
            "first_winner_pct": (g["votes"].max() / g["votes"].sum() * 100) if g["votes"].sum() else 0.0,
            "final_winner_id": int(0),
            "final_winner": g.loc[g["votes"].idxmax(), "name"] if g["votes"].sum() else "",
            "final_winner_pct": (g["votes"].max() / g["votes"].sum() * 100) if g["votes"].sum() else 0.0,
        }),
        include_groups=False,
    ).reset_index()

    # ed_results long format: one row per (ed, candidate)
    # use a fake stable candidacy_id so build_geo can still write v_<slug>
    name_to_id = {n: i + 1 for i, n in enumerate(sorted(set(by_ed_cand["name"])))}
    rows = []
    for r in by_ed_cand.itertuples(index=False):
        rows.append({
            "ed": int(r.ed),
            "candidacy_id": name_to_id[r.name],
            "name": r.name,
            "first_choice": int(r.votes),
            "final_round": int(r.votes),
            "is_major": r.name in majors,
        })
    results = pd.DataFrame(rows)

    summary.to_csv(NORM / f"{election_id}_ed_summary.csv", index=False)
    results.to_csv(NORM / f"{election_id}_ed_results.csv", index=False)
    print(f"  -> {election_id}_ed_summary.csv ({len(summary):,} EDs)")
    print(f"  -> {election_id}_ed_results.csv ({len(results):,} rows)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("usage: normalize_edlevel.py <election_id> <csv_path>")
        sys.exit(1)
    process(sys.argv[1], Path(sys.argv[2]))
