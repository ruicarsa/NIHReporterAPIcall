"""
NIH RePORTER API - Query new grants by institute and date range.

Endpoint: POST https://api.reporter.nih.gov/v2/projects/search

"New" grants = Type 1 awards (first digit of grant number is 1, e.g. 1R01CA123456).
Filtered via award_notice_date to capture when grants were officially awarded.
"""

import json
import requests

# ── Configuration ─────────────────────────────────────────────────────────────

INSTITUTE   = "NIBIB"          # NIH institute abbreviation (e.g. NIGMS, NHLBI, NIAID)
START_DATE  = "2025-10-01"   # Award notice date range start (YYYY-MM-DD)
END_DATE    = "2026-03-12"   # Award notice date range end   (YYYY-MM-DD)

# ── API settings ──────────────────────────────────────────────────────────────

API_URL     = "https://api.reporter.nih.gov/v2/projects/search"
PAGE_SIZE   = 500            # max records per page (API limit: 500)


def fetch_new_grants(institute: str, start_date: str, end_date: str) -> list[dict]:
    """
    Fetch all *new* (Type 1) grants awarded to `institute` between
    `start_date` and `end_date` (inclusive), paginating as needed.

    Returns a flat list of project records.
    """
    payload = {
        "criteria": {
            "agencies": [institute],
            "award_notice_date": {
                "from_date": start_date,
                "to_date":   end_date,
            },
            # Type 1 = new award; filters out renewals (2), supplements (3), etc.
            "award_types": [1],
        },
        "include_fields": [
            "ApplId",
            "ProjectNum",
            "ProjectTitle",
            "AwardAmount",
            "AwardNoticeDate",
            "ProjectStartDate",
            "ProjectEndDate",
            "PiNames",
            "Organization",
            "ActivityCode",
            "FundingAgency",
        ],
        "offset":   0,
        "limit":    PAGE_SIZE,
        "sort_field":  "award_notice_date",
        "sort_order":  "asc",
    }

    all_results = []
    page = 0

    while True:
        payload["offset"] = page * PAGE_SIZE
        print(f"  Fetching page {page + 1} (offset {payload['offset']}) …")

        response = requests.post(API_URL, json=payload, timeout=60)
        response.raise_for_status()
        data = response.json()

        results   = data.get("results", [])
        total     = data.get("meta", {}).get("total", 0)

        all_results.extend(results)
        print(f"  Retrieved {len(all_results)} / {total} records")

        # Stop when we've collected everything
        if len(all_results) >= total or not results:
            break

        page += 1

    return all_results


def main():
    print(f"\nQuerying NIH RePORTER")
    print(f"  Institute : {INSTITUTE}")
    print(f"  Date range: {START_DATE} → {END_DATE}")
    print(f"  Type      : New grants (Type 1) only\n")

    grants = fetch_new_grants(INSTITUTE, START_DATE, END_DATE)

    print(f"\nTotal new grants found: {len(grants)}\n")

    # ── Pretty-print a summary of each grant ──────────────────────────────────
    for g in grants:
        pi_names = ", ".join(
            f"{p.get('first_name', '')} {p.get('last_name', '')}".strip()
            for p in g.get("PiNames", [])
        )
        print(
            f"[{g.get('ProjectNum', 'N/A')}] "
            f"{g.get('ProjectTitle', 'No title')[:70]}\n"
            f"  PI: {pi_names or 'N/A'} | "
            f"Award: ${g.get('AwardAmount', 0):,.0f} | "
            f"Notice date: {g.get('AwardNoticeDate', 'N/A')}\n"
        )

    # ── Save full results to JSON ──────────────────────────────────────────────
    out_file = f"grants_{INSTITUTE}_{START_DATE[:4]}.json"
    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(grants, f, indent=2, default=str)

    print(f"Full results saved to: {out_file}")


if __name__ == "__main__":
    main()
