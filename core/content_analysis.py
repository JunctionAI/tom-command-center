"""
content_analysis.py — per-video pipeline for rory-coach (and any agent needing
video-level content intelligence).

Pipeline per video:
  1. Download via yt-dlp (handles IG public posts + direct media URLs)
  2. Classify into one of Rory's pillars via Claude Haiku
  3. Run Gemini Flash video analysis for structural breakdown

Graceful degradation:
  - If yt-dlp fails (private post, geo-block, rate-limit) → skip video, keep
    whatever metadata we have
  - If Gemini API errors → skip analysis, note the error in the output
  - If Claude API errors for pillar → default to 'unclassified'

Designed to be reusable. rory-coach is the first consumer; future agents
(e.g. a DBH content coach) can share the same helpers.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Video download (yt-dlp)
# ---------------------------------------------------------------------------

def download_video(url: str, dest_dir: Path) -> Optional[Path]:
    """
    Download an IG post video (or any yt-dlp-supported URL) to dest_dir.
    Returns the path to the downloaded .mp4, or None on failure.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                "yt-dlp",
                "--no-playlist",
                "-f", "mp4/best",
                "--output", str(dest_dir / "%(id)s.%(ext)s"),
                "--print", "after_move:filepath",
                "--no-warnings",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=True,
        )
        # yt-dlp prints the final filepath on stdout when --print after_move:filepath
        filepath = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else None
        if filepath and Path(filepath).exists():
            return Path(filepath)
        # Fallback — look for any mp4 in dest_dir newest-first
        mp4s = sorted(dest_dir.glob("*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True)
        return mp4s[0] if mp4s else None
    except subprocess.TimeoutExpired:
        logger.error(f"yt-dlp timeout for {url}")
        return None
    except subprocess.CalledProcessError as e:
        logger.error(f"yt-dlp failed for {url}: {e.stderr[:300] if e.stderr else e}")
        return None
    except FileNotFoundError:
        logger.error("yt-dlp binary not found — install via pip")
        return None


# ---------------------------------------------------------------------------
# Pillar classification (Claude Haiku — cheap + fast)
# ---------------------------------------------------------------------------

PILLAR_CLASSIFIER_PROMPT = """You classify Instagram videos from Rory O'Keeffe
(@rory247okeeffe, NZ MMA fighter + PT) into one of his content pillars.

Rory's pillars:
- meme-skit — borrowed format with his twist (e.g. principal-calls-about-fight)
- class-coaching — walking class, correcting form, teaching moments
- class-candid — personality, humanising, e.g. students being funny
- transformation-josh — client results, transformation series, coaching credibility
- camp-insight — food-day, mental prep, life outside gym (camp life, NOT pad work)
- solo-pad-work — him hitting pads / bag solo (de-prioritised this camp)
- bag-flow — technique demos on bag/equipment
- unclassified — doesn't fit

Given the caption + video description, return ONLY ONE of those pillar names.
No explanation, no quotes, just the pillar string."""


def classify_pillar(
    caption: str,
    video_description: str = "",
    api_key: Optional[str] = None,
    model: str = "claude-haiku-4-5-20251001",
) -> str:
    """
    Classify a post into one of Rory's pillars. Returns the pillar string or 'unclassified'.
    """
    try:
        import anthropic
    except ImportError:
        return "unclassified"

    api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return "unclassified"

    user_msg = f"CAPTION:\n{caption}\n\nVIDEO DESCRIPTION:\n{video_description}"

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=model,
            max_tokens=30,
            system=PILLAR_CLASSIFIER_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        result = resp.content[0].text.strip().lower()
        valid = {
            "meme-skit", "class-coaching", "class-candid", "transformation-josh",
            "camp-insight", "solo-pad-work", "bag-flow", "unclassified",
        }
        return result if result in valid else "unclassified"
    except Exception as e:
        logger.warning(f"Pillar classification failed: {e}")
        return "unclassified"


# ---------------------------------------------------------------------------
# Gemini video analysis
# ---------------------------------------------------------------------------

RORY_VIDEO_ANALYSIS_PROMPT = """You are analysing an Instagram Reel for weekly
content intelligence. Produce a first-principles structural breakdown that a
fighter-operator can act on in ≤30 seconds of reading.

Return in this exact structure (keep each section terse, 2-4 lines max):

## Hook (0-3s)
What the first 3 seconds show. Specifically: first visual frame, first audio,
the hook mechanism (face? motion? text? question?). Verdict: does it stop scroll? Y/N + one-line why.

## Body
Pacing (slow / medium / fast). Key cuts or text overlays with rough timestamps.
Tonality (dry / hype / technical / playful). Authenticity read (feels like him
or feels like a creator-template).

## Close
Last 2 seconds. Does he say anything? Explicit CTA? Quiet close? Verdict: does
it invite a save / share / follow, or just end?

## Structural pattern
Classify the structural family: {face-first-hook, motion-hook, text-hook,
trending-sound-carry, teach-then-payoff, reveal-at-end, story-arc, none}

## What worked
2-3 bullets. Specific to this video, not generic advice.

## What to improve
2-3 bullets. Concrete edits that would likely lift performance. No vague advice.

## Authenticity note
One line. Does his voice come through? If not, what's drifting."""


def analyse_video_gemini(
    video_path: Path,
    caption: str = "",
    model: str = "gemini-2.5-flash",
) -> Optional[dict]:
    """
    Run Gemini video analysis on a local MP4. Returns a dict:
        {ok: bool, analysis_md: str, error: str|None}
    """
    try:
        import google.generativeai as genai
    except ImportError:
        logger.error("google-generativeai not installed — pip install google-generativeai")
        return {"ok": False, "analysis_md": "", "error": "google-generativeai missing"}

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        return {"ok": False, "analysis_md": "", "error": "GEMINI_API_KEY missing"}

    if not video_path.exists():
        return {"ok": False, "analysis_md": "", "error": f"file not found: {video_path}"}

    try:
        genai.configure(api_key=api_key)
        gen_model = genai.GenerativeModel(model)

        # Upload the file to Gemini (required for video)
        uploaded = genai.upload_file(path=str(video_path))
        # Wait for active state
        import time as _time
        timeout = 60
        start = _time.time()
        while uploaded.state.name == "PROCESSING" and _time.time() - start < timeout:
            _time.sleep(2)
            uploaded = genai.get_file(uploaded.name)

        if uploaded.state.name != "ACTIVE":
            return {
                "ok": False,
                "analysis_md": "",
                "error": f"Gemini upload state: {uploaded.state.name}",
            }

        prompt_parts = [RORY_VIDEO_ANALYSIS_PROMPT]
        if caption:
            prompt_parts.append(f"\n\nCAPTION:\n{caption}")
        prompt_parts.append(uploaded)

        response = gen_model.generate_content(prompt_parts)
        analysis = response.text.strip()

        # Best-effort cleanup of uploaded file
        try:
            genai.delete_file(uploaded.name)
        except Exception:
            pass

        return {"ok": True, "analysis_md": analysis, "error": None}
    except Exception as e:
        logger.error(f"Gemini analysis failed: {e}")
        return {"ok": False, "analysis_md": "", "error": str(e)}


# ---------------------------------------------------------------------------
# Full per-post pipeline
# ---------------------------------------------------------------------------

@dataclass
class PostAnalysis:
    post_id: str
    url: str
    caption: str
    pillar: str = "unclassified"
    metrics: dict = field(default_factory=dict)
    gemini_analysis: str = ""
    gemini_error: Optional[str] = None
    video_path: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "post_id": self.post_id,
            "url": self.url,
            "caption": self.caption,
            "pillar": self.pillar,
            "metrics": self.metrics,
            "gemini_analysis": self.gemini_analysis,
            "gemini_error": self.gemini_error,
            "video_path": self.video_path,
        }


def analyse_post(
    post_id: str,
    url: str,
    caption: str,
    metrics: dict,
    workdir: Path,
    classify: bool = True,
    run_gemini: bool = True,
) -> PostAnalysis:
    """
    Full pipeline for one post: download, classify, Gemini-analyse.
    """
    result = PostAnalysis(
        post_id=post_id,
        url=url,
        caption=caption,
        metrics=metrics,
    )

    if classify:
        result.pillar = classify_pillar(caption=caption)

    if run_gemini:
        video_path = download_video(url, workdir)
        if video_path:
            result.video_path = str(video_path)
            gemini_result = analyse_video_gemini(video_path, caption=caption)
            if gemini_result and gemini_result["ok"]:
                result.gemini_analysis = gemini_result["analysis_md"]
            else:
                result.gemini_error = gemini_result["error"] if gemini_result else "unknown"
        else:
            result.gemini_error = "video download failed"

    return result


def analyse_posts_batch(
    posts: list[dict],
    workdir: Path,
    classify: bool = True,
    run_gemini: bool = True,
) -> list[PostAnalysis]:
    """
    Analyse a list of posts. Each post dict needs: id, url, caption, metrics.
    Returns a list of PostAnalysis.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    results = []
    for p in posts:
        try:
            pa = analyse_post(
                post_id=p.get("id", ""),
                url=p.get("url", ""),
                caption=p.get("caption", ""),
                metrics=p.get("metrics", {}),
                workdir=workdir,
                classify=classify,
                run_gemini=run_gemini,
            )
            results.append(pa)
        except Exception as e:
            logger.error(f"analyse_post failed for {p.get('id')}: {e}")
            results.append(PostAnalysis(
                post_id=p.get("id", ""),
                url=p.get("url", ""),
                caption=p.get("caption", ""),
                metrics=p.get("metrics", {}),
                gemini_error=str(e),
            ))
    return results


def analyse_competitor_urls(
    urls: list[str],
    workdir: Path,
    max_videos: int = 10,
) -> list[dict]:
    """
    Analyse a manual list of competitor post URLs (v1 — before auto-scraping).
    Returns list of dicts: {url, pillar, gemini_analysis, error}
    """
    urls = urls[:max_videos]
    workdir.mkdir(parents=True, exist_ok=True)
    results = []

    for url in urls:
        entry = {"url": url, "pillar": "unclassified", "gemini_analysis": "", "error": None}
        video_path = download_video(url, workdir)
        if not video_path:
            entry["error"] = "download failed"
            results.append(entry)
            continue

        g = analyse_video_gemini(video_path, caption="")
        if g and g["ok"]:
            entry["gemini_analysis"] = g["analysis_md"]
            # Pillar classification from video description — use the analysis itself
            entry["pillar"] = classify_pillar(
                caption="",
                video_description=g["analysis_md"][:2000],
            )
        else:
            entry["error"] = g["error"] if g else "gemini failed"
        results.append(entry)

    return results


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) < 2:
        print("Usage: python -m core.content_analysis <url>")
        sys.exit(1)

    url = sys.argv[1]
    with tempfile.TemporaryDirectory() as tmp:
        results = analyse_competitor_urls([url], Path(tmp))
        print(json.dumps(results, indent=2))
