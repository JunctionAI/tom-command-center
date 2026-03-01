#!/usr/bin/env python3
"""
Creative Brief Generator -- Ogilvy DO Brief methodology adapted for DTC supplement marketing.

Produces elite designer-ready briefs from strategy + data + brand guidelines.
Integrated with DBH's proven creative formulas and platform specifications.

Usage:
    python brief_generator.py generate --campaign-type product_launch --product "Green Lipped Mussel" \
        --audience "Joint pain sufferers 45-65" --message "Natural joint support backed by science" \
        --platforms meta_feed,email_hero --deadline 2026-03-15

    python brief_generator.py from-insight "GLM sales are down 12% this week. \
        Competitor launched a cheaper joint supplement. Need a trust-based counter-campaign."

    python brief_generator.py list
    python brief_generator.py view <brief_id>
    python brief_generator.py update-status <brief_id> approved
    python brief_generator.py sample
"""

import sqlite3
import json
import os
import sys
import uuid
import textwrap
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "briefs.db"


# ---------------------------------------------------------------------------
# PROVEN FORMULAS -- from 133 email + 5 Meta campaign analysis
# ---------------------------------------------------------------------------

PROVEN_FORMULAS = {
    "exclusive_access_countdown": {
        "name": "Exclusive Access + Countdown",
        "roas": 7.2,
        "description": "Early access framing with countdown timer creates urgency without discount dependency.",
        "best_for": ["product_launch", "flash_sale", "vip_campaign"],
        "email_evidence": "$9,259 single-email revenue, 42.3% open rate",
        "meta_evidence": "8.45x ROAS on scarcity-framed Meta ads",
        "copy_hooks": [
            "You're getting first access before anyone else",
            "Only [X] hours left -- your exclusive window closes at midnight",
            "VIP early access: this isn't available to the public yet",
        ],
        "design_direction": "Countdown timer element, exclusive badge/seal, premium dark background, gold/bronze accents",
        "avoid": "Overuse -- max 4-6 scarcity campaigns per year or credibility dies",
    },
    "event_announcement": {
        "name": "Event Announcement",
        "roas": 6.8,
        "description": "Frame the campaign as an event worth attending, not a sale worth buying.",
        "best_for": ["seasonal_sale", "product_launch", "brand_moment"],
        "email_evidence": "77.1% open rate on gift-framed event announcements",
        "meta_evidence": "Strong engagement when paired with benefit-specific creative",
        "copy_hooks": [
            "Something special is happening at Deep Blue Health",
            "Mark your calendar -- this only happens once a year",
            "You're invited: [Event Name]",
        ],
        "design_direction": "Event poster aesthetic, date prominently displayed, anticipation-building visuals, clean typography",
        "avoid": "Burying the event details -- date, time, and what they get must be immediate",
    },
    "testimonial_social_proof": {
        "name": "Testimonial / Social Proof",
        "roas": 6.1,
        "description": "Real customer voice removes the #1 purchase objection: 'does it actually work?'",
        "best_for": ["always_on", "retargeting", "new_audience", "trust_building"],
        "email_evidence": "48.53% open rate, $1,067 from 963 recipients on trust-framed sends",
        "meta_evidence": "7.78x ROAS -- highest sustainable Meta formula",
        "copy_hooks": [
            "\"I noticed the difference in just 3 weeks\" -- [Customer Name], [Location]",
            "Join 10,000+ New Zealanders who trust Deep Blue Health",
            "Real results from real people -- no filters, no scripts",
        ],
        "design_direction": "Real customer photo (not stock), warm colour palette, trust badge bottom-right, quote typography prominent",
        "avoid": "Fake testimonials, stock imagery pretending to be customers, unsubstantiated claims",
    },
    "day_of_product_grid": {
        "name": "Day-of Announcement + Product Grid",
        "roas": 5.9,
        "description": "Launch day energy with a visual product grid showing the full range available.",
        "best_for": ["product_launch", "sale_day", "collection_highlight"],
        "email_evidence": "$4,834 revenue from segmented product grid emails, 31.4% open rate",
        "meta_evidence": "4.06x ROAS on tiered bundle presentation format",
        "copy_hooks": [
            "It's here. Shop the full range now.",
            "Today only: the complete [Collection Name] is live",
            "Everything you need for [benefit] -- all in one place",
        ],
        "design_direction": "Clean product grid layout, consistent product photography, price/savings callout per item, category colour coding",
        "avoid": "Cluttered grids with too many products -- max 4-6 items for clarity",
    },
    "final_deadline_countdown": {
        "name": "Final Deadline + Countdown",
        "roas": 5.8,
        "description": "Last-chance urgency for people who opened previous emails but didn't convert.",
        "best_for": ["campaign_close", "flash_sale_end", "seasonal_finale"],
        "email_evidence": "$4,471 revenue, 42.3% open rate on BFCM Last Chance emails",
        "meta_evidence": "Loss aversion framing outperforms gain framing 2:1 in supplement DTC",
        "copy_hooks": [
            "Final hours: this ends at midnight",
            "Last chance -- once it's gone, it's gone",
            "We won't be offering this again until [next occasion]",
        ],
        "design_direction": "High-contrast urgency visual, red/orange accents, countdown clock, single bold CTA button, minimal copy",
        "avoid": "Using 'final chance' language when it isn't actually final -- destroys trust permanently",
    },
}


# ---------------------------------------------------------------------------
# PLATFORM PRESETS
# ---------------------------------------------------------------------------

PLATFORM_PRESETS = {
    "meta_feed": {
        "name": "Meta Feed (Facebook/Instagram)",
        "dimensions": "1080x1080px (square) or 1080x1350px (portrait, recommended)",
        "file_types": "JPG, PNG (static) or MP4, MOV (video, max 240min)",
        "primary_text_limit": 125,
        "headline_limit": 40,
        "description_limit": 30,
        "aspect_ratio": "1:1 or 4:5",
        "notes": "First 3 lines of primary text visible before 'See more'. Front-load the hook. 4:5 portrait gets 20% more real estate in feed.",
        "cta_options": ["Shop Now", "Learn More", "Sign Up", "Get Offer"],
    },
    "meta_stories": {
        "name": "Meta Stories (Facebook/Instagram)",
        "dimensions": "1080x1920px (full-screen vertical)",
        "file_types": "JPG, PNG (static, 5s display) or MP4, MOV (video, max 15s for ads)",
        "primary_text_limit": 125,
        "headline_limit": 40,
        "description_limit": 30,
        "aspect_ratio": "9:16",
        "notes": "Keep text in top 80% -- bottom 20% is CTA zone. No small text. Design for thumb-stopping in first 0.5s. Sound-off by default.",
        "cta_options": ["Shop Now", "Swipe Up", "Learn More"],
    },
    "email_hero": {
        "name": "Email Hero Image (Klaviyo)",
        "dimensions": "600px wide (height flexible, recommended 300-400px for above-the-fold)",
        "file_types": "JPG, PNG, GIF (animated). Keep under 200KB for load speed.",
        "primary_text_limit": None,
        "headline_limit": 60,
        "description_limit": None,
        "aspect_ratio": "Flexible, typically 3:2 or 2:1",
        "notes": "Hero image must work without images loaded (alt text matters). Subject line is your real headline. Preview text is your second hook. Single CTA above the fold.",
        "subject_line_limit": 50,
        "preview_text_limit": 90,
        "cta_options": ["Shop Now", "Discover More", "Claim Your Gift", "See Results"],
    },
    "shopify_banner": {
        "name": "Shopify Homepage Banner",
        "dimensions": "1200x400px (desktop) + 750x750px (mobile version recommended)",
        "file_types": "JPG, PNG. Keep under 500KB.",
        "primary_text_limit": None,
        "headline_limit": 40,
        "description_limit": 80,
        "aspect_ratio": "3:1 (desktop), 1:1 (mobile)",
        "notes": "Text must be legible on mobile. Use overlay for readability on product photos. CTA button, not just text link. Align with current homepage collection.",
        "cta_options": ["Shop Now", "Explore Range", "Learn More", "Shop the Sale"],
    },
    "tiktok_reels": {
        "name": "TikTok / Instagram Reels",
        "dimensions": "1080x1920px (full-screen vertical)",
        "file_types": "MP4, MOV. Max 60s for Reels, 3min for TikTok.",
        "primary_text_limit": 150,
        "headline_limit": None,
        "description_limit": None,
        "aspect_ratio": "9:16",
        "duration_options": ["15s (recommended for ads)", "30s", "60s"],
        "notes": "Hook in first 1-2 seconds. Native-feeling content outperforms polished ads. Caption/subtitle overlay for sound-off viewing. Trending audio when relevant.",
        "cta_options": ["Link in Bio", "Shop Now", "Learn More"],
    },
}


# ---------------------------------------------------------------------------
# BRAND GUIDELINES -- DBH constants
# ---------------------------------------------------------------------------

BRAND_GUIDELINES = {
    "company": "Deep Blue Health",
    "established": "2004",
    "location": "Penrose, Auckland, New Zealand",
    "positioning": "Nature's Secrets -- premium natural health supplements from NZ",
    "values": ["Pure", "Potent", "Traceable"],
    "tone": {
        "primary": "Educational-first, sales-second",
        "secondary": "Scientific authority + conversational accessibility",
        "tertiary": "Warm, trustworthy, proudly New Zealand",
    },
    "mandatory_elements": [
        "Deep Blue Health logo (approved brand asset)",
        "Product series colour coding where applicable",
        "NZ-made trust badge on all customer-facing creative",
    ],
    "mandatory_disclaimers": [
        "Always consult your healthcare professional before starting any supplement.",
        "This product is not intended to diagnose, treat, cure, or prevent any disease.",
        "Results may vary from person to person.",
    ],
    "compliance_rules": [
        "Use 'supports' and 'helps maintain' -- NEVER 'cures' or 'treats'",
        "NZ TAPS/ASA compliant language only",
        "No before/after body images on Meta",
        "No personal health attribute targeting on Meta",
        "Google Ads: no guarantees of efficacy",
        "Testimonials must be genuine, verifiable customer experiences",
    ],
    "product_series_colours": {
        "Animal": "#E18229",
        "Bee": "#FFCC04",
        "Dairy": "#008F4C",
        "Marine": "#0068AD",
        "Herbal": "#74B843",
        "Vitamin": "#AF282E",
    },
    "key_products": [
        "Green Lipped Mussel (GLM)",
        "Marine Collagen",
        "Deer Velvet",
        "Sea Cucumber",
        "Pure Pets (sub-brand)",
        "Propolis range",
        "Colostrum",
        "Krill Oil",
        "Bee Venom",
    ],
}


# ---------------------------------------------------------------------------
# TARGET AUDIENCE PROFILES
# ---------------------------------------------------------------------------

AUDIENCE_PROFILES = {
    "joint_health": {
        "demographic": "Adults 45-70, skewing female (60/40), NZ + AU primary, moderate-high income",
        "psychographic": "Active lifestyle compromised by joint discomfort. Values natural solutions over pharmaceuticals. Research-oriented -- reads labels, compares ingredients. Distrusts 'miracle cure' marketing. Willing to pay premium for quality and proven results.",
        "pain_points": ["Morning stiffness limiting daily activities", "Concern about long-term NSAID use", "Want to stay active with grandchildren/exercise", "Overwhelmed by supplement choices"],
        "purchase_triggers": ["Social proof from peers", "Specific clinical evidence", "NZ-made quality assurance", "Money-back guarantee"],
    },
    "beauty_wellness": {
        "demographic": "Women 30-55, NZ + AU + Asian markets, middle-high income",
        "psychographic": "Believes beauty starts from within. Prefers ingestible beauty over topical-only approach. Follows wellness trends but sceptical of fads. Values clean, traceable ingredients. Often buys for both health and aesthetic benefits.",
        "pain_points": ["Visible signs of aging (skin, hair, nails)", "Supplement fatigue -- too many pills", "Confusion about collagen types and dosage", "Want results they can actually see"],
        "purchase_triggers": ["Before/after timelines (4-8 weeks)", "Marine collagen vs bovine comparison", "Ingredient transparency", "Bundle value"],
    },
    "immune_health": {
        "demographic": "Adults 35-65, families with children, NZ primary",
        "psychographic": "Proactive about family health. Seasonal supplement buyers (winter peaks). Values New Zealand purity and natural immune support. Often buying for household, not just self.",
        "pain_points": ["Frequent colds/flu in family", "Children's immune support concerns", "Want to reduce sick days", "Preference for natural over synthetic vitamins"],
        "purchase_triggers": ["Seasonal urgency (winter)", "Family bundle pricing", "NZ Propolis/Colostrum reputation", "Educational content about immune mechanisms"],
    },
    "pet_health": {
        "demographic": "Dog/cat owners 35-65, NZ primary, moderate income",
        "psychographic": "Treats pets as family members. Will spend on pet health when they see results. Emotional purchase decision masked as rational. Responds to pet-parent community and shared stories.",
        "pain_points": ["Aging pet showing mobility issues", "Vet bills escalating", "Want natural alternatives to pet pharmaceuticals", "Guilt about pet discomfort"],
        "purchase_triggers": ["Pet testimonials with photos/videos", "Vet endorsements", "Visible pet mobility improvement stories", "Subscription convenience"],
    },
    "general_wellness": {
        "demographic": "Adults 25-60, broad, NZ + international",
        "psychographic": "Health-conscious but not obsessive. Supplements as part of a balanced lifestyle. Values convenience and quality. Brand-loyal once trust is established.",
        "pain_points": ["Energy levels declining", "Sleep quality issues", "Want to 'do something' proactive about health", "Decision paralysis from too many supplement options"],
        "purchase_triggers": ["Bundle simplicity (one brand, multiple needs)", "Educational authority content", "Trusted NZ manufacturing", "Subscription discounts"],
    },
}


# ---------------------------------------------------------------------------
# CAMPAIGN TYPES
# ---------------------------------------------------------------------------

CAMPAIGN_TYPES = {
    "product_launch": {
        "name": "Product Launch",
        "description": "Introducing a new product or reformulation to market",
        "recommended_formulas": ["event_announcement", "day_of_product_grid", "exclusive_access_countdown"],
        "typical_sequence": ["Teaser (3-5 days out)", "Launch day announcement", "Social proof follow-up (day 3-5)", "Last chance (day 7)"],
        "default_success_metrics": {"target_roas": 4.0, "target_ctr": 2.5, "target_conversion_rate": 2.0},
    },
    "seasonal_sale": {
        "name": "Seasonal Sale (BFCM, Boxing Day, etc.)",
        "description": "Time-bound promotional event tied to calendar moment",
        "recommended_formulas": ["exclusive_access_countdown", "final_deadline_countdown", "day_of_product_grid"],
        "typical_sequence": ["Early access (VIP, 24hrs before)", "Sale launch", "Mid-sale bestsellers reminder", "Final hours"],
        "default_success_metrics": {"target_roas": 6.0, "target_ctr": 3.0, "target_conversion_rate": 3.5},
    },
    "always_on": {
        "name": "Always-On / Evergreen",
        "description": "Continuous campaigns running in the background for consistent acquisition",
        "recommended_formulas": ["testimonial_social_proof"],
        "typical_sequence": ["Rotate 3-5 creatives monthly", "Test new angles quarterly"],
        "default_success_metrics": {"target_roas": 5.0, "target_ctr": 2.0, "target_conversion_rate": 1.5},
    },
    "retargeting": {
        "name": "Retargeting / Re-engagement",
        "description": "Reaching people who visited but didn't convert, or lapsed customers",
        "recommended_formulas": ["testimonial_social_proof", "final_deadline_countdown"],
        "typical_sequence": ["Social proof ad (day 1-3 post-visit)", "Offer/incentive (day 4-7)", "Final nudge (day 8-14)"],
        "default_success_metrics": {"target_roas": 7.0, "target_ctr": 3.5, "target_conversion_rate": 4.0},
    },
    "email_nurture": {
        "name": "Email Nurture / Flow",
        "description": "Automated email sequence building trust and driving conversion over time",
        "recommended_formulas": ["testimonial_social_proof", "event_announcement"],
        "typical_sequence": ["Welcome + brand story", "Education + mechanism of action", "Social proof + results", "Offer + CTA"],
        "default_success_metrics": {"target_open_rate": 45.0, "target_click_rate": 3.0, "target_revenue_per_email": 2000},
    },
    "flash_sale": {
        "name": "Flash Sale (24-48hr)",
        "description": "Short-window urgency campaign for manufactured scarcity",
        "recommended_formulas": ["exclusive_access_countdown", "final_deadline_countdown"],
        "typical_sequence": ["Announcement (hour 0)", "Reminder (hour 12-18)", "Final hours (last 4hrs)"],
        "default_success_metrics": {"target_roas": 5.5, "target_ctr": 3.0, "target_conversion_rate": 3.0},
    },
    "trust_building": {
        "name": "Trust & Authority Building",
        "description": "Non-promotional content establishing brand credibility and expertise",
        "recommended_formulas": ["testimonial_social_proof"],
        "typical_sequence": ["Educational content", "Customer stories", "Behind-the-scenes / sourcing", "Expert endorsement"],
        "default_success_metrics": {"target_engagement_rate": 5.0, "target_save_rate": 2.0},
    },
}


# ---------------------------------------------------------------------------
# BRIEF DATABASE
# ---------------------------------------------------------------------------

class BriefDB:
    """SQLite storage for brief tracking and performance."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS briefs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                campaign_type TEXT NOT NULL,
                product TEXT,
                target_audience TEXT,
                platforms TEXT,
                proven_formula TEXT,
                status TEXT DEFAULT 'draft',
                assigned_to TEXT DEFAULT 'unassigned',
                deadline TEXT,
                brief_markdown TEXT NOT NULL,
                brief_data TEXT,
                performance_data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                approved_at TIMESTAMP,
                delivered_at TIMESTAMP,
                live_at TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS brief_revisions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id TEXT NOT NULL,
                revision_number INTEGER NOT NULL,
                changes TEXT,
                changed_by TEXT,
                brief_markdown TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (brief_id) REFERENCES briefs(brief_id)
            );

            CREATE TABLE IF NOT EXISTS brief_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brief_id TEXT NOT NULL,
                feedback_from TEXT NOT NULL,
                feedback TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (brief_id) REFERENCES briefs(brief_id)
            );

            CREATE INDEX IF NOT EXISTS idx_briefs_status ON briefs(status);
            CREATE INDEX IF NOT EXISTS idx_briefs_campaign ON briefs(campaign_type);
            CREATE INDEX IF NOT EXISTS idx_briefs_assigned ON briefs(assigned_to);
            CREATE INDEX IF NOT EXISTS idx_briefs_created ON briefs(created_at);
        """)
        self.conn.commit()

    def save_brief(self, brief_id: str, title: str, campaign_type: str,
                   product: str, target_audience: str, platforms: str,
                   proven_formula: str, deadline: str, brief_markdown: str,
                   brief_data: str = None, assigned_to: str = "unassigned") -> int:
        cursor = self.conn.execute(
            """INSERT INTO briefs
               (brief_id, title, campaign_type, product, target_audience, platforms,
                proven_formula, status, assigned_to, deadline, brief_markdown, brief_data)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?, ?, ?)""",
            (brief_id, title, campaign_type, product, target_audience, platforms,
             proven_formula, assigned_to, deadline, brief_markdown, brief_data)
        )
        self.conn.commit()
        return cursor.lastrowid

    def update_status(self, brief_id: str, new_status: str, assigned_to: str = None):
        valid = ["draft", "approved", "in_progress", "delivered", "live", "archived"]
        if new_status not in valid:
            raise ValueError(f"Invalid status '{new_status}'. Must be one of: {valid}")

        timestamp_field = {
            "approved": "approved_at",
            "delivered": "delivered_at",
            "live": "live_at",
        }.get(new_status)

        if timestamp_field:
            self.conn.execute(
                f"UPDATE briefs SET status = ?, {timestamp_field} = ?, updated_at = ? WHERE brief_id = ?",
                (new_status, datetime.now().isoformat(), datetime.now().isoformat(), brief_id)
            )
        else:
            self.conn.execute(
                "UPDATE briefs SET status = ?, updated_at = ? WHERE brief_id = ?",
                (new_status, datetime.now().isoformat(), brief_id)
            )

        if assigned_to:
            self.conn.execute(
                "UPDATE briefs SET assigned_to = ? WHERE brief_id = ?",
                (assigned_to, brief_id)
            )

        self.conn.commit()

    def update_performance(self, brief_id: str, performance_data: dict):
        self.conn.execute(
            "UPDATE briefs SET performance_data = ?, updated_at = ? WHERE brief_id = ?",
            (json.dumps(performance_data), datetime.now().isoformat(), brief_id)
        )
        self.conn.commit()

    def get_brief(self, brief_id: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT * FROM briefs WHERE brief_id = ?", (brief_id,)
        ).fetchone()
        return dict(row) if row else None

    def list_briefs(self, status: str = None, limit: int = 20) -> list:
        if status:
            rows = self.conn.execute(
                "SELECT brief_id, title, campaign_type, product, status, assigned_to, deadline, created_at "
                "FROM briefs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT brief_id, title, campaign_type, product, status, assigned_to, deadline, created_at "
                "FROM briefs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def add_feedback(self, brief_id: str, feedback_from: str, feedback: str):
        self.conn.execute(
            "INSERT INTO brief_feedback (brief_id, feedback_from, feedback) VALUES (?, ?, ?)",
            (brief_id, feedback_from, feedback)
        )
        self.conn.commit()

    def save_revision(self, brief_id: str, changes: str, changed_by: str, brief_markdown: str):
        rev_num = self.conn.execute(
            "SELECT COALESCE(MAX(revision_number), 0) + 1 FROM brief_revisions WHERE brief_id = ?",
            (brief_id,)
        ).fetchone()[0]
        self.conn.execute(
            "INSERT INTO brief_revisions (brief_id, revision_number, changes, changed_by, brief_markdown) "
            "VALUES (?, ?, ?, ?, ?)",
            (brief_id, rev_num, changes, changed_by, brief_markdown)
        )
        self.conn.commit()

    def close(self):
        self.conn.close()


# ---------------------------------------------------------------------------
# BRIEF GENERATOR
# ---------------------------------------------------------------------------

class BriefGenerator:
    """
    Ogilvy DO Brief methodology adapted for DTC supplement marketing.
    Generates designer-ready creative briefs from strategy, data, and brand guidelines.
    """

    def __init__(self, db: BriefDB = None):
        self.db = db or BriefDB()

    def _select_formula(self, campaign_type: str, product: str = None) -> dict:
        """Select the best proven formula for this campaign type."""
        ct = CAMPAIGN_TYPES.get(campaign_type, {})
        recommended = ct.get("recommended_formulas", [])
        if recommended:
            formula_key = recommended[0]
        else:
            formula_key = "testimonial_social_proof"
        return formula_key, PROVEN_FORMULAS[formula_key]

    def _resolve_audience(self, target_audience: str) -> dict:
        """Match free-text audience to a profile or build a custom one."""
        lower = target_audience.lower()
        if any(kw in lower for kw in ["joint", "glm", "mussel", "mobility", "arthritis"]):
            return AUDIENCE_PROFILES["joint_health"]
        elif any(kw in lower for kw in ["beauty", "collagen", "skin", "hair", "nail", "aging"]):
            return AUDIENCE_PROFILES["beauty_wellness"]
        elif any(kw in lower for kw in ["immune", "cold", "flu", "propolis", "colostrum", "winter"]):
            return AUDIENCE_PROFILES["immune_health"]
        elif any(kw in lower for kw in ["pet", "dog", "cat", "pure pets", "animal"]):
            return AUDIENCE_PROFILES["pet_health"]
        else:
            return AUDIENCE_PROFILES["general_wellness"]

    def _resolve_product_series(self, product: str) -> Optional[str]:
        """Determine which DBH product series a product belongs to."""
        lower = product.lower()
        mapping = {
            "Marine": ["glm", "mussel", "sea cucumber", "marine collagen", "krill", "shark", "oyster", "seamax"],
            "Animal": ["deer velvet", "deer blood"],
            "Bee": ["propolis", "bee venom", "bee pollen", "manuka"],
            "Dairy": ["colostrum", "milk"],
            "Herbal": ["maca", "hemp"],
            "Vitamin": ["vitamin", "zinc", "multi"],
        }
        for series, keywords in mapping.items():
            if any(kw in lower for kw in keywords):
                return series
        return None

    def generate_brief(
        self,
        campaign_type: str,
        product: str,
        target_audience: str,
        key_message: str,
        platforms: list[str],
        deadline: str,
        campaign_name: str = None,
        proven_formula_override: str = None,
        assigned_to: str = "Roie",
        objective: str = None,
        key_insight: str = None,
        proof_points: list[str] = None,
        review_rounds: int = 2,
        budget_note: str = None,
    ) -> tuple[str, str]:
        """
        Generate a complete creative brief in markdown format.

        Returns:
            (brief_id, brief_markdown)
        """
        # Resolve components
        brief_id = f"BRIEF-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"

        if proven_formula_override and proven_formula_override in PROVEN_FORMULAS:
            formula_key = proven_formula_override
            formula = PROVEN_FORMULAS[formula_key]
        else:
            formula_key, formula = self._select_formula(campaign_type, product)

        audience = self._resolve_audience(target_audience)
        ct = CAMPAIGN_TYPES.get(campaign_type, CAMPAIGN_TYPES["always_on"])
        product_series = self._resolve_product_series(product)
        series_colour = BRAND_GUIDELINES["product_series_colours"].get(product_series, "#0068AD")

        # Build campaign name
        if not campaign_name:
            campaign_name = f"{product} -- {ct['name']} ({datetime.now().strftime('%b %Y')})"

        # Build objective
        if not objective:
            objective = f"Drive measurable revenue from {product} through a {ct['name'].lower()} campaign using the {formula['name']} formula, targeting {target_audience}."

        # Build key insight
        if not key_insight:
            if audience.get("pain_points"):
                key_insight = (
                    f"Our target audience's core tension: {audience['pain_points'][0]}. "
                    f"They want a solution they can trust, not another marketing promise."
                )

        # Build proof points
        if not proof_points:
            proof_points = [
                "100% New Zealand owned and operated since 2004",
                "GMP-registered facility, HACCP-certified manufacturing",
                "No artificial flavours, colours, or preservatives",
                f"Proven creative formula: {formula['name']} ({formula['roas']}x historical ROAS)",
            ]

        # Success metrics
        success_metrics = ct.get("default_success_metrics", {})

        # Build platform specs section
        platform_specs_lines = []
        for p in platforms:
            preset = PLATFORM_PRESETS.get(p)
            if not preset:
                platform_specs_lines.append(f"### {p}\n*Custom platform -- specify dimensions and requirements.*\n")
                continue
            lines = [f"### {preset['name']}"]
            lines.append(f"- **Dimensions:** {preset['dimensions']}")
            lines.append(f"- **Aspect Ratio:** {preset['aspect_ratio']}")
            lines.append(f"- **File Types:** {preset['file_types']}")
            if preset.get("primary_text_limit"):
                lines.append(f"- **Primary Text:** {preset['primary_text_limit']} characters max")
            if preset.get("headline_limit"):
                lines.append(f"- **Headline:** {preset['headline_limit']} characters max")
            if preset.get("description_limit"):
                lines.append(f"- **Description:** {preset['description_limit']} characters max")
            if preset.get("subject_line_limit"):
                lines.append(f"- **Subject Line:** {preset['subject_line_limit']} characters max")
            if preset.get("preview_text_limit"):
                lines.append(f"- **Preview Text:** {preset['preview_text_limit']} characters max")
            if preset.get("duration_options"):
                lines.append(f"- **Duration Options:** {', '.join(preset['duration_options'])}")
            lines.append(f"- **CTA Options:** {', '.join(preset.get('cta_options', []))}")
            lines.append(f"- **Notes:** {preset['notes']}")
            platform_specs_lines.append("\n".join(lines))

        platform_specs_section = "\n\n".join(platform_specs_lines)

        # Build copy direction
        copy_hooks = formula.get("copy_hooks", [])
        copy_direction_lines = []
        copy_direction_lines.append("**Headline Options:**")
        for i, hook in enumerate(copy_hooks, 1):
            copy_direction_lines.append(f"{i}. {hook}")

        copy_direction_lines.append("")
        copy_direction_lines.append("**Body Copy Hooks:**")
        copy_direction_lines.append(f"- Lead with: {audience.get('pain_points', [''])[0] if audience.get('pain_points') else 'specific benefit'}")
        copy_direction_lines.append(f"- Bridge to: {key_message}")
        copy_direction_lines.append("- Close with: Single, clear CTA -- one action, one button")

        copy_direction_lines.append("")
        copy_direction_lines.append("**CTA Variations:**")
        all_ctas = set()
        for p in platforms:
            preset = PLATFORM_PRESETS.get(p, {})
            all_ctas.update(preset.get("cta_options", []))
        if not all_ctas:
            all_ctas = {"Shop Now", "Learn More"}
        for cta in sorted(all_ctas):
            copy_direction_lines.append(f"- {cta}")

        copy_direction_section = "\n".join(copy_direction_lines)

        # Build design reference
        design_ref_lines = [
            f"**Formula Design Direction:** {formula.get('design_direction', 'N/A')}",
            "",
            "**Competitor References (aspirational quality standard):**",
            "- AG1: Clean minimalism, scientific credibility, premium feel",
            "- Seed: Editorial photography, sophisticated typography, trust-first messaging",
            "- Thorne: Clinical authority, white space, ingredient transparency",
            "- Momentous: Performance-oriented, bold typography, athlete endorsement aesthetic",
            "",
            "**Mood Board Keywords:**",
            f"- Colour: {series_colour} (product series), Deep Blue (#0068AD), clean whites, natural greens",
            "- Feel: Premium, trustworthy, natural, New Zealand purity",
            "- Typography: Clean sans-serif for headlines, readable serif for body",
            "- Photography: Real products, real customers, NZ landscapes for sourcing context",
        ]
        design_ref_section = "\n".join(design_ref_lines)

        # Build timeline
        try:
            deadline_dt = datetime.strptime(deadline, "%Y-%m-%d")
        except (ValueError, TypeError):
            deadline_dt = datetime.now() + timedelta(days=14)
            deadline = deadline_dt.strftime("%Y-%m-%d")

        review_days = review_rounds * 2
        first_draft_due = (deadline_dt - timedelta(days=review_days + 2)).strftime("%Y-%m-%d")
        final_assets_due = (deadline_dt - timedelta(days=1)).strftime("%Y-%m-%d")

        timeline_lines = [
            f"| Milestone | Date |",
            f"|-----------|------|",
            f"| Brief issued | {datetime.now().strftime('%Y-%m-%d')} |",
            f"| First draft due | {first_draft_due} |",
        ]
        for r in range(1, review_rounds + 1):
            review_date = (deadline_dt - timedelta(days=review_days - (r - 1) * 2 + 1)).strftime("%Y-%m-%d")
            revision_date = (deadline_dt - timedelta(days=review_days - r * 2 + 1)).strftime("%Y-%m-%d")
            timeline_lines.append(f"| Review round {r} | {review_date} |")
            if r < review_rounds:
                timeline_lines.append(f"| Revision {r} due | {revision_date} |")
        timeline_lines.append(f"| Final assets delivered | {final_assets_due} |")
        timeline_lines.append(f"| Go live | {deadline} |")
        timeline_section = "\n".join(timeline_lines)

        # Build success metrics section
        metric_labels = {
            "target_roas": "Target ROAS",
            "target_ctr": "Target CTR",
            "target_conversion_rate": "Target Conversion Rate",
            "target_open_rate": "Target Open Rate",
            "target_click_rate": "Target Click Rate",
            "target_revenue_per_email": "Target Revenue Per Email",
            "target_engagement_rate": "Target Engagement Rate",
            "target_save_rate": "Target Save Rate",
        }
        metrics_lines = []
        for metric, value in success_metrics.items():
            label = metric_labels.get(metric, metric.replace("target_", "").replace("_", " ").title())
            if "roas" in metric.lower():
                metrics_lines.append(f"- **{label}:** {value}x")
            elif "rate" in metric.lower():
                metrics_lines.append(f"- **{label}:** {value}%")
            elif "revenue" in metric.lower():
                metrics_lines.append(f"- **{label}:** ${value:,.0f}")
            elif "ctr" in metric.lower():
                metrics_lines.append(f"- **{label}:** {value}%")
            else:
                metrics_lines.append(f"- **{label}:** {value}")
        metrics_section = "\n".join(metrics_lines) if metrics_lines else "- Define after campaign objectives are confirmed."

        # Build the sequence section
        sequence = ct.get("typical_sequence", [])
        sequence_section = ""
        if sequence:
            sequence_section = "\n**Recommended Campaign Sequence:**\n"
            for i, step in enumerate(sequence, 1):
                sequence_section += f"{i}. {step}\n"

        # Assemble the complete brief
        brief_md = f"""# CREATIVE BRIEF: {campaign_name}
**Brief ID:** `{brief_id}`
**Status:** Draft | **Assigned To:** {assigned_to}
**Created:** {datetime.now().strftime('%Y-%m-%d %H:%M')} | **Deadline:** {deadline}

---

## 1. CAMPAIGN OBJECTIVE
{objective}

---

## 2. TARGET AUDIENCE

**Primary Segment:** {target_audience}

**Demographic:** {audience.get('demographic', 'Define based on campaign specifics.')}

**Psychographic:** {audience.get('psychographic', 'Define based on campaign specifics.')}

**Pain Points:**
{chr(10).join(f'- {pp}' for pp in audience.get('pain_points', ['Define based on campaign specifics.']))}

**Purchase Triggers:**
{chr(10).join(f'- {pt}' for pt in audience.get('purchase_triggers', ['Define based on campaign specifics.']))}

---

## 3. KEY INSIGHT
*The human truth driving this campaign:*

> {key_insight}

---

## 4. PROPOSITION
*What we are offering and why it matters:*

**Product:** {product}
{f'**Product Series:** {product_series} ({series_colour})' if product_series else ''}
**Key Message:** {key_message}

---

## 5. PROVEN FORMULA
*Based on analysis of 133 email campaigns + 5 Meta campaigns (total revenue tracked: $296,959)*

**Selected Formula:** {formula['name']} ({formula['roas']}x historical ROAS)

**Why This Formula:** {formula['description']}

**Evidence:**
- Email: {formula['email_evidence']}
- Meta: {formula['meta_evidence']}

**What To Avoid:** {formula['avoid']}
{sequence_section}
---

## 6. PROOF POINTS
*Data, testimonials, and clinical evidence to support the proposition:*

{chr(10).join(f'- {pp}' for pp in proof_points)}

---

## 7. TONE & FEEL
*From Deep Blue Health brand guidelines:*

- **Primary:** {BRAND_GUIDELINES['tone']['primary']}
- **Secondary:** {BRAND_GUIDELINES['tone']['secondary']}
- **Tertiary:** {BRAND_GUIDELINES['tone']['tertiary']}

**Brand Values:** {' | '.join(BRAND_GUIDELINES['values'])}

**Compliance Reminders:**
{chr(10).join(f'- {cr}' for cr in BRAND_GUIDELINES['compliance_rules'])}

---

## 8. MANDATORY ELEMENTS

{chr(10).join(f'- {me}' for me in BRAND_GUIDELINES['mandatory_elements'])}

**Legal Disclaimers (include where required by platform):**
{chr(10).join(f'- {md}' for md in BRAND_GUIDELINES['mandatory_disclaimers'])}

---

## 9. PLATFORM SPECIFICATIONS

{platform_specs_section}

---

## 10. COPY DIRECTION

{copy_direction_section}

---

## 11. DESIGN REFERENCE

{design_ref_section}

---

## 12. SUCCESS METRICS

{metrics_section}

---

## 13. TIMELINE & REVIEW ROUNDS

{timeline_section}

**Review rounds:** {review_rounds}
{f'**Budget note:** {budget_note}' if budget_note else ''}

---

*Brief generated by Tom Command Center | Ogilvy DO methodology adapted for DTC supplement marketing*
*Proven formula data source: 133 email + 5 Meta campaigns, $296,959 revenue tracked*
"""

        # Save to database
        brief_data = json.dumps({
            "campaign_type": campaign_type,
            "product": product,
            "target_audience": target_audience,
            "key_message": key_message,
            "platforms": platforms,
            "proven_formula": formula_key,
            "success_metrics": success_metrics,
            "audience_profile_key": target_audience,
        })

        self.db.save_brief(
            brief_id=brief_id,
            title=campaign_name,
            campaign_type=campaign_type,
            product=product,
            target_audience=target_audience,
            platforms=",".join(platforms),
            proven_formula=formula_key,
            deadline=deadline,
            brief_markdown=brief_md,
            brief_data=brief_data,
            assigned_to=assigned_to,
        )

        return brief_id, brief_md

    def generate_brief_from_insight(
        self,
        insight: str,
        assigned_to: str = "Roie",
        deadline: str = None,
        platforms: list[str] = None,
    ) -> tuple[str, str]:
        """
        Auto-generate a brief from a raw agent insight or strategic observation.

        Parses the insight to extract campaign parameters and generates a full brief.
        Designed to be called by Meridian (DBH Marketing agent) or any agent that
        identifies a marketing opportunity.

        Args:
            insight: Raw text -- could be a performance alert, competitor observation,
                     strategic recommendation, or opportunity spotted by any agent.
            assigned_to: Who will execute the creative.
            deadline: Override deadline. Defaults to 14 days from now.
            platforms: Override platforms. Defaults to meta_feed + email_hero.

        Returns:
            (brief_id, brief_markdown)
        """
        if not deadline:
            deadline = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
        if not platforms:
            platforms = ["meta_feed", "email_hero"]

        lower = insight.lower()

        # Detect product from insight
        product = "Deep Blue Health Range"
        product_keywords = {
            "Green Lipped Mussel": ["glm", "green lipped mussel", "mussel", "joint"],
            "Marine Collagen": ["marine collagen", "collagen", "skin", "beauty"],
            "Deer Velvet": ["deer velvet", "velvet", "energy", "stamina"],
            "Sea Cucumber": ["sea cucumber", "cucumber"],
            "Pure Pets": ["pure pets", "pet", "dog", "cat"],
            "Propolis": ["propolis", "bee", "immune"],
            "Colostrum": ["colostrum", "immunity"],
            "Krill Oil": ["krill", "omega"],
        }
        for prod_name, keywords in product_keywords.items():
            if any(kw in lower for kw in keywords):
                product = prod_name
                break

        # Detect campaign type from insight
        campaign_type = "always_on"
        type_signals = {
            "product_launch": ["launch", "new product", "introducing", "just arrived", "now available"],
            "seasonal_sale": ["bfcm", "black friday", "boxing day", "christmas", "seasonal", "holiday"],
            "flash_sale": ["flash", "24 hour", "48 hour", "limited time", "quick sale"],
            "retargeting": ["retarget", "lapsed", "win back", "winback", "re-engage", "cart abandon"],
            "email_nurture": ["nurture", "sequence", "flow", "welcome", "onboarding"],
            "trust_building": ["trust", "authority", "credibility", "brand awareness", "educational"],
        }
        for ctype, signals in type_signals.items():
            if any(signal in lower for signal in signals):
                campaign_type = ctype
                break

        # Detect urgency / competitor context
        if any(w in lower for w in ["competitor", "losing", "declining", "down", "dropped", "threat"]):
            campaign_type = campaign_type if campaign_type != "always_on" else "trust_building"

        # Detect audience
        target_audience = "Health-conscious adults 35-65"
        audience_signals = {
            "Joint pain sufferers 45-70": ["joint", "arthritis", "mobility", "stiffness"],
            "Beauty-conscious women 30-55": ["beauty", "collagen", "skin", "aging", "wrinkle"],
            "Immune-concerned families 35-65": ["immune", "cold", "flu", "winter", "children"],
            "Dog/cat owners 35-65": ["pet", "dog", "cat", "puppy", "kitten"],
        }
        for aud, signals in audience_signals.items():
            if any(s in lower for s in signals):
                target_audience = aud
                break

        # Extract key message from insight
        key_message = insight.strip()
        if len(key_message) > 200:
            key_message = key_message[:197] + "..."

        # Determine formula based on detected context
        formula_override = None
        if any(w in lower for w in ["competitor", "trust", "proof", "credibility"]):
            formula_override = "testimonial_social_proof"
        elif any(w in lower for w in ["deadline", "last chance", "ending", "final"]):
            formula_override = "final_deadline_countdown"
        elif any(w in lower for w in ["exclusive", "early access", "vip", "first"]):
            formula_override = "exclusive_access_countdown"
        elif any(w in lower for w in ["launch", "new", "introducing"]):
            formula_override = "event_announcement"

        campaign_name = f"[AUTO] {product} -- Response to Insight ({datetime.now().strftime('%b %d')})"

        return self.generate_brief(
            campaign_type=campaign_type,
            product=product,
            target_audience=target_audience,
            key_message=key_message,
            platforms=platforms,
            deadline=deadline,
            campaign_name=campaign_name,
            proven_formula_override=formula_override,
            assigned_to=assigned_to,
            key_insight=f"Agent insight: {insight.strip()[:500]}",
        )

    def list_briefs(self, status: str = None) -> list:
        return self.db.list_briefs(status=status)

    def view_brief(self, brief_id: str) -> Optional[str]:
        brief = self.db.get_brief(brief_id)
        if brief:
            return brief["brief_markdown"]
        return None

    def update_status(self, brief_id: str, new_status: str, assigned_to: str = None):
        self.db.update_status(brief_id, new_status, assigned_to)

    def update_performance(self, brief_id: str, performance_data: dict):
        self.db.update_performance(brief_id, performance_data)

    def close(self):
        self.db.close()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def print_brief_table(briefs: list):
    """Print a formatted table of briefs."""
    if not briefs:
        print("No briefs found.")
        return

    print(f"\n{'ID':<28} {'Title':<45} {'Status':<12} {'Assigned':<10} {'Deadline':<12}")
    print("-" * 107)
    for b in briefs:
        title = b["title"][:42] + "..." if len(b["title"]) > 45 else b["title"]
        print(f"{b['brief_id']:<28} {title:<45} {b['status']:<12} {b['assigned_to']:<10} {b.get('deadline', 'N/A'):<12}")
    print()


def cli_main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Creative Brief Generator -- Ogilvy DO Brief for DTC supplement marketing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""
        Examples:
          %(prog)s generate --campaign-type product_launch --product "Green Lipped Mussel" \\
              --audience "Joint pain sufferers 45-65" --message "Natural joint support backed by NZ science" \\
              --platforms meta_feed,email_hero --deadline 2026-03-15

          %(prog)s from-insight "GLM sales dropped 12%%. Competitor launched cheaper joint supplement. \\
              Need trust-based counter-campaign to reinforce quality positioning."

          %(prog)s list
          %(prog)s list --status approved
          %(prog)s view BRIEF-20260301-ABC123
          %(prog)s update-status BRIEF-20260301-ABC123 approved
          %(prog)s sample

        Campaign Types: product_launch, seasonal_sale, always_on, retargeting, email_nurture, flash_sale, trust_building
        Platforms: meta_feed, meta_stories, email_hero, shopify_banner, tiktok_reels
        Proven Formulas: exclusive_access_countdown, event_announcement, testimonial_social_proof, day_of_product_grid, final_deadline_countdown
        """)
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # generate
    gen_parser = subparsers.add_parser("generate", help="Generate a new creative brief")
    gen_parser.add_argument("--campaign-type", required=True, help="Campaign type (e.g. product_launch)")
    gen_parser.add_argument("--product", required=True, help="Product name")
    gen_parser.add_argument("--audience", required=True, help="Target audience description")
    gen_parser.add_argument("--message", required=True, help="Key message / proposition")
    gen_parser.add_argument("--platforms", required=True, help="Comma-separated platforms (e.g. meta_feed,email_hero)")
    gen_parser.add_argument("--deadline", required=True, help="Deadline date (YYYY-MM-DD)")
    gen_parser.add_argument("--name", help="Campaign name (auto-generated if omitted)")
    gen_parser.add_argument("--formula", help="Override proven formula selection")
    gen_parser.add_argument("--assigned-to", default="Roie", help="Assigned designer (default: Roie)")
    gen_parser.add_argument("--objective", help="Campaign objective (auto-generated if omitted)")
    gen_parser.add_argument("--insight", help="Key human insight driving this campaign")
    gen_parser.add_argument("--review-rounds", type=int, default=2, help="Number of review rounds (default: 2)")
    gen_parser.add_argument("--save-file", help="Also save brief to a markdown file at this path")

    # from-insight
    insight_parser = subparsers.add_parser("from-insight", help="Auto-generate brief from an agent insight")
    insight_parser.add_argument("insight", help="Raw insight text")
    insight_parser.add_argument("--assigned-to", default="Roie", help="Assigned designer (default: Roie)")
    insight_parser.add_argument("--deadline", help="Deadline (YYYY-MM-DD, default: 14 days)")
    insight_parser.add_argument("--platforms", help="Comma-separated platforms (default: meta_feed,email_hero)")
    insight_parser.add_argument("--save-file", help="Also save brief to a markdown file at this path")

    # list
    list_parser = subparsers.add_parser("list", help="List all briefs")
    list_parser.add_argument("--status", help="Filter by status (draft/approved/in_progress/delivered/live)")

    # view
    view_parser = subparsers.add_parser("view", help="View a brief by ID")
    view_parser.add_argument("brief_id", help="Brief ID (e.g. BRIEF-20260301-ABC123)")

    # update-status
    status_parser = subparsers.add_parser("update-status", help="Update brief status")
    status_parser.add_argument("brief_id", help="Brief ID")
    status_parser.add_argument("status", help="New status (draft/approved/in_progress/delivered/live/archived)")
    status_parser.add_argument("--assigned-to", help="Optionally reassign")

    # sample
    subparsers.add_parser("sample", help="Generate a sample brief to demonstrate the system")

    # formulas
    subparsers.add_parser("formulas", help="List all proven formulas with ROAS data")

    # platforms
    subparsers.add_parser("platforms", help="List all platform presets with specs")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    gen = BriefGenerator()

    try:
        if args.command == "generate":
            platforms = [p.strip() for p in args.platforms.split(",")]
            brief_id, brief_md = gen.generate_brief(
                campaign_type=args.campaign_type,
                product=args.product,
                target_audience=args.audience,
                key_message=args.message,
                platforms=platforms,
                deadline=args.deadline,
                campaign_name=args.name,
                proven_formula_override=args.formula,
                assigned_to=args.assigned_to,
                objective=args.objective,
                key_insight=args.insight,
                review_rounds=args.review_rounds,
            )
            print(brief_md)
            print(f"\nBrief saved to database with ID: {brief_id}")
            if args.save_file:
                Path(args.save_file).parent.mkdir(parents=True, exist_ok=True)
                Path(args.save_file).write_text(brief_md)
                print(f"Brief also saved to: {args.save_file}")

        elif args.command == "from-insight":
            platforms = None
            if args.platforms:
                platforms = [p.strip() for p in args.platforms.split(",")]
            brief_id, brief_md = gen.generate_brief_from_insight(
                insight=args.insight,
                assigned_to=args.assigned_to,
                deadline=args.deadline,
                platforms=platforms,
            )
            print(brief_md)
            print(f"\nBrief saved to database with ID: {brief_id}")
            if args.save_file:
                Path(args.save_file).parent.mkdir(parents=True, exist_ok=True)
                Path(args.save_file).write_text(brief_md)
                print(f"Brief also saved to: {args.save_file}")

        elif args.command == "list":
            briefs = gen.list_briefs(status=args.status)
            print_brief_table(briefs)

        elif args.command == "view":
            md = gen.view_brief(args.brief_id)
            if md:
                print(md)
            else:
                print(f"Brief not found: {args.brief_id}")

        elif args.command == "update-status":
            gen.update_status(args.brief_id, args.status, args.assigned_to)
            print(f"Updated {args.brief_id} -> status={args.status}"
                  + (f", assigned_to={args.assigned_to}" if args.assigned_to else ""))

        elif args.command == "sample":
            print("Generating sample brief...\n")
            brief_id, brief_md = gen.generate_brief(
                campaign_type="seasonal_sale",
                product="Green Lipped Mussel",
                target_audience="Joint pain sufferers 45-65, active lifestyle, prefer natural solutions",
                key_message="New Zealand's most trusted joint support -- now at the best price of the year",
                platforms=["meta_feed", "meta_stories", "email_hero", "shopify_banner"],
                deadline=(datetime.now() + timedelta(days=21)).strftime("%Y-%m-%d"),
                campaign_name="GLM Winter Joint Health Sale -- June 2026",
                assigned_to="Roie",
                proof_points=[
                    "Green Lipped Mussel sourced from Marlborough Sounds, NZ",
                    "7.78x ROAS on trust-based Meta campaigns (proven formula)",
                    "48.53% open rate on benefit-specific email sends",
                    "Over 10,000 customers served since 2004",
                    "GMP-certified, no artificial additives",
                    "Customer testimonial: 'I noticed the difference in my morning stiffness within 3 weeks' -- Janet, Christchurch",
                ],
                review_rounds=2,
                budget_note="$500 Meta spend over 14 days, split 60/40 feed/stories",
            )
            print(brief_md)
            print(f"\nSample brief saved with ID: {brief_id}")

        elif args.command == "formulas":
            print("\n=== PROVEN CREATIVE FORMULAS ===")
            print(f"{'Formula':<35} {'ROAS':<8} {'Best For'}")
            print("-" * 80)
            for key, f in PROVEN_FORMULAS.items():
                best_for = ", ".join(f["best_for"][:3])
                print(f"{f['name']:<35} {f['roas']}x    {best_for}")
            print()
            for key, f in PROVEN_FORMULAS.items():
                print(f"\n--- {f['name']} ({f['roas']}x ROAS) ---")
                print(f"  {f['description']}")
                print(f"  Email evidence: {f['email_evidence']}")
                print(f"  Meta evidence: {f['meta_evidence']}")
                print(f"  Avoid: {f['avoid']}")
            print()

        elif args.command == "platforms":
            print("\n=== PLATFORM PRESETS ===")
            for key, p in PLATFORM_PRESETS.items():
                print(f"\n--- {p['name']} (key: {key}) ---")
                print(f"  Dimensions: {p['dimensions']}")
                print(f"  Aspect Ratio: {p['aspect_ratio']}")
                print(f"  File Types: {p['file_types']}")
                if p.get("primary_text_limit"):
                    print(f"  Primary Text: {p['primary_text_limit']} chars")
                if p.get("headline_limit"):
                    print(f"  Headline: {p['headline_limit']} chars")
                if p.get("subject_line_limit"):
                    print(f"  Subject Line: {p['subject_line_limit']} chars")
                print(f"  CTAs: {', '.join(p.get('cta_options', []))}")
                print(f"  Notes: {p['notes']}")
            print()

    finally:
        gen.close()


if __name__ == "__main__":
    cli_main()
