"""
NIH RePORTER – Flask web interface
Render deployment version
"""

import csv
import io
import os
from datetime import date, datetime
import requests
from flask import Flask, render_template_string, request, Response
from flask_caching import Cache

app = Flask(__name__)
cache = Cache(app, config={"CACHE_TYPE": "SimpleCache", "CACHE_DEFAULT_TIMEOUT": 7200})

API_URL   = "https://api.reporter.nih.gov/v2/projects/search"
PAGE_SIZE = 500

HTML = """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>NIH RePORTER – New Grants</title>
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
  <script src="https://cdn.plot.ly/plotly-2.32.0.min.js"></script>
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

    .container { max-width: 1200px; margin: 2rem auto; padding: 0 1.5rem; }

    /* ── Form card ── */
    .card {
      background: #fff;
      border-radius: 10px;
      box-shadow: 0 2px 12px rgba(0,0,0,.08);
      padding: 1.5rem 2rem;
      margin-bottom: 2rem;
    }
    .card-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 1.25rem;
    }
    .card h2 { font-size: 1rem; font-weight: 600; color: #1a3a5c; }

    form { display: flex; flex-wrap: wrap; gap: 1rem; align-items: flex-end; }
    .field { display: flex; flex-direction: column; gap: 4px; }
    label { font-size: 0.78rem; font-weight: 600; color: #555; text-transform: uppercase; letter-spacing: .04em; }
    input, select {
      padding: .5rem .75rem;
      border: 1px solid #d1d5db;
      border-radius: 6px;
      font-size: 0.9rem;
      min-width: 160px;
      background: #fafafa;
    }
    input:focus, select:focus { outline: 2px solid #1a3a5c; border-color: transparent; background: #fff; }

    .type-group { display: flex; flex-direction: column; gap: .3rem; justify-content: center; }
    .type-chk {
      display: flex; align-items: center; gap: .5rem;
      font-size: 0.88rem; font-weight: 500; color: #333;
      cursor: pointer; user-select: none;
    }
    .type-chk input[type=checkbox] {
      min-width: unset; width: 15px; height: 15px;
      padding: 0; cursor: pointer;
      accent-color: #1a3a5c;
    }

    button[type=submit] {
      padding: .55rem 1.4rem;
      background: #1a3a5c;
      color: #fff;
      border: none;
      border-radius: 6px;
      font-size: 0.9rem;
      font-weight: 600;
      cursor: pointer;
      transition: background .15s;
    }
    button[type=submit]:hover { background: #0f2540; }

    /* ── Status / error ── */
    .status { font-size: 0.88rem; color: #555; margin-bottom: 1rem; }
    .error   { color: #c0392b; background: #fdecea; padding: .6rem 1rem; border-radius: 6px; margin-bottom: 1rem; }

    /* ── Results table ── */
    .results-card { background: #fff; border-radius: 10px; box-shadow: 0 2px 12px rgba(0,0,0,.08); overflow: hidden; }
    .results-header {
      display: flex; justify-content: space-between; align-items: center;
      padding: 1rem 1.5rem; border-bottom: 1px solid #e5e7eb;
    }
    .results-header h2 { font-size: 1rem; font-weight: 600; color: #1a3a5c; }
    .badge {
      background: #e8f0fe; color: #1a3a5c;
      padding: .25rem .7rem; border-radius: 999px;
      font-size: 0.78rem; font-weight: 700;
    }
    .btn-download {
      padding: .4rem 1rem;
      background: #fff;
      color: #1a3a5c;
      border: 1.5px solid #1a3a5c;
      border-radius: 6px;
      font-size: 0.82rem;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: .35rem;
      transition: background .15s, color .15s;
    }
    .btn-download:hover { background: #1a3a5c; color: #fff; }

    /* Export PNG button */
    .btn-export {
      padding: .35rem .9rem;
      background: #fff;
      color: #555;
      border: 1.5px solid #d1d5db;
      border-radius: 6px;
      font-size: 0.78rem;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: .3rem;
      transition: background .15s, color .15s, border-color .15s;
    }
    .btn-export:hover { background: #f0f4f8; border-color: #9ca3af; color: #333; }

    .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; font-size: 0.84rem; }
    th {
      background: #f8fafc; text-align: left;
      padding: .7rem 1rem; font-size: 0.75rem; font-weight: 700;
      color: #6b7280; text-transform: uppercase; letter-spacing: .05em;
      border-bottom: 1px solid #e5e7eb;
      white-space: nowrap;
    }
    td { padding: .65rem 1rem; border-bottom: 1px solid #f1f3f5; vertical-align: top; }
    tr:last-child td { border-bottom: none; }
    tr:hover td { background: #f8fafc; }

    .grant-num  { font-family: monospace; font-size: 0.8rem; color: #1a3a5c; white-space: nowrap; }
    .title      { max-width: 340px; }
    .amount     { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
    .amount.big { color: #15803d; font-weight: 600; }
    .date-cell  { white-space: nowrap; }

    .no-results { padding: 2rem; text-align: center; color: #888; }

    /* spinner */
    #spinner { display: none; margin-left: .5rem; }
    .spin {
      width: 16px; height: 16px; border: 2px solid #fff;
      border-top-color: transparent; border-radius: 50%;
      display: inline-block; animation: rot .7s linear infinite; vertical-align: middle;
    }
    @keyframes rot { to { transform: rotate(360deg); } }
  </style>
</head>
<body>

<header>
  <div>
    <h1>NIH RePORTER &nbsp;·&nbsp; New Grant Explorer</h1>
    <span>Data from api.reporter.nih.gov</span><br>
    <span>Rui C Sá</span><br>
    <span><a href="https://github.com/ruicarsa/NIHReporterAPIcall" target="_blank" style="color:#a8c8e8;text-decoration:none;">Source code on GitHub</a></span>
  </div>
</header>

<div class="container">

  <div class="card">
    <h2>Search Parameters</h2>
    <form method="post" onsubmit="document.getElementById('spinner').style.display='inline';">
      <div class="field">
        <label>Institute <span style="font-weight:400;text-transform:none;letter-spacing:0">(blank = all)</span></label>
        <input name="institute" value="{{ institute }}" placeholder="e.g. NIBIB — leave blank for all">
      </div>
      <div class="field">
        <label>Start Date</label>
        <input type="date" name="start_date" value="{{ start_date }}" required>
      </div>
      <div class="field">
        <label>End Date</label>
        <input type="date" name="end_date" value="{{ end_date }}" required>
      </div>
      <div class="field">
        <label>Program Officer <span style="font-weight:400;text-transform:none;letter-spacing:0">(optional)</span></label>
        <input name="po_name" value="{{ po_name }}" placeholder="Last name or full name">
      </div>
      <div class="field">
        <label>Award Type</label>
        <div class="type-group">
          <label class="type-chk">
            <input type="checkbox" name="award_types" value="1" {% if 1 in award_types %}checked{% endif %}>
            Type 1 · New
          </label>
          <label class="type-chk">
            <input type="checkbox" name="award_types" value="2" {% if 2 in award_types %}checked{% endif %}>
            Type 2 · Renewal
          </label>
          <label class="type-chk">
            <input type="checkbox" name="award_types" value="5" {% if 5 in award_types %}checked{% endif %}>
            Type 5 · Continuation
          </label>
        </div>
      </div>
      <button type="submit">
        Search
        <span id="spinner"><span class="spin"></span></span>
      </button>
    </form>
  </div>

  {% if error %}
    <div class="error">{{ error }}</div>
  {% endif %}

  {% if grants is not none %}
    {% if grants %}

      <!-- ── Weekly Cumulative Chart ── -->
      {% if weekly_chart %}
      <div class="card" style="margin-top:2rem;">
        <div class="card-header">
          <h2>Cumulative Grants by Fiscal Week <span style="font-size:.82rem;font-weight:400;color:#6b7280;">(Oct 1 – Sep 30, last 11 fiscal years)</span></h2>
          <button class="btn-export" onclick="exportCharts(['weeklyChart'], 'weekly_chart_{{ institute }}_{{ start_date }}_{{ end_date }}')">&#8681; Export PNG</button>
        </div>
        <div style="height:420px;">
          <canvas id="weeklyChart"></canvas>
        </div>
        <p style="font-size:0.75rem;color:#9ca3af;margin-top:.75rem;">
          X axis = fiscal week (week 1 starts Oct 1). Grey lines = prior 11 fiscal years (full year). Red line = current fiscal year up to requested end date.
        </p>
      </div>
      {% endif %}

      <!-- ── Year-over-Year Comparison ── -->
      {% if year_comparison %}
      <div class="card" style="margin-top:2rem;">
        <div class="card-header">
          <h2>Year-over-Year Comparison <span style="font-size:.82rem;font-weight:400;color:#6b7280;">(same date range)</span></h2>
          <button class="btn-export" onclick="exportCharts(['yoyCountChart','yoyAmountChart'], 'yoy_charts_{{ institute }}_{{ start_date }}_{{ end_date }}')">&#8681; Export PNG</button>
        </div>
        <div style="display:flex;gap:2rem;flex-wrap:wrap;">
          <div style="flex:1;min-width:380px;">
            <canvas id="yoyCountChart"></canvas>
          </div>
          <div style="flex:1;min-width:380px;">
            <canvas id="yoyAmountChart"></canvas>
          </div>
        </div>
      </div>
      {% endif %}

      <!-- ── PO Charts ── -->
      <div class="card" style="margin-top:2rem;">
        <div class="card-header">
          <h2>Grants by Program Officer</h2>
          <button class="btn-export" onclick="exportCharts(['poCountChart','poAmountChart'], 'po_charts_{{ institute }}_{{ start_date }}_{{ end_date }}')">&#8681; Export PNG</button>
        </div>
        <div style="display:flex;gap:2rem;flex-wrap:wrap;">
          <div style="flex:1;min-width:300px;max-height:380px;">
            <canvas id="poCountChart"></canvas>
          </div>
          <div style="flex:1;min-width:300px;max-height:380px;">
            <canvas id="poAmountChart"></canvas>
          </div>
        </div>
      </div>

      <!-- ── Geographic Distribution ── -->
      {% if state_comparison %}
      <div class="card" style="margin-top:2rem;">
        <div class="card-header">
          <h2>Funding by State <span style="font-size:.82rem;font-weight:400;color:#6b7280;">Current year vs. 2021–2024 average (same period)</span></h2>
          <button class="btn-export" onclick="exportStateMap('state_map_{{ institute }}_{{ start_date }}_{{ end_date }}')">&#8681; Export PNG</button>
        </div>
        <div id="stateMap" style="width:100%;height:440px;"></div>
        <p style="font-size:0.75rem;color:#9ca3af;margin-top:.75rem;">
          Color = current year ÷ historical average. Dark blue indicates above-average funding; light blue below average. Grey = no prior-year data.
        </p>
      </div>
      {% endif %}

      <!-- ── Results Table ── -->
      <div class="results-card">
        <div class="results-header">
          <h2>Results for <strong>{{ institute }}</strong>{% if po_name %} · PO: <strong>{{ po_name }}</strong>{% endif %} &nbsp;|&nbsp; {{ start_date }} → {{ end_date }}</h2>
          <div style="display:flex;align-items:center;gap:.75rem;">
            <span class="badge">{{ grants|length }} grants</span>
            <form method="post" action="/download" style="margin:0;">
              <input type="hidden" name="institute"  value="{{ institute }}">
              <input type="hidden" name="start_date" value="{{ start_date }}">
              <input type="hidden" name="end_date"   value="{{ end_date }}">
              <input type="hidden" name="po_name"    value="{{ po_name }}">
              {% for t in award_types %}<input type="hidden" name="award_types" value="{{ t }}">{% endfor %}
              <button type="submit" class="btn-download">&#8681; Download CSV</button>
            </form>
          </div>
        </div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr>
                <th>Grant Number</th>
                <th>Title</th>
                <th>Principal Investigator(s)</th>
                <th>Program Officer</th>
                <th>Organization</th>
                <th class="amount">Award ($)</th>
                <th>Notice Date</th>
                <th>Start Date</th>
              </tr>
            </thead>
            <tbody>
              {% for g in grants %}
              <tr>
                <td class="grant-num">{{ g.project_num or '—' }}</td>
                <td class="title">{{ g.project_title or '—' }}</td>
                <td>
                  {% set pis = g.principal_investigators or [] %}
                  {% if pis %}
                    {{ pis | map(attribute='full_name') | select | join(', ') }}
                  {% else %}—{% endif %}
                </td>
                <td>{{ g.program_officers[0].full_name if g.program_officers else '—' }}</td>
                <td>{{ (g.organization or {}).get('org_name', '—') }}</td>
                <td class="amount {% if g.award_amount and g.award_amount > 500000 %}big{% endif %}">
                  {% if g.award_amount %}
                    ${{ '{:,.0f}'.format(g.award_amount) }}
                  {% else %}—{% endif %}
                </td>
                <td class="date-cell">{{ (g.award_notice_date or '—')[:10] }}</td>
                <td class="date-cell">{{ (g.project_start_date or '—')[:10] }}</td>
              </tr>
              {% endfor %}
            </tbody>
          </table>
        </div>
      </div>

      <script>
        /* ── Shared export helper ── */
        function exportCharts(ids, baseName) {
          ids.forEach((id, i) => {
            const canvas = document.getElementById(id);
            if (!canvas) return;
            const out = document.createElement('canvas');
            out.width  = canvas.width;
            out.height = canvas.height;
            const ctx = out.getContext('2d');
            ctx.fillStyle = '#ffffff';
            ctx.fillRect(0, 0, out.width, out.height);
            ctx.drawImage(canvas, 0, 0);
            const link = document.createElement('a');
            link.download = baseName + (ids.length > 1 ? '_' + (i + 1) : '') + '.png';
            link.href = out.toDataURL('image/png');
            link.click();
          });
        }

        /* ── PO charts ── */
        (function() {
          const grants = {{ grants | tojson }};
          const map = {};
          grants.forEach(g => {
            const pos = g.program_officers || [];
            const name = pos.length ? pos[0].full_name : "Unknown";
            if (!map[name]) map[name] = { count: 0, total: 0 };
            map[name].count++;
            map[name].total += g.award_amount || 0;
          });

          const sorted  = Object.entries(map).sort((a, b) => b[1].count - a[1].count);
          const labels   = sorted.map(e => e[0]);
          const counts   = sorted.map(e => e[1].count);
          const amounts  = sorted.map(e => +(e[1].total / 1e6).toFixed(3));

          const palette = [
            "#1a3a5c","#2e6da4","#4a9edd","#6ab4f0","#8ecef7",
            "#b3e0ff","#d0eeff","#e8f4ff","#0f2540","#3a7bc8"
          ];
          const HIGHLIGHT_NAME = "pereira de sa";
          const colors = labels.map((l, i) =>
            l.toLowerCase().includes(HIGHLIGHT_NAME) ? "#e8720c" : palette[i % palette.length]
          );

          const baseOpts = {
            indexAxis: "y",
            responsive: true,
            maintainAspectRatio: true,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { color: "#f0f0f0" }, ticks: { font: { size: 11 } } },
              y: { ticks: { font: { size: 11 }, color: "#444" }, grid: { display: false } }
            }
          };

          new Chart(document.getElementById("poCountChart"), {
            type: "bar",
            data: {
              labels,
              datasets: [{ label: "# Grants", data: counts, backgroundColor: colors, borderRadius: 4 }]
            },
            options: {
              ...baseOpts,
              plugins: { ...baseOpts.plugins, title: { display: true, text: "Number of Grants", font: { size: 13, weight: "600" }, color: "#1a3a5c", padding: { bottom: 12 } } },
              scales: { ...baseOpts.scales, x: { ...baseOpts.scales.x, ticks: { ...baseOpts.scales.x.ticks, stepSize: 1 } } }
            }
          });

          new Chart(document.getElementById("poAmountChart"), {
            type: "bar",
            data: {
              labels,
              datasets: [{ label: "Total Award ($M)", data: amounts, backgroundColor: colors, borderRadius: 4 }]
            },
            options: {
              ...baseOpts,
              plugins: { ...baseOpts.plugins, title: { display: true, text: "Total Award Amount ($M)", font: { size: 13, weight: "600" }, color: "#1a3a5c", padding: { bottom: 12 } } },
              scales: { ...baseOpts.scales, x: { ...baseOpts.scales.x, ticks: { ...baseOpts.scales.x.ticks, callback: v => "$" + v + "M" } } }
            }
          });
        })();

        /* ── Year-over-Year charts ── */
        {% if year_comparison %}
        (function() {
          const data    = {{ year_comparison | tojson }};
          const labels  = data.map(d => d.label);
          const counts  = data.map(d => d.count);
          const amounts = data.map(d => +(d.amount / 1e6).toFixed(2));
          const colors  = data.map(d => d.current ? "#1a3a5c" : "#93b8d8");

          const sharedOpts = {
            responsive: true,
            plugins: { legend: { display: false } },
            scales: {
              x: { grid: { display: false }, ticks: { font: { size: 11, weight: "600" } } }
            }
          };

          new Chart(document.getElementById("yoyCountChart"), {
            type: "bar",
            data: {
              labels,
              datasets: [{ label: "# Grants", data: counts, backgroundColor: colors, borderRadius: 4, barThickness: 36 }]
            },
            options: {
              ...sharedOpts,
              plugins: {
                ...sharedOpts.plugins,
                title: { display: true, text: "Number of Grants", font: { size: 13, weight: "600" }, color: "#1a3a5c", padding: { bottom: 12 } },
                tooltip: { callbacks: { label: ctx => ` ${ctx.parsed.y} grant${ctx.parsed.y !== 1 ? "s" : ""}` } }
              },
              scales: { ...sharedOpts.scales, y: { grid: { color: "#f0f0f0" }, ticks: { font: { size: 11 }, stepSize: 1 }, title: { display: true, text: "Number of Grants", font: { size: 11 }, color: "#6b7280" } } }
            }
          });

          new Chart(document.getElementById("yoyAmountChart"), {
            type: "bar",
            data: {
              labels,
              datasets: [{ label: "Total Award ($M)", data: amounts, backgroundColor: colors, borderRadius: 4, barThickness: 36 }]
            },
            options: {
              ...sharedOpts,
              plugins: {
                ...sharedOpts.plugins,
                title: { display: true, text: "Total Award Amount ($M)", font: { size: 13, weight: "600" }, color: "#1a3a5c", padding: { bottom: 12 } },
                tooltip: { callbacks: { label: ctx => ` $${ctx.parsed.y.toFixed(2)}M` } }
              },
              scales: { ...sharedOpts.scales, y: { grid: { color: "#f0f0f0" }, ticks: { font: { size: 11 }, callback: v => "$" + v + "M" }, title: { display: true, text: "Total Award ($M)", font: { size: 11 }, color: "#6b7280" } } }
            }
          });
        })();
        {% endif %}

        /* ── Geographic state choropleth ── */
        function exportStateMap(filename) {
          Plotly.downloadImage('stateMap', { format: 'png', filename: filename, width: 960, height: 500 });
        }

        {% if state_comparison %}
        (function() {
          const sd     = {{ state_comparison | tojson }};
          const locs   = sd.map(d => d.state);
          const zVals  = sd.map(d => d.ratio !== null ? d.ratio : 0);
          const texts  = sd.map(d => {
            const r    = d.ratio !== null ? d.ratio.toFixed(2) + '×' : 'no history';
            const curr = '$' + (d.current / 1e6).toFixed(2) + 'M';
            const hist = d.avg_hist > 0 ? '$' + (d.avg_hist / 1e6).toFixed(2) + 'M avg' : 'no history';
            return '<b>' + d.state + '</b><br>Ratio: ' + r + '<br>Current: ' + curr + '<br>Hist avg: ' + hist;
          });

          Plotly.newPlot('stateMap', [{
            type: 'choropleth',
            locationmode: 'USA-states',
            locations: locs,
            z: zVals,
            text: texts,
            hovertemplate: '%{text}<extra></extra>',
            colorscale: [
              [0,      '#d1d5db'],
              [0.0001, '#cce0f5'],
              [0.33,   '#93b8d8'],
              [0.66,   '#2e6da4'],
              [1.0,    '#1a3a5c'],
            ],
            zmin: 0,
            colorbar: {
              title: { text: 'Ratio', side: 'right', font: { size: 12 } },
              thickness: 14,
              len: 0.65,
              tickfont: { size: 11 },
            },
            marker: { line: { color: '#ffffff', width: 1.5 } },
          }], {
            geo: {
              scope: 'usa',
              showlakes: true,
              lakecolor: '#e8f0f7',
              bgcolor: '#f4f6f9',
              landcolor: '#e8ecf0',
              showland: true,
              showframe: false,
              coastlinecolor: '#aaa',
            },
            margin: { t: 10, b: 10, l: 10, r: 80 },
            paper_bgcolor: '#ffffff',
          }, { responsive: true, displayModeBar: false });
        })();
        {% endif %}

        /* ── Weekly cumulative chart ── */
        {% if weekly_chart %}
        (function() {
          const fyData  = {{ weekly_chart | tojson }};
          const xLabels = Array.from({length: 52}, (_, i) => i + 1);

          const dashPatterns = [
            [6,3], [2,3], [10,3], [6,2,2,2], [14,3],
            [4,3,1,3], [8,2,2,2], [3,3,3,3], [10,2,4,2], [2,6]
          ];
          const ptStyles = [
            'circle','triangle','rect','star','cross',
            'crossRot','rectRounded','rectRot','triangle','circle'
          ];

          let histIdx = 0;
          const datasets = fyData.map(d => {
            if (d.current) {
              return {
                label: d.label + ' (current)',
                data: d.data,
                borderColor: '#dc2626',
                backgroundColor: 'transparent',
                borderWidth: 2.5,
                pointRadius: 0,
                pointHoverRadius: 4,
                tension: 0.1,
                spanGaps: false,
                order: 0,
              };
            }
            const i = histIdx++;
            const isFY2025 = d.label === 'FY2025';
            return {
              label: d.label,
              data: d.data,
              borderColor: isFY2025 ? '#2e6da4' : 'rgba(60,60,60,0.45)',
              backgroundColor: 'transparent',
              borderWidth: isFY2025 ? 2 : 1,
              borderDash: isFY2025 ? [] : dashPatterns[i % dashPatterns.length],
              pointStyle: ptStyles[i % ptStyles.length],
              pointRadius: isFY2025 ? 0 : 2,
              pointHoverRadius: 4,
              tension: 0.1,
              spanGaps: true,
              order: isFY2025 ? 0 : 1,
            };
          });

          new Chart(document.getElementById('weeklyChart'), {
            type: 'line',
            data: { labels: xLabels, datasets },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              interaction: { mode: 'index', intersect: false },
              plugins: {
                legend: {
                  display: true,
                  position: 'right',
                  labels: { font: { size: 10 }, padding: 6, usePointStyle: true, pointStyleWidth: 18 }
                },
                tooltip: {
                  callbacks: {
                    title: ctx => `Week ${ctx[0].label} of fiscal year`,
                  }
                }
              },
              scales: {
                x: {
                  title: { display: true, text: 'Fiscal Week (1 = Oct 1)', font: { size: 11 }, color: '#6b7280' },
                  ticks: { font: { size: 10 }, maxTicksLimit: 14 },
                  grid: { color: '#f0f0f0' }
                },
                y: {
                  title: { display: true, text: 'Cumulative Grants', font: { size: 11 }, color: '#6b7280' },
                  ticks: { font: { size: 11 } },
                  grid: { color: '#f0f0f0' }
                }
              }
            }
          });
        })();
        {% endif %}
      </script>

    {% else %}
      <div class="results-card">
        <div class="no-results">No grants found for the selected criteria.</div>
      </div>
    {% endif %}
  {% endif %}

</div>
</body>
</html>
"""


def shift_year(date_str: str, years: int) -> str:
    d = date.fromisoformat(date_str)
    try:
        return d.replace(year=d.year - years).isoformat()
    except ValueError:
        return d.replace(year=d.year - years, day=28).isoformat()


@cache.memoize()
def fetch_count_and_amount(institute: str, start_date: str, end_date: str, award_types: tuple, po_name: str = "") -> tuple:
    criteria: dict = {"award_notice_date": {"from_date": start_date, "to_date": end_date}}
    if institute:
        criteria["agencies"] = [institute]
    if award_types:
        criteria["award_types"] = list(award_types)
    if po_name:
        criteria["po_names"] = [{"any_name": po_name}]

    payload = {
        "criteria": criteria,
        "include_fields": ["AwardAmount"],
        "offset": 0,
        "limit": PAGE_SIZE,
    }

    total_count  = None
    total_amount = 0.0
    fetched      = 0

    while True:
        payload["offset"] = fetched
        resp = requests.post(API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data    = resp.json()
        results = data.get("results", [])
        if total_count is None:
            total_count = data.get("meta", {}).get("total", 0)
        for g in results:
            total_amount += g.get("award_amount") or 0
        fetched += len(results)
        if fetched >= (total_count or 0) or not results:
            break

    return total_count or 0, total_amount


@cache.memoize()
def fetch_state_amounts(institute: str, start_date: str, end_date: str, award_types: tuple, po_name: str = "") -> dict:
    criteria: dict = {"award_notice_date": {"from_date": start_date, "to_date": end_date}}
    if institute:
        criteria["agencies"] = [institute]
    if award_types:
        criteria["award_types"] = list(award_types)
    if po_name:
        criteria["po_names"] = [{"any_name": po_name}]

    payload = {
        "criteria": criteria,
        "include_fields": ["AwardAmount", "Organization"],
        "offset": 0,
        "limit": PAGE_SIZE,
    }

    state_amounts: dict = {}
    fetched      = 0
    total_count  = None

    while True:
        payload["offset"] = fetched
        resp = requests.post(API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data    = resp.json()
        results = data.get("results", [])
        if total_count is None:
            total_count = data.get("meta", {}).get("total", 0)
        for g in results:
            amt   = g.get("award_amount") or 0
            state = (g.get("organization") or {}).get("org_state") or "Unknown"
            state_amounts[state] = state_amounts.get(state, 0) + amt
        fetched += len(results)
        if fetched >= (total_count or 0) or not results:
            break

    return state_amounts


def fiscal_year_start(d: date) -> date:
    return date(d.year, 10, 1) if d.month >= 10 else date(d.year - 1, 10, 1)


@cache.memoize()
def fetch_dates_for_period(institute: str, start: date, end: date, award_types: tuple, po_name: str = "") -> list:
    criteria: dict = {"award_notice_date": {"from_date": start.isoformat(), "to_date": end.isoformat()}}
    if institute:
        criteria["agencies"] = [institute]
    if award_types:
        criteria["award_types"] = list(award_types)
    if po_name:
        criteria["po_names"] = [{"any_name": po_name}]

    payload = {
        "criteria": criteria,
        "include_fields": ["AwardNoticeDate"],
        "offset": 0,
        "limit": PAGE_SIZE,
        "sort_field": "award_notice_date",
        "sort_order": "asc",
    }

    dates       = []
    fetched     = 0
    total_count = None

    while True:
        payload["offset"] = fetched
        resp = requests.post(API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data    = resp.json()
        results = data.get("results", [])
        if total_count is None:
            total_count = data.get("meta", {}).get("total", 0)
        for g in results:
            d = g.get("award_notice_date")
            if d:
                dates.append(d[:10])
        fetched += len(results)
        if fetched >= (total_count or 0) or not results:
            break

    return sorted(dates)


def dates_to_weekly_cumulative(dates: list, fy_start: date) -> list:
    weekly = [0] * 52
    for d_str in dates:
        d = date.fromisoformat(d_str)
        idx = (d - fy_start).days // 7
        if 0 <= idx < 52:
            weekly[idx] += 1
    for i in range(1, 52):
        weekly[i] += weekly[i - 1]
    return weekly


@cache.memoize()
def fetch_grants(institute: str, start_date: str, end_date: str, award_types: tuple, po_name: str = "") -> list:
    criteria: dict = {"award_notice_date": {"from_date": start_date, "to_date": end_date}}
    if institute:
        criteria["agencies"] = [institute]
    if award_types:
        criteria["award_types"] = list(award_types)
    if po_name:
        criteria["po_names"] = [{"any_name": po_name}]

    payload = {
        "criteria": criteria,
        "include_fields": [
            "ProjectNum", "ProjectTitle",
            "AwardAmount", "AwardNoticeDate", "ProjectStartDate",
            "PrincipalInvestigators", "ProgramOfficers", "Organization",
        ],
        "offset":     0,
        "limit":      PAGE_SIZE,
        "sort_field": "award_notice_date",
        "sort_order": "asc",
    }

    all_results = []
    while True:
        payload["offset"] = len(all_results)
        resp = requests.post(API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data    = resp.json()
        results = data.get("results", [])
        total   = data.get("meta", {}).get("total", 0)
        all_results.extend(results)
        if len(all_results) >= total or not results:
            break

    return all_results


@app.route("/", methods=["GET", "POST"])
def index():
    institute        = ""
    start_date       = "2025-10-01"
    end_date         = datetime.today().strftime("%Y-%m-%d")
    award_types      = [1]
    po_name          = ""
    grants           = None
    year_comparison  = None
    state_comparison = None
    weekly_chart     = None
    error            = None

    if request.method == "POST":
        institute   = request.form.get("institute", "").strip().upper()
        start_date  = request.form.get("start_date", "")
        end_date    = request.form.get("end_date", "")
        award_types = tuple(int(v) for v in request.form.getlist("award_types"))
        po_name     = request.form.get("po_name", "").strip()
        try:
            grants = fetch_grants(institute, start_date, end_date, award_types, po_name)
        except requests.HTTPError as ex:
            error = f"API error: {ex.response.status_code} – {ex.response.text[:200]}"
        except Exception as ex:
            error = str(ex)

        if grants is not None:
            try:
                year_comparison = []
                for offset in range(11, 0, -1):
                    s = shift_year(start_date, offset)
                    e = shift_year(end_date, offset)
                    count, amount = fetch_count_and_amount(institute, s, e, award_types, po_name)
                    label = f"{s[:4]}–{e[:4]}" if s[:4] != e[:4] else s[:4]
                    year_comparison.append({"label": label, "count": count, "amount": amount, "current": False})

                curr_amount = sum(g.get("award_amount") or 0 for g in grants)
                curr_label  = f"{start_date[:4]}–{end_date[:4]}" if start_date[:4] != end_date[:4] else start_date[:4]
                year_comparison.append({"label": curr_label, "count": len(grants), "amount": curr_amount, "current": True})
            except Exception:
                year_comparison = None

            try:
                current_state: dict = {}
                for g in grants:
                    amt   = g.get("award_amount") or 0
                    state = (g.get("organization") or {}).get("org_state") or "Unknown"
                    current_state[state] = current_state.get(state, 0) + amt

                hist_by_year = []
                for offset in range(1, 5):
                    s = shift_year(start_date, offset)
                    e = shift_year(end_date, offset)
                    hist_by_year.append(fetch_state_amounts(institute, s, e, award_types, po_name))

                state_comparison = []
                for state, curr_amt in current_state.items():
                    if state in ("Unknown", None):
                        continue
                    hist_vals = [yr.get(state, 0) for yr in hist_by_year]
                    avg_hist  = sum(hist_vals) / 4
                    ratio     = (curr_amt / avg_hist) if avg_hist > 0 else None
                    state_comparison.append({
                        "state":    state,
                        "current":  curr_amt,
                        "avg_hist": round(avg_hist),
                        "ratio":    round(ratio, 3) if ratio is not None else None,
                    })
                state_comparison.sort(key=lambda x: (x["ratio"] is None, -(x["ratio"] or 0)))
            except Exception:
                state_comparison = None

            try:
                fy_s        = fiscal_year_start(date.fromisoformat(start_date))
                curr_end    = date.fromisoformat(end_date)
                curr_wk_idx = min((curr_end - fy_s).days // 7, 51)

                weekly_chart = []
                for yr_off in range(11, 0, -1):
                    hy_s = date(fy_s.year - yr_off, 10, 1)
                    hy_e = date(fy_s.year - yr_off + 1, 9, 30)
                    d_list = fetch_dates_for_period(institute, hy_s, hy_e, award_types, po_name)
                    cum    = dates_to_weekly_cumulative(d_list, hy_s)
                    weekly_chart.append({"label": f"FY{hy_s.year + 1}", "data": cum, "current": False})

                curr_dates = fetch_dates_for_period(institute, fy_s, curr_end, award_types, po_name)
                curr_cum   = dates_to_weekly_cumulative(curr_dates, fy_s)
                curr_data  = [curr_cum[i] if i <= curr_wk_idx else None for i in range(52)]
                weekly_chart.append({"label": f"FY{fy_s.year + 1}", "data": curr_data, "current": True})
            except Exception:
                weekly_chart = None

    return render_template_string(
        HTML,
        institute=institute,
        start_date=start_date,
        end_date=end_date,
        award_types=award_types,
        po_name=po_name,
        grants=grants,
        year_comparison=year_comparison,
        state_comparison=state_comparison,
        weekly_chart=weekly_chart,
        error=error,
    )


@app.route("/download", methods=["POST"])
def download():
    institute   = request.form.get("institute", "").strip().upper()
    start_date  = request.form.get("start_date", "")
    end_date    = request.form.get("end_date", "")
    award_types = tuple(int(v) for v in request.form.getlist("award_types"))
    po_name     = request.form.get("po_name", "").strip()

    grants = fetch_grants(institute, start_date, end_date, award_types, po_name)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Grant Number", "Title", "Principal Investigator(s)",
        "Program Officer", "Organization", "Award ($)",
        "Notice Date", "Start Date",
    ])
    for g in grants:
        pis = ", ".join(
            p.get("full_name", "") for p in (g.get("principal_investigators") or [])
        )
        po = (g.get("program_officers") or [{}])[0].get("full_name", "")
        writer.writerow([
            g.get("project_num", ""),
            g.get("project_title", ""),
            pis,
            po,
            (g.get("organization") or {}).get("org_name", ""),
            g.get("award_amount", ""),
            (g.get("award_notice_date") or "")[:10],
            (g.get("project_start_date") or "")[:10],
        ])

    filename = f"grants_{institute}_{start_date}_{end_date}.csv"
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
