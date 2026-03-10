# google-ads-mastery.md -- Elite Google Ads Management
# Deep Blue Health (NZ/AU DTC Supplement Brand)

**Last updated:** March 10, 2026
**Author:** Research-compiled from top-tier PPC practitioners and Google's own documentation
**Purpose:** Definitive operating manual for Google Ads management. Specific thresholds, decision trees, rules. Nothing generic.

---

## TABLE OF CONTENTS

1. Philosophy and Mental Model
2. Account Architecture
3. Campaign Types and When To Use Each
4. Performance Max Playbook
5. Search Campaign Playbook
6. Shopping and Feed Optimisation
7. Bid Strategy Framework
8. Conversion Tracking and LTV Setup
9. Audience and First-Party Data
10. NZ/AU Market Specifics
11. Autonomous Management Rules
12. Weekly Optimisation Checklist
13. Monthly Strategic Review
14. DBH-Specific Campaign Plan (Sea Cucumber, Marine Collagen, Pure Pets)
15. KPIs and Reporting Framework
16. Common Mistakes To Avoid (with Josh-level errors documented)

---

## 1. PHILOSOPHY AND MENTAL MODEL

### The Foundational Principle: Bidding on Profit, Not Revenue

The single biggest mistake in Google Ads is setting ROAS targets based on revenue. Every ROAS target must be anchored to gross margin, not top-line sales.

The formula:
- Breakeven ROAS = 1 / Gross Margin %
- If gross margin is 50% (e.g., sell for $80, cost is $40), breakeven ROAS = 2.0x
- A target ROAS of 2.5x means you make 25% profit on every ad dollar (above COGS)
- A target ROAS of 4.71x (what Meta claims) means nothing if your margin is 30% -- you're still barely profitable

For DBH: Calculate gross margin per SKU (including fulfilment, payment processing, packaging). Set ROAS targets per SKU group accordingly. Sea Cucumber, Marine Collagen, and Pure Pets likely have different margins and therefore need different ROAS targets.

POAS (Profit on Ad Spend) is the north star metric, not ROAS. POAS = Gross Profit from ads / Ad Spend. A POAS of 1.0 means you cover your costs. Target 1.3-2.0x POAS depending on growth mode.

### Google Ads Mental Model: A Signals-Feeding System

Google's AI does the bidding. Your job is to feed it accurate signals. The better your signals, the better it optimises.

Signals to feed Google:
- Accurate conversion values (ideally profit-weighted, not just revenue)
- Conversion value rules that reflect real customer value (first-time buyer vs repeat)
- Customer Match lists that define what "good customer" looks like
- Asset groups and search themes that tell Google who to target
- Negative keywords that tell Google what to ignore

Most accounts fail not because of budget, but because of signal corruption. Sending wrong conversion values, missing conversion events, or having broken attribution means the AI optimises for the wrong thing.

### The Control Paradox

Google wants you to give it more control. Sometimes you should, sometimes you should not.

Give Google more control when:
- You have 50+ conversions in the last 30 days per campaign
- Conversion tracking is verified and accurate
- You have first-party data (customer lists) loaded
- You are in a growth phase and want Google to find new audiences

Retain manual control when:
- You have fewer than 30 conversions per month (the AI is guessing)
- Your conversion tracking is suspected to be inaccurate
- You are in a cost-control phase
- Google's recommendations would break profitable campaign structure

Never: let Google auto-apply recommendations without review. Auto-apply is how budgets get doubled, keywords get broadened into irrelevance, and accounts get degraded.

### The Attribution Reality

Google Ads uses data-driven attribution by default. This means it distributes credit across multiple touchpoints. This is both useful (more nuanced than last-click) and dangerous (it will attribute credit to assists that Meta or organic drove).

For DBH: Google claims credit for sales that Meta or Klaviyo actually drove. Your real Google ROAS is likely 15-30% lower than reported in Google Ads. Always cross-reference with:
- Shopify attributed revenue (last-click, most conservative)
- A simple incrementality test: pause all Google Ads for 2 weeks, measure revenue change

---

## 2. ACCOUNT ARCHITECTURE

### The Four-Layer Structure

Layer 1: Account Level
- Account-level negative keywords (words that should never trigger any ad, ever)
- Audience Manager (Customer Match lists, remarketing lists)
- Conversion actions
- Linked: Google Analytics 4, Google Merchant Center, Search Console

Layer 2: Campaign Level
- Budget allocation
- Bid strategy
- Geographic targeting
- Campaign-level brand exclusions (for PMax)
- Campaign-level negative keywords (now available for PMax, limit 10,000)

Layer 3: Ad Group / Asset Group Level
- Keyword themes (Search)
- Asset groupings by product/theme/audience (PMax)
- Audience signals (PMax)

Layer 4: Ad / Asset Level
- Headlines, descriptions, images, videos
- Extensions (now called "Assets"): sitelinks, callouts, structured snippets, price, promotion, image

### Recommended Campaign Structure for DBH

Tier 1: Brand Defence
- Campaign type: Search
- Bid strategy: Target Impression Share (90%+ IS, top of page)
- Budget: Small but non-negotiable. Protect your brand name.
- Keywords: "deep blue health", "DBH collagen", "DBH sea cucumber" exact match
- Purpose: Own your brand name. CPCs here should be low ($0.30-$0.80 NZD)

Tier 2: Core Non-Brand Search (High Intent)
- Campaign type: Search
- Bid strategy: Target ROAS (set at breakeven + 20% for discovery phase)
- Keyword strategy: Exact + Phrase for core terms, Broad Match for expansion
- Examples: "marine collagen supplement NZ", "sea cucumber joint health", "joint pain supplement NZ"

Tier 3: Shopping / Feed (Product Intent)
- Campaign type: Standard Shopping (primary) + PMax Feed-Only (secondary)
- Standard Shopping: Higher ROAS target, higher priority = wins more auctions
- PMax Feed-Only: Lower ROAS target, used for discovery and incremental reach

Tier 4: Prospecting / Upper Funnel (Awareness and Discovery)
- Campaign type: Performance Max (full asset groups, not just feed)
- Bid strategy: Maximize Conversion Value (no ROAS target initially, add after 30 days)
- Purpose: Find new audiences across YouTube, Display, Discover, Gmail

Tier 5: Remarketing (Warm Audiences)
- Primarily handled by PMax automatically via first-party audience signals
- Supplement with RLSA modifiers on Search campaigns (bid +30-50% for cart abandoners)

### Budget Allocation Template (Total Monthly Budget = 100%)

Brand Defence: 10%
Core Non-Brand Search: 35%
Standard Shopping: 25%
PMax Prospecting: 20%
YouTube/Discovery (if running): 10%

Adjust as campaigns mature. When non-brand search is profitable at scale, increase its allocation. When PMax is driving discovery efficiently, increase its allocation. Brand should never drop below 10% of budget.

---

## 3. CAMPAIGN TYPES AND WHEN TO USE EACH

### Search Campaigns

Use when:
- Targeting high-intent, bottom-of-funnel keywords ("buy marine collagen NZ")
- You need control over messaging (supplement claims must be compliant)
- Building a keyword list from scratch (see search term data before going broad)
- Budget is limited and you need guaranteed intent

Do not use for:
- Brand awareness or audience discovery at scale
- When you have fewer than 30 conversions/month per campaign (bidding is blind)

### Standard Shopping Campaigns

Use when:
- You have a product feed and want to appear in Google Shopping results
- You want granular control over which products show and at what bids
- PMax is stealing too much budget from profitable search terms
- You want to see individual product-level ROAS clearly

Structure tip: Use product groups and custom labels to segment by margin, bestseller status, and seasonality. Bid higher on high-margin products.

### Performance Max Campaigns

Use when:
- You have 50+ conversions/month and accurate conversion tracking
- You want to reach across Search, Shopping, YouTube, Display, Discover, Gmail simultaneously
- You have creative assets (images, videos) and audience signals to feed Google's AI
- Scaling beyond what Search alone can reach

Do not use PMax as your only campaign. The "black box" problem means you cannot see where spend is going. Always run Standard Shopping alongside PMax.

PMax variants:
- Feed-Only PMax: Only uses your Merchant Center product feed. No creative assets uploaded. Behaves like a smarter Shopping campaign. Best for ecommerce with limited creative assets.
- Full PMax: Uses feed + creative assets (images, videos, headlines, descriptions). Reaches all Google inventory. Most powerful but requires strong creative.

### Performance Max vs Standard Shopping Decision Tree

Question 1: Do you have verified conversion tracking with 50+ monthly conversions?
- No: Use Standard Shopping only. PMax needs data.
- Yes: Continue.

Question 2: Do you have creative assets (images, videos)?
- No: Use Feed-Only PMax + Standard Shopping.
- Yes: Use Full PMax + Standard Shopping.

Question 3: Is your Standard Shopping ROAS acceptable?
- No (below target): Diagnose feed quality first, not campaign type.
- Yes: Add PMax at lower priority for incremental reach.

### YouTube / Video Campaigns

Use when:
- You have video creative (UGC or produced) that explains your product
- You want to build brand awareness in the NZ/AU market
- Remarketing to website visitors who did not purchase (video retargeting converts)
- Budget exceeds $5,000 NZD/month (YouTube needs critical mass to work)

Video ad formats:
- In-stream skippable (most flexible, pay only when watched 30+ seconds)
- Discovery/In-feed video (appears in YouTube search, pay per click)
- Shorts ads (cheap CPMs, growing inventory)

---

## 4. PERFORMANCE MAX PLAYBOOK

### The Core PMax Principle

PMax is a goal-based campaign type. You give it a goal (conversions, conversion value), assets (creative), and signals (audiences, search themes). Google's AI does the rest. Your job is to make those inputs as high-quality as possible.

### Asset Group Strategy

Rule: One asset group per distinct product category or audience theme. Do not mix Sea Cucumber and Pure Pets in the same asset group.

DBH asset group structure:
- Asset Group 1: Sea Cucumber (joint health, mobility, anti-inflammatory)
- Asset Group 2: Marine Collagen (skin health, collagen supplements, anti-aging)
- Asset Group 3: Pure Pets (pet joint health, pet supplements)
- Asset Group 4: Bundle / Value Offers (subscription, multi-buy)
- Asset Group 5: Remarketing / Warm Audiences (assets that assume product familiarity)

Each asset group requires:
- 15 headlines (distinct, not repetitive, each from a different angle)
- 4 descriptions (benefit-led, not feature-led)
- Minimum 3 landscape images (1200x628)
- Minimum 3 square images (1200x1200)
- Minimum 1 portrait image (960x1200) -- for YouTube Shorts/Stories
- Minimum 1 video (15-30 seconds preferred). Without video, Google generates one automatically and it will be poor.
- Logo
- Business name

### Headline Writing for PMax Asset Groups

Write for conversion, not for Ad Strength score. Ad Strength is a diagnostic tool, not a performance predictor.

Headline variety (each group should cover):
- Product name + primary benefit (Sea Cucumber -- Joint Pain Relief)
- Outcome-based (Move Freely Again -- Without Drugs)
- Social proof (3,500+ NZ Customers)
- Specific claim (Reduce Joint Inflammation in 30 Days)
- Urgency/offer (Free Shipping on Orders Over $80)
- Question (Struggling with Stiff Joints?)
- Differentiator (100% New Zealand Marine Sourced)
- Trust signal (TGA Compliant -- New Zealand Made)
- Subscription angle (Subscribe and Save 15%)
- Risk reversal (30-Day Money Back Guarantee)

### Search Themes (Critical for PMax Control)

Search themes = keywords you tell PMax to prioritise. Up to 50 per asset group. They are suggestions, not restrictions. But they meaningfully steer the AI.

For Sea Cucumber asset group:
- sea cucumber supplement
- joint pain supplement NZ
- marine joint health supplement
- anti-inflammatory supplement NZ
- sea cucumber capsules
- natural joint pain relief
- joint support supplement
- glucosamine alternative
- sea cucumber extract benefits
- joint inflammation supplement NZ
- mobility supplement
- arthritis natural supplement

For Marine Collagen asset group:
- marine collagen NZ
- collagen supplement New Zealand
- hydrolysed collagen NZ
- fish collagen supplement
- collagen for skin NZ
- marine collagen capsules
- skin supplement NZ
- collagen powder NZ
- anti-aging supplement NZ
- collagen peptides NZ

For Pure Pets:
- pet joint supplement NZ
- dog joint pain supplement
- pet health supplement NZ
- dog mobility supplement
- natural pet supplement NZ

### Audience Signals (Feed Google What It Needs)

Audience signals are not restrictions. They tell the AI where to start. Google will expand beyond them if it finds conversions elsewhere.

Priority order for signals:

Priority 1 (strongest): Your own first-party data
- Customer Match list: All past purchasers (upload email list from Klaviyo)
- Customer Match list: High-value customers (3+ purchases or LTV > $300 NZD)
- Website visitors (past 180 days)
- Cart abandoners (past 30 days)

Priority 2: Google audiences
- In-market: Health & Fitness Supplements
- In-market: Natural & Alternative Remedies
- In-market: Vitamins & Supplements
- Affinity: Health & Fitness Enthusiasts
- Life event: Recently moved (often start health kick)

Priority 3: Demographic signals
- Age: 35-65 (Sea Cucumber, Marine Collagen skew older)
- Age: 25-45 (Pure Pets skews younger -- pet owners)
- Gender: Slight female skew for Marine Collagen
- Household income: Top 30% (supplement buyers have disposable income)

### Brand Exclusions

Always apply brand exclusions to PMax to prevent it cannibalising your Brand Search campaign.

Apply exclusion for:
- "Deep Blue Health"
- "DBH"
- "deepbluehealth.co.nz"

Note (2025 update): For retail advertisers with product feeds, brand exclusions can now be applied to Search text ads only, while keeping branded Shopping traffic. This is the preferred setting for DBH -- exclude brand from PMax text ads but allow Shopping.

### Negative Keywords for PMax (Critical 2025 Update)

PMax now supports up to 10,000 negative keywords (increased from 100 in March 2025). This is a game-changer. Use it.

Core negative keyword categories for DBH supplements:

Category 1: Free / DIY Intent
- free sea cucumber
- free collagen
- diy collagen
- homemade collagen
- recipe [+any supplement term]
- how to make collagen at home

Category 2: Research / Informational (not buying)
- what is sea cucumber
- sea cucumber biology
- what is collagen
- collagen function
- collagen biology
- sea cucumber habitat
- sea cucumber food recipe [for eating, not supplement]

Category 3: Competitor Brand Exclusions
- [add competitor brand names here]
- [add competitor product names here]

Category 4: Irrelevant Products
- collagen shampoo [unless you sell it]
- collagen face cream [unless relevant]
- collagen injection
- collagen filler
- collagen drink recipe [DIY intent]

Category 5: Job Seekers
- collagen job
- supplement job
- nutrition job
- health supplement careers

Category 6: Wholesale / Trade Intent
- collagen wholesale
- supplement wholesale
- bulk collagen
- supplement manufacturer
- private label supplement

Category 7: Clinical / Prescription Framing
- collagen prescription
- prescription supplement
- medical collagen
- TGA approved prescription [distinction: TGA listed vs TGA approved]

### PMax Learning Period Management

PMax requires at minimum 6 weeks before meaningful optimisation decisions. Rules:

Week 1-2: Do not touch the campaign. Let it gather data.
Week 3-4: Check asset performance labels (Best, Good, Low). Remove "Low" assets. Do not change bid strategy.
Week 5-6: Review audience signal performance. Add converting audience segments.
Week 7+: Begin bid strategy optimisation. Add ROAS target if conversion data is sufficient (50+ conversions).

Anything that resets the learning period:
- Changing bid strategy
- Changing target ROAS by more than 20%
- Changing the campaign budget by more than 30% at once
- Significantly changing asset groups
- Changing geographic targets

Budget change rule: Increase or decrease by maximum 20% every 7 days. Never make step changes.

### What PMax Reporting to Actually Look At

The channel performance breakdown (2025 update) shows: Search, Shopping, Display, YouTube, Discover, Gmail. Use it to understand spend distribution.

Warning signs:
- If Display is consuming 60%+ of budget with low conversion rate: add audience exclusions
- If YouTube is spending heavily but driving zero conversions: you may need better video creative
- If Search is only 20% of budget: check search themes and add more bottom-funnel terms

Asset group performance labels:
- "Best": Keep these, use as templates for new asset creation
- "Good": Keep these
- "Low": Remove after 4 weeks if no improvement. Replace with new variant.

---

## 5. SEARCH CAMPAIGN PLAYBOOK

### Match Type Strategy in 2025/2026

The "barbell" approach is now standard:

Left side of barbell: Exact Match for brand-critical and bottom-funnel terms
- "sea cucumber supplement NZ" [exact]
- "marine collagen NZ" [exact]
- "buy collagen supplement NZ" [exact]
- These trigger when someone has purchase intent and knows what they want

Right side of barbell: Broad Match + Smart Bidding for discovery and scale
- sea cucumber supplement [broad]
- marine collagen [broad]
- joint pain supplement [broad]
- These find adjacent search terms Google believes are relevant

What died in 2025/2026: Phrase Match as a primary strategy. It still exists but is now the old "Exact Match" in terms of specificity. Use it as a middle layer sparingly.

Broad Match rules:
- Never run Broad Match without Smart Bidding (tROAS or Maximize Conversion Value)
- Broad Match needs minimum 30 conversions in the last 30 days in the campaign before enabling
- Below 30 conversions: Exact Match only. The AI has nothing to learn from.
- Above 50 conversions: Broad Match + Smart Bidding becomes powerful (+13% more conversions per Google data)
- Review search term report every 7 days. Add negatives aggressively.

### Campaign Structure: Consolidation vs Separation

The consolidation debate resolved: Consolidate only when you have enough conversion data to teach Google's AI. Separation is valid when you have distinct margin profiles, distinct audience strategies, or distinct messaging needs.

DBH Search Campaign Structure:

Campaign A: Non-Brand High Intent
- Ad Group 1: Sea Cucumber -- Direct Purchase (best exact match terms)
- Ad Group 2: Sea Cucumber -- Symptom-Led (joint pain, inflammation, mobility)
- Ad Group 3: Marine Collagen -- Direct Purchase
- Ad Group 4: Marine Collagen -- Beauty/Skin Outcome
- Ad Group 5: Pure Pets -- Direct Purchase
- Bid Strategy: tROAS set at breakeven + 25% initially

Campaign B: Non-Brand Education/Research
- Ad Group 1: Sea Cucumber -- What Is It / Does It Work
- Ad Group 2: Collagen -- How to Choose / Best Collagen
- Ad Group 3: Natural Alternatives (e.g., "glucosamine alternative NZ")
- Bid Strategy: Maximize Conversions with target CPA (set at 2x acceptable CPA initially)
- Note: Education searchers convert at lower rate but can be nurtured via remarketing

Campaign C: Competitor Keyword (Optional, Careful)
- Target competitor brand names + "alternative" or "vs" queries
- e.g., "BioBalance alternative NZ", "joint supplement vs [competitor]"
- Careful: Google policy allows this, but do not use competitor brand in ad copy
- Bid Strategy: Manual CPC or Max CPC cap to control costs

### RSA (Responsive Search Ad) Best Practices

You get one RSA per ad group. Make it count.

Headline slots: 15 available, all should be used
- Headlines 1-3: Brand/product identity + primary benefit
- Headlines 4-6: Key features (NZ sourced, marine, high potency)
- Headlines 7-9: Outcome statements (feel the difference in 30 days)
- Headlines 10-12: Social proof and trust (3500+ customers, 30-day guarantee)
- Headlines 13-15: Offer/urgency (free shipping, subscribe and save, limited stock)

Description slots: 4 available, use all 4
- Description 1: Core value proposition in 1-2 sentences (benefit-led)
- Description 2: Social proof + risk reversal
- Description 3: Offer details + call to action
- Description 4: Differentiator (NZ-made, TGA compliant, marine sourced)

Pinning strategy: Only pin what legally or strategically must appear in position 1. Pinning one headline to position 1 reduces combinations by 75%. Instead: pin 2-3 compliant headlines to position 1 so Google rotates between compliant options.

TGA compliance pinning: If you must include a compliance disclaimer (e.g., "Always read the label") pin this to a description, not headline position.

Ad Strength warning: Ad Strength score does not affect Ad Rank (confirmed by Google's Ginny Marvin, April 2024). A "Poor" strength ad can outperform an "Excellent" strength ad. Optimise for conversion rate, not Ad Strength. Use Ad Strength as a diagnostic only.

### Keyword Research for DBH Supplements

Intent layering framework:

Transactional (highest commercial value):
- buy + [product] + NZ/Australia
- [product] + online NZ
- [product] + free shipping NZ
- best [product] NZ
- [product] + price NZ

Commercial Investigation (mid-funnel):
- best [product type] supplement NZ
- [product] + review NZ
- [product] vs [competitor]
- [product] + does it work
- [symptom] + supplement NZ

Informational (upper funnel, cheaper CPC, lower conversion rate):
- what is sea cucumber good for
- marine collagen benefits
- sea cucumber joint health
- natural joint pain remedies NZ
- best supplement for joint pain

Symptom-Based (high intent, often underutilised):
- joint pain supplement
- reduce inflammation naturally NZ
- stiff joints supplement
- mobility supplement for over 50s
- natural arthritis supplement NZ
- skin collagen supplement

### Extensions / Assets (Non-Negotiable)

Every Search campaign must have:

Sitelinks (4-6): Link to specific product pages, review page, FAQ, subscription offer
- "Sea Cucumber Capsules" -> product page
- "Marine Collagen" -> product page
- "Customer Reviews" -> reviews page
- "Subscribe and Save 15%" -> subscription page
- "Free Shipping on $80+" -> collections page
- "About Deep Blue Health" -> about page

Callouts (8-10): Short benefit phrases (no links)
- NZ-Owned Brand
- Marine Sourced Ingredients
- 30-Day Money Back Guarantee
- TGA Listed
- Free Shipping on $80+
- Over 3500 Customers
- Subscribe and Save 15%
- No Artificial Fillers

Structured Snippets: Use "Types" or "Services" header
- Types: Sea Cucumber, Marine Collagen, Pure Pets, Joint Health, Skin Health

Price extensions: If running promotions, add price assets showing product price
- Sea Cucumber 60-cap | From $X.XX | [URL]

Promotion extensions: For sales events (Black Friday, mid-year, etc.)
- Add start and end dates. Remove immediately after promotion ends.

Image assets: Upload lifestyle and product images (shown on mobile Search)

---

## 6. SHOPPING AND FEED OPTIMISATION

### Merchant Center Setup (Critical Foundation)

Merchant Center must be:
- Verified and claimed for deepbluehealth.co.nz (and au domain if running AU)
- Products approved (supplement category can trigger policy reviews -- see Section 10)
- Feed submitted without errors (check Diagnostics tab weekly)
- Linked to Google Ads account
- Enhanced conversions configured (pass cart data for margin optimisation)

### Product Title Optimisation

Title is the single most important feed attribute. Google matches search queries against titles.

Title formula for supplements:
[Brand Name] + [Product Type] + [Key Benefit/Ingredient] + [Format] + [Quantity/Size]

Examples:
- "Deep Blue Health Sea Cucumber Joint Health Supplement Capsules 60 Pack"
- "Deep Blue Health Marine Collagen Skin Supplement Capsules 90 Pack"
- "Pure Pets Sea Cucumber Joint Supplement for Dogs Capsules 60 Pack"

Front-load the most important search terms. Google truncates titles in display, so the first 60-70 characters must contain your primary keywords.

Common title mistakes:
- Starting with brand name when brand is not searched (waste valuable character real estate)
- Using marketing language ("Amazing", "Ultimate") instead of searchable terms
- Missing quantity/format (capsules vs powder vs liquid matters to searchers)
- Not including the symptom angle ("Joint Health" is searchable; "Wellness" is vague)

### Custom Labels (Use All 5)

Custom labels allow segmentation in campaigns for bidding. Use them:

Custom Label 0 -- Margin Category
- high_margin (50%+ gross margin)
- mid_margin (35-49% gross margin)
- low_margin (below 35% gross margin)
Purpose: Bid higher on high-margin products via campaign subdivision

Custom Label 1 -- Performance Tier
- bestseller (top 20% by revenue)
- good_performer (top 20-60%)
- slow_mover (bottom 40%)
Purpose: Allocate more budget to proven sellers, suppress slow movers

Custom Label 2 -- Inventory Status
- in_stock_high (30+ days inventory)
- in_stock_low (under 30 days inventory)
- backorder
Purpose: Pause or reduce bids when stock is critically low

Custom Label 3 -- Seasonality
- year_round
- winter_push (joint pain worsens in cold weather -- lean in Q2/Q3 NZ)
- summer_skin (collagen / skin supplements peak in NZ summer Q4/Q1)

Custom Label 4 -- Campaign Strategy
- pmax_priority
- shopping_priority
- exclude_pmax (if a product performs better in Standard Shopping only)

### Feed Quality Maintenance

Run Merchant Center Diagnostics weekly. Zero errors, zero warnings is the goal.

Critical attributes to get right:
- gtin (barcode): Include if your products have a barcode. Required for branded products.
- mpn (manufacturer part number): Include if no GTIN
- condition: "new" for all supplements
- availability: Keep real-time accurate. Disapproved products from incorrect availability waste opportunities.
- price: Must match landing page price exactly. Discrepancies cause disapproval.
- description: 500-1000 characters. Include key ingredients and benefits. Readable prose, not keyword stuffing.
- google_product_category: Use the most specific available (e.g., 5765 = Nutritional Supplements under Health & Beauty)

Supplementary feed: Create a second feed with enhanced title variants (A/B test different title structures) to test if reordering keywords improves impression share.

### Standard Shopping Campaign Structure

Campaign structure for DBH:

Shopping Campaign: Sea Cucumber
- Product Group: All products (sea cucumber category)
- Bid Strategy: Target ROAS = [margin-appropriate target]
- Priority: HIGH
- Budget: Dedicated

Shopping Campaign: Marine Collagen
- Product Group: All products (marine collagen category)
- Bid Strategy: Target ROAS = [margin-appropriate target]
- Priority: HIGH
- Budget: Dedicated

Shopping Campaign: Pure Pets
- Product Group: All products (pets category)
- Bid Strategy: Target ROAS
- Priority: HIGH
- Budget: Dedicated

PMax Feed-Only Campaign (Catch-All):
- All products
- Bid Strategy: Maximize Conversion Value (lower ROAS target than Standard Shopping)
- Priority: LOW
- Purpose: Incremental reach for products not captured by Standard Shopping

The priority/ROAS relationship: Standard Shopping at HIGH priority with higher ROAS target wins auctions it's entered. PMax at LOW priority with lower ROAS target sees only auctions Standard Shopping doesn't win or doesn't find profitable. This prevents PMax from cannibalising profitable shopping traffic.

---

## 7. BID STRATEGY FRAMEWORK

### The Hierarchy: Which Strategy for Which Situation

New campaign (0-30 conversions/month): Maximize Clicks with Max CPC cap, or Manual CPC. Do not use Smart Bidding. There is no data for the AI to learn from.

Growing campaign (30-50 conversions/month): Maximize Conversions (no target initially). Let Google spend to conversion without a ROAS target. You are buying data.

Established campaign (50+ conversions/month): Target ROAS or Maximize Conversion Value with target ROAS. Now the AI has enough signal to optimise efficiently.

Scaling campaign (100+ conversions/month): Increase budget and ROAS target simultaneously. Do not increase budget without sufficient conversion data.

Brand Search campaign: Target Impression Share (90%+ on "top of page"). This is an impression share strategy, not a conversion strategy. Your brand terms are cheap -- dominate them.

### Target ROAS Setting Methodology

Step 1: Calculate your breakeven ROAS
- Gross margin on product = 50%
- Breakeven ROAS = 1 / 0.50 = 2.0x (200%)

Step 2: Determine your minimum profitable ROAS
- Target 25% profit above COGS from ads
- Profitable ROAS = 1 / (margin * 0.75) [to account for a 25% profit cushion above breakeven]
- At 50% margin: Profitable minimum ROAS = 1/(0.50 * 0.75) = 2.67x (267%)

Step 3: Set initial target ROAS
- Set at your profitable minimum (e.g., 2.7x)
- If campaign is in learning or volume is low, set 20% lower to allow the algorithm to gather data
- Increase ROAS target by 0.1-0.2x increments every 2 weeks as you optimise

Step 4: Adjust by SKU margin
- High margin SKU (60%+): Can set aggressive ROAS targets (3.0-5.0x)
- Mid margin SKU (40-50%): Moderate ROAS targets (2.5-3.5x)
- Low margin SKU (30-40%): Conservative ROAS targets (2.0-2.5x)

### Learning Period Rules

Never touch these things during a learning period (7-14 days after major changes):
- Bid strategy
- Target ROAS / CPA
- Budget (more than 20% change)
- Geographic targeting
- Major asset changes (removing best performers)

Learning period triggers (things that restart it):
- Switching from Maximize Conversions to Target ROAS
- Changing target ROAS by more than 20%
- Changing budget by more than 30%
- Pausing and unpausing the campaign

### Seasonality Adjustments

Use for planned events only (1-7 day windows). Best use cases:
- Black Friday / Cyber Monday: Set conversion rate adjustment +50-100% for 48-72 hours
- Mothers Day (big in NZ/AU for gift supplements): +30-50% for the week leading up
- NZ/AU anniversary sales or promotional windows

How to apply:
- Google Ads > Tools > Bid Strategies > Seasonality Adjustments
- Set date range, campaigns, and expected conversion rate uplift %
- Remove immediately after event ends

Do NOT use seasonality adjustments for:
- Ongoing periods of more than 14 days (use campaign-level bid adjustments or budget changes instead)
- Speculative events where you're unsure of uplift

### Portfolio Bid Strategies

Portfolio bid strategies allow you to group multiple campaigns under one shared tROAS/tCPA goal. Use when:
- Running parallel campaigns that target the same customer (e.g., Search + Shopping for Sea Cucumber)
- You want to balance ROAS across campaigns rather than hitting exact targets in each individual one

Warning: Only use portfolio strategies when campaigns are truly complementary. Do not mix brand and non-brand under one portfolio -- they have fundamentally different economics.

### ECPC Deprecation Note

Enhanced CPC was deprecated for Search and Display as of March 31, 2025. If any campaigns are still "effectively using Manual CPC" (because ECPC was not migrated), migrate them to Maximize Conversions with a target CPA, or Manual CPC explicitly.

---

## 8. CONVERSION TRACKING AND LTV SETUP

### The Conversion Tracking Stack (In Order of Priority)

Priority 1: Native Google Ads Conversion Tag
- Install Google Ads conversion tag directly on the Shopify Thank You page
- Tag fires on purchase, captures purchase value (revenue) and transaction ID
- This is the primary conversion source for bidding

Priority 2: Enhanced Conversions
- Layer on top of the native conversion tag
- Captures hashed customer email, phone, name at purchase
- Allows Google to match conversions even with cookie loss (ad blockers, iOS, cross-device)
- Implementation: via Google Tag Manager or Shopify Google Channel app (which now supports Enhanced Conversions)
- Data is SHA256 hashed before leaving the browser. Do NOT send raw PII.

Priority 3: Server-Side Tagging
- Sends conversion data from your server to Google, bypassing client-side limitations
- Higher accuracy, fewer dropped conversions, faster page load (no extra JS)
- Setup: Google Tag Manager Server-Side container (host on Cloud Run or dedicated server)
- For DBH scale, server-side is important once spending $5,000+/month to protect data fidelity

Priority 4: GA4 Import (Secondary, Observation Only)
- Import GA4 key events (purchase) as a secondary conversion action in Google Ads
- Set to "Observation" (not included in Smart Bidding)
- Use to cross-reference attribution between GA4 (last-click) and Google Ads (data-driven)
- If numbers diverge by more than 30%, investigate your tracking setup

### Conversion Value Strategy for LTV Bidding

The default: pass revenue as conversion value. This is the starting point.

The upgrade: pass profit-weighted conversion value. Two approaches:

Approach A -- Margin Multiplier (simpler)
- Calculate average gross margin per SKU
- Configure a supplementary feed or conversion value rules that multiply purchase value by margin %
- e.g., $80 purchase at 50% margin = pass $40 as conversion value
- This aligns tROAS with profit, not revenue. A 3.0x tROAS against profit-weighted value = 1.5x ROAS on revenue (at 50% margin) = profitable

Approach B -- Conversion Value Rules (Google Native, No Dev Required)
- Google Ads > Tools > Conversion Value Rules
- Create rules based on: Location, Device, Audience (Customer Match segments)
- Example rule: "IF customer is in Customer Match list 'High Value Repeat' THEN multiply conversion value by 2.5x"
- This tells Google's AI these customers are worth more -- bid more aggressively to acquire them
- Use for first-time buyer vs repeat buyer distinction (repeat buyers worth 3x more at DBH if subscription conversion rate is high)

Approach C -- LTV Import (Advanced)
- After a cohort of customers has reached 90 days: calculate their actual 90-day revenue
- Import as Offline Conversion: "Customer LTV at 90 Days" conversion action
- This feeds actual LTV data (not predicted) back to Google for future bid optimisation
- Implementation: Klaviyo -> export customer list with revenue -> upload to Google Ads as offline conversion

### Conversion Action Setup in Google Ads

Primary conversion actions (used in bidding):
- Purchase (value-based, use actual purchase value or profit-weighted value)

Secondary conversion actions (observation only):
- Add to Cart (leading indicator)
- Initiate Checkout (leading indicator)
- Account Creation (leading indicator for LTV if subscription focused)

Important: Do NOT include micro-conversions (add-to-cart, page views) as primary conversions for Smart Bidding. This dilutes the signal and causes bidding to optimise for engagements, not revenue.

### Transaction ID Deduplication

Always pass a unique transaction ID with your purchase conversion event. This prevents double-counting when a customer reloads the thank you page. In Shopify: the order ID is the transaction ID.

---

## 9. AUDIENCE AND FIRST-PARTY DATA

### Customer Match: The Most Powerful Signal You Have

Customer Match allows you to upload your customer email list to Google Ads. Google matches hashed emails to logged-in Google accounts. Match rates typically 40-60% for consumer lists.

How to use it for DBH:

Segment 1: All Past Purchasers
- Purpose: Bid modifier in Search (they already trust you, higher conversion rate expected)
- Upload: Full Klaviyo email list, suppress from prospecting to save budget

Segment 2: High Value Customers (LTV > $250 NZD lifetime)
- Purpose: Audience signal for PMax asset groups to find people like them
- Conversion value rule: multiply x2.0 for these users when they're in-market

Segment 3: Lapsed Customers (purchased 6-12 months ago, no recent activity)
- Purpose: Winback campaign targeting -- show subscription offer or new products

Segment 4: Never-Purchased Email Subscribers
- Purpose: Warm audience -- they know the brand, just haven't bought
- Bid modifier: +30% in Search, include as PMax audience signal

Segment 5: One-Time Purchasers (not subscribed)
- Purpose: Upsell / subscription conversion
- Show subscription-specific ads to this segment

April 2025 update: Customer Match user lists no longer have infinite membership duration. Refresh lists at least monthly. Set up automated export from Klaviyo -> Google Ads (via Zapier or direct integration).

Match rate improvement tactics:
- Upload email + phone number together (improves match rate 28-35%)
- Upload email + full name + postal code
- Ensure email list is clean (remove bounces, unsubscribes)

### Similar Audiences: What Replaced Them

Similar Audiences were deprecated in 2023. They are gone. What replaced them:

1. Optimised Targeting (Display/YouTube/Discovery)
   - Google automatically expands targeting to users likely to convert based on your landing page and existing data
   - Turn on in Display campaigns, it works reasonably well
   - Does NOT work the same way as Similar Audiences

2. PMax's AI
   - PMax inherently does what Similar Audiences used to do: it finds new users who look like your converters
   - Feed it Customer Match lists and let it expand from there
   - This is why Customer Match in PMax is critical -- it defines the starting "ideal customer" profile

3. First-Party Data Modelling
   - For serious scale: build lookalike modelling in your CRM (Klaviyo + any analytics tool) and use Custom Intent audiences or Customer Match to reach them

### RLSA (Remarketing Lists for Search Ads)

RLSA = targeting remarketing audiences in Search campaigns. You show ads only to (or bid more for) people who have previously visited your site.

Key RLSA strategies for DBH:

Strategy 1: Bid up for cart abandoners
- List: Past 30-day cart abandoners (GA4 audience or Shopify pixel)
- Bid modifier: +50% in non-brand search campaigns
- Logic: They were about to buy. When they search again, be aggressive.

Strategy 2: Exclude past purchasers from acquisition campaigns
- List: All past purchasers
- Apply as negative audience in prospecting campaigns
- Logic: They already bought. Don't waste acquisition budget on them. Retarget them with upsell campaigns instead.

Strategy 3: Bid up for email subscribers who haven't purchased
- List: Customer Match -- email subscribers, no purchase
- Bid modifier: +30%
- Logic: They're warm. They'll convert at higher rate than a cold visitor.

Strategy 4: Dynamic remarketing (Shopping)
- Audiences: Product viewers (past 30 days), Cart abandoners (past 14 days)
- Campaign: Dynamic remarketing in Display (show the exact product they viewed)
- Note: PMax handles much of this automatically if audience signals are loaded

### In-Market and Affinity Audiences (for Prospecting)

Apply as observation audiences in all Search campaigns. Use data to understand your customer profile, then apply bid modifiers.

Recommended in-market audiences for DBH (apply as observation, see which over-index on conversions, then bid up):
- Health & Fitness > Vitamins & Supplements
- Health & Fitness > Weight Management
- Health & Fitness > Health Conditions (Arthritis, Joint Disorders)
- Beauty & Personal Care > Anti-Aging
- Pets & Animals > Pet Supplies

Data-driven decision: After 4-6 weeks of observation data, if "Vitamins & Supplements" in-market audience converts at 1.5x the campaign average, add +40% bid modifier for that audience.

---

## 10. NZ/AU MARKET SPECIFICS

### The Small Market Problem (and the Opportunity)

NZ is 5 million people. AU is 26 million. The total addressable market for a health supplement is a fraction of that -- say, adults aged 35-65 with disposable income and a health concern. In NZ, that might be 300,000-500,000 people. In AU, 3-5 million.

This means:
- Impression share matters enormously. In a small market, if you are not showing, a competitor is.
- Frequency caps are critical. You will saturate your core audience faster than in the US.
- Brand building is more cost-effective than pure performance because word-of-mouth travels faster.
- CPCs are lower than US/UK but higher than Southeast Asia. Expect $1.50-$4.00 NZD per click for mid-competition supplement terms.

### Geo Targeting Strategy

NZ: Target all of NZ. Do not segment by city unless conversion data shows strong regional variation. NZ is too small for city-level separation to add value. Exception: Auckland is 1/3 of NZ's population and may warrant a separate budget allocation if data shows it.

AU: Target nationally first. After 3 months of data, segment by state to identify over-indexing regions. Typically: NSW, VIC, QLD drive 65-70% of AU ecommerce. Consider separating WA and SA if budget allows for separate bid strategies.

NZ vs AU separation: Run separate campaigns for NZ and AU, not combined. Reasons:
- Different currencies (NZD vs AUD). Conversion values will be distorted if mixed.
- Different regulatory environments (NZ FSANZ vs AU TGA)
- Different CPCs and competition levels
- Different seasonal patterns (though both Southern Hemisphere, not dramatically different)

Budget allocation between NZ and AU:
- Initially allocate proportional to population (NZ: 16%, AU: 84% of combined budget)
- Adjust based on actual ROAS data within 60 days
- NZ often has higher ROAS because DBH has brand recognition there already
- AU is a larger opportunity but a colder market

### Supplement Category Restrictions and Policies

Google Ads supplement policy (global): Google restricts ads for supplements that make health claims that suggest they treat, cure, or prevent diseases. Supplements can be advertised but must not:
- Claim to treat, cure, or prevent a specific disease (e.g., "cures arthritis")
- Use before/after images implying medical treatment
- Make claims that are unsubstantiated or deceptive

Safe language in ad copy:
- "supports joint health" (not "cures joint pain")
- "promotes healthy skin" (not "eliminates wrinkles")
- "formulated for joint comfort" (not "treats arthritis")
- "natural joint support" (allowed)
- "clinically studied ingredients" (if true and verifiable)

TGA (Therapeutic Goods Administration) requirements for AU:
- TGA listed products (AUST L or AUST R number): Can make permitted indications
- The TGA Advertising Code 2021 applies to all advertising of listed therapeutic goods
- Penalties for breaches: Up to $1.65M AUD for individuals, $16.5M for corporations
- What you CAN say for listed supplements: Permitted indications (pre-approved statements only)
- What you CANNOT say: Claim product treats or cures a disease, testimonials that imply disease treatment, comparative claims without substantiation

TGA-safe wording examples for DBH:
- "Supports healthy joint function" (listed indication)
- "Traditionally used in TCM for joint health" (if applicable)
- "Supports skin health and collagen production" (listed indication)
- "Maintains healthy collagen levels" (listed indication)

Risk mitigation: Have all ad copy and landing page copy reviewed against TGA permitted indications list before campaign launch. The fine risk is not worth cutting corners.

FSANZ (NZ/AU food standards): Sea cucumber and marine collagen are food products (not therapeutic goods) if making general health claims (vs therapeutic claims). If sold as food supplements with general health claims, different rules apply. Clarify DBH's regulatory positioning per SKU.

Product disapproval risk: Merchant Center may flag supplement products for manual review. This is normal. Provide accurate product descriptions, avoid prohibited health claims in titles and descriptions, and the approval usually comes within 2-3 business days.

### NZ/AU Seasonal Calendar for Budget Allocation

Jan-Feb (NZ summer peak): Collagen and skin supplements. Increase Marine Collagen budget 30%.
Mar-Apr (AU/NZ autumn, back to routine): Good for subscription push. Steady budgets.
May-Jul (NZ/AU winter): Joint pain awareness peaks. Increase Sea Cucumber budget 40%. Arthritis-adjacent keywords volume increases.
Aug-Sep (pre-summer): Skin and health push starts. Increase Marine Collagen.
Oct-Nov (Black Friday prep): All budgets increase. Seasonality adjustment for Black Friday weekend.
Dec (NZ Christmas): ecommerce peaks. Gift-giving angle for supplements. Increase all budgets. Higher CPCs.

---

## 11. AUTONOMOUS MANAGEMENT RULES

### The Automation Philosophy: Automate the Tactical, Manage the Strategic

Automate: Bidding (let Google's AI handle real-time bid adjustments)
Automate: Budget alerts (script fires when budget exhaustion is imminent)
Automate: Performance anomaly detection (CPA spike, conversion rate drop)
Automate: Negative keyword mining (weekly search term pull and review)
Automate: Feed updates (price and stock changes via feed URL refresh)

Do NOT automate: Creative decisions (headlines, landing pages)
Do NOT automate: Strategic budget shifts between campaigns
Do NOT automate: ROAS target changes
Do NOT automate: Google's recommendations (they often serve Google's interests, not yours)
Do NOT automate: Audience list management (quality control required)

### Google's Auto-Apply Recommendations: Default to OFF

Google's auto-apply recommendations have been shown to increase spend in ways that benefit Google without always improving advertiser outcomes. Review recommendations manually. Apply selectively.

Safe to accept:
- Add new keywords (review each one carefully)
- Improve ad strength (if suggestions are genuinely better headlines)
- Update conversion tracking (if it improves accuracy)

Do not accept without careful review:
- Raise budgets (Google suggests this often; only do it when justified by ROAS)
- Expand to broad match (on its own terms; wait until you have sufficient conversion data)
- Target new locations (your geo strategy is deliberate)
- Add display expansion (often wastes budget on irrelevant placements)

Never accept:
- Any recommendation that significantly changes campaign structure
- Suggestions to raise ROAS targets above profitable level
- Automated app installs or other irrelevant campaign types

### Scripts for DBH Account Management

Script Category 1: Performance Anomaly Detection
- Purpose: Alert when CPA rises 50%+ above 7-day average
- Alert when conversion rate drops 30%+ below 7-day average
- Alert when a campaign has zero conversions in 48 hours during active periods
- Implementation: Google Ads Script + email/Telegram notification

Script Category 2: Budget Pacing
- Purpose: Check daily budget spend rate at 12pm. If on track to exhaust before 6pm, send alert.
- Alert: "Campaign [X] pacing to exhaust budget by 4pm. Consider increasing or will miss evening traffic."
- Implementation: Google Ads Script, run hourly

Script Category 3: PMax Search Term Analysis
- Purpose: Extract search themes data from PMax (using Google Ads API via script)
- Output: Spreadsheet of top queries, cost, conversions, ROAS per query
- Frequency: Weekly
- Use output: Add converting queries to Search campaigns as exact match; add wasted spend queries as negatives

Script Category 4: N-Gram Analysis
- Purpose: Identify high-waste word patterns in search terms
- Logic: If any word appears in 10+ search terms with zero conversions and $50+ spend, flag for negation
- Frequency: Monthly
- Output: Prioritised negative keyword list ranked by wasted spend

Script Category 5: Broken Link / 404 Checker
- Purpose: Check all ad destination URLs weekly for 404 errors
- Alert immediately if any destination URL is returning an error
- Implementation: Google Ads Script, run weekly

Script Category 6: Impression Share Monitor
- Purpose: Alert when impression share on Brand terms drops below 80%
- This means competitors are bidding on your brand name aggressively
- Response: Review auction insights, consider bid increase

### Automated Rules (Google Ads Native)

Rule 1: Pause high-spend, zero-conversion keywords
- Condition: Keyword with 0 conversions AND spend > 2x target CPA in last 14 days
- Action: Pause keyword
- Schedule: Run weekly on Sunday evening

Rule 2: Reduce bid on underperforming ad groups
- Condition: Ad group ROAS < 50% of target ROAS over last 30 days (minimum 10 conversions)
- Action: Reduce target ROAS by 15% (allows more volume while diagnosing)
- Schedule: Monthly, first Monday

Rule 3: Flag rapid budget exhaustion
- Condition: Campaign has used 80% of daily budget before 2pm
- Action: Send email notification
- Schedule: Hourly check 9am-2pm

---

## 12. WEEKLY OPTIMISATION CHECKLIST

Complete every Monday before 10am. This takes 45-60 minutes. Do not skip.

### Performance Review

- Check account-level spend vs budget target for prior week
- Check each campaign's ROAS vs target ROAS (flag any campaign more than 20% off target)
- Check conversion volume: was it above or below 7-day moving average?
- Check impression share on brand campaign: if below 85%, increase brand bid
- Check Quality Score on top 20 keywords by spend (below 5/10 = fix ad copy or landing page)
- Check Google Merchant Center for feed errors or disapprovals
- Record findings in Meridian's CONTEXT.md for agent awareness

### Search Term Mining

- Export Search Terms Report for all Search campaigns, last 7 days
- Sort by Spend (descending), identify non-converting terms with spend > $15 NZD
- Add as negatives (exact match) to relevant campaigns or account-level negative list
- Sort by Conversions (descending), identify converting terms not in keyword list
- Add converting search terms as new exact match keywords in appropriate ad groups
- Check for any brand name matches (should be captured by brand campaign, not non-brand)
- Check for any policy-sensitive terms (e.g., "cure", "treat", disease names as queries)

### Asset Review (Every 2 Weeks)

- Check PMax asset performance labels: remove "Low" performers older than 4 weeks
- Check RSA combination performance in Search: which headline combinations appear most?
- Schedule new creative test if top headlines have been running more than 8 weeks unchanged
- Refresh at least one asset group image or video if campaign has run 90+ days

### Competitive Intelligence

- Check Auction Insights report for brand and top non-brand campaigns
- Note any new competitors appearing in the auction
- Check impression share trends: if declining, identify cause (budget, bid, Quality Score)
- Identify if any competitor is consistently outranking you on key terms

### Feed Check

- Merchant Center > Diagnostics: zero errors, zero warnings target
- Check for any price discrepancy disapprovals (Shopify price changed but feed not updated)
- Check for new product approvals needed (recently added products)
- Verify custom labels are correctly assigned to all active products

---

## 13. MONTHLY STRATEGIC REVIEW

Complete on the first Monday of each month. This is a strategic session, not a tactical one.

### Performance Analysis

- Total Google Ads spend vs monthly budget
- ROAS per campaign (actual vs target)
- Cost per acquisition vs LTV (is the CPA economically justified?)
- Revenue attribution: Google Ads-attributed revenue vs Shopify last-click revenue (note the gap)
- New customer count from Google (separate from existing customer reactivation)
- Conversion rate by campaign and device type
- Geographic performance: NZ vs AU ROAS comparison

### LTV Cohort Update

- Pull 3-month, 6-month, 12-month LTV for customers acquired through Google Ads (segment by campaign where possible via UTM data in Shopify)
- Compare against Meta-acquired customer LTV and organic LTV
- If Google-acquired customers have lower LTV than other channels: reduce Google budget allocation, shift to higher-LTV channels
- If Google-acquired customers have higher LTV: increase budget, improve ROAS targets to allow more volume

### Budget Allocation Decision

Each month, review the cross-channel budget allocation:
- Which campaign had highest ROAS in prior month? Increase its budget.
- Which campaign was under target ROAS for 3+ consecutive months? Diagnose or reduce budget.
- Is there an untested opportunity (e.g., YouTube, Demand Gen) that could expand the funnel?

### ROAS Target Review

- Are targets still aligned with current gross margins? (COGS can change -- review with Tony)
- Are targets too aggressive? (Campaign volume limited, missing impressions?)
- Are targets too loose? (Spending budget easily but ROAS is too low for profitability?)

### Keyword Strategy Review

- Run n-gram analysis on 30-day search terms
- Identify wasted spend patterns (words appearing in 5+ wasted searches)
- Identify opportunity gaps (keywords in Search Terms but not in keyword list)
- Review competitor keyword presence via auction insights trends

### Feed and Creative Refresh

- Have product titles been tested for alternative structures this quarter?
- Are all product descriptions optimised with benefit language?
- Are new product images or video assets needed?
- Plan Q ahead: what seasonal campaigns need building?

---

## 14. DBH-SPECIFIC CAMPAIGN PLAN

### Sea Cucumber -- Campaign Architecture

Product: Sea Cucumber capsules (joint health, anti-inflammatory, mobility)
Target customer: Men and women 40-65, NZ and AU, experiencing joint stiffness, arthritis concerns, reduced mobility. Often already trialling or aware of glucosamine.

Primary search intent angle: Symptom-driven ("joint pain", "stiff joints", "joint inflammation") plus product-driven ("sea cucumber supplement NZ")

Search campaign keywords (exact/phrase):
- [sea cucumber supplement NZ/Australia]
- [sea cucumber capsules]
- [sea cucumber joint health]
- [natural joint pain supplement NZ]
- [joint inflammation supplement]
- [best joint supplement NZ]
- [glucosamine alternative]
- [anti-inflammatory supplement NZ]
- [marine joint health supplement]
- [mobility supplement over 50]

RSA headline angles (must be compliant -- support/promote, not cure/treat):
- "Sea Cucumber for Joint Support"
- "Natural Marine Joint Health Supplement"
- "Supports Joint Comfort and Mobility"
- "100% New Zealand Sea Cucumber"
- "TGA Listed Joint Support"
- "3500+ Customers in NZ and AU"
- "30-Day Money Back Guarantee"
- "Free Shipping on Orders $80+"
- "Subscribe and Save 15% Monthly"
- "Reduce Inflammation Naturally"
- "Marine-Sourced. Bioavailable. Effective."
- "Feel the Difference in 30 Days"
- "Formulated for Active Ageing"
- "No Fillers. Just Sea Cucumber."
- "Stiff Joints? Try Natural Marine Supplement"

PMax asset group signals:
- Customer Match: Past Sea Cucumber purchasers
- In-market: Arthritis & Joint Conditions, Vitamins & Supplements
- Age: 40-65, slight male skew (though both genders targeted)

Shopping title: "Deep Blue Health Sea Cucumber Joint Support Capsules 60 Count"
Custom Label 0: high_margin (if COGS allows)
Custom Label 1: bestseller (if top SKU by revenue)
Custom Label 3: winter_push (NZ/AU winter = May-Aug)

### Marine Collagen -- Campaign Architecture

Product: Marine Collagen capsules (skin health, collagen production, anti-aging)
Target customer: Women 28-55 NZ and AU, interested in skin health, anti-aging, beauty from within.

Primary search intent angle: Product-driven ("marine collagen NZ") plus outcome-driven ("skin collagen supplement", "collagen for skin health")

Search campaign keywords (exact/phrase):
- [marine collagen NZ/Australia]
- [marine collagen supplement]
- [hydrolysed collagen NZ]
- [fish collagen NZ]
- [collagen for skin NZ]
- [collagen capsules NZ]
- [collagen supplement NZ]
- [best collagen supplement NZ]
- [marine collagen peptides]
- [skin supplement NZ]
- [anti-aging supplement NZ]
- [beauty supplement NZ]

RSA headline angles:
- "Marine Collagen for Healthy Skin"
- "New Zealand Marine Collagen Capsules"
- "Supports Skin Health and Collagen Levels"
- "Hydrolysed for Better Absorption"
- "NZ-Owned. Marine Sourced."
- "3500+ Happy Customers"
- "30-Day Money Back Guarantee"
- "Free Shipping Orders $80+"
- "Subscribe for 15% Off Monthly"
- "Glow From the Inside Out"
- "Collagen That Works. Bioavailable."
- "TGA Listed Collagen Supplement"
- "Feel a Difference in 30 Days"
- "Premium Marine Collagen -- NZ Made"
- "Your Daily Skin Ritual. Simplified."

PMax asset group signals:
- Customer Match: Past Marine Collagen purchasers
- In-market: Beauty & Personal Care, Vitamins & Supplements
- Affinity: Beauty & Fitness
- Age: 28-55, strong female skew

Shopping title: "Deep Blue Health Marine Collagen Skin Health Supplement Capsules 90 Count"
Custom Label 0: high_margin (if applicable)
Custom Label 3: summer_skin (NZ/AU summer = Oct-Jan)

### Pure Pets -- Campaign Architecture

Product: Pet joint and health supplements (sea cucumber or collagen based)
Target customer: Dog owners, 30-60, NZ and AU. Older dogs with mobility issues. Owners who take their own supplements and are likely to buy for their pets.

Primary search intent: Problem-driven ("dog joint pain supplement", "pet mobility supplement") plus product-driven ("pet sea cucumber supplement")

Search campaign keywords (exact/phrase):
- [dog joint supplement NZ/Australia]
- [pet joint health supplement]
- [natural dog joint supplement]
- [sea cucumber for dogs]
- [dog mobility supplement]
- [pet health supplement NZ]
- [old dog joint supplement]
- [dog anti-inflammatory supplement]
- [natural pet supplement NZ]
- [supplement for dog arthritis NZ]

Note: "Arthritis" in pet context -- different rules apply vs human therapeutics. Consult TGA guidance on veterinary claims.

RSA headline angles:
- "Pure Pets Joint Supplement for Dogs"
- "Natural Dog Joint Health Supplement"
- "Supports Pet Mobility and Comfort"
- "Marine-Sourced Pet Health Support"
- "For Dogs Who Need Extra Joint Love"
- "NZ-Owned Pet Supplement Brand"
- "30-Day Money Back Guarantee"
- "Free Shipping Orders $80+"
- "3500+ NZ & AU Pet Owners Trust DBH"
- "Subscribe and Save on Pet Supplements"
- "No Nasties. Just Marine Goodness."
- "Support Your Dog's Active Life"
- "Gentle on Digestion. Effective."
- "Vet-Friendly Natural Pet Supplement"
- "Happy Dogs. Happy Owners."

PMax asset group signals:
- Customer Match: Past Pure Pets purchasers
- In-market: Pets > Dog Supplies, Pet Health
- Affinity: Pet Lovers

Shopping title: "Pure Pets Natural Dog Joint Supplement Capsules 60 Count"
Custom Label 3: year_round (pet supplements less seasonal)

### Cross-SKU Funnel Strategy

Top of funnel (awareness): YouTube and PMax Display
- Video ad: "Why DBH -- NZ-made, marine sourced, 3500+ customers" (brand film, 45-60 seconds)
- Video ad: "What is Sea Cucumber and why does it help joints?" (educational, 2-3 minutes, Discovery)
- Video ad: "Marine Collagen -- what's the difference between types?" (educational)

Middle of funnel (consideration): PMax (full assets), Search (informational keywords)
- Symptom-led search ads
- Educational content ads targeting "what is the best joint supplement NZ" type queries
- Remarketing to video viewers who did not visit site

Bottom of funnel (conversion): Search (transactional keywords), Standard Shopping
- "Buy sea cucumber supplement NZ" style queries
- Product-specific Shopping ads
- Remarketing (RLSA, PMax dynamic remarketing) to site visitors who did not purchase

Post-purchase (LTV): Klaviyo primarily, supplemented by Google Customer Match
- Suppress past purchasers from acquisition campaigns
- Run upsell campaigns to single-SKU customers showing the other products

---

## 15. KPIs AND REPORTING FRAMEWORK

### Primary KPIs (Drive Business Decisions)

POAS (Profit on Ad Spend): Target 1.5x+ in growth phase, 2.0x+ in efficiency phase
- Formula: Gross Profit from Google-attributed orders / Google Ads Spend
- Review: Monthly

Actual ROAS (Revenue / Ad Spend): Review weekly but never use as the only metric
- NZ target: 3.5-5.0x (depending on product margin mix)
- AU target: 3.0-4.5x (colder market, lower initial ROAS expected)

CPA (Cost Per Acquisition -- New Customer): Target based on LTV payback period
- If 90-day LTV of Google-acquired customer is $120 NZD, CPA target = $40-60 NZD (30-50% of LTV)
- Review: Monthly (must correlate with LTV data)

New Customer Rate: What % of Google-attributed orders are new customers?
- Benchmark: PMax prospecting should be 60%+ new customers
- Brand Search will be 80%+ existing customers (normal)
- Non-brand Search should be 50%+ new customers

Impression Share -- Non-Brand: Target 40-60% for core terms (small market, 100% IS is expensive)
Impression Share -- Brand: Target 90%+ at all times

Click-Through Rate (CTR): Diagnostic metric
- Search CTR benchmark: 5-8% (below 3% = fix your headlines or your match types are too broad)
- Shopping CTR benchmark: 1-3%
- Display CTR benchmark: 0.3-0.5%

Conversion Rate (CVR): Diagnostic metric
- Search purchase CVR benchmark: 2-5% (above 5% = great landing page; below 1% = landing page problem)
- Shopping CVR benchmark: 1-3%

### Secondary KPIs (Weekly Diagnostic)

Quality Score (top keywords by spend): Target 7+/10 for core terms
Search Lost IS (budget): Should be under 10% (if higher, increase budget or reduce bids)
Search Lost IS (rank): Should be under 15% (if higher, improve Quality Score or bid)
Cost per Click (CPC): Track trend over time. Rising CPC = more competition or lower QS.
Asset Performance Labels (PMax): Track ratio of Best/Good/Low assets. Target 70%+ Best or Good.

### Reporting Cadence

Daily (automated via script or Meridian agent): Total spend, conversions, ROAS vs target. Alert if anomaly.
Weekly (Monday morning review): Full performance review per checklist in Section 12.
Monthly (first Monday): Strategic review per Section 13. Present to Tony in report format.

### UTM Parameter Structure

All Google Ads URLs must include UTM parameters for Shopify attribution tracking. This is the same problem that was identified in Meta -- do not repeat it.

UTM structure:
- utm_source=google
- utm_medium=cpc
- utm_campaign={campaign_name} (use dynamic insertion via Google's {campaign} parameter)
- utm_content={creative_id} or {adgroupid}
- utm_term={keyword}

Full URL example:
https://deepbluehealth.co.nz/products/sea-cucumber?utm_source=google&utm_medium=cpc&utm_campaign={campaign}&utm_content={adgroupid}&utm_term={keyword}

Set these at the campaign level as "Final URL suffix" or "Tracking template" to apply across all ads without manually editing each ad. Verify in Shopify that Google-attributed orders are appearing with correct UTM data.

---

## 16. COMMON MISTAKES TO AVOID (Josh-Level Errors Documented)

This section documents the class of errors that agencies make, particularly those managing small DTC brands without rigorous process. Named "Josh-level" for reference to prior agency management that required post-hoc correction.

### Error 1: Reporting ROAS Without Knowing Gross Margin

What happened: Agency reports 4.71x ROAS as "great performance." At 25% gross margin, that is barely breaking even after ad spend + COGS. Actual profit margin on ads: near zero or negative.

Fix: Always anchor ROAS targets to gross margin. Set margin-adjusted ROAS target before any campaign goes live. Never accept a ROAS number without knowing what margin it implies.

### Error 2: Using Revenue ROAS When Bidding (Should Be Profit ROAS)

What happened: tROAS set based on revenue, not profit. Google optimises for high-revenue orders, but those may be low-margin SKUs or bundles with discounts. Ad spend looks efficient by revenue, catastrophic by profit.

Fix: Use conversion value rules or profit-adjusted conversion values to pass margin-weighted revenue to Google. Set tROAS targets against the profit-adjusted value.

### Error 3: Smart Bidding with Insufficient Conversion Data

What happened: tROAS enabled on campaign with 8 conversions per month. Google's AI is effectively guessing. CPA spikes, budget exhausted on poor-quality traffic. Agency reports "the algorithm needs more time."

Fix: Minimum 30 conversions/month for Maximize Conversions. Minimum 50 conversions/month for Target ROAS. Below these thresholds: Manual CPC or Target Impression Share (brand) only.

### Error 4: No Negative Keywords on PMax

What happened: PMax running with zero negative keywords. Budget spent on queries like "sea cucumber recipe", "sea cucumber sushi", "collagen injection cost", "free collagen samples". Wasted 30-40% of budget on irrelevant traffic.

Fix: Build a 500-word core negative keyword list before any campaign launches. Run weekly search term reviews. PMax now supports 10,000 negative keywords -- use them.

### Error 5: Brand Cannibalisation by PMax

What happened: PMax bidding on brand terms, inflating branded conversion count, making non-brand performance look worse than it is. Agency credits PMax with conversions that would have happened through organic brand search anyway.

Fix: Apply brand exclusions to all PMax campaigns. Keep brand in a separate Search campaign with Target Impression Share. Never let PMax touch brand traffic.

### Error 6: Missing UTM Parameters on Ad URLs

What happened: Google Ads campaigns running with no UTM parameters. Shopify shows 60%+ of revenue as "direct" or "unknown". Cannot attribute Google performance. Cannot diagnose what is working.

Fix: Template-level UTM parameters applied to all campaigns. Verified in Shopify within 48 hours of campaign launch. Not optional.

### Error 7: Auto-Apply Recommendations Enabled

What happened: Google auto-applied "Expand to new keywords" and "Raise budgets" recommendations without review. Budget doubled, broad match enabled on underperforming campaign, CPA tripled in 2 weeks. Agency did not notice for 3 weeks.

Fix: Auto-apply disabled at account level. All recommendations reviewed manually before acceptance. This is a mandatory account setting on day one.

### Error 8: Conversion Tracking Not Verified Before Campaign Launch

What happened: Campaign running for 3 weeks. Smart Bidding is saying "not enough conversions." Manual investigation reveals the Google Ads conversion tag was firing on the Add to Cart page, not the Thank You page. Every add-to-cart was counted as a purchase. ROAS was fabricated.

Fix: Conversion tracking verified via Google Tag Assistant and test purchase before any campaign goes live. Check: (a) tag fires on Thank You page only, (b) conversion value passes correctly, (c) transaction ID deduplication active.

### Error 9: Ignoring Shopping Feed Quality

What happened: Shopping campaigns running with suboptimal product titles (e.g., "Sea Cucumber 60c" instead of "Deep Blue Health Sea Cucumber Joint Health Supplement Capsules 60 Count"). Lower impression share, lower CTR, higher CPC.

Fix: Title optimisation is a conversion rate task. Treat feed quality with the same rigour as ad copy. Titles directly determine what search queries trigger your Shopping ads.

### Error 10: Running PMax Without Any Creative Assets (Videos)

What happened: PMax campaign created without video assets. Google auto-generates a video from images. Auto-generated video is uniformly poor quality. PMax allocates significant budget to YouTube/Discovery with unwatchable creative. CTR low, ROAS terrible.

Fix: Never launch PMax without at least one high-quality video asset per asset group. Minimum: a 30-second product explanation video with voiceover. Ideal: UGC-style video from a customer or founder.

### Error 11: Same ROAS Target Across All Products (Ignoring Margin Differences)

What happened: Single tROAS of 3.5x applied account-wide. High-margin Sea Cucumber (55% margin) needs only 1.82x to break even. Low-margin bundle (30% margin) needs 3.33x to break even. The single target causes Sea Cucumber to underspend (missed opportunity) while the bundle campaign operates at near-zero profit.

Fix: ROAS targets set per campaign, per product margin. Calculate breakeven ROAS for each SKU/category. Apply margin-appropriate targets. Review whenever COGS changes.

### Error 12: Changing Campaign Settings Too Frequently

What happened: ROAS target changed weekly. Budget changed multiple times per week. Learning period never completes. Algorithm permanently in flux. Performance is erratic. Agency blames "market conditions."

Fix: Once set, campaign settings stay for minimum 14 days unless there is a critical performance emergency (e.g., zero conversions for 72 hours, confirmed tracking issue). Budget changes capped at 20% per week. Discipline is the most powerful optimisation lever.

### Error 13: Ignoring the NZ/AU Regulatory Environment

What happened: Ad copy says "Deep Blue Health Sea Cucumber -- reduces joint pain and inflammation." TGA complaint filed. Google Ads account suspended for policy violation. All campaigns paused during investigation. 3 weeks of zero Google traffic.

Fix: Legal review of all ad copy and landing page copy against TGA Permitted Indications before any AU campaign launches. Use "supports" and "promotes" language, not "reduces", "cures", or "treats". Maintain a language compliance checklist for all team members who write ad copy.

### Error 14: Conflating Google-Attributed and Shopify-Attributed Revenue

What happened: Google Ads shows $15,000 revenue from campaigns. Shopify shows $9,000 revenue attributed to Google (CPC). Gap of $6,000. Agency reports Google Ads revenue. Actual Google Ads-driven revenue is 40% lower than reported.

Fix: Always report Shopify last-click revenue alongside Google Ads data-driven attribution. Understand the attribution gap is normal (15-30%) but flag anything above 40% as a signal of attribution model problems. Use Shopify as the source of truth for financial planning. Use Google Ads attribution for optimisation decisions within the platform.

---

## APPENDIX: DBH ACCOUNT LAUNCH SEQUENCE

When launching (or rebuilding) the Google Ads account from scratch, follow this sequence:

Day 1: Foundation
- Link Google Ads to GA4
- Link Google Ads to Google Merchant Center
- Verify Shopify domain in Merchant Center
- Submit product feed to Merchant Center
- Install Google Ads conversion tag via GTM (Thank You page trigger)
- Verify conversion tracking with test purchase
- Set up Enhanced Conversions
- Disable auto-apply recommendations
- Upload Customer Match list (all past purchasers from Klaviyo)
- Set account-level negative keyword list (500 core terms)
- Apply correct UTM tracking template at account level

Day 2-3: Campaign Build
- Build Brand Search campaign (exact match, tIS 90%)
- Build Non-Brand Search campaigns (Core High Intent)
- Build Standard Shopping campaigns (per product category)
- Set all campaigns to Maximize Clicks or Manual CPC initially (no Smart Bidding yet)
- Set conservative daily budgets ($20-30 NZD/day per campaign to start)

Week 1-2: Data Collection
- No bid strategy changes
- Daily search term review (add negatives ruthlessly)
- Monitor for feed disapprovals
- Monitor Merchant Center for errors

Week 3-4: Smart Bidding Activation
- If each campaign has 15+ conversions: switch to Maximize Conversions (no target)
- If fewer than 15: keep on Manual CPC and increase bids on best-performing keywords

Month 2: tROAS Introduction
- If campaign has 50+ conversions: introduce target ROAS at breakeven + 20% (conservative start)
- Do not introduce tROAS on any campaign with fewer than 50 conversions

Month 3: PMax Addition
- Launch Feed-Only PMax at LOW priority, lower tROAS than Standard Shopping
- Load all audience signals (Customer Match lists, website visitors, in-market audiences)
- Set search themes (50 per asset group)
- Launch with dedicated budget, separate from Standard Shopping

Month 4+: Full Account Maturity
- PMax expanded to full assets (if video creative available)
- Conversion value rules implemented for LTV-based bidding
- Script automation active for anomaly detection and search term mining
- Monthly strategic review cadence established
- NZ and AU campaigns running separately with market-appropriate budgets

---

*This document is a living operational manual. Update quarterly with new research, or immediately when Google releases significant platform changes. File lives at: `/agents/dbh-marketing/skills/google-ads-mastery.md`*

*Sources drawn from: Google Ads Help Center, PPC Mastery, Store Growers, Define Digital Academy, Taikun Digital, Echelonn, AdNabu, DataSlayer, groas.ai, Wolfgang Digital, ProfitMetrics, TGA Australia, ICLG Pharmaceutical Advertising Report 2025-2026, Search Scientists, Search Engine Land, Seer Interactive, optmyzr, and Lever Digital.*
