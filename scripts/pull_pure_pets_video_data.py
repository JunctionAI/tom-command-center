#!/usr/bin/env python3
"""Pull Pure Pets video ad performance data from Meta Ads API.

Run locally with env vars:
  META_ACCESS_TOKEN=xxx META_AD_ACCOUNT_ID=xxx python3 scripts/pull_pure_pets_video_data.py

Or trigger via Nexus Telegram: run dbh-marketing (data will be in the briefing)
"""

import os
import sys
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.data_fetcher import fetch_meta_video_metrics


def main():
    print("Pulling Pure Pets video metrics from Meta Ads API...")
    print()

    # Pull with broad date range to catch November 2025 campaign
    result = fetch_meta_video_metrics(
        campaign_filter="Pure Pets",
        since="2025-10-01",
        until="2026-03-05",
    )

    if result.get("error"):
        print(f"Error: {result['error']}")
        print()
        print("Make sure META_ACCESS_TOKEN and META_AD_ACCOUNT_ID are set.")
        print("You can export from Meta Ads Manager manually as a fallback.")
        sys.exit(1)

    # Print formatted report
    print(result["formatted"])
    print()

    # Save to reports
    report_path = os.path.expanduser(
        "~/tom-command-center/reports/pure-pets-video-performance-analysis.md"
    )

    ads = result.get("ads", [])
    lines = [
        "# PURE PETS VIDEO PERFORMANCE ANALYSIS",
        f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"**Date Range:** 2025-10-01 to 2026-03-05",
        f"**Campaign Filter:** Pure Pets",
        f"**Ads Found:** {len(ads)}",
        "",
        "---",
        "",
    ]

    # Raw data section
    lines.append(result["formatted"])
    lines.append("")
    lines.append("---")
    lines.append("")

    if len(ads) > 1:
        # Analysis section
        lines.append("## ANALYSIS")
        lines.append("")

        # Hook rate comparison
        lines.append("### Hook Performance (Which opening grabs attention?)")
        for a in sorted(ads, key=lambda x: x["hook_rate"], reverse=True):
            lines.append(f"- **{a['ad_name']}**: {a['hook_rate']:.1f}% hook rate ({a['p25']:,} of {a['impressions']:,} reached 25%)")
        lines.append("")

        # Drop-off analysis
        lines.append("### Viewer Retention (Where do people leave?)")
        for a in ads:
            lines.append(f"- **{a['ad_name']}**:")
            lines.append(f"  - Start → 25%: {a['p25']:,} viewers")
            lines.append(f"  - 25% → 50%: lost {a['drop_off_25_50']:.1f}%")
            lines.append(f"  - 50% → 75%: lost {a['drop_off_50_75']:.1f}%")
            lines.append(f"  - 75% → 100%: lost {a['drop_off_75_100']:.1f}%")
            lines.append(f"  - Completed: {a['completion_rate']:.1f}%")
        lines.append("")

        # Conversion correlation
        lines.append("### Conversion Correlation (Does watching = buying?)")
        converting_ads = [a for a in ads if a["purchases"] > 0]
        if converting_ads:
            for a in sorted(converting_ads, key=lambda x: x["roas"], reverse=True):
                lines.append(f"- **{a['ad_name']}**: {a['completion_rate']:.1f}% completion → {a['roas']:.2f}x ROAS, ${a['cpa']:,.2f} CPA")
        else:
            lines.append("- No purchases recorded in this period (check attribution window)")
        lines.append("")

        # Winner determination
        lines.append("### Overall Winner")
        best = max(ads, key=lambda x: x["hook_rate"])
        lines.append(f"- Best hook: **{best['ad_name']}** ({best['hook_rate']:.1f}%)")
        best_c = max(ads, key=lambda x: x["completion_rate"])
        lines.append(f"- Best completion: **{best_c['ad_name']}** ({best_c['completion_rate']:.1f}%)")
        cheapest = min(ads, key=lambda x: x["cpa"] if x["cpa"] > 0 else float("inf"))
        if cheapest["cpa"] > 0:
            lines.append(f"- Cheapest CPA: **{cheapest['ad_name']}** (${cheapest['cpa']:,.2f})")

    lines.append("")
    lines.append("---")
    lines.append(f"*Pull this data again: `python3 scripts/pull_pure_pets_video_data.py`*")

    report_content = "\n".join(lines)

    with open(report_path, "w") as f:
        f.write(report_content)

    print(f"\nReport saved to: {report_path}")

    # Also save raw JSON for further analysis
    json_path = os.path.expanduser(
        "~/tom-command-center/reports/pure-pets-video-data.json"
    )
    with open(json_path, "w") as f:
        json.dump({"ads": ads, "date_range": {"since": "2025-10-01", "until": "2026-03-05"}}, f, indent=2)

    print(f"Raw data saved to: {json_path}")


if __name__ == "__main__":
    main()
