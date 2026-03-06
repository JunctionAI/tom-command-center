#!/usr/bin/env python3
"""
Pure Pets Bi-Active — Meta Campaign Builder (Andromeda-Optimized)

Creates the full campaign structure via Meta Marketing API:
  1 Campaign (CBO $55/day, PAUSED)
  1 Ad Set (Broad NZ, Advantage+ Audience)
  12 Ads (all PAUSED, with captions per creative angle)

Usage:
  python core/pure_pets_campaign_builder.py --dry-run   # Preview only
  python core/pure_pets_campaign_builder.py              # Create in PAUSED state

Requires env vars: META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, META_PAGE_ID, META_PIXEL_ID
"""

import os
import sys
import json
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.meta_ads_writer import MetaAdsWriter

logger = logging.getLogger(__name__)

# --- Configuration ---

CAMPAIGN_NAME = "Pure Pets Bi-Active — Sales"
CAMPAIGN_BUDGET_CENTS = 5000  # $50 NZD/day
ADSET_NAME = "PP — Broad NZ"
DESTINATION_URL = (
    "https://deepbluehealth.co.nz/products/pure-pets-bi-active"
    "?utm_source=facebook&utm_medium=cpc&utm_campaign=pp-bi-active"
)

TARGETING = {
    "geo_locations": {
        "countries": ["NZ"],
        "location_types": ["home", "recent"],
    },
    "age_min": 25,
    "age_max": 65,
    "targeting_automation": {
        "advantage_audience": 1,
        "individual_setting": {
            "age": 1,
            "gender": 1,
            "geo": 0,
        },
    },
}

ATTRIBUTION_SPEC = [
    {"event_type": "CLICK_THROUGH", "window_days": 7},
    {"event_type": "VIEW_THROUGH", "window_days": 1},
    {"event_type": "ENGAGED_VIDEO_VIEW", "window_days": 1},
]

# --- Ad Definitions (12 ads, all captions pre-written) ---

ADS = [
    # ===== SOCIAL PROOF / TESTIMONIAL (6 ads) =====
    {
        "name": "PP — Holly Lab A (Mobility)",
        "category": "testimonial",
        "primary_text": (
            '"Our old lab is not struggling as much to get up from lying down. '
            'Seems to be walking with less pain." — Holly\n\n'
            "That moment when your dog can't get up like they used to. "
            "You pretend it's fine. But you know.\n\n"
            "Holly's lab started moving easier within weeks. No surgery. "
            "No harsh drugs. Just Pure Pets Bi-Active — NZ Green Lipped "
            "Mussel + Fish Oil working together."
        ),
        "headline": "Your dog shouldn't have to struggle",
        "description": "Improved mobility in 4-6 weeks",
    },
    {
        "name": "PP — Holly Lab B (5 Stars)",
        "category": "testimonial",
        "primary_text": (
            '"Our old lab is not struggling as much to get up from lying down. '
            'Seems to be walking with less pain." — Holly\n\n'
            "When thousands of pet parents report the same thing — less limping, "
            "easier mornings, more energy — it's not a coincidence.\n\n"
            "Pure Pets Bi-Active is rated 5 stars by NZ fur parents for a reason. "
            "NZ Green Lipped Mussel + Fish Oil. Natural. Effective. Made here."
        ),
        "headline": "5 stars from fur parents who've seen the difference",
        "description": "Rated 5 stars. NZ made.",
    },
    {
        "name": "PP — Holly Lab C (Success Story)",
        "category": "testimonial",
        "primary_text": (
            '"Our old lab is not struggling as much to get up from lying down. '
            'Seems to be walking with less pain." — Holly\n\n'
            "Holly's lab. Vicky's Rottweiler. Lyn's 12-year-old retiree. "
            "Thousands of dogs across NZ — all moving better with Pure Pets Bi-Active.\n\n"
            "Your dog's story doesn't have to be about slowing down. "
            "NZ Green Lipped Mussel + Fish Oil. The joint supplement NZ pet parents "
            "keep coming back to."
        ),
        "headline": "Be the next success story",
        "description": "NZ-made joint support that works",
    },
    {
        "name": "PP — Lyn Senior A (Mobility)",
        "category": "testimonial",
        "primary_text": (
            '"The true miracle was watching our 12-year-old retiree become like '
            'a puppy again." — Lyn M.\n\n'
            "Watching your dog age is the hardest part of being a pet parent. "
            "The slow mornings. The reluctance to play. The spark fading.\n\n"
            "Lyn thought her dog's best days were behind her. Pure Pets Bi-Active "
            "proved her wrong. NZ Green Lipped Mussel + Fish Oil — giving senior "
            "dogs their spark back."
        ),
        "headline": "Their best days aren't behind them",
        "description": "Improved mobility in 4-6 weeks",
    },
    {
        "name": "PP — Lyn Senior B (Puppy Again)",
        "category": "testimonial",
        "primary_text": (
            '"The true miracle was watching our 12-year-old retiree become like '
            'a puppy again." — Lyn M.\n\n'
            "12 years old. Slowing down. Stiffening up. Lyn expected that was "
            "just... it.\n\n"
            "Then Pure Pets Bi-Active. Within weeks — more energy. Easier movement. "
            "The dog she remembered was back.\n\n"
            "Age doesn't have to mean giving up. NZ Green Lipped Mussel + Fish Oil. "
            "Thousands of senior dogs already moving better."
        ),
        "headline": "Age is just a number",
        "description": "NZ-made. Natural. Proven results.",
    },
    {
        "name": "PP — Vicky Rottweiler",
        "category": "testimonial",
        "primary_text": (
            '"He was suffering with his hips and movement... he can now run, '
            'which he wasn\'t doing before." — Vicky M.\n\n'
            "Watching a big dog lose their mobility is heartbreaking. "
            "They want to play, to run, to be themselves — but their body "
            "won't let them.\n\n"
            "Vicky's Rottweiler got his movement back with Pure Pets Bi-Active. "
            "NZ Green Lipped Mussel + Fish Oil — nature's answer to stiff joints."
        ),
        "headline": "They can't ask for help. But you can give it.",
        "description": "Join thousands of happy NZ pet parents",
    },

    # ===== PROBLEM / SOLUTION (1 ad) =====
    {
        "name": "PP — Stiff Joints (Problem-Solution)",
        "category": "problem_solution",
        "primary_text": (
            "Every time they hesitate before jumping up. Every time they're "
            "slow getting to their feet. You know something's not right.\n\n"
            "Pure Pets Bi-Active combines NZ Green Lipped Mussel + Fish Oil "
            "for dual-action joint support — reducing inflammation while "
            "rebuilding cartilage.\n\n"
            "Thousands of NZ pet parents have already seen the difference. "
            "Your dog doesn't have to live with stiff joints."
        ),
        "headline": "Don't ignore the signs",
        "description": "NZ-made. Natural. Results in 4-6 weeks.",
    },

    # ===== EDUCATION / INGREDIENT (1 ad) =====
    {
        "name": "PP — Why Bi-Active (Education)",
        "category": "education",
        "primary_text": (
            "Not all joint supplements are created equal.\n\n"
            "Pure Pets Bi-Active combines two of nature's most researched "
            "joint ingredients:\n"
            "- NZ Green Lipped Mussel — unique omega-3s (ETA) not found in "
            "fish oil, clinically shown to reduce joint inflammation\n"
            "- Fish Oil — supports mobility and healthy coat\n\n"
            "Sourced from New Zealand's pristine waters. Lab-tested. No fillers.\n\n"
            "Your dog deserves more than generic glucosamine."
        ),
        "headline": "The science behind the results",
        "description": "GLM + Fish Oil dual-action formula",
    },

    # ===== SCIENCE / AUTHORITY (3 ads) =====
    {
        "name": "PP — Evolution Venn Diagram",
        "category": "science",
        "primary_text": (
            "Old joint supplements made you choose: natural OR clinically proven.\n\n"
            "Pure Pets Bi-Active is both.\n\n"
            "Powered by NZ Green Lipped Mussel — one of the most studied natural "
            "anti-inflammatories in veterinary science. 100% natural ingredients. "
            "Lab-tested potency.\n\n"
            "The evolution of pet joint care is here."
        ),
        "headline": "Why settle for one when you can have both?",
        "description": "Clinically proven + 100% natural",
    },
    {
        "name": "PP — Nature Meets Science (Bundle)",
        "category": "science_offer",
        "primary_text": (
            "100% natural. Lab-tested. Made in New Zealand.\n\n"
            "Pure Pets Bi-Active brings together what nature created and what "
            "science confirmed — NZ Green Lipped Mussel is one of the most "
            "powerful natural anti-inflammatories for joint health.\n\n"
            "Buy 5 and get 1 FREE. Stock up on the joint support your dog "
            "deserves — because consistency is what delivers real results.\n\n"
            "Free NZ shipping. No fillers. No compromises."
        ),
        "headline": "Where nature meets joint science",
        "description": "Buy 5 Get 1 FREE",
    },
    {
        "name": "PP — Trust Badges (20 Years)",
        "category": "authority",
        "primary_text": (
            "20 years of NZ health science. GMP certified. Export quality. "
            "Now for your pet.\n\n"
            "Deep Blue Health has spent two decades perfecting natural health "
            "supplements — trusted by thousands across New Zealand and exported "
            "worldwide. Pure Pets Bi-Active brings that same pharmaceutical-grade "
            "commitment to your dog's joint health.\n\n"
            "NZ-made. NZ-sourced Green Lipped Mussel. Lab-tested every batch.\n\n"
            "Premium joint care for the pets we love."
        ),
        "headline": "Trusted by NZ families for 20 years",
        "description": "NZ Made. GMP. Export Quality.",
    },

    # ===== OFFER / VALUE (1 ad) =====
    {
        "name": "PP — Bundle Tiers (Save Up To)",
        "category": "offer",
        "primary_text": (
            "The more you buy, the more you save — because joint health "
            "isn't a one-month thing.\n\n"
            "Buy 2 — Save 10%\n"
            "Buy 3 — Save 15%\n"
            "Buy 4 — Save 20%\n"
            "Buy 5 — Get 1 FREE\n\n"
            "Pure Pets Bi-Active works best with consistent daily use. "
            "Pet parents who commit to 3+ months see the biggest improvements "
            "in mobility, energy, and comfort.\n\n"
            "Stock up. Save more. Watch your dog thrive.\n\n"
            "Free NZ shipping on all orders."
        ),
        "headline": "Save up to 20% (or get 1 FREE)",
        "description": "Joint health is a long game",
    },
]


def build_campaign(dry_run: bool = False, existing_campaign_id: str = None) -> dict:
    """
    Build the full Pure Pets campaign structure.

    Returns dict of created IDs: {campaign_id, adset_id, ad_ids: [...]}
    """
    result = {"campaign_id": None, "adset_id": None, "ad_ids": []}

    # --- Preview mode (no credentials needed) ---
    if dry_run:
        print("=" * 60)
        print("DRY RUN — Pure Pets Campaign Structure Preview")
        print("=" * 60)
        print(f"\nCAMPAIGN: {CAMPAIGN_NAME}")
        print(f"  Objective: OUTCOME_SALES")
        print(f"  Budget: ${CAMPAIGN_BUDGET_CENTS / 100:.0f}/day (CBO)")
        print(f"  Status: PAUSED")
        print(f"\nAD SET: {ADSET_NAME}")
        print(f"  Targeting: NZ, age 25-65, all genders")
        print(f"  Optimization: Purchase (OFFSITE_CONVERSIONS)")
        print(f"  Audience: Advantage+ (EXPANSION_ALL)")
        print(f"  Attribution: 7d click, 1d view")
        print(f"\nADS ({len(ADS)} total):")
        print("-" * 60)
        for i, ad in enumerate(ADS, 1):
            print(f"\n  [{i}] {ad['name']}")
            print(f"      Category: {ad['category']}")
            print(f"      Headline: {ad['headline']}")
            print(f"      Description: {ad['description']}")
            # Show first 120 chars of primary text
            preview = ad["primary_text"][:120].replace("\n", " ")
            print(f"      Primary text: {preview}...")
        print(f"\n{'=' * 60}")
        print(f"Destination URL: {DESTINATION_URL}")
        print(f"CTA: SHOP_NOW")
        print(f"\nTo create for real: python {__file__}")
        return result

    # --- Validate credentials ---
    writer = MetaAdsWriter()
    page_id = os.environ.get("META_PAGE_ID")
    pixel_id = os.environ.get("META_PIXEL_ID")

    if not writer.available:
        print("ERROR: META_ACCESS_TOKEN and META_AD_ACCOUNT_ID required")
        sys.exit(1)

    if not page_id:
        print("ERROR: META_PAGE_ID required (Facebook Page ID for ads)")
        sys.exit(1)

    # --- Create or reuse campaign ---
    if existing_campaign_id:
        campaign_id = existing_campaign_id
        print(f"Using existing campaign: {campaign_id}")
    else:
        print(f"Creating campaign: {CAMPAIGN_NAME}...")
        campaign = writer.create_campaign(
            name=CAMPAIGN_NAME,
            objective="OUTCOME_SALES",
            daily_budget_cents=CAMPAIGN_BUDGET_CENTS,
            status="PAUSED",
            campaign_budget_optimization=True,
        )
        campaign_id = campaign.get("id")
        if not campaign_id:
            print(f"ERROR: Failed to create campaign: {campaign}")
            sys.exit(1)
        print(f"  Campaign created: {campaign_id}")
    result["campaign_id"] = campaign_id

    # --- Create ad set ---
    print(f"Creating ad set: {ADSET_NAME}...")
    promoted_object = {"pixel_id": pixel_id, "custom_event_type": "PURCHASE"} if pixel_id else None
    adset = writer.create_adset(
        name=ADSET_NAME,
        campaign_id=campaign_id,
        targeting=TARGETING,
        optimization_goal="OFFSITE_CONVERSIONS",
        billing_event="IMPRESSIONS",
        promoted_object=promoted_object,
        bid_strategy="LOWEST_COST_WITHOUT_CAP",
        status="PAUSED",
        attribution_spec=ATTRIBUTION_SPEC,
    )
    adset_id = adset.get("id")
    if not adset_id:
        print(f"ERROR: Failed to create ad set: {adset}")
        sys.exit(1)
    result["adset_id"] = adset_id
    print(f"  Ad set created: {adset_id}")

    # --- Create ads ---
    print(f"\nCreating {len(ADS)} ads...")
    for i, ad_def in enumerate(ADS, 1):
        # Create creative first
        creative = writer.create_ad_creative(
            name=ad_def["name"],
            page_id=page_id,
            message=ad_def["primary_text"],
            link=DESTINATION_URL,
            call_to_action_type="SHOP_NOW",
            link_caption=ad_def["headline"],
            description=ad_def["description"],
        )
        creative_id = creative.get("id")
        if not creative_id:
            print(f"  WARNING: Failed to create creative for '{ad_def['name']}': {creative}")
            continue

        # Create ad using the creative
        ad = writer.create_ad(
            name=ad_def["name"],
            adset_id=adset_id,
            creative_id=creative_id,
            status="PAUSED",
        )
        ad_id = ad.get("id")
        if ad_id:
            result["ad_ids"].append({"id": ad_id, "name": ad_def["name"], "creative_id": creative_id})
            print(f"  [{i}/{len(ADS)}] {ad_def['name']} — ad:{ad_id} creative:{creative_id}")
        else:
            print(f"  [{i}/{len(ADS)}] WARNING: Failed to create ad '{ad_def['name']}': {ad}")

    # --- Save IDs ---
    data_dir = Path(__file__).resolve().parent.parent / "data"
    data_dir.mkdir(exist_ok=True)
    ids_file = data_dir / "pure_pets_campaign_ids.json"
    ids_file.write_text(json.dumps(result, indent=2))
    print(f"\nIDs saved to: {ids_file}")

    # --- Summary ---
    print(f"\n{'=' * 60}")
    print(f"PURE PETS CAMPAIGN CREATED (ALL PAUSED)")
    print(f"{'=' * 60}")
    print(f"Campaign: {campaign_id}")
    print(f"Ad Set:   {adset_id}")
    print(f"Ads:      {len(result['ad_ids'])}/{len(ADS)} created")
    print(f"\nNext steps:")
    print(f"  1. Upload creative images to each ad in Meta Ads Manager")
    print(f"  2. Review captions on each ad")
    print(f"  3. Activate campaign when ready")

    return result


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    dry_run = "--dry-run" in sys.argv
    # Allow passing existing campaign ID to resume after partial failure
    existing_id = None
    for arg in sys.argv[1:]:
        if arg.startswith("--campaign-id="):
            existing_id = arg.split("=", 1)[1]

    result = build_campaign(dry_run=dry_run, existing_campaign_id=existing_id)
