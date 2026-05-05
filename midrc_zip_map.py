"""
MIDRC ZIP3 Distribution Map
============================
Queries data.midrc.org for case-level zip code distribution and renders
an interactive bubble-map of the US grouped by 3-digit ZIP prefix.

Authentication
--------------
MIDRC requires a registered account for controlled data.
Provide your API token via:
  • Environment variable:  MIDRC_TOKEN=<your-token>
  • The "API Token" field in the UI (sent as X-MIDRC-Token header)

Run
---
  python midrc_zip_map.py
Then open http://localhost:5001/midrc
"""

import functools
import os
from typing import List, Optional

import pandas as pd
import pgeocode
import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

MIDRC_GUPPY = "https://data.midrc.org/guppy/graphql"
_nomi = pgeocode.Nominatim("us")


# ── Geocoding ─────────────────────────────────────────────────────────────────

@functools.lru_cache(maxsize=1024)
def _zip3_info(zip3: str):
    """
    Return (lat, lon, state_code) for the nearest valid US zip code that begins
    with *zip3*.  Tries several common suffixes; returns (None, None, None) if
    none resolve.
    """
    for suffix in ("01", "00", "11", "21", "02", "50", "51", "03", "99"):
        row = _nomi.query_postal_code(zip3 + suffix)
        if not pd.isna(row.latitude):
            state = str(row.state_code) if not pd.isna(row.state_code) else None
            return float(row.latitude), float(row.longitude), state
    return None, None, None


# ── MIDRC Guppy API ───────────────────────────────────────────────────────────

_ZIP_HISTOGRAM_QUERY = """
{
  _aggregation {
    case {
      zip {
        histogram {
          key
          count
        }
      }
    }
  }
}
"""


def _fetch_zip_histogram(token: Optional[str]) -> List[dict]:
    """POST the histogram aggregation query to MIDRC Guppy."""
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.post(
        MIDRC_GUPPY,
        json={"query": _ZIP_HISTOGRAM_QUERY},
        headers=headers,
        timeout=30,
    )
    resp.raise_for_status()

    body = resp.json()
    if "errors" in body:
        raise RuntimeError(f"GraphQL errors: {body['errors']}")

    histogram = (
        body.get("data", {})
        .get("_aggregation", {})
        .get("case", {})
        .get("zip", {})
        .get("histogram", [])
    )
    return histogram


def _aggregate_to_zip3(histogram: List[dict]):
    """
    Sum case counts by 3-digit ZIP prefix, attach geocoded centroids/states,
    and return (zip3_data, states_with_data) where:
      - zip3_data is a list of {zip3, count, lat, lon, state} sorted by count desc
      - states_with_data is a sorted list of unique 2-letter state codes

    MIDRC may store zip codes as:
      • 3-digit strings (HIPAA-compliant truncation), e.g. "900"
      • 5-digit strings, e.g. "90210"
    Both are normalised to 3-digit prefixes.
    """
    counts: dict[str, int] = {}
    for item in histogram:
        raw = str(item.get("key") or "").strip()
        if not raw or raw.lower() in ("none", "null", ""):
            continue
        if len(raw) <= 3:
            prefix = raw.zfill(3)          # already 3-digit
        else:
            prefix = raw.zfill(5)[:3]      # take first 3 of 5-digit zip

        counts[prefix] = counts.get(prefix, 0) + int(item.get("count", 0))

    zip3_data = []
    states_with_data = set()
    for prefix, count in sorted(counts.items(), key=lambda kv: -kv[1]):
        lat, lon, state = _zip3_info(prefix)
        if lat is not None:
            zip3_data.append({
                "zip3": prefix, "count": count,
                "lat": lat, "lon": lon, "state": state,
            })
            if state:
                states_with_data.add(state)

    return zip3_data, sorted(states_with_data)


# ── API endpoint ──────────────────────────────────────────────────────────────

@app.route("/midrc/api/zip3")
def api_zip3():
    """
    Returns JSON: list of { zip3, count, lat, lon } sorted by count desc.

    Token resolution order:
      1. MIDRC_TOKEN environment variable
      2. X-MIDRC-Token request header (set by the UI)
      3. ?token= query parameter (convenience / curl)
    """
    token = (
        os.environ.get("MIDRC_TOKEN")
        or request.headers.get("X-MIDRC-Token")
        or request.args.get("token")
    ) or None

    try:
        histogram = _fetch_zip_histogram(token)
    except requests.HTTPError as ex:
        code = ex.response.status_code
        msg  = ex.response.text[:300]
        return jsonify({"error": f"MIDRC API returned HTTP {code}: {msg}"}), 502
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500

    if not histogram:
        return jsonify({"error": (
            "No zip histogram data returned. "
            "This field may require authentication — please provide your MIDRC API token."
        )}), 200

    try:
        zip3_data, states_with_data = _aggregate_to_zip3(histogram)
    except Exception as ex:
        return jsonify({"error": f"Processing error: {ex}"}), 500

    return jsonify({"zip3_data": zip3_data, "states_with_data": states_with_data})


# ── Map page ──────────────────────────────────────────────────────────────────

@app.route("/midrc")
def midrc_page():
    return render_template_string(_MAP_HTML)


_MAP_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>MIDRC · ZIP3 Distribution Map</title>
  <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
  <style>
    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: system-ui, sans-serif; background: #f4f6f9; color: #1a1a2e; min-height: 100vh; }

    header {
      background: #1a3a5c;
      color: #fff;
      padding: 1.2rem 2rem;
      display: flex;
      align-items: center;
      gap: 1rem;
    }
    header h1 { font-size: 1.3rem; font-weight: 600; }
    header span { font-size: 0.85rem; opacity: 0.7; }

    .container { max-width: 1400px; margin: 2rem auto; padding: 0 1.5rem; }

    .card {
      background: #fff;
      border-radius: 10px;
      box-shadow: 0 2px 12px rgba(0,0,0,.08);
      padding: 1.5rem 2rem;
      margin-bottom: 1.5rem;
    }
    .card h2 { font-size: 1rem; font-weight: 600; margin-bottom: 1rem; color: #1a3a5c; }

    .token-form { display: flex; gap: .75rem; align-items: flex-end; flex-wrap: wrap; }
    .field { display: flex; flex-direction: column; gap: 4px; flex: 1; min-width: 280px; }
    label { font-size: 0.78rem; font-weight: 600; color: #555; text-transform: uppercase; letter-spacing: .04em; }
    input[type=password] {
      padding: .5rem .75rem;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      font-size: 0.9rem;
      background: #fafafa;
      width: 100%;
    }
    input:focus { outline: 2px solid #1a3a5c; border-color: transparent; background: #fff; }

    button {
      padding: .55rem 1.4rem;
      background: #1a3a5c;
      color: #fff;
      border: none;
      border-radius: 6px;
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      white-space: nowrap;
      height: 38px;
    }
    button:hover:not(:disabled) { background: #0f2540; }
    button:disabled { background: #6b7280; cursor: default; }

    .hint { font-size: 0.78rem; color: #6b7280; margin-top: .35rem; line-height: 1.5; }
    .hint a { color: #2e6da4; }

    .error { color: #c0392b; background: #fdecea; padding: .75rem 1rem; border-radius: 6px; margin-bottom: 1.5rem; font-size: 0.9rem; }

    /* Stats row */
    .stats { display: flex; gap: 1rem; flex-wrap: wrap; margin-bottom: 1.5rem; }
    .stat-box {
      background: #fff;
      border-radius: 10px;
      box-shadow: 0 2px 12px rgba(0,0,0,.08);
      padding: 1.1rem 1.5rem;
      flex: 1;
      min-width: 150px;
    }
    .stat-box .slabel { font-size: 0.72rem; font-weight: 700; color: #6b7280; text-transform: uppercase; letter-spacing: .05em; }
    .stat-box .svalue { font-size: 1.8rem; font-weight: 700; color: #1a3a5c; margin-top: .15rem; }
    .stat-box .ssub   { font-size: 0.78rem; color: #6b7280; margin-top: .1rem; }

    /* Map */
    #map-container { background: #fff; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.08); overflow: hidden; margin-bottom: 1.5rem; }
    #map { width: 100%; height: 620px; }

    /* Spinner */
    #loading { display: none; text-align: center; padding: 3rem; color: #6b7280; }
    .spinner {
      width: 36px; height: 36px;
      border: 3px solid #e5e7eb;
      border-top-color: #1a3a5c;
      border-radius: 50%;
      animation: spin .8s linear infinite;
      margin: 0 auto 1rem;
    }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* Top ZIP3 table */
    .top-table { font-size: 0.84rem; width: 100%; border-collapse: collapse; }
    .top-table th {
      background: #f8fafc; text-align: left; padding: .55rem .85rem;
      font-size: 0.75rem; font-weight: 700; color: #6b7280; text-transform: uppercase;
      letter-spacing: .05em; border-bottom: 1px solid #e5e7eb;
    }
    .top-table td { padding: .55rem .85rem; border-bottom: 1px solid #f1f3f5; }
    .top-table tr:last-child td { border-bottom: none; }
    .top-table tr:hover td { background: #f8fafc; }
    .zip3-badge {
      background: #e8f0fe; color: #1a3a5c;
      padding: .15rem .5rem; border-radius: 4px;
      font-family: monospace; font-weight: 700; font-size: 0.88rem;
    }
    .bar-bg { background: #e8f0fe; border-radius: 3px; height: 8px; width: 100%; min-width: 80px; }
    .bar-fill { background: #1a3a5c; border-radius: 3px; height: 8px; }
  </style>
</head>
<body>

<header>
  <div>
    <h1>MIDRC &nbsp;·&nbsp; 3-Digit ZIP Code Distribution</h1>
    <span>data.midrc.org · Geographic distribution of case data</span>
  </div>
</header>

<div class="container">

  <!-- Token -->
  <div class="card">
    <h2>MIDRC API Access</h2>
    <div class="token-form">
      <div class="field">
        <label>API Token <span style="font-weight:400;text-transform:none;letter-spacing:0">(optional for open data)</span></label>
        <input type="password" id="tokenInput" placeholder="Paste your MIDRC API token here">
        <span class="hint">
          Get your token at <a href="https://data.midrc.org" target="_blank">data.midrc.org</a>
          → Login → Profile → API Keys → Create API Key.<br>
          Leave blank to query only publicly accessible data (zip codes may be restricted).
        </span>
      </div>
      <button id="loadBtn" onclick="loadData()">Load Map</button>
    </div>
  </div>

  <div id="errorBox" class="error" style="display:none"></div>

  <!-- Stats -->
  <div class="stats" id="statsRow" style="display:none">
    <div class="stat-box">
      <div class="slabel">Total Cases</div>
      <div class="svalue" id="statTotal">—</div>
      <div class="ssub">with zip code data</div>
    </div>
    <div class="stat-box">
      <div class="slabel">ZIP3 Regions</div>
      <div class="svalue" id="statRegions">—</div>
      <div class="ssub">distinct 3-digit prefixes</div>
    </div>
    <div class="stat-box">
      <div class="slabel">Top Region</div>
      <div class="svalue" id="statTopZip">—</div>
      <div class="ssub" id="statTopCount">—</div>
    </div>
    <div class="stat-box">
      <div class="slabel">Largest Share</div>
      <div class="svalue" id="statTopPct">—</div>
      <div class="ssub">of total cases</div>
    </div>
  </div>

  <!-- Loading -->
  <div id="loading">
    <div class="spinner"></div>
    <p>Querying MIDRC and geocoding ZIP3 regions… this may take a few seconds.</p>
  </div>

  <!-- Map -->
  <div id="map-container" style="display:none">
    <div id="map"></div>
  </div>

  <!-- Top ZIP3 table -->
  <div id="tableCard" class="card" style="display:none">
    <h2>Top 25 ZIP3 Regions by Case Count</h2>
    <table class="top-table">
      <thead>
        <tr>
          <th>#</th>
          <th>ZIP3 Prefix</th>
          <th>Cases</th>
          <th>Share</th>
          <th style="min-width:120px"></th>
        </tr>
      </thead>
      <tbody id="tableBody"></tbody>
    </table>
  </div>

</div>

<script>
async function loadData() {
  const token = document.getElementById('tokenInput').value.trim();
  const btn   = document.getElementById('loadBtn');

  // Reset UI
  ['errorBox','map-container','tableCard'].forEach(id =>
    document.getElementById(id).style.display = 'none'
  );
  document.getElementById('statsRow').style.display = 'none';
  document.getElementById('loading').style.display  = 'block';
  btn.disabled    = true;
  btn.textContent = 'Loading…';

  try {
    const headers = { 'Content-Type': 'application/json' };
    if (token) headers['X-MIDRC-Token'] = token;

    const resp = await fetch('/midrc/api/zip3', { headers });
    const body = await resp.json();

    if (body.error) throw new Error(body.error);
    const data   = body.zip3_data   || [];
    const states = body.states_with_data || [];
    if (!data.length) throw new Error(
      'No ZIP code data was returned. This field likely requires authentication — ' +
      'please enter your MIDRC API token above.'
    );

    renderStats(data);
    renderMap(data, states);
    renderTable(data);

  } catch (err) {
    const box = document.getElementById('errorBox');
    box.textContent = 'Error: ' + err.message;
    box.style.display = 'block';
  } finally {
    document.getElementById('loading').style.display = 'none';
    btn.disabled    = false;
    btn.textContent = 'Load Map';
  }
}

function renderStats(data) {
  const total = data.reduce((s, d) => s + d.count, 0);
  const pct   = (data[0].count / total * 100).toFixed(1) + '%';
  document.getElementById('statTotal').textContent   = total.toLocaleString();
  document.getElementById('statRegions').textContent = data.length;
  document.getElementById('statTopZip').textContent  = data[0].zip3 + 'xx';
  document.getElementById('statTopCount').textContent = data[0].count.toLocaleString() + ' cases';
  document.getElementById('statTopPct').textContent  = pct;
  document.getElementById('statsRow').style.display  = 'flex';
}

function renderMap(data, states) {
  const total  = data.reduce((s, d) => s + d.count, 0);
  const maxCnt = Math.max(...data.map(d => d.count));

  // Layer 1: choropleth — states with data shaded darker grey
  const stateTrace = {
    type: 'choropleth',
    locationmode: 'USA-states',
    locations: states,
    z: states.map(() => 1),
    colorscale: [[0, '#9ca3af'], [1, '#9ca3af']],
    showscale: false,
    hoverinfo: 'skip',
    marker: { line: { color: '#e5e7eb', width: 0.8 } },
  };

  // Layer 2: bubble markers per ZIP3 prefix
  const bubbleTrace = {
    type: 'scattergeo',
    mode: 'markers',
    lon: data.map(d => d.lon),
    lat: data.map(d => d.lat),
    text: data.map(d =>
      `<b>ZIP3: ${d.zip3}xx</b><br>` +
      `State: ${d.state || '—'}<br>` +
      `Cases: ${d.count.toLocaleString()}<br>` +
      `Share: ${(d.count / total * 100).toFixed(2)}%`
    ),
    hovertemplate: '%{text}<extra></extra>',
    marker: {
      size: data.map(d => 5 + Math.sqrt(d.count / maxCnt) * 46),
      color: data.map(d => d.count),
      colorscale: [
        [0,    '#cfe2f3'],
        [0.15, '#93c5e9'],
        [0.35, '#4a9edd'],
        [0.6,  '#2e6da4'],
        [0.8,  '#1a3a5c'],
        [1,    '#09192c'],
      ],
      cmin: 0,
      cmax: maxCnt,
      colorbar: {
        title: { text: 'Cases', font: { size: 12 } },
        thickness: 14,
        len: 0.65,
        x: 1.01,
        tickfont: { size: 11 },
      },
      line: { width: 0.8, color: 'rgba(255,255,255,0.7)' },
      opacity: 0.85,
    },
  };

  const layout = {
    geo: {
      scope: 'usa',
      projection: { type: 'albers usa' },
      showland: true,
      landcolor: '#eef2f7',
      showlakes: true,
      lakecolor: '#dbeafe',
      showcoastlines: true,
      coastlinecolor: '#94a3b8',
      showstates: true,
      statecolor: '#cbd5e1',
      bgcolor: 'rgba(0,0,0,0)',
    },
    margin: { t: 10, b: 10, l: 10, r: 60 },
    paper_bgcolor: '#fff',
    hoverlabel: {
      bgcolor: '#1a3a5c',
      font: { color: '#fff', size: 13 },
      bordercolor: '#1a3a5c',
    },
  };

  document.getElementById('map-container').style.display = 'block';
  Plotly.newPlot('map', [stateTrace, bubbleTrace], layout, { responsive: true, displayModeBar: false });
}

function renderTable(data) {
  const total  = data.reduce((s, d) => s + d.count, 0);
  const top25  = data.slice(0, 25);
  const maxCnt = top25[0].count;

  const tbody = document.getElementById('tableBody');
  tbody.innerHTML = top25.map((d, i) => {
    const pct     = (d.count / total * 100).toFixed(2);
    const barW    = Math.round(d.count / maxCnt * 100);
    return `
      <tr>
        <td style="color:#6b7280;font-size:.8rem">${i + 1}</td>
        <td><span class="zip3-badge">${d.zip3}xx</span></td>
        <td style="font-variant-numeric:tabular-nums">${d.count.toLocaleString()}</td>
        <td style="color:#6b7280">${pct}%</td>
        <td>
          <div class="bar-bg">
            <div class="bar-fill" style="width:${barW}%"></div>
          </div>
        </td>
      </tr>`;
  }).join('');

  document.getElementById('tableCard').style.display = 'block';
}
</script>

</body>
</html>"""


if __name__ == "__main__":
    app.run(debug=True, port=5001)
