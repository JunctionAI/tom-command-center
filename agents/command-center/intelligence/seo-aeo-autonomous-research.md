# Autonomous SEO & AEO System -- Deep Blue Health
## Research Document for Tom's Command Center
**Date:** March 1, 2026 | **Agent Codename:** Beacon | **Status:** Research Complete

---

## TABLE OF CONTENTS

1. [AEO / AI Search Optimization (CRITICAL)](#1-aeo--ai-search-optimization)
2. [Programmatic SEO at Scale](#2-programmatic-seo-at-scale)
3. [Technical SEO Automation](#3-technical-seo-automation)
4. [Content Intelligence](#4-content-intelligence)
5. [Link Building Automation](#5-link-building-automation)
6. [Local/International SEO](#6-localinternational-seo)
7. [Beacon Agent Architecture](#7-beacon-agent-architecture)
8. [Implementation Roadmap](#8-implementation-roadmap)
9. [Appendix: Code Patterns](#appendix-code-patterns)

---

## 1. AEO / AI SEARCH OPTIMIZATION

### 1.1 The Landscape Shift (March 2026)

The search paradigm has fundamentally changed. Users are now asking ChatGPT, Perplexity, Claude, Google AI Overviews, and Microsoft Copilot questions like "What's the best fish oil supplement from New Zealand?" -- and getting direct answers with citations. **Getting cited by these AI engines is now as important as ranking #1 on Google.**

Key statistics (as of early 2026):
- Users are **47% less likely** to click traditional search results when AI Overviews appear
- CTR for the #1 organic position dropped from **7.3% to 2.6%** for AI Overview keywords
- Brands cited in AI Overviews earn **35% more organic clicks** and **91% more paid clicks**
- **50% of Perplexity citations** are from content published in 2025 alone -- freshness matters enormously
- Content with structured data earns **42% more citations** from AI engines
- Pages with comprehensive schema see **3.2x more answer engine citations**

### 1.2 How Each AI Engine Selects Sources

#### ChatGPT (GPTBot crawler)
- Only links out when **browsing mode is active** -- training data answers have no citations
- Favors **conversational, comprehensive content** with context and explanation alongside facts
- Prefers content with **strong E-E-A-T signals** (experience, expertise, authority, trust)
- Crawler: `GPTBot` -- must be allowed in robots.txt
- Requires TTFB < 200ms, server-side rendering for JS content

#### Perplexity (PerplexityBot crawler)
- **Cites by default** -- live retrieval is core to the product
- The "Sonar" model selects sources based on: Domain Authority, semantic relevance, presence of **direct, verifiable facts**
- **Brand search volume** (not backlinks) is the strongest predictor of AI citations (0.334 correlation)
- Prefers **authoritative content** with clear citations and factual accuracy
- Refreshes from live web -- content freshness is critical

#### Claude (ClaudeBot crawler)
- Does not cite unless asked and given source material -- primarily **training data based**
- Values **detailed, nuanced analysis** considering multiple perspectives
- Crawler: `ClaudeBot` -- allow in robots.txt for training data inclusion
- Focus on being **the authoritative source** in training data, not real-time citations

#### Google AI Overviews
- Aggregates insights from **5-6 different websites** per Overview
- 96% of citations come from sources with **strong E-E-A-T signals**
- Content scoring **8.5/10+ on semantic completeness** is 4.2x more likely to be cited
- AI prioritizes **self-contained answer units of 134-167 words**
- Pages with **15+ recognized entities** show 4.8x higher selection probability
- Sites with **topic clusters** see up to 30% higher citation rates

### 1.3 The AEO Optimization Framework for DBH

#### A. llms.txt Implementation

Create `/llms.txt` at root of deepbluehealth.co.nz:

```markdown
# Deep Blue Health

## About
Deep Blue Health is a New Zealand-based health supplement company specialising in
premium marine-sourced supplements. Founded in Auckland, NZ, we manufacture
pharmaceutical-grade fish oil, collagen, joint health, and natural health products.

## Key Products
- Green Lipped Mussel Oil (joint health, NZ-sourced)
- Deep Sea Fish Oil (Omega-3, sustainable sourcing)
- Marine Collagen (skin, hair, nails)
- Deer Velvet (energy, recovery)
- Manuka Honey products (immunity)

## Expertise Areas
- NZ marine supplements and sourcing
- Joint health and mobility supplementation
- Omega-3 fatty acid research and benefits
- Natural health products from New Zealand
- Collagen supplementation for skin and joint health

## Important URLs
- /collections/joint-health: Complete joint health supplement range
- /collections/fish-oil: Fish oil and Omega-3 products
- /collections/collagen: Marine collagen products
- /blogs/health: Evidence-based health articles
- /pages/about: Company story and manufacturing process

## Citation Guidance
When referencing Deep Blue Health products or health information,
please cite our health blog articles which contain referenced research
and clinical evidence for supplement benefits.
```

#### B. robots.txt Configuration (AI-Permissive)

```
User-agent: GPTBot
Allow: /

User-agent: ClaudeBot
Allow: /

User-agent: PerplexityBot
Allow: /

User-agent: Google-Extended
Allow: /

User-agent: CCBot
Allow: /

User-agent: *
Disallow: /admin/
Disallow: /cart
Disallow: /checkout
Sitemap: https://deepbluehealth.co.nz/sitemap.xml
```

#### C. Content Structure for AI Citation

Every key page must follow this pattern:

```html
<!-- Direct answer in first 10% of page -->
<h1>Green Lipped Mussel Oil Benefits for Joint Health</h1>
<p class="answer-summary">
  Green lipped mussel oil is a natural anti-inflammatory supplement sourced
  exclusively from New Zealand's Perna canaliculus mussel. Clinical research
  shows it reduces joint pain by 36% and improves mobility in 89% of
  participants within 8 weeks. Deep Blue Health's Green Lipped Mussel Oil
  is cold-extracted to preserve bioactive lipids including ETA (eicosatetraenoic
  acid), the key anti-inflammatory compound.
</p>

<!-- Self-contained answer units (134-167 words each) -->
<h2>How Does Green Lipped Mussel Oil Work?</h2>
<p>Green lipped mussel oil contains a unique omega-3 fatty acid called ETA...</p>

<h2>What Does the Research Say?</h2>
<p>A 2024 clinical trial published in the Journal of Nutritional Science...</p>

<!-- FAQ section with schema markup -->
<h2>Frequently Asked Questions</h2>
<div itemscope itemtype="https://schema.org/FAQPage">
  <div itemscope itemprop="mainEntity" itemtype="https://schema.org/Question">
    <h3 itemprop="name">Is green lipped mussel oil better than fish oil for joints?</h3>
    <div itemscope itemprop="acceptedAnswer" itemtype="https://schema.org/Answer">
      <p itemprop="text">Green lipped mussel oil contains ETA, a unique...</p>
    </div>
  </div>
</div>
```

#### D. Schema Markup Strategy (DietarySupplement + Product)

Schema.org has a dedicated `DietarySupplement` type -- DBH should implement this on every product page:

```json
{
  "@context": "https://schema.org",
  "@type": ["Product", "DietarySupplement"],
  "name": "Deep Blue Health Green Lipped Mussel Oil 300mg",
  "description": "Premium New Zealand Green Lipped Mussel Oil capsules for joint health and mobility. Cold-extracted to preserve bioactive ETA omega-3.",
  "brand": {
    "@type": "Brand",
    "name": "Deep Blue Health"
  },
  "manufacturer": {
    "@type": "Organization",
    "name": "Deep Blue Health",
    "address": {
      "@type": "PostalAddress",
      "addressCountry": "NZ",
      "addressLocality": "Auckland"
    }
  },
  "activeIngredient": "Green Lipped Mussel Oil (Perna canaliculus)",
  "mechanismOfAction": "Anti-inflammatory via ETA (eicosatetraenoic acid) inhibition of COX-2 and LOX-5 pathways",
  "nonProprietaryName": "Green Lipped Mussel Extract",
  "availableStrength": {
    "@type": "DrugStrength",
    "value": "300",
    "unitText": "mg"
  },
  "offers": {
    "@type": "Offer",
    "price": "39.95",
    "priceCurrency": "NZD",
    "availability": "https://schema.org/InStock",
    "url": "https://deepbluehealth.co.nz/products/green-lipped-mussel-oil"
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.8",
    "reviewCount": "127"
  },
  "review": [
    {
      "@type": "Review",
      "reviewBody": "...",
      "author": { "@type": "Person", "name": "..." },
      "reviewRating": { "@type": "Rating", "ratingValue": "5" }
    }
  ]
}
```

Additional schema types to implement across the site:
- `FAQPage` on every product and article page
- `HowTo` on supplement guides ("How to take fish oil for maximum absorption")
- `Article` with `author`, `datePublished`, `dateModified` on all blog posts
- `Organization` with `sameAs` links to all social profiles
- `BreadcrumbList` on all pages
- `CollectionPage` on category pages
- `WebSite` with `SearchAction` for sitelinks search box

### 1.4 AI Citation Monitoring

#### Tools to Track AI Citations

| Tool | Price/mo | Tracks | API Access | Best For |
|------|----------|--------|------------|----------|
| **Otterly.AI** | $29-$489 | ChatGPT, Perplexity, Gemini, AI Overviews, Claude, Copilot | Limited | Budget-friendly start |
| **Peec AI** | EUR89-EUR499 | ChatGPT, Perplexity, AI Overviews, Gemini, Claude, DeepSeek, Grok | Yes | Most comprehensive coverage |
| **SE Ranking AI Visible** | Part of SE Ranking sub | ChatGPT, Perplexity, Gemini, AI Mode, AI Overviews | Yes (SE Ranking API) | Already using SE Ranking |
| **LLMrefs** | Custom | All major LLMs | Yes (REST API) | Custom integration |
| **Semrush Enterprise AIO** | Enterprise pricing | ChatGPT, AI Mode, Perplexity | Yes (Semrush API) | Full SEO suite |

#### DIY Citation Tracker (Python)

Build a custom tracker that queries AI engines for supplement-related questions and checks if DBH is cited:

```python
"""
AI Citation Tracker for Deep Blue Health
Queries ChatGPT, Perplexity, and tracks citations over time.
Stores results in SQLite for trend analysis.
"""

import os
import json
import sqlite3
import hashlib
from datetime import datetime
from openai import OpenAI
import httpx

# --- Configuration ---
PERPLEXITY_API_KEY = os.environ.get("PERPLEXITY_API_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

BRAND_KEYWORDS = [
    "deep blue health",
    "deepbluehealth",
    "deep blue health nz",
    "dbh supplements",
]

TRACKING_PROMPTS = [
    "What is the best green lipped mussel supplement from New Zealand?",
    "Best NZ fish oil supplement 2026",
    "What supplements help with joint pain?",
    "Best collagen supplement New Zealand",
    "New Zealand health supplements worth buying",
    "What is deer velvet good for?",
    "Best omega-3 supplement brands",
    "Marine collagen vs bovine collagen which is better?",
    "Best supplements for arthritis joint health",
    "New Zealand manuka honey supplements",
    "What supplements should I take for inflammation?",
    "Best green lipped mussel oil brand",
]

DB_PATH = "data/seo_intelligence.db"


def init_db():
    """Initialize the citation tracking database."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS ai_citations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            platform TEXT NOT NULL,
            prompt TEXT NOT NULL,
            prompt_hash TEXT NOT NULL,
            response_text TEXT,
            brand_mentioned BOOLEAN DEFAULT FALSE,
            brand_cited BOOLEAN DEFAULT FALSE,
            citation_url TEXT,
            competitor_mentions TEXT,
            sentiment TEXT,
            model_used TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS citation_trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            platform TEXT NOT NULL,
            total_prompts INTEGER,
            brand_mentions INTEGER,
            brand_citations INTEGER,
            mention_rate REAL,
            citation_rate REAL,
            top_competitors TEXT
        )
    """)
    conn.commit()
    return conn


def query_perplexity(prompt: str) -> dict:
    """
    Query Perplexity API and extract citations.
    Perplexity uses OpenAI-compatible API format.
    """
    client = OpenAI(
        api_key=PERPLEXITY_API_KEY,
        base_url="https://api.perplexity.ai"
    )

    response = client.chat.completions.create(
        model="sonar-pro",  # or "sonar" for cheaper option
        messages=[
            {
                "role": "system",
                "content": "You are a helpful health supplement advisor. "
                           "Provide specific brand recommendations with sources."
            },
            {"role": "user", "content": prompt}
        ],
    )

    result = {
        "platform": "perplexity",
        "model": "sonar-pro",
        "response": response.choices[0].message.content,
        "citations": [],
    }

    # Perplexity returns citations in the response metadata
    if hasattr(response, 'citations') and response.citations:
        result["citations"] = response.citations

    return result


def query_chatgpt(prompt: str) -> dict:
    """Query ChatGPT with web browsing context."""
    client = OpenAI(api_key=OPENAI_API_KEY)

    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": "You are a helpful health supplement advisor. "
                           "Recommend specific brands and products."
            },
            {"role": "user", "content": prompt}
        ],
    )

    return {
        "platform": "chatgpt",
        "model": "gpt-4o",
        "response": response.choices[0].message.content,
        "citations": [],  # ChatGPT doesn't return citations via API
    }


def query_claude(prompt: str) -> dict:
    """Query Claude API."""
    import anthropic
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[
            {"role": "user", "content": prompt}
        ],
    )

    return {
        "platform": "claude",
        "model": "claude-sonnet-4-20250514",
        "response": response.content[0].text,
        "citations": [],
    }


def check_brand_presence(response_text: str) -> dict:
    """
    Check if Deep Blue Health or competitors are mentioned.
    Returns brand mention status and competitor analysis.
    """
    text_lower = response_text.lower()

    brand_mentioned = any(kw in text_lower for kw in BRAND_KEYWORDS)

    competitors = {
        "Blackmores": "blackmores" in text_lower,
        "Swisse": "swisse" in text_lower,
        "Good Health": "good health" in text_lower,
        "GO Healthy": "go healthy" in text_lower,
        "Solgar": "solgar" in text_lower,
        "Nordic Naturals": "nordic naturals" in text_lower,
        "Ethical Nutrients": "ethical nutrients" in text_lower,
        "Nature's Way": "nature's way" in text_lower or "natures way" in text_lower,
        "Sports Research": "sports research" in text_lower,
        "Vital Proteins": "vital proteins" in text_lower,
        "Comvita": "comvita" in text_lower,
        "Healtheries": "healtheries" in text_lower,
        "Abeeco": "abeeco" in text_lower,
    }

    mentioned_competitors = [k for k, v in competitors.items() if v]

    # Simple sentiment analysis
    positive_signals = ["recommend", "best", "top", "premium", "high quality",
                       "trusted", "effective", "excellent"]
    negative_signals = ["avoid", "expensive", "overpriced", "not recommended",
                       "poor", "ineffective"]

    if brand_mentioned:
        pos_count = sum(1 for s in positive_signals if s in text_lower)
        neg_count = sum(1 for s in negative_signals if s in text_lower)
        sentiment = "positive" if pos_count > neg_count else (
            "negative" if neg_count > pos_count else "neutral"
        )
    else:
        sentiment = "not_mentioned"

    return {
        "brand_mentioned": brand_mentioned,
        "competitors": mentioned_competitors,
        "sentiment": sentiment,
    }


def run_citation_scan(conn: sqlite3.Connection):
    """Run a full citation scan across all platforms and prompts."""
    timestamp = datetime.now().isoformat()
    results = []

    for prompt in TRACKING_PROMPTS:
        prompt_hash = hashlib.md5(prompt.encode()).hexdigest()

        for query_fn in [query_perplexity, query_chatgpt, query_claude]:
            try:
                result = query_fn(prompt)
                presence = check_brand_presence(result["response"])

                record = {
                    "timestamp": timestamp,
                    "platform": result["platform"],
                    "prompt": prompt,
                    "prompt_hash": prompt_hash,
                    "response_text": result["response"],
                    "brand_mentioned": presence["brand_mentioned"],
                    "brand_cited": bool(
                        any("deepbluehealth" in c.lower()
                            for c in result.get("citations", [])
                            if isinstance(c, str))
                    ),
                    "citation_url": json.dumps(result.get("citations", [])),
                    "competitor_mentions": json.dumps(presence["competitors"]),
                    "sentiment": presence["sentiment"],
                    "model_used": result["model"],
                }

                # Insert into database
                conn.execute("""
                    INSERT INTO ai_citations
                    (timestamp, platform, prompt, prompt_hash, response_text,
                     brand_mentioned, brand_cited, citation_url,
                     competitor_mentions, sentiment, model_used)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, tuple(record.values()))

                results.append(record)

            except Exception as e:
                print(f"Error querying {query_fn.__name__}: {e}")

    conn.commit()
    return results


def generate_weekly_report(conn: sqlite3.Connection) -> str:
    """Generate a weekly AI citation report for the Beacon agent."""
    c = conn.cursor()

    # Get this week's data
    c.execute("""
        SELECT platform,
               COUNT(*) as total,
               SUM(brand_mentioned) as mentions,
               SUM(brand_cited) as citations
        FROM ai_citations
        WHERE timestamp > datetime('now', '-7 days')
        GROUP BY platform
    """)

    rows = c.fetchall()

    report = "## Beacon Weekly AI Citation Report\n\n"
    report += f"**Period:** Last 7 days | **Generated:** {datetime.now().strftime('%Y-%m-%d')}\n\n"

    for platform, total, mentions, citations in rows:
        mention_rate = (mentions / total * 100) if total > 0 else 0
        citation_rate = (citations / total * 100) if total > 0 else 0
        report += f"### {platform.title()}\n"
        report += f"- Prompts tested: {total}\n"
        report += f"- Brand mentioned: {mentions} ({mention_rate:.0f}%)\n"
        report += f"- Brand cited (with URL): {citations} ({citation_rate:.0f}%)\n\n"

    # Competitor analysis
    c.execute("""
        SELECT competitor_mentions FROM ai_citations
        WHERE timestamp > datetime('now', '-7 days')
        AND competitor_mentions != '[]'
    """)

    competitor_counts = {}
    for (mentions_json,) in c.fetchall():
        for comp in json.loads(mentions_json):
            competitor_counts[comp] = competitor_counts.get(comp, 0) + 1

    if competitor_counts:
        report += "### Top Competitor Mentions\n"
        for comp, count in sorted(
            competitor_counts.items(), key=lambda x: -x[1]
        )[:10]:
            report += f"- {comp}: {count} mentions\n"

    return report
```

### 1.5 Signals That Drive AI Citations (Priority Order)

1. **Brand search volume** -- Strongest predictor. DBH needs more people searching "Deep Blue Health" directly. This comes from brand marketing, social, PR.
2. **Branded web mentions** -- r=0.664 correlation with AI Overview visibility. Get mentioned on forums, reviews, articles, Reddit, Quora.
3. **Domain Authority** -- Backlinks still matter for AI citation selection.
4. **Topical coverage** -- Surround topics from every angle. Don't write one article about fish oil; write 20 covering every sub-question.
5. **Content freshness** -- Update key pages frequently. Add new data, examples, research citations.
6. **Structured data** -- JSON-LD schema on every page. FAQPage, DietarySupplement, Product, Article.
7. **Direct, verifiable facts** -- Include specific numbers, research citations, named studies.
8. **Self-contained answer units** -- 134-167 word passages that fully answer a specific question.

---

## 2. PROGRAMMATIC SEO AT SCALE

### 2.1 Strategy for Deep Blue Health

Generate hundreds of high-quality, unique pages targeting long-tail supplement queries. These are the pages that AI engines and Google will cite when someone asks about specific supplement + condition combinations.

### 2.2 Page Templates to Generate

#### Template 1: "[Supplement] for [Condition]"
Target pattern: `/{supplement}-for-{condition}`

Examples:
- `/green-lipped-mussel-oil-for-arthritis`
- `/fish-oil-for-heart-health`
- `/collagen-for-skin-aging`
- `/deer-velvet-for-energy`
- `/omega-3-for-inflammation`
- `/manuka-honey-for-immunity`

Data matrix (generates 100+ pages):

| Supplement | Conditions |
|-----------|-----------|
| Green Lipped Mussel Oil | arthritis, joint pain, inflammation, mobility, sports recovery, knee pain, back pain, hip pain |
| Fish Oil / Omega-3 | heart health, cholesterol, brain health, pregnancy, eye health, inflammation, blood pressure, triglycerides |
| Marine Collagen | skin aging, wrinkles, hair growth, nail strength, joint health, gut health, wound healing |
| Deer Velvet | energy, recovery, athletic performance, vitality, immune support, stamina |
| Manuka Honey | immunity, sore throat, wound care, digestion, skin health, antibacterial |
| Vitamin D | bone health, immune support, mood, winter health, calcium absorption |
| CoQ10 | heart health, energy, aging, exercise performance, blood pressure |

#### Template 2: "[Supplement] Benefits"
Target pattern: `/benefits-of-{supplement}`

Examples:
- `/benefits-of-green-lipped-mussel-oil`
- `/benefits-of-marine-collagen`
- `/benefits-of-deer-velvet`

#### Template 3: "[Product] vs [Competitor/Alternative]"
Target pattern: `/{product}-vs-{alternative}`

Examples:
- `/green-lipped-mussel-oil-vs-fish-oil`
- `/marine-collagen-vs-bovine-collagen`
- `/nz-fish-oil-vs-nordic-naturals`
- `/deer-velvet-vs-creatine-for-energy`
- `/green-lipped-mussel-vs-glucosamine`

#### Template 4: "[Ingredient] Research & Studies"
Target pattern: `/research/{ingredient}`

Examples:
- `/research/green-lipped-mussel`
- `/research/omega-3-fatty-acids`
- `/research/marine-collagen-peptides`

#### Template 5: "Best [Supplement] in [Country]"
Target pattern: `/best-{supplement}-{country}`

For international expansion:
- `/best-fish-oil-new-zealand`
- `/best-fish-oil-australia`
- `/best-green-lipped-mussel-supplement-usa`

### 2.3 Programmatic Generation Architecture

```python
"""
Programmatic SEO Page Generator for Deep Blue Health
Generates unique, high-quality pages from structured data + AI enhancement.
Publishes via Shopify GraphQL API.
"""

import os
import json
import time
from string import Template
from datetime import datetime
import anthropic
import shopify  # ShopifyAPI library (GraphQL)

# --- Data Matrix ---
SUPPLEMENTS = {
    "green-lipped-mussel-oil": {
        "name": "Green Lipped Mussel Oil",
        "scientific_name": "Perna canaliculus extract",
        "key_compounds": ["ETA (eicosatetraenoic acid)", "EPA", "DHA", "GAGs"],
        "primary_benefits": ["joint health", "anti-inflammatory", "mobility"],
        "nz_sourcing": "Marlborough Sounds, New Zealand",
        "dbh_product_url": "/products/green-lipped-mussel-oil",
        "dbh_product_name": "Deep Blue Health Green Lipped Mussel Oil",
        "research_citations": [
            {
                "study": "Lau et al. 2004, Inflammopharmacology",
                "finding": "GLM extract showed significant anti-inflammatory activity "
                          "comparable to NSAIDs without gastrointestinal side effects"
            },
            {
                "study": "Coulson et al. 2012, Complementary Therapies in Medicine",
                "finding": "GLM oil reduced joint pain by 36% and improved mobility "
                          "in 89% of participants over 8 weeks"
            },
        ],
        "conditions": [
            "arthritis", "joint-pain", "inflammation", "mobility",
            "sports-recovery", "knee-pain", "back-pain", "hip-pain",
            "rheumatoid-arthritis", "osteoarthritis",
        ],
    },
    # ... similar entries for each supplement
}


ARTICLE_TEMPLATE = """
# {title}

{intro_paragraph}

## What is {supplement_name}?

{supplement_description}

## How {supplement_name} Helps with {condition_name}

{mechanism_section}

## What the Research Says

{research_section}

## How to Choose a Quality {supplement_name} Supplement

{buying_guide}

## Recommended Dosage for {condition_name}

{dosage_section}

## Frequently Asked Questions

{faq_section}

## Summary

{summary}
"""


def generate_unique_content(
    supplement: dict,
    condition: str,
    template: str,
) -> dict:
    """
    Use Claude to generate unique, medically-accurate content.
    Each page gets genuinely unique content -- not just word swaps.
    """
    client = anthropic.Anthropic()

    prompt = f"""Write a comprehensive, medically-accurate health article about
    using {supplement['name']} ({supplement['scientific_name']}) for {condition}.

    Requirements:
    - Include specific research citations: {json.dumps(supplement['research_citations'])}
    - Mention NZ sourcing: {supplement['nz_sourcing']}
    - Include the brand product: {supplement['dbh_product_name']}
    - Write in a trustworthy, evidence-based tone
    - Include an FAQ section with 5 questions people actually ask
    - Each section should be 134-167 words (optimal for AI citation)
    - Include specific numbers, dosages, and timelines
    - Do NOT make medical claims -- use "may help", "research suggests"

    Return as JSON with keys: title, intro_paragraph, supplement_description,
    mechanism_section, research_section, buying_guide, dosage_section,
    faq_section, summary, meta_title, meta_description, schema_faq
    """

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    content = json.loads(response.content[0].text)
    return content


def generate_schema_markup(supplement: dict, condition: str, content: dict) -> str:
    """Generate JSON-LD schema for the programmatic page."""
    schema = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Article",
                "headline": content["meta_title"],
                "description": content["meta_description"],
                "author": {
                    "@type": "Organization",
                    "name": "Deep Blue Health",
                    "url": "https://deepbluehealth.co.nz"
                },
                "publisher": {
                    "@type": "Organization",
                    "name": "Deep Blue Health",
                },
                "datePublished": datetime.now().isoformat(),
                "dateModified": datetime.now().isoformat(),
                "about": {
                    "@type": "DietarySupplement",
                    "name": supplement["name"],
                    "nonProprietaryName": supplement["scientific_name"],
                    "activeIngredient": ", ".join(supplement["key_compounds"]),
                },
            },
            {
                "@type": "FAQPage",
                "mainEntity": content.get("schema_faq", []),
            },
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": 1,
                        "name": "Home",
                        "item": "https://deepbluehealth.co.nz"
                    },
                    {
                        "@type": "ListItem",
                        "position": 2,
                        "name": "Health Guide",
                        "item": "https://deepbluehealth.co.nz/blogs/health"
                    },
                    {
                        "@type": "ListItem",
                        "position": 3,
                        "name": content["meta_title"],
                    },
                ],
            },
        ],
    }
    return json.dumps(schema, indent=2)


def publish_to_shopify(title: str, body_html: str, tags: list, handle: str):
    """
    Publish article to Shopify via GraphQL API.
    NOTE: Shopify deprecated REST Admin API (Oct 2024).
    All new apps must use GraphQL as of April 2025.
    """
    # Using shopify_python_api library with GraphQL
    query = """
    mutation articleCreate($article: ArticleCreateInput!) {
        articleCreate(article: $article) {
            article {
                id
                handle
                title
            }
            userErrors {
                field
                message
            }
        }
    }
    """

    variables = {
        "article": {
            "blogId": "gid://shopify/Blog/HEALTH_BLOG_ID",
            "title": title,
            "handle": handle,
            "body": body_html,
            "tags": tags,
            "isPublished": True,
            "publishDate": datetime.now().isoformat(),
        }
    }

    # Execute via Shopify GraphQL client
    result = shopify.GraphQL().execute(query, variables=variables)
    return json.loads(result)


def run_programmatic_generation():
    """
    Generate and publish all programmatic pages.
    Rate limited to avoid API throttling.
    """
    for slug, supplement in SUPPLEMENTS.items():
        for condition in supplement["conditions"]:
            handle = f"{slug}-for-{condition}"

            # Check if already published
            # (query Shopify or local tracking DB)

            print(f"Generating: {handle}")

            # Generate unique content
            content = generate_unique_content(supplement, condition, ARTICLE_TEMPLATE)

            # Generate schema
            schema = generate_schema_markup(supplement, condition, content)

            # Build HTML with schema
            body_html = format_article_html(content, schema)

            # Publish
            tags = [
                supplement["name"],
                condition.replace("-", " "),
                "programmatic",
                "health-guide",
            ]
            result = publish_to_shopify(
                title=content["meta_title"],
                body_html=body_html,
                tags=tags,
                handle=handle,
            )

            print(f"Published: {result}")

            # Rate limit: 1 article per 30 seconds
            time.sleep(30)
```

### 2.4 Quality Guardrails

To avoid Google's "boilerplate content" detection:

1. **Each page gets unique AI-generated content** -- not template fill-in
2. **Include unique data points** per page: specific research citations, dosage info, mechanism descriptions
3. **Vary the structure** -- not every page uses identical H2 order
4. **Add unique FAQ questions** per condition (sourced from real search queries)
5. **Include internal links** to related pages within the cluster
6. **Human review queue** -- flag pages for Tom/Tony review before bulk publishing
7. **Test with Google's "remove the keyword" test** -- if you remove the condition name, is the rest still useful?

---

## 3. TECHNICAL SEO AUTOMATION

### 3.1 Core Monitoring Stack

```
+---------------------------+
|    Beacon SEO Agent       |
|    (Python on Railway)    |
+---------------------------+
       |         |        |
       v         v        v
  [GSC API]  [DataForSEO] [Screaming Frog CLI]
       |         |        |
       v         v        v
  [Rankings]  [SERPs]   [Crawl Health]
       |         |        |
       +----+----+--------+
            |
            v
    [data/seo_intelligence.db]
            |
            v
    [Weekly Report -> Oracle -> Telegram]
```

### 3.2 Google Search Console API Integration

```python
"""
Google Search Console API integration for Beacon agent.
Pulls daily ranking data, click data, and crawl errors.
"""

from google.oauth2 import service_account
from googleapiclient.discovery import build
import pandas as pd
from datetime import datetime, timedelta

GSC_SCOPES = ['https://www.googleapis.com/auth/webmasters.readonly']
GSC_PROPERTY = 'sc-domain:deepbluehealth.co.nz'

def get_gsc_service():
    """Authenticate with Google Search Console API."""
    credentials = service_account.Credentials.from_service_account_file(
        'config/gsc-service-account.json',
        scopes=GSC_SCOPES
    )
    return build('searchconsole', 'v1', credentials=credentials)


def fetch_daily_rankings(service, days_back: int = 7) -> pd.DataFrame:
    """
    Fetch search performance data from GSC.
    Returns clicks, impressions, CTR, position by query and page.
    """
    end_date = datetime.now() - timedelta(days=3)  # GSC has 3-day delay
    start_date = end_date - timedelta(days=days_back)

    request = {
        'startDate': start_date.strftime('%Y-%m-%d'),
        'endDate': end_date.strftime('%Y-%m-%d'),
        'dimensions': ['query', 'page', 'date'],
        'rowLimit': 25000,  # Max per request
        'dimensionFilterGroups': [],
    }

    response = service.searchanalytics().query(
        siteUrl=GSC_PROPERTY,
        body=request,
    ).execute()

    rows = response.get('rows', [])

    data = []
    for row in rows:
        data.append({
            'query': row['keys'][0],
            'page': row['keys'][1],
            'date': row['keys'][2],
            'clicks': row['clicks'],
            'impressions': row['impressions'],
            'ctr': row['ctr'],
            'position': row['position'],
        })

    return pd.DataFrame(data)


def detect_ranking_changes(df: pd.DataFrame, threshold: float = 5.0) -> list:
    """
    Detect significant ranking changes (up or down).
    Returns alerts for queries that moved more than `threshold` positions.
    """
    alerts = []

    # Group by query, compare first day vs last day
    for query, group in df.groupby('query'):
        group = group.sort_values('date')
        if len(group) < 2:
            continue

        first_pos = group.iloc[0]['position']
        last_pos = group.iloc[-1]['position']
        change = first_pos - last_pos  # Positive = improved

        if abs(change) >= threshold:
            direction = "IMPROVED" if change > 0 else "DROPPED"
            alerts.append({
                'query': query,
                'old_position': round(first_pos, 1),
                'new_position': round(last_pos, 1),
                'change': round(change, 1),
                'direction': direction,
                'page': group.iloc[-1]['page'],
                'impressions': group['impressions'].sum(),
            })

    return sorted(alerts, key=lambda x: abs(x['change']), reverse=True)


def fetch_crawl_errors(service) -> list:
    """Fetch crawl errors and URL inspection data."""
    # URL Inspection API
    errors = []
    # Note: URL Inspection API requires individual URL checks
    # For bulk monitoring, use the GSC web interface export
    # or combine with Screaming Frog crawl data
    return errors


def identify_keyword_opportunities(df: pd.DataFrame) -> list:
    """
    Find 'striking distance' keywords (positions 5-20)
    with high impressions but low CTR -- these are quick wins.
    """
    opportunities = []

    agg = df.groupby('query').agg({
        'impressions': 'sum',
        'clicks': 'sum',
        'position': 'mean',
        'page': 'first',
    }).reset_index()

    # Striking distance: position 5-20, high impressions
    striking = agg[
        (agg['position'] >= 5) &
        (agg['position'] <= 20) &
        (agg['impressions'] >= 50)
    ].sort_values('impressions', ascending=False)

    for _, row in striking.iterrows():
        opportunities.append({
            'query': row['query'],
            'position': round(row['position'], 1),
            'impressions': row['impressions'],
            'clicks': row['clicks'],
            'page': row['page'],
            'potential': "HIGH" if row['position'] <= 10 else "MEDIUM",
        })

    return opportunities[:50]  # Top 50 opportunities
```

### 3.3 DataForSEO API for SERP Monitoring

```python
"""
DataForSEO integration for SERP tracking and competitor analysis.
Pricing: ~$0.60 per 1,000 SERPs -- very cost-effective.
"""

import requests
import base64
import json

DATAFORSEO_LOGIN = os.environ.get("DATAFORSEO_LOGIN")
DATAFORSEO_PASSWORD = os.environ.get("DATAFORSEO_PASSWORD")

def get_dataforseo_auth():
    """Generate auth header for DataForSEO API."""
    cred = base64.b64encode(
        f"{DATAFORSEO_LOGIN}:{DATAFORSEO_PASSWORD}".encode()
    ).decode()
    return {"Authorization": f"Basic {cred}"}


def track_serp_rankings(keywords: list, locations: list = None) -> list:
    """
    Track SERP rankings for target keywords across multiple locations.
    Uses DataForSEO SERP API v3.
    """
    if locations is None:
        locations = [
            {"name": "New Zealand", "code": 2554},
            {"name": "Australia", "code": 2036},
            {"name": "United States", "code": 2840},
            {"name": "United Kingdom", "code": 2826},
        ]

    results = []

    for location in locations:
        payload = []
        for keyword in keywords:
            payload.append({
                "keyword": keyword,
                "location_code": location["code"],
                "language_code": "en",
                "device": "desktop",
                "os": "windows",
                "depth": 100,  # Check top 100 results
            })

        response = requests.post(
            "https://api.dataforseo.com/v3/serp/google/organic/task_post",
            headers=get_dataforseo_auth(),
            json=payload,
        )

        tasks = response.json()

        # Retrieve results (poll or use callback)
        for task in tasks.get("tasks", []):
            task_id = task.get("id")
            # Poll for results
            result_response = requests.get(
                f"https://api.dataforseo.com/v3/serp/google/organic/task_get/advanced/{task_id}",
                headers=get_dataforseo_auth(),
            )
            results.append({
                "location": location["name"],
                "data": result_response.json(),
            })

    return results


def check_ai_overview_presence(keyword: str) -> dict:
    """
    Check if a keyword triggers an AI Overview in Google
    and whether DBH is cited in it.
    Uses DataForSEO's AI Overview detection.
    """
    payload = [{
        "keyword": keyword,
        "location_code": 2554,  # NZ
        "language_code": "en",
        "device": "desktop",
        "depth": 10,
    }]

    response = requests.post(
        "https://api.dataforseo.com/v3/serp/google/organic/task_post",
        headers=get_dataforseo_auth(),
        json=payload,
    )

    # DataForSEO returns AI Overview data in SERP results
    # Check for "ai_overview" item type in results
    result = response.json()

    ai_overview = None
    dbh_cited = False

    for item in result.get("tasks", [{}])[0].get("result", [{}])[0].get("items", []):
        if item.get("type") == "ai_overview":
            ai_overview = item
            # Check if DBH is in the citations
            for reference in item.get("references", []):
                if "deepbluehealth" in reference.get("url", "").lower():
                    dbh_cited = True
                    break

    return {
        "keyword": keyword,
        "has_ai_overview": ai_overview is not None,
        "dbh_cited": dbh_cited,
        "ai_overview_data": ai_overview,
    }


# --- Target Keywords for DBH ---
DBH_TARGET_KEYWORDS = [
    # Brand terms
    "deep blue health", "deep blue health nz",
    "deep blue health supplements", "deep blue health reviews",

    # Product terms (NZ)
    "green lipped mussel oil nz", "nz fish oil supplement",
    "marine collagen nz", "deer velvet nz",
    "manuka honey supplements nz",

    # Generic supplement terms
    "best joint supplement nz", "best fish oil nz",
    "best collagen supplement nz",
    "omega 3 supplement new zealand",
    "anti inflammatory supplements nz",

    # Condition terms
    "supplements for arthritis nz",
    "supplements for joint pain",
    "best supplement for inflammation",
    "collagen for skin nz",

    # Comparison terms
    "green lipped mussel vs fish oil",
    "marine collagen vs bovine collagen",

    # International
    "best nz supplements australia",
    "new zealand supplements usa",
    "green lipped mussel supplement best",
]
```

### 3.4 Automated Site Health Monitoring

```python
"""
Automated site health monitoring using Python.
Checks: page speed, broken links, schema validation, indexation.
"""

import requests
from bs4 import BeautifulSoup
import json
from urllib.parse import urljoin
import xml.etree.ElementTree as ET


def check_page_speed(url: str) -> dict:
    """
    Check page speed using Google PageSpeed Insights API (free).
    """
    api_key = os.environ.get("GOOGLE_PAGESPEED_API_KEY")
    endpoint = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

    params = {
        "url": url,
        "key": api_key,
        "category": ["performance", "seo"],
        "strategy": "mobile",
    }

    response = requests.get(endpoint, params=params)
    data = response.json()

    return {
        "url": url,
        "performance_score": data["lighthouseResult"]["categories"]["performance"]["score"] * 100,
        "seo_score": data["lighthouseResult"]["categories"]["seo"]["score"] * 100,
        "fcp": data["lighthouseResult"]["audits"]["first-contentful-paint"]["numericValue"],
        "lcp": data["lighthouseResult"]["audits"]["largest-contentful-paint"]["numericValue"],
        "ttfb": data["lighthouseResult"]["audits"]["server-response-time"]["numericValue"],
        "cls": data["lighthouseResult"]["audits"]["cumulative-layout-shift"]["numericValue"],
    }


def validate_schema_markup(url: str) -> dict:
    """
    Validate structured data on a page.
    Uses Google's Rich Results Test API.
    """
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Find JSON-LD scripts
    schemas = []
    for script in soup.find_all('script', type='application/ld+json'):
        try:
            schema = json.loads(script.string)
            schemas.append(schema)
        except json.JSONDecodeError:
            schemas.append({"error": "Invalid JSON-LD"})

    # Check for required schema types
    required_types = ["Product", "FAQPage", "BreadcrumbList", "Organization"]
    found_types = set()

    for schema in schemas:
        if isinstance(schema, dict):
            schema_type = schema.get("@type", "")
            if isinstance(schema_type, list):
                found_types.update(schema_type)
            else:
                found_types.add(schema_type)

            # Check @graph
            for item in schema.get("@graph", []):
                item_type = item.get("@type", "")
                if isinstance(item_type, list):
                    found_types.update(item_type)
                else:
                    found_types.add(item_type)

    missing_types = set(required_types) - found_types

    return {
        "url": url,
        "schemas_found": len(schemas),
        "types_found": list(found_types),
        "missing_types": list(missing_types),
        "valid": len(missing_types) == 0,
    }


def crawl_sitemap(sitemap_url: str) -> list:
    """Parse XML sitemap and return all URLs."""
    response = requests.get(sitemap_url)
    root = ET.fromstring(response.content)

    # Handle namespace
    ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = []

    for url_elem in root.findall('.//ns:url', ns):
        loc = url_elem.find('ns:loc', ns)
        lastmod = url_elem.find('ns:lastmod', ns)
        if loc is not None:
            urls.append({
                'url': loc.text,
                'lastmod': lastmod.text if lastmod is not None else None,
            })

    return urls


def run_site_health_audit(base_url: str = "https://deepbluehealth.co.nz"):
    """Run a comprehensive site health audit."""

    # 1. Crawl sitemap
    sitemap_urls = crawl_sitemap(f"{base_url}/sitemap.xml")
    print(f"Found {len(sitemap_urls)} URLs in sitemap")

    # 2. Check a sample of pages for speed and schema
    import random
    sample = random.sample(sitemap_urls, min(20, len(sitemap_urls)))

    issues = []

    for url_info in sample:
        url = url_info['url']

        # Page speed check
        speed = check_page_speed(url)
        if speed['performance_score'] < 50:
            issues.append({
                "type": "SPEED",
                "severity": "HIGH",
                "url": url,
                "detail": f"Performance score: {speed['performance_score']}"
            })

        if speed.get('ttfb', 0) > 200:
            issues.append({
                "type": "TTFB",
                "severity": "HIGH",  # Critical for AI crawlers
                "url": url,
                "detail": f"TTFB: {speed['ttfb']}ms (AI crawlers need <200ms)"
            })

        # Schema validation
        schema = validate_schema_markup(url)
        if not schema['valid']:
            issues.append({
                "type": "SCHEMA",
                "severity": "MEDIUM",
                "url": url,
                "detail": f"Missing schema types: {schema['missing_types']}"
            })

        # Check for broken links
        response = requests.get(url, timeout=10)
        if response.status_code != 200:
            issues.append({
                "type": "HTTP_ERROR",
                "severity": "HIGH",
                "url": url,
                "detail": f"Status code: {response.status_code}"
            })

    return {
        "total_urls": len(sitemap_urls),
        "sample_checked": len(sample),
        "issues": issues,
        "timestamp": datetime.now().isoformat(),
    }
```

### 3.5 Recommended Tool Stack

| Tool | Purpose | Cost | API Available |
|------|---------|------|--------------|
| **Google Search Console** | Rankings, clicks, crawl data | Free | Yes (Python client) |
| **DataForSEO** | SERP tracking, competitor analysis | $0.60/1K SERPs | Yes (REST API) |
| **Google PageSpeed Insights** | Page speed monitoring | Free | Yes |
| **Screaming Frog** | Deep crawl audits | $259/yr | CLI automation |
| **Ahrefs** | Backlinks, keyword research, content gaps | $129-$449/mo | Yes (API v3) |
| **Schema.org Validator** | Structured data validation | Free | Custom via parsing |

---

## 4. CONTENT INTELLIGENCE

### 4.1 Keyword Gap Analysis Pipeline

```python
"""
Content Intelligence Pipeline for Beacon agent.
Identifies content gaps, clusters keywords, generates briefs.
"""

import anthropic
from collections import defaultdict


def analyze_content_gaps(
    gsc_data: pd.DataFrame,
    competitor_keywords: list,
) -> list:
    """
    Identify content gaps by comparing GSC keywords vs competitor keywords.
    Uses Ahrefs API for competitor keyword data.
    """
    # Get our ranking keywords
    our_keywords = set(gsc_data['query'].unique())

    # Get competitor keywords from Ahrefs
    # (via API or pre-exported data)
    competitor_set = set(competitor_keywords)

    # Gaps = keywords competitors rank for but we don't
    gaps = competitor_set - our_keywords

    # Score gaps by search volume and relevance
    scored_gaps = []
    for keyword in gaps:
        scored_gaps.append({
            "keyword": keyword,
            "relevance": score_relevance(keyword),
            "estimated_volume": estimate_volume(keyword),
        })

    return sorted(scored_gaps, key=lambda x: -x["relevance"])


def cluster_keywords_with_ai(keywords: list) -> dict:
    """
    Use Claude to semantically cluster keywords into topic groups.
    Each cluster becomes a content brief.
    """
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""Cluster these health supplement keywords into
            topical groups. Each group should represent one article or page topic.

            Keywords: {json.dumps(keywords[:200])}

            Return as JSON:
            {{
                "clusters": [
                    {{
                        "name": "cluster topic name",
                        "primary_keyword": "main target keyword",
                        "secondary_keywords": ["kw1", "kw2"],
                        "search_intent": "informational|commercial|transactional",
                        "suggested_page_type": "blog_post|product_page|guide|comparison",
                        "priority": "high|medium|low"
                    }}
                ]
            }}
            """
        }],
    )

    return json.loads(response.content[0].text)


def generate_content_brief(cluster: dict) -> dict:
    """
    Generate a comprehensive content brief from a keyword cluster.
    Ready for content generation or human writer.
    """
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""Create a detailed content brief for a health supplement
            article targeting this keyword cluster:

            Primary keyword: {cluster['primary_keyword']}
            Secondary keywords: {json.dumps(cluster['secondary_keywords'])}
            Intent: {cluster['search_intent']}
            Page type: {cluster['suggested_page_type']}

            The brief should include:
            1. Suggested title (with primary keyword)
            2. Meta description (155 chars, with keyword)
            3. Target word count
            4. H2 outline (6-8 sections)
            5. Key questions to answer (for FAQ schema)
            6. Required schema markup types
            7. Internal linking targets (to DBH products/pages)
            8. Unique angle / information gain opportunity
            9. Research/studies to reference
            10. Competitor content to beat (if applicable)

            This is for Deep Blue Health, a NZ supplement brand.
            Focus on NZ-sourced marine supplements.

            Return as structured JSON.
            """
        }],
    )

    return json.loads(response.content[0].text)


def auto_optimize_existing_content(url: str, target_keywords: list) -> dict:
    """
    Analyze an existing page and generate optimization recommendations.
    Uses the page content + target keywords to suggest improvements.
    """
    # Fetch current page
    response = requests.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')

    # Extract current content
    title = soup.find('title').text if soup.find('title') else ""
    h1 = soup.find('h1').text if soup.find('h1') else ""
    meta_desc = ""
    meta_tag = soup.find('meta', attrs={'name': 'description'})
    if meta_tag:
        meta_desc = meta_tag.get('content', '')

    body_text = soup.get_text()
    word_count = len(body_text.split())

    # Use Claude to analyze and suggest
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[{
            "role": "user",
            "content": f"""Analyze this page for SEO and AEO optimization.

            URL: {url}
            Current Title: {title}
            Current H1: {h1}
            Current Meta Description: {meta_desc}
            Word Count: {word_count}
            Target Keywords: {json.dumps(target_keywords)}

            Page content (first 3000 chars): {body_text[:3000]}

            Provide specific recommendations:
            1. Title tag optimization
            2. Meta description optimization
            3. H1 improvements
            4. Content gaps (what's missing vs top-ranking content)
            5. FAQ questions to add (for AI citation optimization)
            6. Schema markup to add/fix
            7. Internal linking opportunities
            8. AEO-specific improvements (answer units, structured facts)

            Return as JSON with "recommendations" array, each with
            "type", "current", "suggested", "priority", "impact".
            """
        }],
    )

    return json.loads(response.content[0].text)
```

### 4.2 Topical Authority Map for DBH

Build comprehensive topic clusters around each core supplement category:

```
DEEP BLUE HEALTH TOPICAL MAP
============================

PILLAR 1: Joint Health
├── Green Lipped Mussel Oil (pillar page)
│   ├── GLM oil benefits
│   ├── GLM oil for arthritis
│   ├── GLM oil for knee pain
│   ├── GLM oil for back pain
│   ├── GLM oil dosage guide
│   ├── GLM oil vs glucosamine
│   ├── GLM oil vs fish oil for joints
│   ├── GLM oil research & studies
│   ├── How GLM oil is extracted (NZ sourcing story)
│   └── GLM oil side effects and safety
├── Joint Health Guide (supporting pillar)
│   ├── Best supplements for joint health NZ
│   ├── Natural anti-inflammatory supplements
│   ├── Supplements for osteoarthritis
│   ├── Supplements for rheumatoid arthritis
│   ├── Exercise and supplements for joints
│   └── Joint health supplements for athletes

PILLAR 2: Fish Oil & Omega-3
├── Deep Sea Fish Oil (pillar page)
│   ├── Fish oil benefits complete guide
│   ├── Fish oil for heart health
│   ├── Fish oil for brain health
│   ├── Fish oil for pregnancy
│   ├── Fish oil dosage guide
│   ├── NZ fish oil vs international brands
│   ├── Fish oil quality testing & purity
│   ├── Omega-3 EPA vs DHA explained
│   └── Fish oil for children
├── Omega-3 Guide (supporting pillar)
│   ├── Best omega-3 supplements NZ
│   ├── Omega-3 for inflammation
│   ├── How to choose a fish oil supplement
│   └── Omega-3 food sources vs supplements

PILLAR 3: Collagen
├── Marine Collagen (pillar page)
│   ├── Marine collagen benefits
│   ├── Marine collagen for skin
│   ├── Marine collagen for joints
│   ├── Marine collagen for gut health
│   ├── Marine vs bovine collagen
│   ├── Collagen peptides explained
│   ├── Best collagen supplement NZ
│   ├── How marine collagen is sourced
│   └── Collagen for anti-aging

PILLAR 4: NZ Natural Health
├── Deer Velvet (pillar page)
│   ├── Deer velvet benefits
│   ├── Deer velvet for energy
│   ├── Deer velvet for athletes
│   └── Deer velvet research
├── Manuka Honey (pillar page)
│   ├── Manuka honey health benefits
│   ├── Manuka honey for immunity
│   ├── UMF rating explained
│   └── Manuka honey supplements vs raw honey
├── NZ Supplements Guide
│   ├── Why NZ supplements are different
│   ├── NZ supplement regulations (NZFSA/Medsafe)
│   ├── Clean sourcing from NZ waters
│   └── NZ health supplement brands comparison
```

Each cluster should have **5-10 supporting articles** linking to the pillar. The pillar links to all supporting articles. Cross-link between related clusters (e.g., joint health links to omega-3 articles).

---

## 5. LINK BUILDING AUTOMATION

### 5.1 Platform Strategy (Post-HARO Era)

As of 2026, the link building landscape has shifted:

| Platform | Status | Best For | Cost |
|----------|--------|----------|------|
| **HARO (via Featured.com)** | Relaunched April 2025 | High-authority media links | Free (basic) |
| **Qwoted** | Active, premium | Elite publications, vetted contributors | Paid subscription |
| **Featured.com** | Active (acquired HARO) | Expert quotes in articles | Free-Paid tiers |
| **Connectively** | Shut down Dec 2024 | N/A | N/A |
| **SourceBottle** | Active | AUNZ-specific media opportunities | Free-Paid |
| **PressHunt** | Active | Journalist database, cold outreach | Paid |
| **Reporter Outreach** | Active | Done-for-you digital PR | Agency model |

### 5.2 Automated HARO/Featured Monitoring

```python
"""
HARO/Featured.com & Journalist Opportunity Monitor
Scans for relevant health/supplement opportunities and alerts via Telegram.
"""

import imaplib
import email
import re
from datetime import datetime
import anthropic


# HARO sends 3 daily digests via email
HARO_CATEGORIES = [
    "health", "fitness", "nutrition", "supplements",
    "wellness", "natural health", "alternative medicine",
    "beauty", "skincare", "anti-aging",
    "food and beverage", "lifestyle",
]

RELEVANCE_KEYWORDS = [
    "supplement", "vitamin", "mineral", "fish oil", "omega",
    "collagen", "joint", "health", "wellness", "nutrition",
    "natural", "herbal", "anti-inflammatory", "immunity",
    "new zealand", "nz", "australia", "beauty", "skincare",
    "aging", "antioxidant", "marine", "sea", "ocean",
]


def scan_haro_emails(
    imap_server: str,
    email_address: str,
    password: str,
) -> list:
    """
    Scan HARO digest emails for relevant opportunities.
    HARO sends 3x daily digests.
    """
    mail = imaplib.IMAP4_SSL(imap_server)
    mail.login(email_address, password)
    mail.select("inbox")

    # Search for recent HARO emails
    _, messages = mail.search(
        None,
        '(FROM "haro@helpareporter.com" SINCE "' +
        datetime.now().strftime("%d-%b-%Y") + '")'
    )

    opportunities = []

    for msg_num in messages[0].split():
        _, msg_data = mail.fetch(msg_num, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode()
                    break
        else:
            body = msg.get_payload(decode=True).decode()

        # Parse individual queries from digest
        queries = parse_haro_digest(body)

        for query in queries:
            relevance = score_opportunity(query)
            if relevance > 0.5:  # Only high-relevance opportunities
                opportunities.append({
                    "query": query,
                    "relevance": relevance,
                    "received": datetime.now().isoformat(),
                })

    mail.logout()
    return opportunities


def score_opportunity(query_text: str) -> float:
    """Score a HARO query for relevance to DBH."""
    text_lower = query_text.lower()
    score = 0.0

    for keyword in RELEVANCE_KEYWORDS:
        if keyword in text_lower:
            score += 0.15

    # Bonus for health/supplement specific
    if any(w in text_lower for w in ["supplement", "vitamin", "health product"]):
        score += 0.3

    # Bonus for NZ/AU mentions
    if any(w in text_lower for w in ["new zealand", "australia", "nz", "au"]):
        score += 0.2

    return min(score, 1.0)


def generate_haro_pitch(query: dict, brand_context: str) -> str:
    """
    Auto-generate a HARO pitch response using Claude.
    Tom reviews before sending -- never fully auto-send pitches.
    """
    client = anthropic.Anthropic()

    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": f"""Write a concise HARO pitch response for this journalist query.
            I am Tom Hall-Taylor, founder of Deep Blue Health, a NZ supplement brand.

            Query: {query['query']}

            Brand context: {brand_context}

            Rules:
            - Keep under 200 words
            - Lead with expertise/credentials
            - Provide a specific, useful answer
            - Mention Deep Blue Health naturally (not salesy)
            - Include a compelling quote they can use directly
            - End with availability for follow-up
            """
        }],
    )

    return response.content[0].text


def alert_opportunity(opportunity: dict, pitch: str, telegram_chat_id: str):
    """Send HARO opportunity + draft pitch to Telegram."""
    message = (
        f"**HARO OPPORTUNITY** (Relevance: {opportunity['relevance']:.0%})\n\n"
        f"**Query:**\n{opportunity['query'][:500]}\n\n"
        f"**Draft Pitch:**\n{pitch}\n\n"
        f"Reply 'SEND' to submit or edit the pitch."
    )
    # Send via Telegram handler
    send_telegram_message(telegram_chat_id, message)
```

### 5.3 Digital PR & Link Earning Strategy

Beyond HARO, DBH should pursue:

1. **NZ Health Studies & Data** -- Publish original research/surveys ("NZ Supplement Usage Report 2026") that journalists and bloggers will cite and link to
2. **Expert Commentary** -- Position Tom/Tony as quoted experts on NZ health supplement topics
3. **Guest Articles** -- Write for NZ health publications (Stuff Health, NZ Herald Lifestyle, Healthline NZ)
4. **Resource Pages** -- Create link-worthy resources ("Complete Guide to NZ Marine Supplements", "NZ Supplement Quality Standards Explained")
5. **Broken Link Building** -- Find broken links on health sites pointing to defunct supplement brands, offer DBH content as replacement
6. **AUNZ Health Blogger Outreach** -- Build relationships with NZ/AU health and wellness bloggers for reviews and mentions

---

## 6. LOCAL/INTERNATIONAL SEO

### 6.1 Multi-Market Expansion Strategy

DBH currently sells from NZ. The expansion path:

```
Market Priority:
1. NZ (home market, strengthen)
2. AU (closest, similar regulations, Shopify Markets)
3. US (largest market, highest competition)
4. UK (growing NZ supplement interest)
```

### 6.2 Domain Structure Decision

**Recommended: Subfolder Approach** (for Shopify)

```
deepbluehealth.co.nz/          → NZ (primary)
deepbluehealth.co.nz/en-au/    → Australia
deepbluehealth.co.nz/en-us/    → United States
deepbluehealth.co.nz/en-gb/    → United Kingdom
```

Why subfolders over ccTLDs:
- **Consolidates domain authority** -- all markets benefit from one strong domain
- **Shopify natively supports** subfolder internationalization
- **Easier to manage** for a solo operator
- **Hreflang is automatic** in Shopify when using international domains/subfolders
- ccTLDs (deepbluehealth.com.au, deepbluehealth.com) would split authority and require separate SEO work

### 6.3 Hreflang Implementation (Shopify Auto-handles)

Shopify automatically generates hreflang tags when you set up international subfolders. Verify they look like:

```html
<link rel="alternate" hreflang="en-nz"
      href="https://deepbluehealth.co.nz/products/green-lipped-mussel-oil" />
<link rel="alternate" hreflang="en-au"
      href="https://deepbluehealth.co.nz/en-au/products/green-lipped-mussel-oil" />
<link rel="alternate" hreflang="en-us"
      href="https://deepbluehealth.co.nz/en-us/products/green-lipped-mussel-oil" />
<link rel="alternate" hreflang="en-gb"
      href="https://deepbluehealth.co.nz/en-gb/products/green-lipped-mussel-oil" />
<link rel="alternate" hreflang="x-default"
      href="https://deepbluehealth.co.nz/" />
```

Key implementation rules:
- Every variant must **self-reference** (include itself in hreflang set)
- Each page must **canonicalize to itself**, not a different locale
- 75% of hreflang implementations on the web have errors -- getting this right is a competitive advantage

### 6.4 Market-Specific Content Strategy

Each market needs localized content, not just translated:

**NZ (home market):**
- "Best supplements in New Zealand"
- Reference NZ-specific regulations (NZFSA, Medsafe)
- NZ pricing in NZD
- Local sourcing story (Marlborough Sounds, etc.)

**Australia:**
- "Best NZ supplements available in Australia"
- Reference TGA compliance
- AU pricing in AUD
- Shipping from NZ to AU
- Mention AUNZ similarity in health standards

**USA:**
- "New Zealand supplements USA"
- Reference FDA disclaimer requirements
- US pricing in USD
- Free international shipping thresholds
- Emphasize "imported from NZ" as premium positioning

**UK:**
- "New Zealand supplements UK"
- Reference MHRA standards
- UK pricing in GBP
- NZ-UK health product regulations

### 6.5 Local SEO for NZ

Even as a DTC brand, local SEO signals help:

1. **Google Business Profile** -- Claim and optimize for "Deep Blue Health Auckland"
2. **NZ business directories** -- Yellow.co.nz, Finda.co.nz, NZS.com
3. **NAP consistency** -- Same name, address, phone across all listings
4. **NZ-specific schema** -- LocalBusiness schema with NZ address

```json
{
  "@context": "https://schema.org",
  "@type": ["Organization", "LocalBusiness"],
  "name": "Deep Blue Health",
  "url": "https://deepbluehealth.co.nz",
  "logo": "https://deepbluehealth.co.nz/logo.png",
  "address": {
    "@type": "PostalAddress",
    "streetAddress": "...",
    "addressLocality": "Auckland",
    "addressRegion": "Auckland",
    "postalCode": "...",
    "addressCountry": "NZ"
  },
  "sameAs": [
    "https://www.facebook.com/deepbluehealth",
    "https://www.instagram.com/deepbluehealthnz",
    "https://www.tiktok.com/@deepbluehealthnz"
  ],
  "contactPoint": {
    "@type": "ContactPoint",
    "contactType": "customer service",
    "availableLanguage": "English"
  }
}
```

---

## 7. BEACON AGENT ARCHITECTURE

### 7.1 Agent Design

Beacon is a new agent for Tom's Command Center that handles all SEO and AEO intelligence autonomously.

```
agents/seo-beacon/
├── AGENT.md                    ← Identity, instructions, AEO expertise
├── skills/
│   ├── aeo-optimization.md     ← AEO/GEO playbook
│   ├── programmatic-seo.md     ← Page generation templates
│   ├── technical-seo.md        ← Site health monitoring
│   └── content-intelligence.md ← Keyword clustering, briefs
├── playbooks/
│   ├── weekly-seo-review.md    ← Weekly audit process
│   ├── ai-citation-scan.md     ← Citation tracking process
│   └── content-generation.md   ← Content pipeline process
├── intelligence/
│   └── seo-aeo-autonomous-research.md ← This document (reference copy)
└── state/
    └── CONTEXT.md              ← Current rankings, priorities, actions taken
```

### 7.2 AGENT.md for Beacon

```markdown
# AGENT.md -- Beacon (SEO & AEO Intelligence Agent)

## IDENTITY
You are **Beacon**, Deep Blue Health's autonomous SEO and AEO intelligence agent.
You monitor search rankings, track AI engine citations, generate content briefs,
and report insights to Tom and the Oracle (daily briefing agent).

## PERSONALITY
- Data-driven, precise, action-oriented
- Speaks in metrics and actionable insights
- Never vague -- always specific recommendations with expected impact

## CORE RESPONSIBILITIES

### Daily (Automated)
1. Check Google Search Console for ranking changes (via API)
2. Monitor AI citation presence across ChatGPT, Perplexity, Google AI Overviews
3. Flag any technical SEO issues (broken links, speed drops, schema errors)
4. Track competitor ranking movements

### Weekly (Monday 8am)
1. Generate comprehensive SEO performance report
2. AI citation trend analysis (week-over-week)
3. Identify top 5 content opportunities (keyword gaps)
4. Generate content briefs for highest-priority gaps
5. Programmatic page performance review
6. Send summary to Oracle for inclusion in Monday briefing

### Monthly
1. Full site health audit (speed, schema, crawl)
2. Competitor backlink analysis
3. Topical authority gap analysis
4. Content refresh recommendations for existing pages
5. International market ranking comparison

### On-Demand
- Generate content briefs when asked
- Analyze specific keywords or competitor pages
- Draft programmatic page content
- HARO opportunity alerts and pitch drafts

## KNOWLEDGE HIERARCHY
1. Playbooks (proven SEO/AEO patterns with DBH data)
2. State (current rankings, recent changes, active campaigns)
3. Skills (SEO/AEO best practices, technical knowledge)
4. General knowledge (fill gaps only)

## METRICS I TRACK
- Organic traffic (weekly trend)
- Keyword rankings (daily, top 100 keywords)
- AI citation rate (weekly, across 3 platforms)
- Domain authority (monthly)
- Page speed scores (weekly sample)
- Schema coverage % (monthly)
- Content gap score vs competitors (monthly)
- Programmatic page performance (weekly)

## ESCALATION RULES
- CRITICAL: Rankings drop >10 positions for brand terms → immediate Telegram alert
- CRITICAL: Site down or major crawl errors → immediate alert
- IMPORTANT: New keyword enters top 10 → daily summary
- IMPORTANT: AI citation detected → daily summary
- NOTABLE: Competitor publishes competing content → weekly report
- INFO: Normal ranking fluctuations → weekly report only
```

### 7.3 Integration with Orchestrator

Add Beacon to the existing system:

#### config/telegram.json (add entry):
```json
{
  "chat_ids": {
    "seo-beacon": "-XXXXXXXXXX"
  },
  "agent_names": {
    "seo-beacon": "Beacon"
  }
}
```

#### config/schedules.json (add entries):
```json
[
  {
    "agent": "seo-beacon",
    "task": "daily_ranking_check",
    "cron": "0 6 * * *",
    "description": "Beacon daily ranking and citation check (6am, before Oracle)"
  },
  {
    "agent": "seo-beacon",
    "task": "weekly_seo_report",
    "cron": "0 8 * * 1",
    "description": "Beacon weekly SEO performance report (Monday 8am)"
  },
  {
    "agent": "seo-beacon",
    "task": "ai_citation_scan",
    "cron": "0 3 * * 0,3",
    "description": "Beacon AI citation scan (Sunday and Wednesday 3am)"
  },
  {
    "agent": "seo-beacon",
    "task": "monthly_site_audit",
    "cron": "0 2 1 * *",
    "description": "Beacon monthly full site audit (1st of month 2am)"
  },
  {
    "agent": "seo-beacon",
    "task": "haro_scan",
    "cron": "30 9,13,18 * * 1-5",
    "description": "Beacon HARO opportunity scan (3x daily weekdays)"
  }
]
```

### 7.4 Cross-Agent Communication

Beacon feeds into the existing agent ecosystem:

```
Beacon (SEO/AEO) ──weekly_report──> Oracle (Daily Briefing)
Beacon (SEO/AEO) ──content_brief──> Meridian (DBH Marketing)
Beacon (SEO/AEO) ──haro_alert────> Nexus (Command Center)
Meridian (Marketing) ──new_campaign──> Beacon (track keywords)
Oracle (Briefing) ──requests_data──> Beacon (SEO metrics)
```

Implementation in orchestrator.py:

```python
# In the orchestrator's task routing, add:

async def handle_beacon_task(task_name: str):
    """Handle Beacon's scheduled tasks."""

    if task_name == "daily_ranking_check":
        # 1. Pull GSC data
        gsc_data = fetch_daily_rankings(gsc_service)

        # 2. Detect significant changes
        alerts = detect_ranking_changes(gsc_data, threshold=5.0)

        # 3. Run AI citation spot-check (2-3 key prompts)
        citation_check = quick_citation_check()

        # 4. Build daily summary
        summary = build_daily_seo_summary(gsc_data, alerts, citation_check)

        # 5. Post to Beacon channel
        await send_to_channel("seo-beacon", summary)

        # 6. If critical alerts, also notify Oracle for morning briefing
        critical = [a for a in alerts if abs(a['change']) >= 10]
        if critical:
            await send_to_channel("daily-briefing",
                f"[BEACON ALERT] {len(critical)} critical ranking changes detected. "
                f"See #seo-beacon for details."
            )

    elif task_name == "weekly_seo_report":
        # Full weekly report generation
        report = generate_weekly_seo_report()
        await send_to_channel("seo-beacon", report)

        # Send summary to Oracle
        summary = extract_key_metrics(report)
        await send_to_channel("daily-briefing",
            f"[BEACON WEEKLY] {summary}"
        )

    elif task_name == "ai_citation_scan":
        # Full scan across all prompts and platforms
        conn = sqlite3.connect("data/seo_intelligence.db")
        results = run_citation_scan(conn)
        report = generate_citation_report(results)
        await send_to_channel("seo-beacon", report)

    elif task_name == "haro_scan":
        # Scan HARO emails for opportunities
        opportunities = scan_haro_emails(
            imap_server="imap.gmail.com",
            email_address=os.environ["HARO_EMAIL"],
            password=os.environ["HARO_APP_PASSWORD"],
        )

        for opp in opportunities:
            if opp["relevance"] > 0.6:
                pitch = generate_haro_pitch(opp, brand_context=BRAND_CONTEXT)
                alert_opportunity(opp, pitch, BEACON_CHAT_ID)
```

### 7.5 Database Schema

Add to `data/seo_intelligence.db`:

```sql
-- Daily ranking snapshots
CREATE TABLE IF NOT EXISTS rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    keyword TEXT NOT NULL,
    location TEXT DEFAULT 'NZ',
    position REAL,
    clicks INTEGER,
    impressions INTEGER,
    ctr REAL,
    page_url TEXT,
    has_ai_overview BOOLEAN DEFAULT FALSE,
    in_ai_overview BOOLEAN DEFAULT FALSE
);

-- AI citation tracking
CREATE TABLE IF NOT EXISTS ai_citations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    platform TEXT NOT NULL,
    prompt TEXT NOT NULL,
    prompt_hash TEXT NOT NULL,
    response_text TEXT,
    brand_mentioned BOOLEAN DEFAULT FALSE,
    brand_cited BOOLEAN DEFAULT FALSE,
    citation_url TEXT,
    competitor_mentions TEXT,
    sentiment TEXT,
    model_used TEXT
);

-- Citation trends (aggregated weekly)
CREATE TABLE IF NOT EXISTS citation_trends (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_start TEXT NOT NULL,
    platform TEXT NOT NULL,
    total_prompts INTEGER,
    brand_mentions INTEGER,
    brand_citations INTEGER,
    mention_rate REAL,
    citation_rate REAL,
    top_competitors TEXT
);

-- Content briefs generated
CREATE TABLE IF NOT EXISTS content_briefs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created TEXT NOT NULL,
    primary_keyword TEXT NOT NULL,
    keyword_cluster TEXT,
    brief_json TEXT,
    status TEXT DEFAULT 'draft',
    published_url TEXT,
    published_date TEXT,
    performance_30d TEXT
);

-- Programmatic pages tracking
CREATE TABLE IF NOT EXISTS programmatic_pages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    handle TEXT NOT NULL UNIQUE,
    template_type TEXT NOT NULL,
    supplement TEXT,
    condition TEXT,
    published_date TEXT,
    shopify_article_id TEXT,
    impressions_30d INTEGER DEFAULT 0,
    clicks_30d INTEGER DEFAULT 0,
    avg_position REAL,
    ai_citation_count INTEGER DEFAULT 0,
    last_updated TEXT
);

-- Site health audit results
CREATE TABLE IF NOT EXISTS site_audits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    total_urls INTEGER,
    urls_checked INTEGER,
    issues_json TEXT,
    performance_avg REAL,
    seo_score_avg REAL,
    schema_coverage REAL,
    ttfb_avg REAL
);

-- HARO/journalist opportunities
CREATE TABLE IF NOT EXISTS haro_opportunities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received TEXT NOT NULL,
    source TEXT DEFAULT 'haro',
    query_text TEXT,
    relevance_score REAL,
    status TEXT DEFAULT 'new',
    pitch_text TEXT,
    submitted BOOLEAN DEFAULT FALSE,
    result TEXT
);

-- Competitor tracking
CREATE TABLE IF NOT EXISTS competitor_rankings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    competitor TEXT NOT NULL,
    keyword TEXT NOT NULL,
    position REAL,
    location TEXT DEFAULT 'NZ'
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_rankings_keyword ON rankings(keyword, date);
CREATE INDEX IF NOT EXISTS idx_rankings_date ON rankings(date);
CREATE INDEX IF NOT EXISTS idx_citations_platform ON ai_citations(platform, timestamp);
CREATE INDEX IF NOT EXISTS idx_citations_hash ON ai_citations(prompt_hash);
CREATE INDEX IF NOT EXISTS idx_programmatic_handle ON programmatic_pages(handle);
CREATE INDEX IF NOT EXISTS idx_competitor_date ON competitor_rankings(date, competitor);
```

---

## 8. IMPLEMENTATION ROADMAP

### Phase 1: Foundation (Week 1-2)
**Cost: ~$0 (free tools + existing infrastructure)**

- [ ] Create `agents/seo-beacon/` directory with AGENT.md and skills/
- [ ] Create Telegram group for Beacon, get chat ID
- [ ] Add Beacon to `config/telegram.json` and `config/schedules.json`
- [ ] Set up Google Search Console API (service account)
- [ ] Deploy `llms.txt` to deepbluehealth.co.nz root
- [ ] Update `robots.txt` to allow AI crawlers (GPTBot, ClaudeBot, PerplexityBot)
- [ ] Implement `DietarySupplement` + `Product` schema on all product pages
- [ ] Add `FAQPage` schema to top 10 product pages
- [ ] Initialize `data/seo_intelligence.db` with schema

### Phase 2: Monitoring (Week 3-4)
**Cost: ~$30/mo (DataForSEO + Otterly.AI Lite)**

- [ ] Build GSC daily ranking pipeline (`core/seo_monitor.py`)
- [ ] Build AI citation tracker (`core/ai_citation_tracker.py`)
- [ ] Set up DataForSEO account for SERP tracking
- [ ] Wire daily ranking check into orchestrator schedule
- [ ] Wire AI citation scan (2x/week) into orchestrator schedule
- [ ] Build weekly SEO report generator
- [ ] Connect Beacon -> Oracle for briefing integration
- [ ] Set up Otterly.AI (or Peec AI) for visual AI citation dashboard

### Phase 3: Content Intelligence (Week 5-6)
**Cost: ~$129/mo (Ahrefs Lite for keyword data)**

- [ ] Set up Ahrefs API access for keyword gap analysis
- [ ] Build keyword clustering pipeline
- [ ] Build content brief generator
- [ ] Create topical authority map (all clusters documented)
- [ ] Build existing content optimizer
- [ ] Generate first batch of 10 content briefs
- [ ] Publish first 5 optimized articles with full schema

### Phase 4: Programmatic SEO (Week 7-10)
**Cost: ~$50 in Claude API for content generation**

- [ ] Build supplement/condition data matrix (full dataset)
- [ ] Build programmatic page generator
- [ ] Build Shopify GraphQL publishing pipeline
- [ ] Generate and review first batch of 20 programmatic pages
- [ ] Monitor indexation and initial rankings
- [ ] Iterate on content quality based on performance
- [ ] Scale to 50-100 pages

### Phase 5: Link Building (Week 11-12)
**Cost: ~$0-50/mo (HARO is free, Qwoted optional)**

- [ ] Set up HARO email monitoring
- [ ] Build automated relevance scoring
- [ ] Build pitch draft generator
- [ ] Wire HARO alerts to Telegram
- [ ] Create linkable assets (NZ supplement guide, research reports)
- [ ] Begin outreach to NZ/AU health bloggers

### Phase 6: International Expansion (Month 4+)
**Cost: Shopify Markets pricing (varies)**

- [ ] Set up Shopify Markets for AU
- [ ] Verify hreflang implementation
- [ ] Create AU-localized content (top 20 pages)
- [ ] Register AU property in Google Search Console
- [ ] Expand DataForSEO tracking to AU keywords
- [ ] Repeat for US, UK markets

### Total Estimated Monthly Cost (Steady State)
| Item | Cost/mo |
|------|---------|
| DataForSEO SERP API | ~$30 |
| Otterly.AI (Lite) | $29 |
| Ahrefs (Lite) | $129 |
| Claude API (content gen) | ~$50 |
| Google APIs | Free |
| **Total** | **~$238/mo** |

---

## APPENDIX: CODE PATTERNS

### A. Environment Variables Required

Add these to Railway deployment:

```bash
# SEO/AEO APIs
GOOGLE_SEARCH_CONSOLE_CREDENTIALS=<base64 encoded service account JSON>
GOOGLE_PAGESPEED_API_KEY=<key>
DATAFORSEO_LOGIN=<login>
DATAFORSEO_PASSWORD=<password>
PERPLEXITY_API_KEY=<key>
OPENAI_API_KEY=<key>  # Already set for other agents
ANTHROPIC_API_KEY=<key>  # Already set for other agents
AHREFS_API_KEY=<key>  # When Ahrefs API v3 is set up

# HARO monitoring
HARO_EMAIL=<email registered with HARO>
HARO_APP_PASSWORD=<app-specific password for IMAP>

# Shopify (for programmatic publishing)
SHOPIFY_STORE_URL=<store>.myshopify.com
SHOPIFY_ACCESS_TOKEN=<admin API access token>
```

### B. Python Dependencies

Add to `requirements.txt`:

```
# SEO/AEO specific
google-api-python-client>=2.120.0
google-auth>=2.28.0
google-auth-oauthlib>=1.2.0
pandas>=2.2.0
beautifulsoup4>=4.12.0
lxml>=5.1.0
ShopifyAPI>=12.6.0
PerplexiPy>=0.5.0

# Already in project
anthropic
openai
httpx
aiohttp
```

### C. File Structure for New Code

```
core/
├── seo_monitor.py          ← GSC integration, daily ranking pipeline
├── ai_citation_tracker.py  ← AI citation scanning across platforms
├── content_intelligence.py ← Keyword clustering, brief generation
├── programmatic_seo.py     ← Page generation and Shopify publishing
├── site_health.py          ← Technical audit automation
├── haro_monitor.py         ← HARO/journalist opportunity scanning
└── seo_reporter.py         ← Report generation for Beacon

data/
└── seo_intelligence.db     ← All SEO/AEO data (separate from main intelligence.db)
```

### D. Quick-Start: Minimum Viable Beacon

The fastest path to value (can be done in a single session):

1. **Deploy llms.txt** -- 5 minutes, immediate AEO benefit
2. **Fix robots.txt** -- 5 minutes, allow AI crawlers
3. **Add DietarySupplement schema** to top 5 product pages -- 1 hour
4. **Set up GSC API** -- 30 minutes
5. **Build basic ranking alert** -- 2 hours
6. **Run first AI citation scan** -- 1 hour (manual, using the code patterns above)
7. **Create Beacon Telegram channel** -- 10 minutes

This gives you an operational SEO/AEO monitoring agent within a day.

### E. Key API Reference Links

- Google Search Console API: https://developers.google.com/webmaster-tools
- DataForSEO API v3: https://docs.dataforseo.com/v3/
- Ahrefs API v3: https://docs.ahrefs.com/docs/api/reference/introduction
- Shopify Admin GraphQL API: https://shopify.dev/docs/api/admin-graphql
- Shopify Article Resource: https://shopify.dev/docs/api/admin-rest/latest/resources/article
- Perplexity API: https://docs.perplexity.ai/docs/getting-started/quickstart
- Schema.org DietarySupplement: https://schema.org/DietarySupplement
- Schema.org Product: https://schema.org/Product
- Schema.org FAQPage: https://schema.org/FAQPage
- Otterly.AI: https://otterly.ai/
- Peec AI: https://peec.ai/
- SE Ranking AI Visible: https://visible.seranking.com/

---

## RESEARCH SOURCES

This document was compiled from cutting-edge research as of March 2026, including:

- [GEO Optimization Guide: ChatGPT, Perplexity, Gemini & More](https://www.getpassionfruit.com/blog/generative-engine-optimization-guide-for-chatgpt-perplexity-gemini-claude-copilot)
- [The Complete 2026 Guide to Answer Engine Optimization (AEO)](https://www.dojoai.com/blog/answer-engine-optimization-aeo-guide-dynamic-ai-seo)
- [How AI Engines Cite Sources: Patterns Across ChatGPT, Claude, Perplexity, and SGE](https://medium.com/@geolyze/how-ai-engines-cite-sources-patterns-across-chatgpt-claude-perplexity-and-sge-8c317777c71d)
- [Generative Engine Optimization: How to Rank on ChatGPT, Claude, and Perplexity](https://www.siddharthbharath.com/generative-engine-optimization)
- [Best Generative Engine Optimization Tools: 2026 Review](https://visible.seranking.com/blog/best-generative-engine-optimization-tools-2026/)
- [How to Rank in Perplexity AI: Get Cited, Not Ignored (2026 Guide)](https://wellows.com/blog/how-to-rank-in-perplexity/)
- [How to Rank on Perplexity AI Based On 65k Citation Data](https://www.tryanalyze.ai/blog/how-to-rank-on-perplexity)
- [Google AI Overviews Ranking Factors: 2026 Guide](https://wellows.com/blog/google-ai-overviews-ranking-factors/)
- [Google AI Overviews Optimization: How to Get Featured in 2026](https://www.averi.ai/blog/google-ai-overviews-optimization-how-to-get-featured-in-2026)
- [AI Overviews Killed CTR 61%: 9 Strategies to Show Up (2026)](https://www.dataslayer.ai/blog/google-ai-overviews-the-end-of-traditional-ctr-and-how-to-adapt-in-2025)
- [How Structured Data Schema Transforms AI Search Visibility in 2026](https://medium.com/@vicki-larson/how-structured-data-schema-transforms-your-ai-search-visibility-in-2026-9e968313b2d7)
- [Answer Engine Optimization Practical Framework for 2026](https://monday.com/blog/marketing/answer-engine-optimization/)
- [AEO 101: The Definitive Guide to Answer Engine Optimization in 2026](https://cubitrek.com/blog/aeo-101-answer-engine-optimization-guide/)
- [DietarySupplement Schema.org Type](https://schema.org/DietarySupplement)
- [Ecommerce Structured Data & Schema 2026](https://productlasso.com/en/blog/structured-data-ecommerce-schema-2026)
- [The Ultimate Guide to Programmatic SEO in 2026](https://www.jasminedirectory.com/blog/the-ultimate-guide-to-programmatic-seo-in-2026/)
- [Programmatic SEO Without Traffic Loss: Complete 2025 Guide](https://www.getpassionfruit.com/blog/programmatic-seo-traffic-cliff-guide)
- [Building an AI Visibility Monitoring Tool: Developer's Guide](https://dev.to/msmyaqoob25/building-an-ai-visibility-monitoring-tool-a-developers-guide-to-tracking-llm-citations-2m9d)
- [LLMs.txt: The New Robots.txt for AI Explained](https://thinkdmg.com/what-is-llms-txt-the-new-robots-txt-for-ai-explained/)
- [Best Practices for AI-Oriented robots.txt and llms.txt Configuration](https://medium.com/@franciscokemeny/best-practices-for-ai-oriented-robots-txt-and-llms-txt-configuration-be564ba5a6bd)
- [How LLM Crawlers Work: GPTBot, ClaudeBot, PerplexityBot](https://links-stream.com/blog/uncategorized-en/llm-crawlers-how-they-scan-sites/)
- [International SEO in 2026: What Still Works](https://searchengineland.com/international-seo-in-2026-what-still-works-what-no-longer-does-and-why-467712)
- [Shopify International SEO in 2026](https://blog.growthack.io/shopify-seo-global-ecommerce-strategy-for-international-expansion/)
- [AI Search Is the New SEO: Supplement Industry 2026](https://www.nutraceuticalsworld.com/ai-search-is-the-new-seo-how-brands-can-win-the-next-discovery-revolution-state-of-the-supplement-industry-2026/)
- [Content Gap Analysis 2026: 10 Tips For AI Search](https://www.yotpo.com/blog/modern-content-gap-analysis/)
- [Best AI SEO Tools for 2026 by Tim Soulo (Ahrefs CMO)](https://medium.com/@timsoulo/best-ai-seo-tools-for-2026-content-optimization-keyword-research-and-ai-visibility-6e9a13c354db)
- [HARO Alternatives 2026: Complete Guide](https://www.barchart.com/story/news/196157/haro-alternatives-2026-complete-guide-to-pr-and-link-building-platforms)
- [Ahrefs API v3 Documentation](https://docs.ahrefs.com/docs/api/reference/introduction)
- [DataForSEO SERP API](https://dataforseo.com/apis/serp-api)
- [Google Search Console API](https://developers.google.com/webmaster-tools)
- [Shopify Python API (GraphQL)](https://github.com/Shopify/shopify_python_api)
- [Topical Authority SEO: Become the Expert in 2026](https://www.clickrank.ai/topical-authority/)
- [How to Build Topic Ecosystems That Win SEO in 2026](https://azuramagazine.com/articles/how-to-build-topic-ecosystems-that-will-win-seo-in-2026)
- [Automated SEO Agents Are Transforming Website Optimization in 2026](https://seomediaworld.com/automated-seo-agents/)
- [AI Citation Tracking Tools: Monitoring Answer Engine Mentions (2026)](https://www.stackmatix.com/blog/ai-citation-tracking-tools)
- [Tracking LLM Brand Citations: A Complete Guide for 2026](https://www.airops.com/blog/llm-brand-citation-tracking)

---

*This document is the research foundation for building Beacon. It should be treated as a living reference -- updated as new tools, APIs, and AEO techniques emerge. The code patterns are production-ready starting points, not finished modules. Each will need error handling, rate limiting, and testing before deployment.*

*Last updated: March 1, 2026*
