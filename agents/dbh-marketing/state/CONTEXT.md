# CONTEXT.md — Meridian State
## Last Updated: March 2, 2026

## SYSTEM STATUS
All integrations LIVE. Shopify, Klaviyo, Meta Ads data is injected into your
prompt automatically by the orchestrator. USE THE DATA BELOW YOUR TASK PROMPT.
Do NOT say "data unavailable" — if data is injected, use it. If a section shows
an error message in brackets like [Klaviyo error: ...], report that specific error.

## VERIFIED REVENUE BASELINE (Shopify, confirmed)
- Dec 2025: $34,673 (216 orders, $160 AOV)
- Jan 2026: $46,814 (295 orders, $159 AOV)
- Feb 2026: $39,183 (269 orders, $146 AOV)
- 3-month average: ~$40,223/month
- Target: $85K/month by June 2026 (requires 2x+ growth)

## TOP PRODUCTS (90-day revenue, verified)
1. Sea Cucumber: $22,715 (234 units) — CLEAR #1 by 3x
2. Oyster: $8,403 (170 units)
3. Deer Velvet Twin Pack: $8,089 (63 units)
4. GLM Twin Pack: $7,584 (106 units)
5. Bee Venom: $3,945 (66 units)
6. 100% Colostrum: $3,341 (65 units)
7. Black Maca: $3,072 (76 units)
8. Pure Pets Bi-Active: $2,437 (44 units)
9. Pure Pets GLM: $2,267 (76 units)

## CHANNEL ATTRIBUTION (Shopify referrer data)
- Direct/Other: ~43% (likely includes untracked Meta/email clicks)
- Google: ~41% (biggest tracked channel — SEO/AEO is critical)
- Email/Klaviyo: ~7% overall, but growing (Feb was 14%)
- Meta/Facebook: ~5%
- Draft Orders: ~2%

## KEY INSIGHT: Google drives more revenue than email and Meta combined.
The SEO/AEO play is the highest-leverage growth channel.

## PROVEN FORMULAS REFERENCE
1. TRUST + SOCIAL PROOF = 7.78x ROAS (Meta), 48.53% open rate (Email)
2. EXCLUSIVITY + SCARCITY = 8.45x ROAS (Meta), $9,259 revenue (Email)
3. GIFT PSYCHOLOGY = 77.1% open rate, 4.15% click rate (Email)

## BENCHMARKS (from playbooks)
- Email open rate target: >35%
- Email click rate target: >2.5%
- Meta ROAS target: >4x
- Revenue/email target: >$500

## INTEGRATION NOTES
- Klaviyo: API key may need campaigns:read scope for metrics. If metrics fail,
  the brief should still show campaign names and note "metrics unavailable — API scope needed".
- Meta: May need ads_read permission on token. If data fails, note the specific error.
- Xero: Needs re-auth (tokens expired). Flag as "Xero not connected yet".

## ACTIVE CAMPAIGNS

### Marine Collagen — Test & Learn — March 2026
**Status**: LIVE (activated March 24, 2026)
**Budget**: $20/day total ($5/day per ad set)
**Target**: NZ women 35-55, Advantage+ placements, optimizing for Purchase
**Pixel**: Deep Blue Health Pixel v2
**Campaign ID**: 120242640198760245
**Product URL**: https://www.deepbluehealth.co.nz/products/marine-collagen

**Ad Sets Running (4 of 4)**:
- H1 — Trust + Social Proof: Testimonial creative (Sally J. nurse review), social proof copy
- H2a — Joint Health Angle: Educational creative ("Not all collagen is the same"), joint/absorption copy
- H2b — Skin Health Angle: Seasonal creative ("Before the cold air hits"), skin hydration copy
- H4 — Offer / Value Stack: What's Inside creative (ingredients), bundle pricing + MARINECOLLAGEN code (single bottles only)

**Deleted**: H3 (UGC Video) and H5 (Broad) — empty, will recreate when content/winner available

**Hypotheses Being Tested**:
- H1: Social proof/testimonials outperform education for cold supplement audiences
- H2a vs H2b: Joint health buyers (pain-motivated) vs skin buyers (vanity-motivated) — which segment is more valuable?
- H2b: Seasonal urgency creative outperforms evergreen messaging
- H4: Ingredients transparency + offers attract higher-AOV bundle buyers vs discount-seekers
- Cross-cutting: Which ANGLE (trust/joint/skin/offer) becomes default creative direction for all DBH products?

**Decision Framework (after $50 spend per ad set)**:
- ROAS > 3x: Scale to $15/day, clone winner into Broad ad set
- ROAS 2-3x: Hold, let run another $50
- ROAS < 2x: Kill immediately, reallocate to winners
- Track AOV per ad set: H4 bundle rate is key signal

**What Carries Forward**:
- Winning angle -> default creative direction for Sea Cucumber, GLM, all products
- Seasonal vs evergreen -> creative calendar planning
- Testimonial vs education -> content strategy with Roie
- Bundle vs single rate by ad set -> pricing page optimisation

### Discount Code Active
- MARINECOLLAGEN = 10% off single bottles only (NOT stackable with bundle pricing)

## RECENT LEARNINGS
- Email attribution growing month-over-month (4% Dec → 14% Feb)
- Sea Cucumber is the hero product, not GLM as historically assumed
- Colostrum selling at $3.3K without campaign push — opportunity for dedicated campaign
- Meta app now in LIVE mode — can create ad creatives via API (fixed March 24, 2026)
- Proven formula reference: Trust + Social Proof = 7.78x ROAS historically
