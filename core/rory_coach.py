"""
rory_coach.py — Weekly content intelligence brief for Rory O'Keeffe.

Runs every Sunday 9am NZ via orchestrator schedule. Generates and emails
a ~300-500 word weekly brief covering:
  - Last 7 days of IG performance
  - Structural observations of what worked
  - This week's pillar plan (6 posts, balanced)
  - 3 specific content ideas grounded in his data + competitor snapshots
  - Authenticity note

Graceful degradation:
  - If IG access token not set → skip metrics pull, note in brief, use prior state
  - If competitor scraping fails → skip competitor ideas, use his own winners
  - If SMTP creds missing → write brief to file, log warning, return without send

Usage:
    # Manual / dry-run (no send):
    python -m core.rory_coach --dry-run

    # Manual send (bypass schedule):
    python -m core.rory_coach --send

    # Scheduled (via orchestrator):
    # Called from orchestrator.run_scheduled_task('rory-coach', 'weekly_brief', ...)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

try:
    import anthropic
except ImportError:
    anthropic = None

BASE_DIR = Path(__file__).resolve().parent.parent
AGENT_DIR = BASE_DIR / "agents" / "rory-coach"
STATE_DIR = AGENT_DIR / "state"
BRIEFS_DIR = STATE_DIR / "briefs"
ANALYSES_DIR = STATE_DIR / "analyses"
VIDEO_WORKDIR = STATE_DIR / "videos"
PROMPTS_DIR = AGENT_DIR / "prompts"
CONFIG_PATH = BASE_DIR / "config" / "rory-config.json"

NZ_TZ = ZoneInfo("Pacific/Auckland")
MODEL = "claude-opus-4-7"
MAX_TOKENS = 2500

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config + state
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    if not CONFIG_PATH.exists():
        raise FileNotFoundError(f"Rory config missing: {CONFIG_PATH}")
    with CONFIG_PATH.open() as f:
        return json.load(f)


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open() as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Failed to load {path}: {e} — using default")
        return default


def _load_text(path: Path, default: str = "") -> str:
    if not path.exists():
        return default
    try:
        return path.read_text(encoding="utf-8")
    except Exception as e:
        logger.warning(f"Failed to read {path}: {e}")
        return default


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2, default=str)


# ---------------------------------------------------------------------------
# Data pulls
# ---------------------------------------------------------------------------

def fetch_ig_data(config: dict, days: int = 7) -> Optional[dict]:
    """
    Pull last N days of Rory's IG posts + metrics via Graph API.

    Returns None gracefully if token not set — Claude handles the fallback
    in its prompt (notes 'no IG pull this week').
    """
    token = config.get("rory_ig_access_token", "")
    user_id = config.get("rory_ig_user_id", "")

    if not token or token.startswith("FILL_ME"):
        logger.info("Rory IG token not set — skipping data pull")
        return None
    if not user_id or user_id.startswith("FILL_ME"):
        logger.info("Rory IG user_id not set — skipping data pull")
        return None

    try:
        from core.instagram_direct_client import InstagramDirectClient

        client = InstagramDirectClient(access_token=token, user_id=user_id)
        since = (datetime.now(NZ_TZ) - timedelta(days=days)).isoformat()
        posts = client.list_recent_media(since=since) if hasattr(
            client, "list_recent_media"
        ) else []

        return {
            "posts": posts,
            "pulled_at": datetime.now(NZ_TZ).isoformat(),
            "days": days,
        }
    except Exception as e:
        logger.error(f"IG pull failed: {e}")
        return None


def fetch_competitor_snapshots(config: dict) -> Optional[list]:
    """
    Pull top post this week from each competitor in config.competitors.

    v1: stub — returns None (graceful). v2 wires IG Graph API with per-competitor
    tokens or public scrape.
    """
    logger.info("Competitor scraping not yet wired (v2) — skipping")
    return None


# ---------------------------------------------------------------------------
# Synthesis
# ---------------------------------------------------------------------------

def _build_user_prompt(
    config: dict,
    ig_data: Optional[dict],
    rory_post_analyses: Optional[list],
    competitor_analyses: Optional[list],
    baseline: dict,
    winners: dict,
    prior_brief: str,
    week_range: str,
    manual_notes: str = "",
) -> str:
    parts = [
        f"# Weekly Brief — {week_range}",
        "",
        "## Config",
        f"Fight date: {config.get('fight_date', 'unknown')}",
        f"Deprioritised pillars: {config.get('deprioritised_pillars', [])}",
        "",
        "## Pillars (target posts per week)",
    ]
    for p in config.get("pillars", []):
        parts.append(f"- {p['name']}: {p['target_per_week']} — {p['notes']}")

    parts.extend([
        "",
        "## IG data summary (last 7 days)",
        json.dumps(ig_data, indent=2) if ig_data else "NO PULL — token not set. "
        "Note this once in the brief and work from prior winners + state.",
    ])

    # Rory's per-post deep analyses
    if rory_post_analyses:
        parts.extend(["", "## Per-post deep analysis (Rory's last 7 days)"])
        for pa in rory_post_analyses:
            parts.append(f"\n### Post {pa.get('post_id', '?')} — pillar: {pa.get('pillar', '?')}")
            parts.append(f"URL: {pa.get('url', '-')}")
            parts.append(f"Metrics: {json.dumps(pa.get('metrics', {}))}")
            parts.append(f"Caption: {pa.get('caption', '')[:200]}")
            if pa.get("gemini_analysis"):
                parts.append(f"\nGemini breakdown:\n{pa['gemini_analysis']}")
            elif pa.get("gemini_error"):
                parts.append(f"[Gemini analysis skipped: {pa['gemini_error']}]")
    else:
        parts.extend(["", "## Per-post analysis", "Not run this week."])

    # Competitor analyses
    if competitor_analyses:
        parts.extend(["", "## Competitor analyses (top performers from his benchmarks)"])
        for c in competitor_analyses:
            parts.append(f"\n### {c.get('url', '?')} — pillar: {c.get('pillar', '?')}")
            if c.get("gemini_analysis"):
                parts.append(c["gemini_analysis"])
            elif c.get("error"):
                parts.append(f"[Skipped: {c['error']}]")
    else:
        parts.extend([
            "",
            "## Competitor analyses",
            "None this week — no competitor URLs supplied. Work from Rory's own winners + prior state. "
            "Don't fabricate competitor posts.",
        ])

    parts.extend([
        "",
        "## Baseline (rolling state)",
        json.dumps(baseline, indent=2) if baseline else "No baseline yet — first brief.",
        "",
        "## Winners (top historical performers)",
        json.dumps(winners, indent=2) if winners else "No winners catalogued yet.",
        "",
        "## Prior brief (for compounding context)",
        prior_brief if prior_brief else "No prior brief — this is week 1.",
    ])

    if manual_notes:
        parts.extend(["", "## Manual notes from Tom", manual_notes])

    parts.extend([
        "",
        "---",
        "Now write the email. Format per prompts/weekly-brief.md.",
        "",
        "Use the per-post Gemini analyses to ground specific 'what worked / what to "
        "improve' observations in Rory's actual videos — not generic advice.",
        "",
        "Use the competitor analyses (if present) to extract the ONE structural pattern "
        "worth borrowing per idea. Don't copy — say 'flip this to your voice.' Reference "
        "the handle by @handle only (no full URL in the email body).",
        "",
        "Return ONLY the email body. Start with 'Hey mate,' — end with 'Tom' on its own line.",
    ])
    return "\n".join(parts)


def analyse_rory_posts(config: dict, ig_data: Optional[dict]) -> Optional[list]:
    """Run pillar classification + Gemini video analysis on each of Rory's posts."""
    pipeline_config = config.get("analysis_pipeline", {})
    if not pipeline_config.get("include_video_analysis_own_posts", True):
        return None
    if not ig_data or not ig_data.get("posts"):
        logger.info("No IG posts to analyse")
        return None

    try:
        from core.content_analysis import analyse_posts_batch
    except ImportError as e:
        logger.error(f"content_analysis module unavailable: {e}")
        return None

    posts_input = []
    for post in ig_data["posts"]:
        posts_input.append({
            "id": post.get("id", ""),
            "url": post.get("permalink", post.get("url", "")),
            "caption": post.get("caption", ""),
            "metrics": {
                "views": post.get("views", post.get("play_count")),
                "likes": post.get("like_count"),
                "comments": post.get("comments_count"),
                "saves": post.get("saved"),
                "shares": post.get("shares"),
                "impressions": post.get("impressions"),
                "reach": post.get("reach"),
            },
        })

    logger.info(f"Analysing {len(posts_input)} Rory posts with Gemini + pillar classifier")
    results = analyse_posts_batch(
        posts=posts_input,
        workdir=VIDEO_WORKDIR / "rory",
        classify=pipeline_config.get("include_pillar_classification", True),
        run_gemini=True,
    )
    # Persist analyses to disk for audit trail
    now = datetime.now(NZ_TZ).strftime("%Y-%m-%d")
    _write_json(ANALYSES_DIR / f"{now}-rory-posts.json", [r.to_dict() for r in results])
    return [r.to_dict() for r in results]


def analyse_competitors(config: dict) -> Optional[list]:
    """Run Gemini on the week's manual competitor URL list."""
    pipeline_config = config.get("analysis_pipeline", {})
    if not pipeline_config.get("include_competitor_video_analysis", True):
        return None

    urls = config.get("competitor_post_urls_this_week", [])
    if not urls:
        logger.info("No competitor URLs supplied for this week")
        return None

    try:
        from core.content_analysis import analyse_competitor_urls
    except ImportError as e:
        logger.error(f"content_analysis module unavailable: {e}")
        return None

    max_videos = pipeline_config.get("max_competitor_videos_per_week", 10)
    logger.info(f"Analysing {min(len(urls), max_videos)} competitor videos")
    results = analyse_competitor_urls(
        urls=urls,
        workdir=VIDEO_WORKDIR / "competitors",
        max_videos=max_videos,
    )
    now = datetime.now(NZ_TZ).strftime("%Y-%m-%d")
    _write_json(ANALYSES_DIR / f"{now}-competitors.json", results)
    return results


def synthesise(
    config: dict,
    ig_data: Optional[dict],
    rory_post_analyses: Optional[list],
    competitor_analyses: Optional[list],
    manual_notes: str = "",
) -> tuple[str, str]:
    """
    Generate the brief via Claude Opus. Returns (subject, body).
    """
    if anthropic is None:
        raise RuntimeError("anthropic SDK not installed — add to requirements.txt")

    now = datetime.now(NZ_TZ)
    last_sunday = now - timedelta(days=(now.weekday() + 1) % 7 or 7)
    last_monday = last_sunday - timedelta(days=6)
    week_range = f"{last_monday.strftime('%b %-d')}-{last_sunday.strftime('%-d')}"

    system_prompt = _load_text(PROMPTS_DIR / "weekly-brief.md")
    if not system_prompt:
        raise FileNotFoundError(f"weekly-brief.md prompt missing at {PROMPTS_DIR}")

    baseline = _load_json(STATE_DIR / "baseline.json", {})
    winners = _load_json(STATE_DIR / "winners.json", {})
    prior_brief = _load_text(STATE_DIR / "last-brief.md")

    user_prompt = _build_user_prompt(
        config=config,
        ig_data=ig_data,
        rory_post_analyses=rory_post_analyses,
        competitor_analyses=competitor_analyses,
        baseline=baseline,
        winners=winners,
        prior_brief=prior_brief,
        week_range=week_range,
        manual_notes=manual_notes,
    )

    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")

    model = config.get("analysis_pipeline", {}).get("synthesis_model", MODEL)
    client = anthropic.Anthropic(api_key=api_key)
    logger.info(f"Calling Claude {model} for Rory weekly brief ({week_range})")

    resp = client.messages.create(
        model=model,
        max_tokens=MAX_TOKENS,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    body = resp.content[0].text.strip()
    subject = f"Rory — week of {week_range}"
    return subject, body


# ---------------------------------------------------------------------------
# Delivery + state
# ---------------------------------------------------------------------------

def send_brief(config: dict, subject: str, body: str) -> dict:
    recipients = config.get("recipients") or []
    if not recipients:
        single = config.get("rory_email", "")
        if single and not single.startswith("FILL_ME"):
            recipients = [single]

    recipients = [r for r in recipients if r and not r.startswith("FILL_ME")]
    if not recipients:
        logger.warning("No valid recipients — brief written to file only")
        return {"ok": False, "error": "no recipients configured", "sent": False}

    smtp_email = config.get("smtp_email") or os.environ.get("SMTP_EMAIL", "")
    smtp_pw = os.environ.get("SMTP_APP_PASSWORD") or config.get("smtp_app_password", "")
    if smtp_pw and smtp_pw.startswith("FILL_ME"):
        smtp_pw = ""
    if smtp_email and smtp_email.startswith("FILL_ME"):
        smtp_email = ""

    if not smtp_email or not smtp_pw:
        logger.warning("SMTP credentials missing — brief written to file only")
        return {"ok": False, "error": "smtp credentials missing", "sent": False}

    from core.email_sender import send_email

    per_recipient = []
    all_ok = True
    for r in recipients:
        result = send_email(
            to=r,
            subject=subject,
            body_text=body,
            sender_email=smtp_email,
            sender_password=smtp_pw,
            sender_name=config.get("sender_name", "Tom"),
        )
        per_recipient.append({"to": r, **result})
        if not result.get("ok"):
            all_ok = False

    return {
        "ok": all_ok,
        "sent": all_ok,
        "per_recipient": per_recipient,
        "error": None if all_ok else "one or more sends failed — see per_recipient",
    }


def update_state(
    subject: str,
    body: str,
    ig_data: Optional[dict],
    competitor_data: Optional[list],
) -> None:
    now = datetime.now(NZ_TZ)
    archive_path = BRIEFS_DIR / f"{now.strftime('%Y-%m-%d')}-weekly.md"
    _write_text(
        archive_path,
        f"# {subject}\n\n_Generated: {now.isoformat()}_\n\n---\n\n{body}\n",
    )

    last_brief_path = STATE_DIR / "last-brief.md"
    _write_text(last_brief_path, body)

    if ig_data:
        _write_json(STATE_DIR / "latest-ig-pull.json", ig_data)

    if competitor_data:
        _write_json(STATE_DIR / "latest-competitor-pull.json", competitor_data)

    logger.info(f"State updated — archive at {archive_path}")


# ---------------------------------------------------------------------------
# Orchestrator entry point
# ---------------------------------------------------------------------------

def run_weekly_brief(
    dry_run: bool = False,
    manual_notes: str = "",
    telegram_config: Optional[dict] = None,
) -> dict:
    """
    Main entry point — called by orchestrator on Sunday 9am NZ.

    Returns dict: {ok, subject, body_preview, sent, archive_path, error}
    """
    logger.info(f"Rory weekly brief starting — dry_run={dry_run}")

    try:
        config = _load_config()
    except Exception as e:
        return {"ok": False, "error": f"config load failed: {e}"}

    ig_data = fetch_ig_data(config)

    # Deep analysis phase — per-post Gemini + pillar classification
    rory_post_analyses = analyse_rory_posts(config, ig_data)

    # Competitor video analyses (from manual URL list v1)
    competitor_analyses = analyse_competitors(config)

    try:
        subject, body = synthesise(
            config=config,
            ig_data=ig_data,
            rory_post_analyses=rory_post_analyses,
            competitor_analyses=competitor_analyses,
            manual_notes=manual_notes,
        )
    except Exception as e:
        logger.error(f"Synthesis failed: {e}", exc_info=True)
        return {"ok": False, "error": f"synthesis failed: {e}"}

    update_state(subject, body, ig_data, competitor_analyses)
    archive_path = str(
        BRIEFS_DIR / f"{datetime.now(NZ_TZ).strftime('%Y-%m-%d')}-weekly.md"
    )

    if dry_run:
        logger.info("Dry run — skipping send")
        return {
            "ok": True,
            "subject": subject,
            "body_preview": body[:400],
            "body": body,
            "sent": False,
            "archive_path": archive_path,
            "dry_run": True,
        }

    send_result = send_brief(config, subject, body)

    if telegram_config:
        try:
            from core.notification_router import route_notification

            bot_token = telegram_config.get(
                "bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", "")
            )
            chat_id = telegram_config.get("chat_ids", {}).get("command-center", "")
            if chat_id and bot_token:
                status = "sent" if send_result.get("sent") else "FAILED"
                msg = (
                    f"Rory weekly brief — {status}\n"
                    f"Subject: {subject}\n"
                    f"Archive: {archive_path}"
                )
                if not send_result.get("sent"):
                    msg += f"\nError: {send_result.get('error', 'unknown')}"
                route_notification(
                    chat_id, msg, bot_token,
                    severity="IMPORTANT", agent="command-center",
                )
        except Exception as e:
            logger.warning(f"Telegram notify failed: {e}")

    return {
        "ok": True,
        "subject": subject,
        "body_preview": body[:400],
        "body": body,
        "sent": send_result.get("sent", False),
        "archive_path": archive_path,
        "error": send_result.get("error"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Rory Coach — weekly brief")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Generate + write archive, but don't email",
    )
    parser.add_argument(
        "--send", action="store_true",
        help="Generate + email (use for manual override)",
    )
    parser.add_argument(
        "--notes", default="",
        help="Manual notes from Tom to include in the synthesis prompt "
             "(e.g. pasted IG stats when API not wired)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not args.dry_run and not args.send:
        print("Choose --dry-run or --send")
        sys.exit(1)

    result = run_weekly_brief(dry_run=args.dry_run, manual_notes=args.notes)

    print("=" * 60)
    print(f"OK: {result.get('ok')}")
    print(f"Subject: {result.get('subject', '-')}")
    print(f"Sent: {result.get('sent')}")
    print(f"Archive: {result.get('archive_path', '-')}")
    if result.get("error"):
        print(f"Error: {result['error']}")
    print("=" * 60)
    print()
    print("PREVIEW:")
    print("-" * 60)
    print(result.get("body", result.get("body_preview", "(no body)")))
    print("-" * 60)


if __name__ == "__main__":
    main()
