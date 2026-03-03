#!/usr/bin/env python3
"""
Tony Report Generator — Automated weekly CEO report.

Generates a clear, non-technical report every Monday 7am.
Saved as file (NOT sent via Telegram). Tom reviews, edits, emails to Tony.

Output:
  - ~/dbh-aios/reports/tony-reports/tony-report-YYYY-MM-DD.md
  - ~/dbh-aios/reports/tony-reports/tony-report-latest.md (overwritten each week)
"""

import logging
from datetime import datetime, date, timedelta
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")
logger = logging.getLogger(__name__)

REPORTS_DIR = Path.home() / "dbh-aios" / "reports" / "tony-reports"


def generate_tony_report() -> str:
    """
    Pull 7-day data from all sources and format into Tony-readable markdown.
    Returns the formatted report string.
    """
    report_date = date.today().isoformat()
    week_start = (date.today() - timedelta(days=7)).isoformat()

    sections = []
    sections.append(f"# Weekly Performance Report — {report_date}")
    sections.append(f"*Week of {week_start} to {report_date}*\n")

    # Section 1: Revenue
    sections.append("## 1. Revenue This Week\n")
    try:
        from core.data_fetcher import fetch_shopify_data
        shopify_data = fetch_shopify_data(days=7)
        sections.append(shopify_data)
    except Exception as e:
        sections.append(f"Shopify data not available: {e}")

    # Section 2: Meta Ads (Verified ROAS)
    sections.append("\n## 2. Meta Ads Performance (Shopify-Verified)\n")
    try:
        from core.roas_tracker import get_weekly_roas_summary
        roas_summary = get_weekly_roas_summary()
        sections.append(roas_summary)
    except Exception as e:
        sections.append(f"ROAS data not available: {e}")

    # Section 3: Retention + Email
    sections.append("\n## 3. Retention & Email\n")
    try:
        from core.data_fetcher import fetch_klaviyo_data
        klaviyo_data = fetch_klaviyo_data(days=7)
        sections.append(klaviyo_data)
    except Exception as e:
        sections.append(f"Klaviyo data not available: {e}")

    # Section 4: CPA:LTV Tracker
    sections.append("\n## 4. CPA:LTV Snapshot\n")
    try:
        from core.order_intelligence import get_customer_db_summary
        customer_summary = get_customer_db_summary()
        sections.append(customer_summary)
    except Exception as e:
        sections.append(f"Customer intelligence not available: {e}")

    # Section 5: SEO Progress
    sections.append("\n## 5. SEO & Content\n")
    try:
        seo_dir = Path.home() / "dbh-aios" / "reports" / "seo-articles"
        if seo_dir.exists():
            recent_articles = sorted(seo_dir.glob("*.md"), reverse=True)[:7]
            if recent_articles:
                sections.append(f"Articles published this week: {len(recent_articles)}")
                for article in recent_articles:
                    sections.append(f"  - {article.stem}")
            else:
                sections.append("No articles published this week.")
        else:
            sections.append("SEO article system not yet active.")
    except Exception as e:
        sections.append(f"SEO data not available: {e}")

    # Section 6: What's Coming
    sections.append("\n## 6. What's Coming Next Week\n")
    try:
        from core.asana_client import AsanaClient
        asana = AsanaClient()
        if asana.available:
            tasks = asana.get_incomplete_tasks()
            if tasks:
                sections.append("Upcoming tasks:")
                for task in tasks[:10]:
                    due = task.get("due_on", "no date")
                    sections.append(f"  - {task.get('name', 'Unnamed')} (due: {due})")
            else:
                sections.append("No upcoming Asana tasks.")
        else:
            sections.append("Asana not connected.")
    except Exception as e:
        sections.append(f"Asana data not available: {e}")

    report = "\n".join(sections)

    # Add footer
    report += f"\n\n---\n*Generated automatically by the AI system on {datetime.now(NZ_TZ).strftime('%A %d %B %Y at %I:%M %p NZST')}*"
    report += "\n*Review, edit if needed, then email to Tony.*"

    return report


def save_tony_report(report: str) -> str:
    """
    Save the Tony report to the file system.
    Returns the file path.
    """
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    report_date = date.today().isoformat()

    # Save dated version
    dated_path = REPORTS_DIR / f"tony-report-{report_date}.md"
    dated_path.write_text(report, encoding='utf-8')

    # Overwrite latest
    latest_path = REPORTS_DIR / "tony-report-latest.md"
    latest_path.write_text(report, encoding='utf-8')

    logger.info(f"Tony report saved: {dated_path}")
    return str(dated_path)


def generate_and_save() -> str:
    """Generate and save the Tony report. Returns notification text."""
    report = generate_tony_report()
    path = save_tony_report(report)
    return f"Tony Report ready for review: {path}\n\nOpen, edit if needed, then email to Tony."


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = generate_tony_report()
    path = save_tony_report(report)
    print(f"Report saved to: {path}")
    print(report[:500] + "...")
