// NYC election archive — MapLibre frontend
// Loads manifest.json and one results_<id>.geojson per election.
// User picks election + round + candidate; map recolors via data-driven style.

const TILES_BASE = ".";  // results_<year>.geojson live alongside index.html

const params = new URLSearchParams(location.search);
const tilesBase = params.get("tiles") || TILES_BASE;

// Self-contained dark style: solid background + dim OSM raster tiles. No external
// vector style dependency, so the app loads even if a CDN is blocked.
const STYLE = {
  version: 8,
  glyphs: "https://demotiles.maplibre.org/font/{fontstack}/{range}.pbf",
  sources: {
    osm: {
      type: "raster",
      tiles: [
        "https://a.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://b.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png",
      ],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
    },
  },
  layers: [
    { id: "bg", type: "background", paint: { "background-color": "#0e0f12" } },
    {
      id: "osm",
      type: "raster",
      source: "osm",
      paint: {
        "raster-opacity": 0.35,
        "raster-saturation": -0.6,
        "raster-brightness-max": 0.45,
      },
    },
  ],
};
const map = new maplibregl.Map({
  container: "map",
  style: STYLE,
  center: [-73.95, 40.72],
  zoom: 10,
  maxZoom: 16,
  minZoom: 9,
});
map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");

const state = {
  manifest: null,
  data: {},        // election id -> geojson
  election: null,  // election id (e.g. "2025_general_mayor")
  round: "fc",     // "fc" or "fr"; locked to "fc" for non-RCV elections
  candidate: null,
  compare: "",     // "" or "<id>:<round>:<slug>"
};

const els = {
  election: document.getElementById("election"),
  round: document.getElementById("round-toggle"),
  candidate: document.getElementById("candidate"),
  compare: document.getElementById("compare"),
  legendTitle: document.getElementById("legend-title"),
  legendBar: document.getElementById("legend-bar"),
  legendTicks: document.getElementById("legend-ticks"),
  hover: document.getElementById("hover-info"),
  tooltip: document.getElementById("tooltip"),
};

const fmt = {
  pct: v => (v == null ? "—" : v.toFixed(1) + "%"),
  int: v => (v == null ? "—" : v.toLocaleString()),
};

// Diverging palette for diff (-30..+30 percentage points), sequential for share (0..70%)
const SHARE_STOPS = [
  [0,   "#1a1a2e"],
  [10,  "#2e1f4d"],
  [25,  "#5a2d72"],
  [40,  "#a83279"],
  [55,  "#e94e4e"],
  [70,  "#f5b800"],
];
const DIFF_STOPS = [
  [-40, "#0c4a6e"],
  [-20, "#0284c7"],
  [-5,  "#7dd3fc"],
  [0,   "#3a3d45"],
  [5,   "#fbbf24"],
  [20,  "#f97316"],
  [40,  "#dc2626"],
];

function buildColorExpression(prop, mode) {
  const stops = mode === "diff" ? DIFF_STOPS : SHARE_STOPS;
  const expr = ["interpolate", ["linear"], ["coalesce", ["get", prop], 0]];
  for (const [v, c] of stops) expr.push(v, c);
  return expr;
}

function diffExpression(propA, propB) {
  // a - b, but using coalesce so missing -> 0
  return ["-", ["coalesce", ["get", propA], 0], ["coalesce", ["get", propB], 0]];
}

async function loadManifest() {
  const r = await fetch("manifest.json");
  state.manifest = await r.json();
  for (const e of state.manifest.elections) {
    const r2 = await fetch(`${tilesBase}/results_${e.id}.geojson`);
    state.data[e.id] = await r2.json();
  }
}

function currentElection() {
  return state.manifest.elections.find(x => x.id === state.election);
}

function setupSources() {
  // One source, one layer — election change just swaps the data on the source.
  const firstId = state.manifest.elections[0].id;
  map.addSource("ed", { type: "geojson", data: state.data[firstId] });
  map.addLayer({
    id: "ed-fill",
    type: "fill",
    source: "ed",
    paint: {
      "fill-color": "#333",
      "fill-opacity": 0.85,
      "fill-outline-color": "rgba(0,0,0,0.25)",
    },
  });
  map.addLayer({
    id: "ed-outline-hover",
    type: "line",
    source: "ed",
    paint: { "line-color": "#fff", "line-width": 2 },
    filter: ["==", "ed", -1],
  });
  attachInteractions();
}

function populateElectionSelect() {
  els.election.innerHTML = "";
  // Group by year for readability when there are many elections.
  const byYear = new Map();
  for (const e of state.manifest.elections) {
    if (!byYear.has(e.year)) byYear.set(e.year, []);
    byYear.get(e.year).push(e);
  }
  const years = [...byYear.keys()].sort((a, b) => b - a);
  for (const y of years) {
    const elections = byYear.get(y);
    if (elections.length === 1) {
      const e = elections[0];
      const opt = document.createElement("option");
      opt.value = e.id;
      opt.textContent = e.label;
      els.election.appendChild(opt);
    } else {
      const og = document.createElement("optgroup");
      og.label = String(y);
      for (const e of elections) {
        const opt = document.createElement("option");
        opt.value = e.id;
        opt.textContent = e.label.replace(`${y} `, "");
        og.appendChild(opt);
      }
      els.election.appendChild(og);
    }
  }
  // Default to the most recent general (most editorially relevant), else first.
  const def = state.manifest.elections.find(e => e.year === years[0] && e.type === "general")
            || state.manifest.elections[0];
  state.election = def.id;
  els.election.value = def.id;
}

function populateCandidateSelect() {
  const e = currentElection();
  els.candidate.innerHTML = "";
  for (const c of e.majors) {
    const opt = document.createElement("option");
    opt.value = c.slug;
    opt.textContent = c.name;
    els.candidate.appendChild(opt);
  }
  state.candidate = e.majors[0].slug;
  els.candidate.value = state.candidate;
}

function populateCompareSelect() {
  // Same-election compare only — cross-election diff by ED ID is unreliable
  // because ED boundaries change between elections.
  els.compare.innerHTML = '<option value="">— off —</option>';
  const e = currentElection();
  const rounds = e.rcv ? [["fc", "first choice"], ["fr", "RCV final"]] : [["fc", "vote share"]];
  for (const c of e.majors) {
    if (c.slug === state.candidate) continue;
    for (const r of rounds) {
      const opt = document.createElement("option");
      opt.value = `${e.id}:${r[0]}:${c.slug}`;
      opt.textContent = e.rcv ? `${c.name} • ${r[1]}` : c.name;
      els.compare.appendChild(opt);
    }
  }
}

function syncRoundToggleVisibility() {
  const e = currentElection();
  const wrap = els.round.parentElement;  // the .control wrapper
  if (!e.rcv) {
    wrap.style.display = "none";
    state.round = "fc";
    for (const b of els.round.querySelectorAll("button")) {
      b.classList.toggle("active", b.dataset.round === "fc");
    }
  } else {
    wrap.style.display = "";
  }
}

function activeProp() {
  return `${state.round}_${state.candidate}`;
}

function applyStyle() {
  if (!state.election || !state.candidate) return;
  renderLegend(state.compare !== "" ? "diff" : "share");
  // Map updates only happen once MapLibre has finished loading. The legend and
  // hover panel work without it.
  if (!map.getSource("ed")) return;
  const baseSrc = state.data[state.election];
  const compareOn = state.compare !== "";
  if (compareOn) {
    const [eC_id, rC, sC] = state.compare.split(":");
    const cmpSrc = state.data[eC_id];
    const cmpProp = `${rC}_${sC}`;
    const lookup = new Map();
    for (const f of cmpSrc.features) lookup.set(f.properties.ed, f.properties[cmpProp] ?? 0);
    for (const f of baseSrc.features) {
      f.properties.__diff = (f.properties[activeProp()] ?? 0) - (lookup.get(f.properties.ed) ?? 0);
    }
    map.getSource("ed").setData(baseSrc);
    map.setPaintProperty("ed-fill", "fill-color", buildColorExpression("__diff", "diff"));
  } else {
    map.getSource("ed").setData(baseSrc);
    map.setPaintProperty("ed-fill", "fill-color", buildColorExpression(activeProp(), "share"));
  }
}

function shortName(name) {
  // "Andrew M. Cuomo" -> "Cuomo"; "Eric L. Adams" -> "Adams"
  const parts = name.trim().split(/\s+/);
  return parts[parts.length - 1];
}

function roundLabel(rcv, round) {
  if (!rcv) return "vote share";
  return round === "fc" ? "first-choice share" : "RCV final-round share";
}

function renderLegend(mode) {
  const stops = mode === "diff" ? DIFF_STOPS : SHARE_STOPS;
  const grad = stops.map(([v, c], i) => `${c} ${(i / (stops.length - 1)) * 100}%`).join(", ");
  els.legendBar.style.background = `linear-gradient(to right, ${grad})`;
  const e = currentElection();
  const cand = e.majors.find(c => c.slug === state.candidate);

  if (mode === "diff") {
    const [eC_id, rC, sC] = state.compare.split(":");
    const eC = state.manifest.elections.find(x => x.id === eC_id);
    const candC = eC.majors.find(c => c.slug === sC);
    const negColor = stops[0][1];
    const posColor = stops[stops.length - 1][1];
    els.legendTitle.innerHTML = `Where each candidate ran stronger`;
    els.legendTicks.innerHTML = `
      <span style="color:${negColor}; font-weight:600">${shortName(candC.name)} +30 pp</span>
      <span style="color:var(--ink-dim)">even</span>
      <span style="color:${posColor}; font-weight:600">${shortName(cand.name)} +30 pp</span>
    `;
  } else {
    els.legendTicks.innerHTML = stops.map(([v]) => `<span>${v}%</span>`).join("");
    els.legendTitle.innerHTML = `<strong>${cand.name}</strong> — ${roundLabel(e.rcv, state.round)}`;
  }
}

function attachInteractions() {
  map.on("mousemove", "ed-fill", e => {
    const f = e.features[0];
    if (!f) return;
    map.getCanvas().style.cursor = "pointer";
    map.setFilter("ed-outline-hover", ["==", "ed", f.properties.ed]);
    showTooltip(e.point, f.properties);
    renderHover(f.properties);
  });
  map.on("mouseleave", "ed-fill", () => {
    map.getCanvas().style.cursor = "";
    map.setFilter("ed-outline-hover", ["==", "ed", -1]);
    els.tooltip.style.display = "none";
  });
}

function showTooltip(point, p) {
  const e = currentElection();
  const winner = state.round === "fc" ? p.first_winner : p.final_winner;
  const winnerPct = state.round === "fc" ? p.first_winner_pct : p.final_winner_pct;
  const compareOn = state.compare !== "";
  const cand = e.majors.find(c => c.slug === state.candidate);
  const candVal = p[activeProp()];
  let body = "";
  if (compareOn) {
    const [eC_id, rC, sC] = state.compare.split(":");
    const eC = state.manifest.elections.find(x => x.id === eC_id);
    const candC = eC.majors.find(c => c.slug === sC);
    body = `<div class="lead">${cand.name}: ${fmt.pct(candVal)}</div>
      <table>
      <tr><td>vs ${candC.name}</td><td>${fmt.pct(p.__diff)} pp</td></tr>
      </table>`;
  } else {
    const winnerRoundLabel = e.rcv ? (state.round === "fc" ? "1st choice" : "RCV final") : "";
    body = `<div class="lead">${cand.name}: ${fmt.pct(candVal)}</div>
      <table>
      <tr><td>Winner${winnerRoundLabel ? " (" + winnerRoundLabel + ")" : ""}</td><td>${winner || "—"} ${fmt.pct(winnerPct)}</td></tr>
      <tr><td>${e.rcv ? "Ballots cast" : "Votes cast"}</td><td>${fmt.int(p.ballots)}</td></tr>
      </table>`;
  }
  els.tooltip.innerHTML = `<h3>ED ${p.ed} (AD ${Math.floor(p.ed/1000)}, ED ${(p.ed%1000).toString().padStart(3,'0')})</h3>${body}`;
  const x = Math.min(point.x + 14, window.innerWidth - 260);
  const y = Math.min(point.y + 14, window.innerHeight - 140);
  els.tooltip.style.left = x + "px";
  els.tooltip.style.top = y + "px";
  els.tooltip.style.display = "block";
}

function renderHover(p) {
  const e = currentElection();
  const rows = e.majors.map(c => {
    const fc = p[`fc_${c.slug}`];
    const fr = p[`fr_${c.slug}`];
    const display = e.rcv ? `${fmt.pct(fc)} → ${fmt.pct(fr)}` : fmt.pct(fc);
    return `<div class="stat"><span class="k">${c.name}</span><span class="v">${display}</span></div>`;
  }).join("");
  els.hover.innerHTML = `
    <div style="font-size:12px;color:var(--ink-dim);margin-bottom:6px;">ED ${p.ed} • ${fmt.int(p.ballots)} ${e.rcv ? "ballots" : "votes"}</div>
    ${rows}
    ${e.rcv ? '<div style="margin-top:6px;font-size:11px;color:var(--ink-dim);">first choice → RCV final</div>' : ""}
  `;
}

// Wire UI
els.election.addEventListener("change", () => {
  state.election = els.election.value;
  state.compare = "";
  populateCandidateSelect();
  populateCompareSelect();
  syncRoundToggleVisibility();
  applyStyle();
});
els.candidate.addEventListener("change", () => {
  state.candidate = els.candidate.value;
  populateCompareSelect();
  applyStyle();
});
els.compare.addEventListener("change", () => {
  state.compare = els.compare.value;
  applyStyle();
});
els.round.addEventListener("click", e => {
  const btn = e.target.closest("button");
  if (!btn) return;
  state.round = btn.dataset.round;
  for (const b of els.round.querySelectorAll("button")) b.classList.toggle("active", b === btn);
  applyStyle();
});

// Two-phase init: UI loads from manifest immediately (independent of map),
// then map sources/styling attach when MapLibre is ready. This way the
// dropdowns work even if the basemap CDN is slow or blocked.
let _mapReady = false;
let _uiReady = false;

function whenMapReady(fn) {
  if (_mapReady) fn();
  else map.on("load", () => fn());
}

async function initUI() {
  if (_uiReady) return;
  await loadManifest();
  populateElectionSelect();
  populateCandidateSelect();
  populateCompareSelect();
  syncRoundToggleVisibility();
  _uiReady = true;
  whenMapReady(initMap);
}

function initMap() {
  setupSources();   // includes attachInteractions
  applyStyle();
}

map.on("load", () => {
  _mapReady = true;
  if (_uiReady && !map.getSource("ed")) initMap();
});
if (map.isStyleLoaded()) {
  _mapReady = true;
}

initUI();
