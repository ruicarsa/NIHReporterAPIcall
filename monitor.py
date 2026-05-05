"""
NIH RePORTER – Daily grant monitor
Checks for new grants matching fixed criteria and emails when results change.

Setup:
  1. Fill in GMAIL_USER and GMAIL_APP_PASSWORD below.
  2. Run once manually to seed the cache: python monitor.py
  3. The scheduled task will run it daily after that.
"""

import json
import smtplib
import ssl
from datetime import date
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import requests

# ── Credentials (fill these in) ───────────────────────────────────────────────
GMAIL_USER         = "your.email@gmail.com"   # sender = recipient
GMAIL_APP_PASSWORD = "xxxx xxxx xxxx xxxx"    # Gmail App Password (not your login password)

# ── Fixed query parameters ────────────────────────────────────────────────────
INSTITUTE   = "NIBIB"
START_DATE  = "2025-10-01"
PO_NAME     = "Pereira de Sa"
AWARD_TYPES = [1]           # Type 1 = new grants only

# ── Paths ─────────────────────────────────────────────────────────────────────
CACHE_FILE = Path(__file__).parent / ".monitor_cache.json"
API_URL    = "https://api.reporter.nih.gov/v2/projects/search"
PAGE_SIZE  = 500


# ── Fetch ──────────────────────────────────────────────────────────────────────

def fetch_grants(end_date: str) -> list[dict]:
    criteria = {
        "agencies": [INSTITUTE],
        "award_notice_date": {"from_date": START_DATE, "to_date": end_date},
        "award_types": AWARD_TYPES,
        "po_names": [{"any_name": PO_NAME}],
    }
    payload = {
        "criteria": criteria,
        "include_fields": [
            "ProjectNum", "ProjectTitle", "AwardAmount",
            "AwardNoticeDate", "PrincipalInvestigators", "Organization",
        ],
        "offset": 0,
        "limit": PAGE_SIZE,
        "sort_field": "award_notice_date",
        "sort_order": "asc",
    }
    results = []
    while True:
        payload["offset"] = len(results)
        resp = requests.post(API_URL, json=payload, timeout=60)
        resp.raise_for_status()
        data  = resp.json()
        batch = data.get("results", [])
        total = data.get("meta", {}).get("total", 0)
        results.extend(batch)
        if len(results) >= total or not batch:
            break
    return results


# ── Cache ──────────────────────────────────────────────────────────────────────

def load_cache() -> set[str]:
    if CACHE_FILE.exists():
        return set(json.loads(CACHE_FILE.read_text()))
    return set()


def save_cache(project_nums: set[str]) -> None:
    CACHE_FILE.write_text(json.dumps(sorted(project_nums)))


# ── Email ──────────────────────────────────────────────────────────────────────

def send_email(new_grants: list[dict], end_date: str) -> None:
    subject = f"[NIH Monitor] {len(new_grants)} new grant(s) detected – {INSTITUTE} / {PO_NAME}"

    rows = ""
    for g in new_grants:
        pis = ", ".join(
            p.get("full_name", "") for p in (g.get("principal_investigators") or [])
        )
        org    = (g.get("organization") or {}).get("org_name", "—")
        amount = f"${g['award_amount']:,.0f}" if g.get("award_amount") else "—"
        notice = (g.get("award_notice_date") or "—")[:10]
        rows += f"""
        <tr>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;font-family:monospace;font-size:12px">{g.get('project_num','—')}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee">{g.get('project_title','—')}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee">{pis}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee">{org}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee;text-align:right">{amount}</td>
          <td style="padding:6px 10px;border-bottom:1px solid #eee">{notice}</td>
        </tr>"""

    html = f"""
    <html><body style="font-family:system-ui,sans-serif;color:#1a1a2e">
      <h2 style="color:#1a3a5c">NIH RePORTER – New Grants Detected</h2>
      <p><strong>Institute:</strong> {INSTITUTE} &nbsp;|&nbsp;
         <strong>Program Officer:</strong> {PO_NAME} &nbsp;|&nbsp;
         <strong>Window:</strong> {START_DATE} → {end_date}</p>
      <p>{len(new_grants)} new grant(s) since last check:</p>
      <table style="border-collapse:collapse;width:100%;font-size:13px">
        <thead>
          <tr style="background:#1a3a5c;color:#fff">
            <th style="padding:8px 10px;text-align:left">Grant #</th>
            <th style="padding:8px 10px;text-align:left">Title</th>
            <th style="padding:8px 10px;text-align:left">PI(s)</th>
            <th style="padding:8px 10px;text-align:left">Organization</th>
            <th style="padding:8px 10px;text-align:right">Award</th>
            <th style="padding:8px 10px;text-align:left">Notice Date</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = GMAIL_USER
    msg["To"]      = GMAIL_USER
    msg.attach(MIMEText(html, "html"))

    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as server:
        server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
        server.sendmail(GMAIL_USER, GMAIL_USER, msg.as_string())

    print(f"Email sent to {GMAIL_USER}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    end_date = date.today().isoformat()
    print(f"Querying {INSTITUTE} | {START_DATE} → {end_date} | PO: {PO_NAME}")

    grants      = fetch_grants(end_date)
    current_ids = {g["project_num"] for g in grants if g.get("project_num")}
    cached_ids  = load_cache()

    new_ids     = current_ids - cached_ids
    new_grants  = [g for g in grants if g.get("project_num") in new_ids]

    print(f"Total grants: {len(grants)} | New since last run: {len(new_grants)}")

    if new_grants:
        send_email(new_grants, end_date)
    else:
        print("No changes — no email sent.")

    save_cache(current_ids)


if __name__ == "__main__":
    main()
