#!/usr/bin/env python3
"""
Design Pipeline -- End-to-end creative production from brief to live ad.

The complete flow:
  1. Agent insight/strategy triggers a creative brief (brief_generator)
  2. Brief assigned to designer (Roie) OR AI pipeline (Pencil/Creatify/Flair)
  3. Design tracked through stages (design_tracker)
  4. Approved creative pushed to Meta/Klaviyo (write-back clients)
  5. Performance tracked back to brief for learning loop

This module orchestrates the full pipeline and provides the integration
points between brief_generator, design_tracker, and the AI creative tools.

Usage:
    from core.design_pipeline import DesignPipeline

    pipeline = DesignPipeline()

    # Create a campaign from an agent insight
    campaign = pipeline.create_campaign_from_insight(
        insight="GLM ROAS dropped 40% -- need fresh creative",
        agent_name="dbh-marketing"
    )

    # Or create from explicit parameters
    campaign = pipeline.create_campaign(
        product="Green Lipped Mussel",
        campaign_type="retargeting",
        audience="Joint pain sufferers 45-65",
        platforms=["meta_feed", "meta_stories", "email_hero"]
    )

    # Get pipeline status for briefings
    status = pipeline.get_pipeline_status()
"""

import json
import logging
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# AI Creative Tool Registry
# ---------------------------------------------------------------------------

AI_CREATIVE_TOOLS = {
    "pencil": {
        "name": "Pencil (trypencil.com)",
        "type": "full_ad_generation",
        "capabilities": ["static_ads", "video_ads", "copy_variants", "performance_prediction"],
        "best_for": ["meta_feed", "meta_stories", "tiktok", "display"],
        "input": "shopify_url + brand_guidelines + brief",
        "output": "multiple ad variants with Pencil Score (predicted performance)",
        "api": "limited",  # API exists but may require Enterprise tier
        "cost_tier": "medium",  # Pro $179/mo annual, Unlimited $599+/mo
        "notes": "Full ad creative suite with performance prediction from $1B ad spend data. "
                 "Direct Shopify + Meta integration. Agent Builder for workflow automation. "
                 "NOTE: trypencil.com NOT pencil.dev (that's a different product).",
        "pricing": {"starter": 79, "pro": 179, "unlimited": 599},
        "shopify_integration": True,
        "meta_direct_publish": True,
    },
    "creatify": {
        "name": "Creatify",
        "type": "video_ad_generation",
        "capabilities": ["video_ads", "ugc_style", "product_demos", "ai_avatars"],
        "best_for": ["meta_feed", "meta_stories", "tiktok", "reels"],
        "input": "product_url",
        "output": "5-10 video ad variants with 1500+ AI avatars",
        "api": True,  # Fully public REST API at docs.creatify.ai
        "cost_tier": "low",  # ~$19/mo
        "notes": "Paste product URL, get video ads. Best for quick video content.",
    },
    "flair_ai": {
        "name": "Flair AI",
        "type": "product_photography",
        "capabilities": ["hero_shots", "lifestyle_scenes", "styled_product_photos"],
        "best_for": ["meta_feed", "email_hero", "shopify_banner"],
        "input": "product_photo + scene_description",
        "output": "styled product images in any setting",
        "api": False,
        "cost_tier": "low",  # ~$29/mo
        "notes": "Drag-and-drop product into AI-generated scenes (ocean, botanicals, etc.)",
    },
    "nanobanana": {
        "name": "NanoBanana (Google Gemini)",
        "type": "style_transfer",
        "capabilities": ["style_transfer", "product_scenes", "text_on_image"],
        "best_for": ["meta_feed", "email_hero", "social"],
        "input": "reference_image + product_photo + description",
        "output": "styled product image matching reference aesthetic",
        "api": True,
        "cost_tier": "free",
        "notes": "Upload Pinterest reference + product = styled output. Free 4K generation.",
    },
    "kling": {
        "name": "Kling AI",
        "type": "image_to_video",
        "capabilities": ["product_reveal_video", "hero_animations", "motion_graphics"],
        "best_for": ["meta_stories", "tiktok", "reels"],
        "input": "static_image + motion_prompt",
        "output": "animated video from still image",
        "api": True,
        "cost_tier": "low",  # ~$7/mo
        "notes": "Animate product photos into hero reveal videos.",
    },
    "captions_ai": {
        "name": "Captions.ai",
        "type": "video_post_production",
        "capabilities": ["auto_captions", "effects", "polish", "talking_head"],
        "best_for": ["tiktok", "reels", "youtube_shorts"],
        "input": "raw_video",
        "output": "polished video with captions and effects",
        "api": False,
        "cost_tier": "low",  # ~$15/mo
        "notes": "Post-production polish for video content.",
    },
    "photoroom": {
        "name": "Photoroom",
        "type": "background_removal",
        "capabilities": ["background_removal", "batch_processing", "product_cutouts"],
        "best_for": ["all"],
        "input": "product_photos",
        "output": "clean cutouts on any background",
        "api": True,
        "cost_tier": "low",  # ~$13/mo
        "notes": "Batch background removal for product images.",
    },
}

# Platform -> recommended tool chain
PLATFORM_TOOL_CHAINS = {
    "meta_feed": ["pencil", "flair_ai", "nanobanana"],
    "meta_stories": ["pencil", "creatify", "kling"],
    "email_hero": ["flair_ai", "nanobanana", "photoroom"],
    "tiktok": ["creatify", "kling", "captions_ai"],
    "reels": ["creatify", "kling", "captions_ai"],
    "shopify_banner": ["flair_ai", "nanobanana", "photoroom"],
}


class DesignPipeline:
    """
    Orchestrates the full creative production pipeline:
    Brief → Design (Human or AI) → Review → Approval → Deployment
    """

    def __init__(self):
        # Lazy-load components to avoid circular imports
        self._brief_gen = None
        self._tracker = None

    @property
    def brief_gen(self):
        if self._brief_gen is None:
            from core.brief_generator import BriefGenerator
            self._brief_gen = BriefGenerator()
        return self._brief_gen

    @property
    def tracker(self):
        if self._tracker is None:
            from core.design_tracker import DesignTracker
            self._tracker = DesignTracker()
        return self._tracker

    # ------------------------------------------------------------------
    # Campaign Creation
    # ------------------------------------------------------------------

    def create_campaign(
        self,
        product: str,
        campaign_type: str,
        audience: str,
        platforms: list[str],
        key_message: str = None,
        deadline_days: int = 7,
        assign_to: str = "AI",  # "Roie" or "AI"
        formula_override: str = None,
    ) -> dict:
        """
        Create a full campaign: brief + design tasks for each platform.

        Returns dict with brief_id, brief_markdown, and task_ids.
        """
        deadline = (datetime.now() + timedelta(days=deadline_days)).strftime("%Y-%m-%d")

        if not key_message:
            key_message = f"Premium NZ {product} -- natural, science-backed, trusted by thousands"

        # 1. Generate the brief
        brief_id, brief_md = self.brief_gen.generate_brief(
            campaign_type=campaign_type,
            product=product,
            target_audience=audience,
            key_message=key_message,
            platforms=platforms,
            deadline=deadline,
            assigned_to=assign_to,
            proven_formula_override=formula_override,
        )

        # 2. Create design tasks for each platform
        task_ids = []
        for platform in platforms:
            # Determine task type from platform
            if platform in ("meta_stories", "tiktok", "reels"):
                task_type = "video"
            elif platform in ("email_hero", "shopify_banner"):
                task_type = "email" if "email" in platform else "banner"
            else:
                task_type = "static_ad"

            # Recommend AI tools for this platform
            recommended_tools = PLATFORM_TOOL_CHAINS.get(platform, ["pencil"])
            tool_names = [AI_CREATIVE_TOOLS[t]["name"] for t in recommended_tools if t in AI_CREATIVE_TOOLS]

            task_id = self.tracker.create_task(
                brief_id=None,  # Link via brief_id string in campaign_name
                assigned_to=assign_to,
                task_type=task_type,
                campaign_name=f"{brief_id}: {product} {platform}",
                platform=platform.split("_")[0] if "_" in platform else platform,
                notes=f"AI tools: {', '.join(tool_names)}\nPlatform: {platform}\nBrief: {brief_id}",
            )
            task_ids.append(task_id)

        # 3. Log to event bus if available
        try:
            from core.event_bus import EventBus
            bus = EventBus()
            bus.publish(
                event_type="content.brief_ready",
                source_agent="design-pipeline",
                severity="NOTABLE",
                payload={
                    "brief_id": brief_id,
                    "product": product,
                    "campaign_type": campaign_type,
                    "platforms": platforms,
                    "assigned_to": assign_to,
                    "task_count": len(task_ids),
                }
            )
            bus.close()
        except Exception:
            pass

        logger.info(f"Campaign created: {brief_id} -- {len(task_ids)} design tasks")

        return {
            "brief_id": brief_id,
            "brief_markdown": brief_md,
            "task_ids": task_ids,
            "assigned_to": assign_to,
            "platforms": platforms,
            "recommended_tools": {
                p: [AI_CREATIVE_TOOLS[t]["name"] for t in PLATFORM_TOOL_CHAINS.get(p, []) if t in AI_CREATIVE_TOOLS]
                for p in platforms
            },
        }

    def create_campaign_from_insight(
        self,
        insight: str,
        agent_name: str,
        assign_to: str = "AI",
    ) -> dict:
        """
        Create a campaign directly from an agent insight.
        Uses the brief_generator's from-insight method.
        """
        brief_id, brief_md = self.brief_gen.generate_brief_from_insight(insight)

        # Parse the brief to extract platforms and product
        # (The brief generator includes platform specs in the markdown)
        platforms = []
        product = "Deep Blue Health"
        for line in brief_md.split("\n"):
            if "Meta Feed" in line:
                platforms.append("meta_feed")
            if "Stories" in line:
                platforms.append("meta_stories")
            if "Email Hero" in line:
                platforms.append("email_hero")
            if "Product:" in line or "Campaign:" in line:
                product = line.split(":", 1)[1].strip()[:50]

        if not platforms:
            platforms = ["meta_feed", "email_hero"]

        # Create design tasks
        task_ids = []
        for platform in platforms:
            task_type = "video" if platform in ("meta_stories", "tiktok", "reels") else "static_ad"
            task_id = self.tracker.create_task(
                brief_id=None,
                assigned_to=assign_to,
                task_type=task_type,
                campaign_name=f"{brief_id}: {product} {platform}",
                platform=platform.split("_")[0] if "_" in platform else platform,
                notes=f"From insight by {agent_name}: {insight[:200]}",
            )
            task_ids.append(task_id)

        logger.info(f"Insight-driven campaign: {brief_id} from {agent_name}")

        return {
            "brief_id": brief_id,
            "brief_markdown": brief_md,
            "task_ids": task_ids,
            "source_agent": agent_name,
            "source_insight": insight,
        }

    # ------------------------------------------------------------------
    # Pipeline Status
    # ------------------------------------------------------------------

    def get_pipeline_status(self) -> str:
        """Get full pipeline status formatted for agent briefings."""
        lines = ["=== CREATIVE PIPELINE STATUS ==="]

        # Active design tasks
        pipeline = self.tracker.format_design_pipeline_status()
        if pipeline:
            lines.append(pipeline)

        # Recommend next actions
        lines.append("\n--- RECOMMENDED ACTIONS ---")

        # Check for overdue tasks
        try:
            overdue = self.tracker.conn.execute("""
                SELECT campaign_name, assigned_to, status,
                       julianday('now') - julianday(assigned_at) as days_open
                FROM design_tasks
                WHERE status NOT IN ('approved', 'live')
                AND julianday('now') - julianday(assigned_at) > 3
                ORDER BY days_open DESC
            """).fetchall()
            if overdue:
                lines.append(f"  OVERDUE: {len(overdue)} tasks open >3 days")
                for t in overdue[:3]:
                    lines.append(f"    - {t['campaign_name']} ({t['assigned_to']}, {int(t['days_open'])}d)")
        except Exception:
            pass

        return "\n".join(lines)

    def get_tool_recommendation(self, platforms: list[str]) -> str:
        """Get AI tool recommendations for given platforms."""
        lines = ["=== AI CREATIVE TOOL RECOMMENDATIONS ==="]
        for platform in platforms:
            tools = PLATFORM_TOOL_CHAINS.get(platform, [])
            if tools:
                lines.append(f"\n{platform}:")
                for t in tools:
                    tool = AI_CREATIVE_TOOLS.get(t, {})
                    lines.append(f"  - {tool.get('name', t)}: {tool.get('notes', '')}")
        return "\n".join(lines)

    def format_for_briefing(self) -> str:
        """Combined brief for morning briefings."""
        parts = []

        # Pipeline status
        pipeline = self.tracker.format_for_briefing()
        if pipeline:
            parts.append(pipeline)

        return "\n\n".join(parts) if parts else ""

    def close(self):
        """Clean up connections."""
        if self._tracker:
            self._tracker.conn.close()
        if self._brief_gen:
            self._brief_gen.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    pipeline = DesignPipeline()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m core.design_pipeline create <product> <type> <audience> <platforms>")
        print("  python -m core.design_pipeline insight <insight_text>")
        print("  python -m core.design_pipeline status")
        print("  python -m core.design_pipeline tools <platform1,platform2>")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "create" and len(sys.argv) >= 6:
        result = pipeline.create_campaign(
            product=sys.argv[2],
            campaign_type=sys.argv[3],
            audience=sys.argv[4],
            platforms=sys.argv[5].split(","),
        )
        print(f"Campaign: {result['brief_id']}")
        print(f"Tasks: {len(result['task_ids'])}")
        print(f"\nTools recommended:")
        for p, tools in result['recommended_tools'].items():
            print(f"  {p}: {', '.join(tools)}")

    elif cmd == "insight" and len(sys.argv) >= 3:
        insight = " ".join(sys.argv[2:])
        result = pipeline.create_campaign_from_insight(insight, "cli")
        print(f"Campaign: {result['brief_id']}")
        print(f"\n{result['brief_markdown'][:500]}...")

    elif cmd == "status":
        print(pipeline.get_pipeline_status())

    elif cmd == "tools" and len(sys.argv) >= 3:
        platforms = sys.argv[2].split(",")
        print(pipeline.get_tool_recommendation(platforms))

    else:
        print("Unknown command")

    pipeline.close()
