"""
NIH RePORTER – Automated chart exporter
Queries NIBIB grants for the current fiscal year and saves all charts as PNGs.
Run directly: python export_charts.py
"""

import os
from datetime import date
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ── Config ────────────────────────────────────────────────────────────────────
INSTITUTE  = "NIBIB"
API_URL    = "https://api.reporter.nih.gov/v2/projects/search"
PAGE_SIZE  = 500
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

BLUE_PALETTE = [
    "#1a3a5c","#2e6da4","#4a9edd","#6ab4f0","#8ecef7",
    "#b3e0ff","#d0eeff","#e8f4ff","#0f2540","#3a7bc8",
]
HIGHLIGHT_PO = "pereira de sa"


# ── Date helpers ──────────────────────────────────────────────────────────────

def fiscal_year_start(d: date) -> date:
    return date(d.year, 10, 1) if d.month >= 10 else date(d.year - 1, 10, 1)


def shift_year(date_str: str, years: int) -> str:
    d = date.fromisoformat(date_str)
    try:
        return d.replace(year=d.year - years).isoformat()
    except ValueError:
        return d.replace(year=d.year - years, day=28).isoformat()


# ── API helpers ───────────────────────────────────────────────────────────────

def _criteria(award_types, start_date, end_date):
    c = {
        "agencies": [INSTITUTE],
        "award_notice_date": {"from_date": start_date, "to_date": end_date},
    }
    if award_types:
        c["award_types"] = award_types
    return c


def _paginate(criteria, fields):
    """Yield all result records for the given criteria + fields."""
    fetched = 0
    total   = None
    while True:
        payload = {
            "criteria": criteria,
            "include_fields": fields,
            "offset": fetched,
            "limit": PAGE_SIZE,
            "sort_field": "award_notice_date",
            "sort_order": "asc",
        }
        resp = requests.post(API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data    = resp.json()
        results = data.get("results", [])
        if total is None:
            total = data.get("meta", {}).get("total", 0)
        yield from results
        fetched += len(results)
        if fetched >= total or not results:
            break


def fetch_grants(award_types, start_date, end_date):
    fields = [
        "ProjectNum", "ProjectTitle", "AwardAmount", "AwardNoticeDate",
        "ProjectStartDate", "PrincipalInvestigators", "ProgramOfficers", "Organization",
    ]
    return list(_paginate(_criteria(award_types, start_date, end_date), fields))


def fetch_count_and_amount(award_types, start_date, end_date):
    total_count  = 0
    total_amount = 0.0
    for g in _paginate(_criteria(award_types, start_date, end_date), ["AwardAmount"]):
        total_count  += 1
        total_amount += g.get("award_amount") or 0
    return total_count, total_amount


def fetch_state_amounts(award_types, start_date, end_date):
    state_amounts: dict = {}
    for g in _paginate(_criteria(award_types, start_date, end_date), ["AwardAmount", "Organization"]):
        amt   = g.get("award_amount") or 0
        state = (g.get("organization") or {}).get("org_state") or "Unknown"
        state_amounts[state] = state_amounts.get(state, 0) + amt
    return state_amounts


def fetch_dates_for_period(award_types, start: date, end: date):
    dates = []
    for g in _paginate(_criteria(award_types, start.isoformat(), end.isoformat()), ["AwardNoticeDate"]):
        d = g.get("award_notice_date")
        if d:
            dates.append(d[:10])
    return sorted(dates)


def dates_to_weekly_cumulative(dates, fy_start: date):
    weekly = [0] * 52
    for d_str in dates:
        d = date.fromisoformat(d_str)
        idx = (d - fy_start).days // 7
        if 0 <= idx < 52:
            weekly[idx] += 1
    for i in range(1, 52):
        weekly[i] += weekly[i - 1]
    return weekly


# ── Chart savers ──────────────────────────────────────────────────────────────

def _savefig(fig, path):
    fig.savefig(path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(f"  Saved: {path}")


def save_po_charts(grants, title, out_prefix):
    po_map: dict = {}
    for g in grants:
        pos  = g.get("program_officers") or []
        name = pos[0]["full_name"] if pos else "Unknown"
        if name not in po_map:
            po_map[name] = {"count": 0, "total": 0.0}
        po_map[name]["count"] += 1
        po_map[name]["total"] += g.get("award_amount") or 0

    sorted_po = sorted(po_map.items(), key=lambda x: -x[1]["count"])
    names   = [x[0] for x in sorted_po]
    counts  = [x[1]["count"] for x in sorted_po]
    amounts = [x[1]["total"] / 1e6 for x in sorted_po]
    colors  = [
        "#e8720c" if HIGHLIGHT_PO in n.lower() else BLUE_PALETTE[i % len(BLUE_PALETTE)]
        for i, n in enumerate(names)
    ]

    h = max(4, len(names) * 0.42 + 1.2)
    fig, axes = plt.subplots(1, 2, figsize=(14, h))
    fig.suptitle(f"Grants by Program Officer\n{title}", fontsize=12, fontweight="bold")

    for ax, data, xlabel in zip(axes, [counts, amounts], ["Number of Grants", "Total Award ($M)"]):
        ax.barh(names, data, color=colors)
        ax.set_xlabel(xlabel)
        ax.invert_yaxis()
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(axis="y", labelsize=9)

    fig.tight_layout()
    _savefig(fig, os.path.join(OUTPUT_DIR, f"{out_prefix}_po_charts.png"))


def save_yoy_charts(year_comparison, title, out_prefix):
    labels  = [d["label"]  for d in year_comparison]
    counts  = [d["count"]  for d in year_comparison]
    amounts = [d["amount"] / 1e6 for d in year_comparison]
    colors  = ["#1a3a5c" if d["current"] else "#93b8d8" for d in year_comparison]

    fig, axes = plt.subplots(1, 2, figsize=(14, 4))
    fig.suptitle(f"Year-over-Year Comparison\n{title}", fontsize=12, fontweight="bold")

    for ax, data, ylabel in zip(axes, [counts, amounts], ["Number of Grants", "Total Award ($M)"]):
        ax.bar(labels, data, color=colors)
        ax.set_ylabel(ylabel)
        ax.tick_params(axis="x", rotation=45, labelsize=8)
        ax.spines[["top", "right"]].set_visible(False)

    fig.tight_layout()
    _savefig(fig, os.path.join(OUTPUT_DIR, f"{out_prefix}_yoy_charts.png"))


def save_state_chart(state_comparison, title, out_prefix):
    states = [d["state"] for d in state_comparison]
    ratios = [d["ratio"] if d["ratio"] is not None else 0 for d in state_comparison]
    colors = [
        "#1a3a5c" if r >= 1 else ("#93b8d8" if r > 0 else "#d1d5db")
        for r in ratios
    ]

    h = max(4, len(states) * 0.38 + 1.2)
    fig, ax = plt.subplots(figsize=(10, h))
    ax.set_title(f"Funding by State (current ÷ 2021–2024 avg)\n{title}", fontsize=12, fontweight="bold")
    ax.barh(states, ratios, color=colors)
    ax.axvline(1.0, color="#555", linewidth=1, linestyle="--", label="Baseline (1.0×)")
    ax.set_xlabel("Ratio (current year / historical average)")
    ax.invert_yaxis()
    ax.spines[["top", "right"]].set_visible(False)
    ax.tick_params(axis="y", labelsize=9)
    ax.legend(fontsize=9)

    fig.tight_layout()
    _savefig(fig, os.path.join(OUTPUT_DIR, f"{out_prefix}_state_chart.png"))


def save_weekly_chart(weekly_chart, title, out_prefix):
    weeks = list(range(1, 53))
    dash_patterns = [
        (6, 3), (2, 3), (10, 3), (6, 2, 2, 2), (14, 3),
        (4, 3, 1, 3), (8, 2, 2, 2), (3, 3, 3, 3), (10, 2, 4, 2), (2, 6), (5, 5),
    ]

    fig, ax = plt.subplots(figsize=(13, 5))
    ax.set_title(f"Cumulative Grants by Fiscal Week\n{title}", fontsize=12, fontweight="bold")

    hist_idx = 0
    for d in weekly_chart:
        if d["current"]:
            data = [v for v in d["data"] if v is not None]
            ax.plot(weeks[:len(data)], data,
                    color="#dc2626", linewidth=2.5, label=d["label"] + " (current)", zorder=5)
        elif d["label"] == "FY2025":
            ax.plot(weeks, d["data"],
                    color="#2e6da4", linewidth=2.0, label=d["label"], zorder=4)
        else:
            dp = dash_patterns[hist_idx % len(dash_patterns)]
            ax.plot(weeks, d["data"],
                    color=(0.24, 0.24, 0.24), linewidth=0.9, alpha=0.45,
                    dashes=dp, label=d["label"])
            hist_idx += 1

    ax.set_xlabel("Fiscal Week (1 = Oct 1)")
    ax.set_ylabel("Cumulative Grants")
    ax.legend(fontsize=8, loc="upper left", ncol=2, framealpha=0.8)
    ax.spines[["top", "right"]].set_visible(False)
    ax.grid(axis="y", color="#f0f0f0", linewidth=0.8)

    fig.tight_layout()
    _savefig(fig, os.path.join(OUTPUT_DIR, f"{out_prefix}_weekly_chart.png"))


# ── Main export run ───────────────────────────────────────────────────────────

def run_export(award_types: list, type_label: str):
    today      = date.today()
    fy_s       = fiscal_year_start(today)
    start_date = fy_s.isoformat()
    end_date   = today.isoformat()
    date_str   = today.strftime("%Y%m%d")
    type_str   = "types" + "_".join(str(t) for t in award_types)
    out_prefix = f"{date_str}_NIBIB_{type_str}"
    title      = f"NIBIB {type_label}  |  {start_date} to {end_date}"

    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")

    # ── Fetch main grants ──
    grants = fetch_grants(award_types, start_date, end_date)
    print(f"  Grants fetched: {len(grants)}")

    # ── YoY (11 prior periods + current) ──
    year_comparison = []
    for offset in range(11, 0, -1):
        s = shift_year(start_date, offset)
        e = shift_year(end_date, offset)
        count, amount = fetch_count_and_amount(award_types, s, e)
        lbl = f"{s[:4]}–{e[:4]}" if s[:4] != e[:4] else s[:4]
        year_comparison.append({"label": lbl, "count": count, "amount": amount, "current": False})

    curr_amount = sum(g.get("award_amount") or 0 for g in grants)
    curr_lbl    = f"{start_date[:4]}–{end_date[:4]}" if start_date[:4] != end_date[:4] else start_date[:4]
    year_comparison.append({"label": curr_lbl, "count": len(grants), "amount": curr_amount, "current": True})

    # ── State comparison (current vs 4-year avg) ──
    current_state: dict = {}
    for g in grants:
        amt   = g.get("award_amount") or 0
        state = (g.get("organization") or {}).get("org_state") or "Unknown"
        current_state[state] = current_state.get(state, 0) + amt

    hist_by_year = []
    for offset in range(1, 5):
        s = shift_year(start_date, offset)
        e = shift_year(end_date, offset)
        hist_by_year.append(fetch_state_amounts(award_types, s, e))

    state_comparison = []
    for state, curr_amt in current_state.items():
        if state in ("Unknown", None):
            continue
        hist_vals = [yr.get(state, 0) for yr in hist_by_year]
        avg_hist  = sum(hist_vals) / 4
        ratio     = (curr_amt / avg_hist) if avg_hist > 0 else None
        state_comparison.append({
            "state": state, "current": curr_amt,
            "avg_hist": round(avg_hist),
            "ratio": round(ratio, 3) if ratio is not None else None,
        })
    state_comparison.sort(key=lambda x: (x["ratio"] is None, -(x["ratio"] or 0)))

    # ── Weekly cumulative (11 prior FYs + current) ──
    curr_wk_idx = min((today - fy_s).days // 7, 51)
    weekly_chart = []
    for yr_off in range(11, 0, -1):
        hy_s = date(fy_s.year - yr_off, 10, 1)
        hy_e = date(fy_s.year - yr_off + 1, 9, 30)
        d_list = fetch_dates_for_period(award_types, hy_s, hy_e)
        cum    = dates_to_weekly_cumulative(d_list, hy_s)
        weekly_chart.append({"label": f"FY{hy_s.year + 1}", "data": cum, "current": False})

    curr_dates = fetch_dates_for_period(award_types, fy_s, today)
    curr_cum   = dates_to_weekly_cumulative(curr_dates, fy_s)
    curr_data  = [curr_cum[i] if i <= curr_wk_idx else None for i in range(52)]
    weekly_chart.append({"label": f"FY{fy_s.year + 1}", "data": curr_data, "current": True})

    # ── Save all charts ──
    save_po_charts(grants, title, out_prefix)
    save_yoy_charts(year_comparison, title, out_prefix)
    save_state_chart(state_comparison, title, out_prefix)
    save_weekly_chart(weekly_chart, title, out_prefix)


if __name__ == "__main__":
    run_export([1, 2], "Type 1+2 (New & Renewal)")
    run_export([5],    "Type 5 (Continuation)")
    print("\nAll done.")
