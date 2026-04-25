// NYC election archive — MapLibre frontend
// Loads manifest.json and one results_<year>.geojson per election.
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
  data: {},      // year -> geojson
  election: null,
  round: "fc",   // "fc" or "fr"
  candidate: null,
  compare: "",   // "" or "<year>:<round>:<slug>"
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
    const r2 = await fetch(`${tilesBase}/results_${e.year}.geojson`);
    state.data[e.year] = await r2.json();
  }
}

function setupSources() {
  // One source, one layer — election change just swaps the data on the source.
  // (Avoids fragile getLayer().source comparisons across MapLibre versions.)
  const first = state.manifest.elections[0].year;
  map.addSource("ed", { type: "geojson", data: state.data[first] });
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
  for (const e of state.manifest.elections) {
    const opt = document.createElement("option");
    opt.value = e.year;
    opt.textContent = `${e.year} Democratic primary — Mayor`;
    els.election.appendChild(opt);
  }
  state.election = state.manifest.elections[0].year;
}

function populateCandidateSelect() {
  const e = state.manifest.elections.find(x => x.year === state.election);
  els.candidate.innerHTML = "";
  for (const c of e.majors) {
    const opt = document.createElement("option");
    opt.value = c.slug;
    opt.textContent = c.name;
    els.candidate.appendChild(opt);
  }
  // default: most recognizable / leading — pick first
  state.candidate = e.majors[0].slug;
  els.candidate.value = state.candidate;
}

function populateCompareSelect() {
  // Only same-year, same-round comparisons are geographically meaningful: the 2021 and
  // 2025 elections use different ED numbering, so cross-year diff by ED ID is misleading.
  // Keep the option to compare any major candidate to any other within the active year.
  els.compare.innerHTML = '<option value="">— off —</option>';
  const e = state.manifest.elections.find(x => x.year === state.election);
  for (const c of e.majors) {
    if (c.slug === state.candidate) continue;
    for (const r of [["fc", "first choice"], ["fr", "RCV final"]]) {
      const opt = document.createElement("option");
      opt.value = `${e.year}:${r[0]}:${c.slug}`;
      opt.textContent = `${c.name} • ${r[1]}`;
      els.compare.appendChild(opt);
    }
  }
}

function activeProp() {
  return `${state.round}_${state.candidate}`;
}

function applyStyle() {
  if (!state.election || !state.candidate) return;
  const baseSrc = state.data[state.election];
  const compareOn = state.compare !== "";
  if (compareOn) {
    // Compute per-feature diff in JS, write to __diff, then setData.
    const [yC, rC, sC] = state.compare.split(":");
    const cmpSrc = state.data[yC];
    const cmpProp = `${rC}_${sC}`;
    const lookup = new Map();
    for (const f of cmpSrc.features) lookup.set(f.properties.ed, f.properties[cmpProp] ?? 0);
    for (const f of baseSrc.features) {
      f.properties.__diff = (f.properties[activeProp()] ?? 0) - (lookup.get(f.properties.ed) ?? 0);
    }
    map.getSource("ed").setData(baseSrc);
    map.setPaintProperty("ed-fill", "fill-color", buildColorExpression("__diff", "diff"));
    renderLegend("diff");
  } else {
    map.getSource("ed").setData(baseSrc);
    map.setPaintProperty("ed-fill", "fill-color", buildColorExpression(activeProp(), "share"));
    renderLegend("share");
  }
}

function renderLegend(mode) {
  const stops = mode === "diff" ? DIFF_STOPS : SHARE_STOPS;
  const grad = stops.map(([v, c], i) => `${c} ${(i / (stops.length - 1)) * 100}%`).join(", ");
  els.legendBar.style.background = `linear-gradient(to right, ${grad})`;
  els.legendTicks.innerHTML = stops.map(([v]) => `<span>${mode === "diff" ? (v > 0 ? "+" + v : v) : v}%</span>`).join("");
  const e = state.manifest.elections.find(x => x.year === state.election);
  const cand = e.majors.find(c => c.slug === state.candidate);
  if (mode === "diff") {
    const [yC, rC, sC] = state.compare.split(":");
    const eC = state.manifest.elections.find(x => x.year === yC);
    const candC = eC.majors.find(c => c.slug === sC);
    els.legendTitle.innerHTML = `<strong>${cand.name}</strong> ${state.round === "fc" ? "first choice" : "RCV final"} <span style="color:var(--ink-dim)">minus</span> <strong>${candC.name}</strong> ${rC === "fc" ? "first choice" : "RCV final"} (pp)`;
  } else {
    els.legendTitle.innerHTML = `<strong>${cand.name}</strong> — ${state.round === "fc" ? "first-choice" : "RCV final-round"} share`;
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
  const e = state.manifest.elections.find(x => x.year === state.election);
  const winner = state.round === "fc" ? p.first_winner : p.final_winner;
  const winnerPct = state.round === "fc" ? p.first_winner_pct : p.final_winner_pct;
  const compareOn = state.compare !== "";
  const cand = e.majors.find(c => c.slug === state.candidate);
  const candVal = p[activeProp()];
  let body = "";
  if (compareOn) {
    const [yC, rC, sC] = state.compare.split(":");
    const eC = state.manifest.elections.find(x => x.year === yC);
    const candC = eC.majors.find(c => c.slug === sC);
    body = `<div class="lead">${cand.name}: ${fmt.pct(candVal)}</div>
      <table>
      <tr><td>vs ${candC.name} (${yC} ${rC === "fc" ? "1st" : "RCV"})</td><td>${fmt.pct(p.__diff)} pp</td></tr>
      </table>`;
  } else {
    body = `<div class="lead">${cand.name}: ${fmt.pct(candVal)}</div>
      <table>
      <tr><td>Winner (${state.round === "fc" ? "1st choice" : "RCV final"})</td><td>${winner || "—"} ${fmt.pct(winnerPct)}</td></tr>
      <tr><td>Ballots cast</td><td>${fmt.int(p.ballots)}</td></tr>
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
  const e = state.manifest.elections.find(x => x.year === state.election);
  const rows = e.majors.map(c => {
    const fc = p[`fc_${c.slug}`];
    const fr = p[`fr_${c.slug}`];
    return `<div class="stat"><span class="k">${c.name}</span><span class="v">${fmt.pct(fc)} → ${fmt.pct(fr)}</span></div>`;
  }).join("");
  els.hover.innerHTML = `
    <div style="font-size:12px;color:var(--ink-dim);margin-bottom:6px;">ED ${p.ed} • ${fmt.int(p.ballots)} ballots</div>
    ${rows}
    <div style="margin-top:6px;font-size:11px;color:var(--ink-dim);">first choice → RCV final</div>
  `;
}

// Wire UI
els.election.addEventListener("change", () => {
  state.election = els.election.value;
  state.compare = "";
  populateCandidateSelect();
  populateCompareSelect();
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

let _inited = false;
async function init() {
  if (_inited) return;
  _inited = true;
  await loadManifest();
  setupSources();
  populateElectionSelect();
  populateCandidateSelect();
  populateCompareSelect();
  attachInteractions();
  applyStyle();
}
map.on("load", init);
if (map.isStyleLoaded()) init();
