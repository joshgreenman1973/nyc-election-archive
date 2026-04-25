# NYC election archive

Election district-level results for NYC mayoral primaries. Phase 1 covers the 2021 and 2025 Democratic primaries — both first-choice tallies and ranked-choice voting (RCV) final-round tallies, computed per election district from the official Cast Vote Records.

**Live site:** https://joshgreenman1973.github.io/nyc-election-archive/
**Methodology:** [docs/methodology.html](docs/methodology.html)

The NYC Board of Elections does not publish per-ED results for citywide ranked-choice races; it publishes citywide round-by-round PDFs and the raw cast vote records. This repo derives the per-ED tallies that don't exist anywhere else.

## Repo layout

```
data-pipeline/         Python scripts (run in order)
  fetch_shapefile.py   pulls the NYC DCP ED shapefile (paginated ArcGIS REST)
  normalize_cvr.py     extracts DEM Mayor ballots from each year's CVR ZIP
  build_results.py     per-ED first-choice + per-ED RCV elimination
  build_geo.py         joins results to shapefile, emits one GeoJSON per election
data/
  raw/                 BOE CVR ZIPs and the ED GeoJSON (gitignored — fetch with scripts)
  normalized/          per-ballot CSVs and per-ED result CSVs
  tiles/               results_<year>.geojson — one per election, served to the frontend
docs/                  static frontend (MapLibre + vanilla JS)
  index.html
  app.js
  methodology.html
  manifest.json        emitted by build_geo.py
```

## Reproducing the build

Requires Python 3.9+ with `pandas`, `openpyxl`, `requests`. No virtual env or build system — every script is standalone.

```sh
mkdir -p data/raw && cd data/raw
curl -sSL -o cvr_2021.zip "https://www.vote.nyc/sites/default/files/pdf/election_results/2021/20210622Primary%20Election/cvr/PE2021_CVR_Final.zip"
curl -sSL -o cvr_2025.zip "https://www.vote.nyc/sites/default/files/pdf/election_results/2025/20250624Primary%20Election/rcv/2025_Primary_CVR_2025-07-17.zip"
unzip -q cvr_2021.zip -d cvr_2021 && unzip -q cvr_2025.zip -d cvr_2025
cd ../..

python3 data-pipeline/fetch_shapefile.py
python3 data-pipeline/normalize_cvr.py     # ~10 minutes; reads ~50 XLSX files
python3 data-pipeline/build_results.py     # per-ED RCV; ~2 minutes
python3 data-pipeline/build_geo.py         # joins + manifest

# Serve locally
cd docs && python3 -m http.server 8000
```

## What's in the CSVs

`data/normalized/<year>_dem_mayor_ballots.csv.gz` — one row per ballot:

| ed | choice_1 | choice_2 | choice_3 | choice_4 | choice_5 |
|----|----------|----------|----------|----------|----------|

`ed` is `AD * 1000 + ED` (matches `ElectDist` in the shapefile). `choice_N` is a candidacy ID (see `<year>_candidate_map.csv`) or empty for undervote / overvote / write-in.

`data/normalized/<year>_ed_results.csv` — one row per (ED, candidate):

| ed | candidacy_id | name | first_choice | final_round | is_major |
|----|--------------|------|--------------|-------------|----------|

`data/normalized/<year>_ed_summary.csv` — one row per ED with the leading candidate in each round, total ballots, etc.

## Phase 2

Deferred from this release: 2017 / 2013 mayoral primaries (need contemporary ED shapefiles), citywide-elimination RCV for direct comparison with BOE-published numbers, voter-enrollment denominators (FOIL request), aggregate-up views (AD / Council District / NTA), Council and other races.

## License

Code: MIT. Data is public-domain output of NYC government processes; please cite NYC Board of Elections + NYC Department of City Planning.
