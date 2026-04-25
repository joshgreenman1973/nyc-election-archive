"""Roll up CVR ballots to per-ED first-choice tallies and per-ED RCV final-round tallies.

Inputs:  data/normalized/{year}_dem_mayor_ballots.csv.gz
         data/normalized/{year}_candidate_map.csv
Outputs: data/normalized/{year}_ed_results.csv  (long format: ed,candidate,first_choice,final_round)
         data/normalized/{year}_ed_summary.csv  (wide: ed, total_ballots, first_winner, final_winner, ...)

RCV: per-ED, repeatedly eliminate the candidate with fewest active votes; redistribute
those ballots to the next non-eliminated, non-undervote choice. Stop when one candidate
has >50% of remaining active ballots, or only two remain.

Scope: Phase 1 limits the candidate set to "major" candidates (>= 1% of citywide
first-choice). Minor candidates are still counted in first-choice but eliminated together
in round 1 of the RCV simulation, which matches what BOE does at certification.
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).parent.parent
NORM = ROOT / "data" / "normalized"

YEARS = ["2021", "2025"]
MAJOR_THRESHOLD = 0.01  # 1% of citywide first-choice to be "major"
N_CHOICES = 5


def load(year: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    ballots = pd.read_csv(NORM / f"{year}_dem_mayor_ballots.csv.gz")
    cmap = pd.read_csv(NORM / f"{year}_candidate_map.csv")
    return ballots, cmap


def major_candidates(ballots: pd.DataFrame) -> set[int]:
    fc = ballots["choice_1"].dropna().astype(int)
    counts = fc.value_counts()
    threshold = MAJOR_THRESHOLD * len(fc)
    return set(counts[counts >= threshold].index.tolist())


def rcv_round(ballot_choices: list[list[int]], eliminated: set[int]) -> tuple[Counter, int | None]:
    """One RCV round. Returns (active vote counts, candidate to eliminate or None if done)."""
    tally: Counter = Counter()
    for ranking in ballot_choices:
        for cand in ranking:
            if cand in eliminated:
                continue
            tally[cand] += 1
            break
    if not tally:
        return tally, None
    total = sum(tally.values())
    leader, lead_votes = tally.most_common(1)[0]
    if lead_votes > total / 2 or len(tally) <= 2:
        return tally, None
    loser = min(tally, key=lambda c: tally[c])
    return tally, loser


def extract_rankings(ballots: pd.DataFrame, candidates: set[int]) -> list[list[int]]:
    rankings = []
    for row in ballots.itertuples(index=False):
        seen: set[int] = set()
        ranking: list[int] = []
        for i in range(1, N_CHOICES + 1):
            c = getattr(row, f"choice_{i}")
            if pd.isna(c):
                continue
            c = int(c)
            if c in candidates and c not in seen:
                ranking.append(c)
                seen.add(c)
        rankings.append(ranking)
    return rankings


def citywide_elimination_order(all_ballots: pd.DataFrame, candidates: set[int]) -> set[int]:
    """Run RCV on the full election. Return the set of survivors at the final round."""
    rankings = extract_rankings(all_ballots, candidates)
    eliminated: set[int] = set()
    while True:
        tally, loser = rcv_round(rankings, eliminated)
        if loser is None:
            return set(tally.keys())
        eliminated.add(loser)


def tally_final_round(ballots_for_ed: pd.DataFrame, survivors: set[int]) -> Counter:
    """For one ED, tally each ballot to its highest-ranked surviving candidate."""
    tally: Counter = Counter()
    for row in ballots_for_ed.itertuples(index=False):
        seen: set[int] = set()
        for i in range(1, N_CHOICES + 1):
            c = getattr(row, f"choice_{i}")
            if pd.isna(c):
                continue
            c = int(c)
            if c in seen:
                continue
            seen.add(c)
            if c in survivors:
                tally[c] += 1
                break
    return tally


def process_year(year: str) -> None:
    print(f"\n=== {year} ===")
    ballots, cmap = load(year)
    name_of = dict(zip(cmap["candidacy_id"], cmap["name"]))
    majors = major_candidates(ballots)
    print(f"  major candidates ({len(majors)}):", sorted(name_of.get(c, str(c)) for c in majors))
    print(f"  ballots: {len(ballots):,}, EDs: {ballots['ed'].nunique()}")

    survivors = citywide_elimination_order(ballots, majors)
    print(f"  citywide RCV finalists: {sorted(name_of.get(c, str(c)) for c in survivors)}")

    rows = []
    summary_rows = []
    eds = sorted(ballots["ed"].unique())
    for i, ed in enumerate(eds, 1):
        sub = ballots[ballots["ed"] == ed]
        first = sub["choice_1"].dropna().astype(int)
        first_counts = first.value_counts().to_dict()
        final_tally = tally_final_round(sub, survivors)
        active_final = sum(final_tally.values())
        first_winner = max(first_counts, key=first_counts.get) if first_counts else None
        final_winner = max(final_tally, key=final_tally.get) if final_tally else None
        all_cands = set(first_counts) | set(final_tally) | majors
        for c in all_cands:
            rows.append({
                "ed": ed,
                "candidacy_id": c,
                "name": name_of.get(c, f"#{c}"),
                "first_choice": int(first_counts.get(c, 0)),
                "final_round": int(final_tally.get(c, 0)),
                "is_major": c in majors,
            })
        summary_rows.append({
            "ed": ed,
            "ballots": len(sub),
            "first_choice_total": int(len(first)),
            "final_round_active": active_final,
            "first_winner_id": first_winner,
            "first_winner": name_of.get(first_winner, ""),
            "first_winner_pct": (first_counts[first_winner] / len(first) * 100) if first_winner and len(first) else 0,
            "final_winner_id": final_winner,
            "final_winner": name_of.get(final_winner, ""),
            "final_winner_pct": (final_tally[final_winner] / active_final * 100) if final_winner and active_final else 0,
        })
        if i % 500 == 0 or i == len(eds):
            print(f"  processed {i}/{len(eds)} EDs")

    pd.DataFrame(rows).to_csv(NORM / f"{year}_ed_results.csv", index=False)
    pd.DataFrame(summary_rows).to_csv(NORM / f"{year}_ed_summary.csv", index=False)
    print(f"  -> {year}_ed_results.csv ({len(rows):,} rows)")
    print(f"  -> {year}_ed_summary.csv ({len(summary_rows):,} EDs)")


if __name__ == "__main__":
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for y in YEARS:
        if only and y != only:
            continue
        process_year(y)
