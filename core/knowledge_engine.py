#!/usr/bin/env python3
"""
Knowledge Engine -- Curated Evening Reading for Sage

The intellectual companion to Tom's Command Center.
Every evening, Sage reads the day's context (agent states, decisions, events,
learning insights) and selects the most relevant foundational concept to teach.

The goal: over time, Tom builds a comprehensive mental framework that connects
directly to the real challenges he faces daily. Not abstract learning -- applied
wisdom that references specific decisions and events from the same day.

Architecture:
  1. KNOWLEDGE_LIBRARY -- ~66 foundational concepts across 6 domains
  2. analyse_today_context() -- reads agent states, decisions, events, learning DB
  3. select_evening_reading() -- scores concepts vs today's context, picks best + wildcard
  4. format_evening_reading() -- generates prompt instructions for Claude delivery
  5. Reading log at data/reading_log.db -- prevents repeats, tracks engagement

Data lives at data/reading_log.db (SQLite WAL mode).

CLI:
  python -m core.knowledge_engine today       -- What would tonight's reading be?
  python -m core.knowledge_engine concepts    -- List all concepts by domain
  python -m core.knowledge_engine history     -- Show reading log
  python -m core.knowledge_engine suggest     -- Show top 5 candidates with scores
"""

import sqlite3
import json
import os
import random
import logging
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Optional

logger = logging.getLogger(__name__)

# Resolve paths relative to this file's location (works in Docker + local)
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
AGENTS_DIR = BASE_DIR / "agents"
DB_PATH = DATA_DIR / "reading_log.db"

# Sibling database paths for cross-referencing
DECISIONS_DB_PATH = DATA_DIR / "decisions.db"
EVENT_BUS_DB_PATH = DATA_DIR / "event_bus.db"
LEARNING_DB_PATH = DATA_DIR / "learning.db"
INTELLIGENCE_DB_PATH = DATA_DIR / "intelligence.db"

# All 10 agents in the system
ALL_AGENTS = [
    "global-events",       # Atlas
    "dbh-marketing",       # Meridian
    "pure-pets",           # Scout
    "new-business",        # Venture
    "health-fitness",      # Titan
    "social",              # Compass
    "creative-projects",   # Lens
    "daily-briefing",      # Oracle
    "command-center",      # Nexus
    "strategic-advisor",   # PREP
]

AGENT_DISPLAY = {
    "global-events":     "Atlas",
    "dbh-marketing":     "Meridian",
    "pure-pets":         "Scout",
    "new-business":      "Venture",
    "health-fitness":    "Titan",
    "social":            "Compass",
    "creative-projects": "Lens",
    "daily-briefing":    "Oracle",
    "command-center":    "Nexus",
    "strategic-advisor": "PREP",
    "evening-reading":   "Sage",
}

# How many days before a concept can repeat
REPEAT_COOLDOWN_DAYS = 30


# =============================================================================
# KNOWLEDGE LIBRARY
# =============================================================================
# Each concept is keyed by a unique slug. Fields:
#   name:        Human-readable name
#   domain:      One of the 6 domain categories
#   author:      Primary thinker associated (for attribution)
#   summary:     1-2 sentence core idea
#   keywords:    List of keywords for context matching
#   deep_dive:   Book/essay/video recommendation for further reading

KNOWLEDGE_LIBRARY = {

    # =========================================================================
    # MENTAL MODELS (~15)
    # =========================================================================

    "first_principles": {
        "name": "First Principles Thinking",
        "domain": "mental_models",
        "author": "Aristotle / Elon Musk",
        "summary": "Break problems down to their most fundamental truths, then reason up from there. Don't reason by analogy -- reason from the ground truth.",
        "keywords": ["fundamentals", "problem", "solve", "build", "create", "rethink", "assumption", "strategy", "redesign", "architecture"],
        "deep_dive": "Book: 'The First 20 Hours' by Josh Kaufman; Musk's battery cost analysis interview"
    },
    "inversion": {
        "name": "Inversion",
        "domain": "mental_models",
        "author": "Charlie Munger",
        "summary": "Instead of asking 'how do I succeed?', ask 'how would I fail?' Then avoid those things. Invert, always invert.",
        "keywords": ["fail", "risk", "avoid", "mistake", "problem", "loss", "prevent", "churn", "decline", "drop"],
        "deep_dive": "Book: 'Poor Charlie's Almanack' by Charlie Munger"
    },
    "second_order_thinking": {
        "name": "Second-Order Thinking",
        "domain": "mental_models",
        "author": "Howard Marks",
        "summary": "What happens AFTER what happens? First-order thinking is simplistic. Second-order thinkers ask: 'And then what?'",
        "keywords": ["consequence", "impact", "downstream", "effect", "chain", "reaction", "long-term", "future", "ripple"],
        "deep_dive": "Book: 'The Most Important Thing' by Howard Marks"
    },
    "circle_of_competence": {
        "name": "Circle of Competence",
        "domain": "mental_models",
        "author": "Warren Buffett / Charlie Munger",
        "summary": "Know what you know, and know what you don't. The size of your circle matters less than knowing its boundaries.",
        "keywords": ["expertise", "skill", "delegate", "outsource", "focus", "competence", "strength", "weakness", "hire"],
        "deep_dive": "Buffett's 1996 Berkshire Hathaway annual letter"
    },
    "map_vs_territory": {
        "name": "Map vs Territory",
        "domain": "mental_models",
        "author": "Alfred Korzybski",
        "summary": "The model is not the reality. Data, dashboards, and reports are maps -- useful but never the full picture. Always ground-truth.",
        "keywords": ["data", "dashboard", "report", "analytics", "metrics", "reality", "assumption", "model", "forecast", "prediction"],
        "deep_dive": "Paper: 'Science and Sanity' by Alfred Korzybski; Taleb's commentary in Antifragile"
    },
    "leverage": {
        "name": "Leverage",
        "domain": "mental_models",
        "author": "Naval Ravikant",
        "summary": "Code, media, capital, labour -- in that order. New-age leverage (code + media) doesn't require permission. Maximise output per unit of input.",
        "keywords": ["automation", "ai", "code", "media", "content", "scale", "system", "efficiency", "build", "agent", "bot"],
        "deep_dive": "Naval's tweetstorm 'How to Get Rich' and the Almanack of Naval Ravikant"
    },
    "opportunity_cost": {
        "name": "Opportunity Cost",
        "domain": "mental_models",
        "author": "Economics / Frederic Bastiat",
        "summary": "Every yes is a no to something else. The true cost of any choice is the best alternative you gave up.",
        "keywords": ["priority", "choose", "decision", "tradeoff", "budget", "time", "focus", "spend", "invest", "allocate"],
        "deep_dive": "Bastiat's 'That Which Is Seen, and That Which Is Not Seen' (1850)"
    },
    "pareto_principle": {
        "name": "Pareto Principle (80/20)",
        "domain": "mental_models",
        "author": "Vilfredo Pareto",
        "summary": "80% of outputs come from 20% of inputs. Focus ruthlessly on the vital few. Applies to customers, products, efforts, and problems.",
        "keywords": ["focus", "priority", "top", "best", "customer", "product", "revenue", "performance", "efficient", "cut"],
        "deep_dive": "Book: 'The 80/20 Principle' by Richard Koch"
    },
    "compounding": {
        "name": "Compounding",
        "domain": "mental_models",
        "author": "Albert Einstein (attributed)",
        "summary": "Small, consistent advantages create exponential results over time. The eighth wonder of the world. Applies to money, knowledge, relationships, and habits.",
        "keywords": ["growth", "compound", "consistent", "habit", "daily", "improve", "accumulate", "long-term", "invest", "learning"],
        "deep_dive": "Book: 'The Psychology of Money' by Morgan Housel (Chapter: 'Getting Wealthy vs. Staying Wealthy')"
    },
    "antifragility": {
        "name": "Antifragility",
        "domain": "mental_models",
        "author": "Nassim Nicholas Taleb",
        "summary": "Some systems don't just resist disorder -- they gain from it. Build systems that get stronger from stress, volatility, and random shocks.",
        "keywords": ["chaos", "volatility", "stress", "risk", "resilient", "robust", "shock", "tariff", "disruption", "crisis", "adapt"],
        "deep_dive": "Book: 'Antifragile' by Nassim Nicholas Taleb"
    },
    "occams_razor": {
        "name": "Occam's Razor",
        "domain": "mental_models",
        "author": "William of Ockham",
        "summary": "The simplest explanation is usually correct. When diagnosing problems, start with the obvious before building elaborate theories.",
        "keywords": ["simple", "debug", "diagnose", "problem", "cause", "root", "error", "fix", "straightforward"],
        "deep_dive": "Any good overview of epistemology or philosophy of science"
    },
    "hanlons_razor": {
        "name": "Hanlon's Razor",
        "domain": "mental_models",
        "author": "Robert J. Hanlon",
        "summary": "Never attribute to malice what is adequately explained by incompetence, ignorance, or oversight. Most failures are accidents, not conspiracies.",
        "keywords": ["people", "team", "mistake", "communication", "misunderstand", "supplier", "vendor", "partner", "delay"],
        "deep_dive": "Broader reading on cognitive biases: 'Thinking, Fast and Slow' by Kahneman"
    },
    "survivorship_bias": {
        "name": "Survivorship Bias",
        "domain": "mental_models",
        "author": "Abraham Wald (WWII analysis)",
        "summary": "We only see the winners. The graveyard of failures is invisible. Study failures as carefully as you study successes.",
        "keywords": ["success", "case study", "benchmark", "competitor", "compare", "example", "story", "winner", "result"],
        "deep_dive": "Book: 'Fooled by Randomness' by Taleb; the Abraham Wald airplane armour story"
    },
    "lindy_effect": {
        "name": "Lindy Effect",
        "domain": "mental_models",
        "author": "Benoit Mandelbrot / Nassim Taleb",
        "summary": "The longer something non-perishable has survived, the longer it's likely to survive. Old ideas, brands, and technologies that persist have earned their place.",
        "keywords": ["proven", "classic", "lasting", "brand", "trust", "heritage", "long-term", "endure", "tradition"],
        "deep_dive": "Taleb's 'Antifragile', Chapter 18: 'On the Difference between a Large Stone and a Thousand Pebbles'"
    },
    "via_negativa": {
        "name": "Via Negativa",
        "domain": "mental_models",
        "author": "Nassim Taleb / Stoic tradition",
        "summary": "Improvement by subtraction. Often the most powerful move is removing what doesn't work rather than adding more. Less but better.",
        "keywords": ["simplify", "remove", "cut", "eliminate", "reduce", "stop", "clean", "streamline", "less", "focus"],
        "deep_dive": "Book: 'Essentialism' by Greg McKeown; Taleb's 'Antifragile'"
    },

    # =========================================================================
    # STRATEGY & BUSINESS (~15)
    # =========================================================================

    "moats": {
        "name": "Moats",
        "domain": "strategy_business",
        "author": "Warren Buffett",
        "summary": "What makes you hard to compete with? Brand, switching costs, network effects, cost advantages, intangible assets. Without a moat, margins erode to zero.",
        "keywords": ["competitive", "advantage", "brand", "differentiate", "defend", "market", "position", "protect", "unique"],
        "deep_dive": "Book: '7 Powers' by Hamilton Helmer"
    },
    "aggregation_theory": {
        "name": "Aggregation Theory",
        "domain": "strategy_business",
        "author": "Ben Thompson",
        "summary": "In the internet age, owning demand (customers) beats owning supply. Aggregators win by being the best at connecting users to commoditised supply.",
        "keywords": ["platform", "marketplace", "customer", "demand", "supply", "digital", "internet", "distribution", "dtc", "direct"],
        "deep_dive": "Ben Thompson's Stratechery blog: 'Aggregation Theory' series"
    },
    "blue_ocean": {
        "name": "Blue Ocean Strategy",
        "domain": "strategy_business",
        "author": "W. Chan Kim & Renee Mauborgne",
        "summary": "Create uncontested market space instead of fighting in crowded red oceans. Make the competition irrelevant by redefining the value proposition.",
        "keywords": ["new", "market", "innovate", "different", "niche", "uncontested", "create", "category", "unique", "opportunity"],
        "deep_dive": "Book: 'Blue Ocean Strategy' by Kim & Mauborgne"
    },
    "jobs_to_be_done": {
        "name": "Jobs To Be Done",
        "domain": "strategy_business",
        "author": "Clayton Christensen",
        "summary": "People don't buy products -- they hire them for a job. Understand what job your customer is trying to get done, and you'll never be disrupted.",
        "keywords": ["customer", "need", "want", "problem", "product", "solve", "use", "buy", "purchase", "motivation", "pain"],
        "deep_dive": "Book: 'Competing Against Luck' by Clayton Christensen"
    },
    "positioning": {
        "name": "Positioning",
        "domain": "strategy_business",
        "author": "Al Ries & Jack Trout",
        "summary": "Own a word in the customer's mind. Positioning isn't what you do to a product -- it's what you do to the mind of the prospect.",
        "keywords": ["brand", "position", "message", "perception", "customer", "mind", "differentiate", "tagline", "identity"],
        "deep_dive": "Book: 'Positioning: The Battle for Your Mind' by Ries & Trout"
    },
    "network_effects": {
        "name": "Network Effects",
        "domain": "strategy_business",
        "author": "Various (Metcalfe's Law)",
        "summary": "Value increases with each user. Direct network effects (phone), indirect (marketplace), data network effects (AI). The strongest moat in tech.",
        "keywords": ["user", "growth", "community", "platform", "marketplace", "viral", "referral", "member", "network"],
        "deep_dive": "NFX.com essays on the 16 types of network effects"
    },
    "flywheel_effect": {
        "name": "Flywheel Effect",
        "domain": "strategy_business",
        "author": "Jim Collins",
        "summary": "No single push creates momentum. Consistent effort in the same direction compounds into an unstoppable flywheel. Amazon's flywheel is the canonical example.",
        "keywords": ["momentum", "consistent", "compound", "growth", "loop", "reinvest", "cycle", "repeat", "build", "system"],
        "deep_dive": "Book: 'Good to Great' by Jim Collins (Flywheel chapter); 'Turning the Flywheel' monograph"
    },
    "crossing_the_chasm": {
        "name": "Crossing the Chasm",
        "domain": "strategy_business",
        "author": "Geoffrey Moore",
        "summary": "Early adopters are not the mainstream. There's a chasm between them. To cross it, you need a beachhead segment, whole product, and compelling reason to buy.",
        "keywords": ["adoption", "customer", "segment", "market", "early", "mainstream", "launch", "new", "growth", "scale"],
        "deep_dive": "Book: 'Crossing the Chasm' by Geoffrey Moore"
    },
    "unit_economics": {
        "name": "Unit Economics",
        "domain": "strategy_business",
        "author": "Fundamental business principle",
        "summary": "Revenue per unit minus cost per unit. Period. If the unit economics don't work, no amount of volume will save you. LTV > CAC or you die.",
        "keywords": ["ltv", "cac", "margin", "cost", "revenue", "profit", "unit", "acquisition", "customer", "order", "aov", "roas"],
        "deep_dive": "David Skok's 'For Entrepreneurs' blog on SaaS/DTC unit economics"
    },
    "barbell_strategy": {
        "name": "Barbell Strategy",
        "domain": "strategy_business",
        "author": "Nassim Nicholas Taleb",
        "summary": "Extreme safety + extreme risk, nothing in the middle. Protect downside aggressively, then swing for asymmetric upside with the rest.",
        "keywords": ["risk", "safe", "bet", "invest", "portfolio", "allocation", "conservative", "aggressive", "upside", "downside"],
        "deep_dive": "Book: 'Antifragile' by Taleb, plus Nassim's barbell in Black Swan"
    },
    "power_law": {
        "name": "Power Law",
        "domain": "strategy_business",
        "author": "Peter Thiel / Pareto",
        "summary": "A few things matter enormously, most don't at all. In venture, one deal returns the entire fund. In business, one product or channel drives everything.",
        "keywords": ["top", "best", "dominant", "winner", "concentrate", "focus", "channel", "product", "revenue", "returns"],
        "deep_dive": "Book: 'Zero to One' by Peter Thiel (Power Law chapter)"
    },
    "innovators_dilemma": {
        "name": "The Innovator's Dilemma",
        "domain": "strategy_business",
        "author": "Clayton Christensen",
        "summary": "Great companies fail because they listen to their best customers and focus on sustaining innovation. Disruptive innovation comes from below, serving non-consumers.",
        "keywords": ["disrupt", "innovate", "change", "new", "technology", "competitor", "startup", "threat", "shift", "replace"],
        "deep_dive": "Book: 'The Innovator's Dilemma' by Clayton Christensen"
    },
    "lean_startup": {
        "name": "The Lean Startup",
        "domain": "strategy_business",
        "author": "Eric Ries",
        "summary": "Build-Measure-Learn. Ship the minimum viable product, measure real customer behaviour, learn, iterate. Speed of iteration beats quality of plan.",
        "keywords": ["mvp", "test", "experiment", "iterate", "launch", "feedback", "validate", "hypothesis", "lean", "build", "measure"],
        "deep_dive": "Book: 'The Lean Startup' by Eric Ries"
    },
    "platform_vs_product": {
        "name": "Platform vs Product Thinking",
        "domain": "strategy_business",
        "author": "Various",
        "summary": "Products serve users. Platforms serve ecosystems. Building a platform means enabling others to create value, which compounds the total value back to you.",
        "keywords": ["platform", "ecosystem", "integration", "api", "marketplace", "partner", "build", "system", "scale", "infrastructure"],
        "deep_dive": "Book: 'Platform Revolution' by Parker, Van Alstyne & Choudary"
    },
    "economies_of_scale_scope": {
        "name": "Economies of Scale vs Scope",
        "domain": "strategy_business",
        "author": "Alfred Chandler / economics",
        "summary": "Scale: doing MORE of the same thing reduces per-unit cost. Scope: doing DIFFERENT things that share resources. Both are levers. Know which you're pulling.",
        "keywords": ["scale", "grow", "expand", "cost", "efficiency", "product", "line", "range", "diversify", "volume"],
        "deep_dive": "Porter's 'Competitive Advantage' on cost drivers"
    },

    # =========================================================================
    # PSYCHOLOGY & PERSUASION (~10)
    # =========================================================================

    "loss_aversion": {
        "name": "Loss Aversion",
        "domain": "psychology_persuasion",
        "author": "Daniel Kahneman / Amos Tversky",
        "summary": "Losing hurts roughly 2x more than winning feels good. Frame offers around what customers stand to lose, not just what they gain.",
        "keywords": ["loss", "pain", "fear", "miss", "expire", "urgency", "fomo", "scarcity", "customer", "email", "ad", "copy"],
        "deep_dive": "Book: 'Thinking, Fast and Slow' by Daniel Kahneman"
    },
    "social_proof": {
        "name": "Social Proof",
        "domain": "psychology_persuasion",
        "author": "Robert Cialdini",
        "summary": "People follow people. Reviews, testimonials, 'most popular', 'X people bought this' -- humans look to others to decide what's correct.",
        "keywords": ["review", "testimonial", "social", "proof", "popular", "trust", "customer", "ugc", "rating", "recommend"],
        "deep_dive": "Book: 'Influence' by Robert Cialdini"
    },
    "anchoring": {
        "name": "Anchoring",
        "domain": "psychology_persuasion",
        "author": "Kahneman & Tversky",
        "summary": "The first number sets the frame. Show the original price before the discount. Present the expensive option first. The anchor shapes all subsequent judgement.",
        "keywords": ["price", "discount", "compare", "offer", "deal", "value", "perception", "original", "was", "now"],
        "deep_dive": "Book: 'Predictably Irrational' by Dan Ariely"
    },
    "reciprocity": {
        "name": "Reciprocity",
        "domain": "psychology_persuasion",
        "author": "Robert Cialdini",
        "summary": "Give first, receive later. Free samples, valuable content, unexpected gifts -- when you give, people feel obligated to give back.",
        "keywords": ["give", "free", "sample", "content", "value", "gift", "bonus", "loyalty", "relationship", "nurture"],
        "deep_dive": "Book: 'Influence' by Robert Cialdini (Reciprocity chapter)"
    },
    "commitment_consistency": {
        "name": "Commitment & Consistency",
        "domain": "psychology_persuasion",
        "author": "Robert Cialdini",
        "summary": "Small yeses lead to big yeses. Once people take a small action (sign up, try a sample), they want to stay consistent with that identity.",
        "keywords": ["funnel", "step", "sign", "subscribe", "trial", "sample", "commit", "journey", "onboard", "flow"],
        "deep_dive": "Book: 'Influence' by Robert Cialdini (Commitment chapter)"
    },
    "scarcity": {
        "name": "Scarcity",
        "domain": "psychology_persuasion",
        "author": "Robert Cialdini",
        "summary": "Less available = more desired. Limited editions, countdown timers, 'only X left' -- scarcity creates urgency and increases perceived value.",
        "keywords": ["limited", "exclusive", "stock", "countdown", "urgent", "expire", "deadline", "rare", "remaining", "sold"],
        "deep_dive": "Book: 'Influence' by Robert Cialdini (Scarcity chapter)"
    },
    "dunning_kruger": {
        "name": "The Dunning-Kruger Effect",
        "domain": "psychology_persuasion",
        "author": "David Dunning / Justin Kruger",
        "summary": "Confidence does not equal competence. Beginners overestimate their ability; experts underestimate theirs. Calibrate accordingly.",
        "keywords": ["confidence", "skill", "learn", "expertise", "overconfident", "humble", "assess", "evaluate", "hire"],
        "deep_dive": "Original paper: 'Unskilled and Unaware of It' (1999)"
    },
    "cognitive_dissonance": {
        "name": "Cognitive Dissonance",
        "domain": "psychology_persuasion",
        "author": "Leon Festinger",
        "summary": "When beliefs and actions conflict, something has to give. People rationalise their purchases, their habits, their identity. Use this in post-purchase experience.",
        "keywords": ["belief", "action", "justify", "rationalise", "brand", "loyalty", "identity", "post-purchase", "experience"],
        "deep_dive": "Book: 'A Theory of Cognitive Dissonance' by Leon Festinger"
    },
    "peak_end_rule": {
        "name": "Peak-End Rule",
        "domain": "psychology_persuasion",
        "author": "Daniel Kahneman",
        "summary": "People remember experiences based on two moments: the peak (most intense) and the end. Nail the unboxing. Nail the follow-up email.",
        "keywords": ["experience", "unboxing", "delivery", "email", "follow-up", "customer", "satisfaction", "journey", "moment", "delight"],
        "deep_dive": "Book: 'Thinking, Fast and Slow' by Kahneman (Experience vs Memory chapter)"
    },
    "status_vs_wealth_games": {
        "name": "Status Games vs Wealth Games",
        "domain": "psychology_persuasion",
        "author": "Naval Ravikant",
        "summary": "Status is zero-sum: for you to rise, someone must fall. Wealth is positive-sum: create value and everyone wins. Play wealth games, not status games.",
        "keywords": ["status", "wealth", "comparison", "social", "value", "create", "compete", "ego", "win", "game"],
        "deep_dive": "Almanack of Naval Ravikant"
    },

    # =========================================================================
    # HISTORY & PHILOSOPHY (~10)
    # =========================================================================

    "stoicism": {
        "name": "Stoicism",
        "domain": "history_philosophy",
        "author": "Marcus Aurelius / Epictetus / Seneca",
        "summary": "Control what you can, accept what you can't. The obstacle is the way. Emotional regulation isn't suppression -- it's choosing your response deliberately.",
        "keywords": ["stress", "control", "accept", "challenge", "obstacle", "emotion", "calm", "patience", "difficult", "pressure"],
        "deep_dive": "Book: 'Meditations' by Marcus Aurelius (Gregory Hays translation)"
    },
    "meditations": {
        "name": "The Meditations",
        "domain": "history_philosophy",
        "author": "Marcus Aurelius",
        "summary": "Practical philosophy for leaders under pressure. Written by a Roman Emperor during wartime -- not ivory tower theory but battlefield-tested wisdom on duty, ego, and mortality.",
        "keywords": ["leadership", "duty", "ego", "pressure", "decision", "responsibility", "team", "character", "integrity"],
        "deep_dive": "Book: 'Meditations' by Marcus Aurelius; companion: 'The Inner Citadel' by Pierre Hadot"
    },
    "art_of_war": {
        "name": "The Art of War",
        "domain": "history_philosophy",
        "author": "Sun Tzu",
        "summary": "Know yourself, know your enemy, win every battle. Choose battles wisely. Speed and surprise beat raw force. Victory comes from preparation, not impulse.",
        "keywords": ["competitor", "strategy", "market", "battle", "position", "advantage", "timing", "intelligence", "plan"],
        "deep_dive": "Book: 'The Art of War' by Sun Tzu (many translations; Griffith is solid)"
    },
    "the_prince": {
        "name": "The Prince",
        "domain": "history_philosophy",
        "author": "Niccolo Machiavelli",
        "summary": "Power dynamics and political realism. Better to be feared than loved (if you can't be both). Understand how power works even if you don't play dirty.",
        "keywords": ["power", "leadership", "politics", "negotiate", "influence", "authority", "partner", "deal", "relationship"],
        "deep_dive": "Book: 'The Prince' by Machiavelli (Tim Parks translation)"
    },
    "seneca_on_time": {
        "name": "Seneca on Time",
        "domain": "history_philosophy",
        "author": "Seneca",
        "summary": "'It is not that we have a short time to live, but that we waste much of it.' Guard your time more zealously than your money. You can earn more money.",
        "keywords": ["time", "focus", "priority", "waste", "busy", "calendar", "schedule", "productivity", "efficiency", "distraction"],
        "deep_dive": "Essay: 'On the Shortness of Life' by Seneca (Penguin Great Ideas edition)"
    },
    "lindy_in_history": {
        "name": "The Lindy Heuristic in History",
        "domain": "history_philosophy",
        "author": "Various historians / Taleb",
        "summary": "What lasts has staying power. Ideas, institutions, and technologies that survive centuries (writing, trade, storytelling) are more robust than anything new.",
        "keywords": ["proven", "classic", "tradition", "lasting", "trust", "heritage", "brand", "endure", "timeless", "wisdom"],
        "deep_dive": "Book: 'Antifragile' by Taleb; 'Sapiens' by Yuval Noah Harari for historical framing"
    },
    "alexander_at_26": {
        "name": "Alexander the Great at 26",
        "domain": "history_philosophy",
        "author": "Historical",
        "summary": "By 26, Alexander had conquered the known world. Not through luck but through relentless ambition, learned mentorship (Aristotle), and speed of execution. Age is not an excuse.",
        "keywords": ["age", "young", "ambition", "speed", "execute", "lead", "bold", "grow", "vision", "founder"],
        "deep_dive": "Book: 'Alexander the Great' by Philip Freeman"
    },
    "renaissance_polymath": {
        "name": "The Renaissance Polymath Model",
        "domain": "history_philosophy",
        "author": "Da Vinci / Alberti / historical",
        "summary": "Wide competence, deep in one. Da Vinci was artist, engineer, anatomist, inventor. The modern version: T-shaped skills. Be dangerous in many domains, world-class in one.",
        "keywords": ["skill", "learn", "generalist", "specialist", "diverse", "creative", "build", "design", "multidisciplinary"],
        "deep_dive": "Book: 'Range' by David Epstein; 'Leonardo da Vinci' by Walter Isaacson"
    },
    "creative_destruction": {
        "name": "Creative Destruction",
        "domain": "history_philosophy",
        "author": "Joseph Schumpeter",
        "summary": "Innovation doesn't just create new value -- it destroys old value. The entrepreneur is the force of creative destruction. Embrace it or be destroyed by it.",
        "keywords": ["innovate", "disrupt", "change", "new", "technology", "replace", "obsolete", "transform", "market", "shift"],
        "deep_dive": "Book: 'Capitalism, Socialism and Democracy' by Schumpeter"
    },
    "pareto_elite": {
        "name": "The Pareto Elite",
        "domain": "history_philosophy",
        "author": "Vilfredo Pareto / historical pattern",
        "summary": "Throughout history, 20% of people create 80% of value. This isn't unfair -- it's physics. Be in the 20%. Then be in the 20% of the 20%.",
        "keywords": ["performance", "elite", "top", "excellence", "standard", "output", "results", "achieve", "productive"],
        "deep_dive": "Book: 'The 80/20 Principle' by Richard Koch; Pareto's original sociological work"
    },

    # =========================================================================
    # HEALTH & PERFORMANCE (~8)
    # =========================================================================

    "sleep_architecture": {
        "name": "Sleep Architecture",
        "domain": "health_performance",
        "author": "Matthew Walker",
        "summary": "7-8 hours is non-negotiable for cognition, emotional regulation, and physical recovery. Sleep debt cannot be repaid on weekends. Protect sleep like revenue.",
        "keywords": ["sleep", "rest", "recovery", "tired", "energy", "morning", "night", "fatigue", "cognitive", "performance"],
        "deep_dive": "Book: 'Why We Sleep' by Matthew Walker"
    },
    "zone_2_training": {
        "name": "Zone 2 Training",
        "domain": "health_performance",
        "author": "Dr. Peter Attia / Iñigo San Millán",
        "summary": "The aerobic base that enables everything else. Zone 2 = can hold a conversation but it's not easy. 3-4 hours per week transforms metabolic health and longevity.",
        "keywords": ["training", "cardio", "run", "walk", "exercise", "fitness", "heart", "endurance", "zone", "aerobic"],
        "deep_dive": "Peter Attia's podcast and blog on Zone 2; Book: 'Outlive' by Peter Attia"
    },
    "protein_leverage": {
        "name": "Protein Leverage Hypothesis",
        "domain": "health_performance",
        "author": "Simpson & Raubenheimer",
        "summary": "Humans eat until they get enough protein. If your food is low-protein, you'll overeat calories to hit the protein target. Prioritise protein first.",
        "keywords": ["protein", "diet", "nutrition", "meal", "food", "eating", "supplement", "health", "weight", "body"],
        "deep_dive": "Book: 'Eat Like the Animals' by Simpson & Raubenheimer"
    },
    "circadian_rhythm": {
        "name": "Circadian Rhythm",
        "domain": "health_performance",
        "author": "Andrew Huberman / circadian biology",
        "summary": "Light, temperature, and meal timing regulate your internal clock. Morning sunlight, cool sleeping environment, and consistent meal windows optimise everything downstream.",
        "keywords": ["morning", "light", "routine", "schedule", "energy", "timing", "sleep", "wake", "rhythm", "habit"],
        "deep_dive": "Huberman Lab podcast episodes on circadian biology; Book: 'The Circadian Code' by Satchin Panda"
    },
    "hormesis": {
        "name": "Hormesis",
        "domain": "health_performance",
        "author": "Biological principle",
        "summary": "Small stressors make you stronger. Cold exposure, fasting, exercise, heat stress -- controlled doses of discomfort trigger adaptive responses.",
        "keywords": ["cold", "fast", "fasting", "sauna", "stress", "exercise", "hard", "challenge", "adapt", "tough", "recovery"],
        "deep_dive": "Huberman Lab on deliberate cold exposure; Book: 'The Comfort Crisis' by Michael Easter"
    },
    "neuroplasticity": {
        "name": "Neuroplasticity Windows",
        "domain": "health_performance",
        "author": "Andrew Huberman / neuroscience",
        "summary": "Learning is biological. Your brain physically rewires during focused attention + sleep. Intense focus followed by rest creates lasting neural change. Learning is a skill.",
        "keywords": ["learn", "study", "focus", "brain", "skill", "practice", "improve", "master", "attention", "deep"],
        "deep_dive": "Huberman Lab podcast: 'How to Learn Faster'; Book: 'The Brain That Changes Itself' by Doidge"
    },
    "eisenhower_matrix": {
        "name": "The Eisenhower Matrix",
        "domain": "health_performance",
        "author": "Dwight D. Eisenhower",
        "summary": "Urgent vs Important. Most people live in urgent-unimportant. Leaders live in important-not-urgent. Schedule the important. Delegate or delete the rest.",
        "keywords": ["priority", "urgent", "important", "task", "schedule", "delegate", "focus", "time", "manage", "plan"],
        "deep_dive": "Book: 'First Things First' by Stephen Covey"
    },
    "deep_work": {
        "name": "Deep Work",
        "domain": "health_performance",
        "author": "Cal Newport",
        "summary": "Undistracted focus is a superpower in a distracted world. Schedule 2-4 hour blocks of zero-interruption deep work. Shallow work fills the gaps. Never reverse this.",
        "keywords": ["focus", "distraction", "work", "productivity", "block", "schedule", "concentrate", "attention", "output", "quality"],
        "deep_dive": "Book: 'Deep Work' by Cal Newport"
    },

    # =========================================================================
    # WEALTH & FINANCE (~8)
    # =========================================================================

    "asymmetric_bets": {
        "name": "Asymmetric Bets",
        "domain": "wealth_finance",
        "author": "Nassim Taleb / venture capital principle",
        "summary": "Small downside, massive upside. Structure decisions so you can't lose much but can win enormously. Startup investing, content creation, and experiments all follow this pattern.",
        "keywords": ["risk", "bet", "upside", "downside", "invest", "experiment", "test", "opportunity", "chance", "venture"],
        "deep_dive": "Book: 'The Black Swan' by Taleb; AngelList/Naval on venture math"
    },
    "cashflow_vs_capital_gains": {
        "name": "Cash Flow vs Capital Gains",
        "domain": "wealth_finance",
        "author": "Fundamental finance",
        "summary": "Cash flow = income you can spend now. Capital gains = appreciation you realise later. Most wealth is built on cash flow. Don't confuse paper gains with real money.",
        "keywords": ["revenue", "income", "profit", "cash", "flow", "payment", "subscription", "recurring", "money", "margin"],
        "deep_dive": "Book: 'Rich Dad Poor Dad' by Kiyosaki (despite its flaws, this distinction is solid)"
    },
    "kelly_criterion": {
        "name": "The Kelly Criterion",
        "domain": "wealth_finance",
        "author": "John Larry Kelly Jr.",
        "summary": "Optimal bet sizing based on your edge. Bet proportional to your advantage, not your conviction. Overbetting with an edge still leads to ruin.",
        "keywords": ["budget", "spend", "allocate", "invest", "risk", "bet", "size", "proportion", "aggressive", "conservative"],
        "deep_dive": "Book: 'Fortune's Formula' by William Poundstone"
    },
    "margin_of_safety": {
        "name": "Margin of Safety",
        "domain": "wealth_finance",
        "author": "Benjamin Graham",
        "summary": "Buffer against being wrong. Never invest (or plan) assuming the best case. Build in room for error, delays, and bad luck.",
        "keywords": ["buffer", "conservative", "plan", "forecast", "projection", "safe", "cushion", "contingency", "risk", "error"],
        "deep_dive": "Book: 'The Intelligent Investor' by Benjamin Graham"
    },
    "skin_in_the_game": {
        "name": "Skin in the Game",
        "domain": "wealth_finance",
        "author": "Nassim Nicholas Taleb",
        "summary": "Don't trust advice from people who don't bear the consequences. Alignment of incentives is everything. If they don't eat their own cooking, walk away.",
        "keywords": ["incentive", "align", "trust", "advisor", "consultant", "agency", "partner", "accountability", "risk", "vendor"],
        "deep_dive": "Book: 'Skin in the Game' by Nassim Nicholas Taleb"
    },
    "optionality": {
        "name": "Optionality",
        "domain": "wealth_finance",
        "author": "Nassim Taleb / finance",
        "summary": "Keep doors open, reduce irreversible decisions. Options have value even if you never exercise them. Build flexibility into everything.",
        "keywords": ["option", "flexible", "reversible", "decision", "pivot", "change", "adapt", "alternative", "choice", "hedge"],
        "deep_dive": "Book: 'Antifragile' by Taleb (optionality chapter); options theory in finance"
    },
    "time_value_of_money": {
        "name": "Time Value of Money",
        "domain": "wealth_finance",
        "author": "Fundamental finance",
        "summary": "A dollar today is worth more than a dollar tomorrow. Because you can invest it, compound it, or deploy it. Speed of execution has financial value.",
        "keywords": ["cash", "now", "delay", "speed", "quick", "payment", "terms", "invoice", "collect", "receive", "time"],
        "deep_dive": "Any introductory finance textbook; Damodaran's NYU valuation course (free on YouTube)"
    },
    "wealth_equation": {
        "name": "The Wealth Equation",
        "domain": "wealth_finance",
        "author": "Naval Ravikant",
        "summary": "Specific knowledge + leverage + accountability = wealth. Specific knowledge is found by pursuing your genuine curiosity. Leverage through code, media, capital.",
        "keywords": ["wealth", "build", "knowledge", "leverage", "accountability", "ai", "code", "media", "brand", "create", "own"],
        "deep_dive": "The Almanack of Naval Ravikant by Eric Jorgenson (free online)"
    },
}

# Domain display names for pretty output
DOMAIN_DISPLAY = {
    "mental_models":         "Mental Models",
    "strategy_business":     "Strategy & Business",
    "psychology_persuasion": "Psychology & Persuasion",
    "history_philosophy":    "History & Philosophy",
    "health_performance":    "Health & Performance",
    "wealth_finance":        "Wealth & Finance",
}


# =============================================================================
# READING LOG DATABASE
# =============================================================================

class ReadingLog:
    """SQLite-backed reading log with WAL mode. Tracks delivered readings and feedback."""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS readings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                concept_key TEXT NOT NULL,
                concept_name TEXT NOT NULL,
                domain TEXT NOT NULL,
                relevance_score REAL NOT NULL,
                context_summary TEXT,
                selection_type TEXT NOT NULL DEFAULT 'primary',
                delivered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reading_id INTEGER NOT NULL,
                rating INTEGER CHECK(rating BETWEEN 1 AND 5),
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (reading_id) REFERENCES readings(id)
            );

            CREATE INDEX IF NOT EXISTS idx_readings_date ON readings(date);
            CREATE INDEX IF NOT EXISTS idx_readings_concept ON readings(concept_key);
            CREATE INDEX IF NOT EXISTS idx_readings_domain ON readings(domain);
            CREATE INDEX IF NOT EXISTS idx_feedback_reading ON feedback(reading_id);
        """)
        self.conn.commit()

    def log_reading(self, concept_key: str, concept_name: str, domain: str,
                    relevance_score: float, context_summary: str,
                    selection_type: str = "primary",
                    reading_date: str = None) -> int:
        """Log a delivered reading. Returns the reading ID."""
        reading_date = reading_date or date.today().isoformat()
        cursor = self.conn.execute(
            """INSERT INTO readings (date, concept_key, concept_name, domain,
               relevance_score, context_summary, selection_type)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (reading_date, concept_key, concept_name, domain,
             relevance_score, context_summary, selection_type)
        )
        self.conn.commit()
        return cursor.lastrowid

    def log_feedback(self, reading_id: int, rating: int, notes: str = None):
        """Log feedback for a reading."""
        self.conn.execute(
            "INSERT INTO feedback (reading_id, rating, notes) VALUES (?, ?, ?)",
            (reading_id, rating, notes)
        )
        self.conn.commit()

    def get_recent_concepts(self, days: int = REPEAT_COOLDOWN_DAYS) -> set:
        """Get concept keys delivered within the last N days."""
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        rows = self.conn.execute(
            "SELECT DISTINCT concept_key FROM readings WHERE date > ?",
            (cutoff,)
        ).fetchall()
        return {r["concept_key"] for r in rows}

    def get_domain_engagement(self) -> dict:
        """Get average feedback rating per domain to learn Tom's preferences."""
        rows = self.conn.execute(
            """SELECT r.domain, AVG(f.rating) as avg_rating, COUNT(f.id) as feedback_count
               FROM readings r
               LEFT JOIN feedback f ON f.reading_id = r.id
               WHERE f.rating IS NOT NULL
               GROUP BY r.domain
               ORDER BY avg_rating DESC"""
        ).fetchall()
        return {r["domain"]: {"avg_rating": r["avg_rating"],
                               "feedback_count": r["feedback_count"]}
                for r in rows}

    def get_history(self, limit: int = 30) -> list:
        """Get reading history with optional feedback."""
        rows = self.conn.execute(
            """SELECT r.*, f.rating, f.notes as feedback_notes
               FROM readings r
               LEFT JOIN feedback f ON f.reading_id = r.id
               ORDER BY r.delivered_at DESC
               LIMIT ?""",
            (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Get overall reading statistics."""
        stats = {}
        stats["total_readings"] = self.conn.execute(
            "SELECT COUNT(*) FROM readings"
        ).fetchone()[0]
        stats["total_feedback"] = self.conn.execute(
            "SELECT COUNT(*) FROM feedback"
        ).fetchone()[0]
        stats["avg_rating"] = self.conn.execute(
            "SELECT AVG(rating) FROM feedback"
        ).fetchone()[0]
        stats["unique_concepts"] = self.conn.execute(
            "SELECT COUNT(DISTINCT concept_key) FROM readings"
        ).fetchone()[0]
        stats["domains_covered"] = self.conn.execute(
            "SELECT COUNT(DISTINCT domain) FROM readings"
        ).fetchone()[0]

        # Concepts by domain
        rows = self.conn.execute(
            """SELECT domain, COUNT(*) as cnt FROM readings
               GROUP BY domain ORDER BY cnt DESC"""
        ).fetchall()
        stats["readings_by_domain"] = {r["domain"]: r["cnt"] for r in rows}

        return stats

    def close(self):
        """Close the database connection."""
        self.conn.close()


# =============================================================================
# CONTEXT ANALYSIS
# =============================================================================

def _safe_db_query(db_path: str, query: str, params: tuple = ()) -> list:
    """Execute a query against a sibling database, returning [] if it doesn't exist."""
    if not os.path.exists(db_path):
        return []
    try:
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        rows = conn.execute(query, params).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.debug(f"Could not query {db_path}: {e}")
        return []


def analyse_today_context() -> dict:
    """
    Read the day's context from all available sources:
      - Agent state files (CONTEXT.md)
      - Decision logger (today's decisions)
      - Event bus (today's events)
      - Learning DB (recent insights)
      - Intelligence DB (recent cycles, events)

    Returns a structured dict:
      {
          "domains": [...],       # Active domains today
          "challenges": [...],    # Problems/issues detected
          "decisions": [...],     # Decisions made today
          "events": [...],        # Notable events today
          "themes": [...],        # Recurring keywords/topics
          "raw_text": "..."       # Combined text for keyword matching
      }
    """
    today_str = date.today().isoformat()
    context = {
        "domains": set(),
        "challenges": [],
        "decisions": [],
        "events": [],
        "themes": [],
        "raw_text": "",
    }

    raw_text_parts = []

    # --- 1. Agent state files ---
    for agent in ALL_AGENTS:
        state_path = AGENTS_DIR / agent / "state" / "CONTEXT.md"
        if state_path.exists():
            try:
                text = state_path.read_text(encoding="utf-8")
                raw_text_parts.append(text)
                # Detect domains from agent name
                if agent in ("dbh-marketing", "pure-pets"):
                    context["domains"].add("marketing")
                    context["domains"].add("ecommerce")
                elif agent == "global-events":
                    context["domains"].add("geopolitics")
                elif agent == "health-fitness":
                    context["domains"].add("health")
                    context["domains"].add("fitness")
                elif agent == "new-business":
                    context["domains"].add("business")
                    context["domains"].add("technology")
                elif agent == "creative-projects":
                    context["domains"].add("creative")
                elif agent == "social":
                    context["domains"].add("social")
                elif agent == "strategic-advisor":
                    context["domains"].add("strategy")
                    context["domains"].add("finance")
            except Exception as e:
                logger.debug(f"Could not read state for {agent}: {e}")

    # --- 2. Decision logger (today's decisions) ---
    decisions = _safe_db_query(
        str(DECISIONS_DB_PATH),
        "SELECT * FROM decisions WHERE date(created_at) = ? ORDER BY created_at DESC",
        (today_str,)
    )
    for d in decisions:
        context["decisions"].append({
            "agent": d.get("agent", "unknown"),
            "title": d.get("title", d.get("decision", "")),
            "type": d.get("decision_type", d.get("status", "")),
            "reasoning": d.get("reasoning", d.get("rationale", "")),
        })
        raw_text_parts.append(d.get("title", ""))
        raw_text_parts.append(d.get("reasoning", d.get("rationale", "")))

    # --- 3. Event bus (today's events) ---
    events = _safe_db_query(
        str(EVENT_BUS_DB_PATH),
        """SELECT * FROM events WHERE date(created_at) = ?
           ORDER BY CASE severity
             WHEN 'CRITICAL' THEN 0
             WHEN 'IMPORTANT' THEN 1
             WHEN 'NOTABLE' THEN 2
             WHEN 'INFO' THEN 3
           END, created_at DESC""",
        (today_str,)
    )
    for e in events:
        payload = {}
        try:
            payload = json.loads(e.get("payload", "{}"))
        except (json.JSONDecodeError, TypeError):
            pass
        context["events"].append({
            "source": e.get("source_agent", "unknown"),
            "type": e.get("event_type", ""),
            "severity": e.get("severity", "INFO"),
            "payload": payload,
        })
        raw_text_parts.append(e.get("event_type", ""))
        raw_text_parts.append(json.dumps(payload))

    # --- 4. Learning DB (recent insights, last 3 days to catch trends) ---
    insights = _safe_db_query(
        str(LEARNING_DB_PATH),
        """SELECT * FROM insights WHERE created_at > datetime('now', '-3 days')
           ORDER BY created_at DESC LIMIT 30"""
    )
    for i in insights:
        raw_text_parts.append(i.get("content", i.get("insight", "")))
        raw_text_parts.append(i.get("category", i.get("domain", "")))
        raw_text_parts.append(i.get("tags", ""))

    # --- 5. Intelligence DB (recent events and decisions) ---
    intel_events = _safe_db_query(
        str(INTELLIGENCE_DB_PATH),
        """SELECT * FROM events WHERE created_at > datetime('now', '-1 day')
           ORDER BY created_at DESC LIMIT 20"""
    )
    for e in intel_events:
        raw_text_parts.append(e.get("title", ""))
        raw_text_parts.append(e.get("description", ""))

    intel_decisions = _safe_db_query(
        str(INTELLIGENCE_DB_PATH),
        """SELECT * FROM decisions WHERE created_at > datetime('now', '-1 day')
           ORDER BY created_at DESC LIMIT 20"""
    )
    for d in intel_decisions:
        context["decisions"].append({
            "agent": d.get("agent", "unknown"),
            "title": d.get("decision", ""),
            "type": d.get("status", ""),
            "reasoning": d.get("reasoning", ""),
        })
        raw_text_parts.append(d.get("decision", ""))
        raw_text_parts.append(d.get("reasoning", ""))

    # --- Build combined raw text for keyword matching ---
    context["raw_text"] = " ".join(
        str(part) for part in raw_text_parts if part
    ).lower()

    # --- Extract themes from raw text frequency ---
    context["themes"] = _extract_themes(context["raw_text"])

    # --- Detect challenges from keywords ---
    challenge_indicators = [
        "drop", "decline", "fail", "error", "issue", "problem",
        "risk", "churn", "low", "delay", "critical", "warning",
        "overspend", "loss", "stuck", "blocked",
    ]
    for indicator in challenge_indicators:
        if indicator in context["raw_text"]:
            context["challenges"].append(indicator)

    # Convert domains set to list for serialisation
    context["domains"] = list(context["domains"])

    return context


def _extract_themes(raw_text: str) -> list:
    """Extract the most frequent meaningful themes from combined text."""
    # Business-relevant theme words to look for
    theme_words = [
        "revenue", "growth", "customer", "campaign", "email", "meta", "ads",
        "roas", "conversion", "brand", "product", "strategy", "market",
        "competitor", "price", "budget", "spend", "profit", "margin",
        "team", "design", "creative", "content", "social", "tariff",
        "health", "fitness", "training", "nutrition", "sleep",
        "risk", "invest", "cash", "flow", "scale", "system",
        "automation", "ai", "data", "platform", "launch", "test",
        "learn", "improve", "decision", "focus", "priority",
    ]

    word_counts = {}
    for word in theme_words:
        count = raw_text.count(word)
        if count > 0:
            word_counts[word] = count

    # Return top themes sorted by frequency
    sorted_themes = sorted(word_counts.items(), key=lambda x: -x[1])
    return [theme for theme, _count in sorted_themes[:15]]


# =============================================================================
# KNOWLEDGE SELECTION
# =============================================================================

def score_concept(concept_key: str, concept: dict, context: dict) -> float:
    """
    Score a knowledge concept against the day's context.

    Scoring factors:
      1. Keyword overlap between concept keywords and today's raw text
      2. Domain relevance (concept domain matches active domains)
      3. Challenge relevance (concept keywords match detected challenges)
      4. Theme alignment (concept keywords match extracted themes)
    """
    score = 0.0
    raw_text = context.get("raw_text", "")
    active_domains = set(context.get("domains", []))
    challenges = set(context.get("challenges", []))
    themes = set(context.get("themes", []))
    keywords = concept.get("keywords", [])

    # --- 1. Keyword overlap with raw text (0-5 points) ---
    keyword_hits = sum(1 for kw in keywords if kw in raw_text)
    score += min(keyword_hits * 0.5, 5.0)

    # --- 2. Domain relevance (0-3 points) ---
    domain_map = {
        "mental_models":         {"strategy", "business", "marketing", "technology"},
        "strategy_business":     {"marketing", "ecommerce", "business", "strategy"},
        "psychology_persuasion": {"marketing", "ecommerce", "social", "creative"},
        "history_philosophy":    {"strategy", "business", "geopolitics"},
        "health_performance":    {"health", "fitness"},
        "wealth_finance":        {"finance", "business", "strategy", "ecommerce"},
    }
    concept_domains = domain_map.get(concept["domain"], set())
    domain_overlap = len(concept_domains & active_domains)
    score += min(domain_overlap * 1.0, 3.0)

    # --- 3. Challenge relevance (0-3 points) ---
    challenge_keywords = {
        "drop": ["inversion", "antifragility", "margin_of_safety", "loss_aversion"],
        "decline": ["inversion", "flywheel_effect", "unit_economics"],
        "fail": ["inversion", "survivorship_bias", "lean_startup"],
        "error": ["occams_razor", "hanlons_razor", "margin_of_safety"],
        "risk": ["antifragility", "barbell_strategy", "asymmetric_bets", "margin_of_safety"],
        "churn": ["jobs_to_be_done", "peak_end_rule", "commitment_consistency"],
        "overspend": ["unit_economics", "kelly_criterion", "opportunity_cost"],
        "loss": ["loss_aversion", "margin_of_safety", "stoicism"],
        "stuck": ["first_principles", "via_negativa", "deep_work"],
        "blocked": ["stoicism", "eisenhower_matrix", "via_negativa"],
    }
    for challenge in challenges:
        if concept_key in challenge_keywords.get(challenge, []):
            score += 1.5

    # --- 4. Theme alignment (0-3 points) ---
    theme_hits = sum(1 for kw in keywords if kw in themes)
    score += min(theme_hits * 0.75, 3.0)

    # --- 5. Decision count bonus (more decisions = value more reflective concepts) ---
    if len(context.get("decisions", [])) >= 3:
        reflective_concepts = {
            "second_order_thinking", "inversion", "opportunity_cost",
            "circle_of_competence", "eisenhower_matrix", "stoicism",
        }
        if concept_key in reflective_concepts:
            score += 1.0

    return round(score, 2)


def select_evening_reading(context: dict, reading_log: ReadingLog = None) -> dict:
    """
    Score all concepts against today's context and select:
      - TOP concept (highest relevance score)
      - WILDCARD concept (highest-scoring from a DIFFERENT domain, for breadth)

    Respects the 30-day cooldown on recently delivered concepts.

    Returns:
      {
          "primary": {"key": ..., "concept": ..., "score": ..., "reason": ...},
          "wildcard": {"key": ..., "concept": ..., "score": ..., "reason": ...},
          "all_scores": [(key, score), ...]  # for diagnostics
      }
    """
    log = reading_log or ReadingLog()
    recent_concepts = log.get_recent_concepts()

    # Score every concept
    scored = []
    for key, concept in KNOWLEDGE_LIBRARY.items():
        if key in recent_concepts:
            continue  # Skip recently delivered
        s = score_concept(key, concept, context)
        scored.append((key, s))

    scored.sort(key=lambda x: -x[1])

    if not scored:
        # All concepts delivered recently -- reset by picking least-recently used
        logger.warning("All concepts delivered within cooldown period. Selecting from full library.")
        for key, concept in KNOWLEDGE_LIBRARY.items():
            s = score_concept(key, concept, context)
            scored.append((key, s))
        scored.sort(key=lambda x: -x[1])

    # Primary: highest score
    primary_key, primary_score = scored[0]
    primary_concept = KNOWLEDGE_LIBRARY[primary_key]
    primary_domain = primary_concept["domain"]

    # Build relevance explanation for primary
    primary_reason = _build_relevance_reason(primary_key, primary_concept, context)

    # Wildcard: highest score from a DIFFERENT domain
    wildcard_key = None
    wildcard_score = 0.0
    wildcard_concept = None
    for key, s in scored[1:]:
        if KNOWLEDGE_LIBRARY[key]["domain"] != primary_domain:
            wildcard_key = key
            wildcard_score = s
            wildcard_concept = KNOWLEDGE_LIBRARY[key]
            break

    # Fallback: if all remaining are same domain, just pick #2
    if wildcard_key is None and len(scored) > 1:
        wildcard_key, wildcard_score = scored[1]
        wildcard_concept = KNOWLEDGE_LIBRARY[wildcard_key]

    wildcard_reason = ""
    if wildcard_key:
        wildcard_reason = _build_relevance_reason(wildcard_key, wildcard_concept, context)

    result = {
        "primary": {
            "key": primary_key,
            "concept": primary_concept,
            "score": primary_score,
            "reason": primary_reason,
        },
        "wildcard": {
            "key": wildcard_key,
            "concept": wildcard_concept,
            "score": wildcard_score,
            "reason": wildcard_reason,
        } if wildcard_key else None,
        "all_scores": scored[:20],  # Top 20 for diagnostics
    }

    if reading_log is None:
        log.close()

    return result


def _build_relevance_reason(concept_key: str, concept: dict, context: dict) -> str:
    """Build a human-readable explanation of why this concept was selected."""
    reasons = []
    raw_text = context.get("raw_text", "")
    keywords = concept.get("keywords", [])

    matched_keywords = [kw for kw in keywords if kw in raw_text]
    if matched_keywords:
        reasons.append(f"Keyword matches: {', '.join(matched_keywords[:5])}")

    if context.get("decisions"):
        decision_titles = [d.get("title", "") for d in context["decisions"][:3]]
        reasons.append(f"Today's decisions: {'; '.join(t for t in decision_titles if t)[:150]}")

    if context.get("challenges"):
        reasons.append(f"Challenges detected: {', '.join(context['challenges'][:5])}")

    if context.get("themes"):
        theme_overlap = [t for t in context["themes"][:5] if t in keywords]
        if theme_overlap:
            reasons.append(f"Theme alignment: {', '.join(theme_overlap)}")

    return " | ".join(reasons) if reasons else "General relevance to active domains"


# =============================================================================
# FORMAT FOR DELIVERY
# =============================================================================

def format_evening_reading(selection: dict, context: dict) -> str:
    """
    Generate a formatted prompt instruction for Claude to deliver the evening reading.

    This is NOT the reading itself -- it's the instructions Claude uses to generate
    the reading in Sage's voice, personalised to Tom's day.

    Returns a string to be used as the system/user prompt for the Sage agent.
    """
    primary = selection["primary"]
    wildcard = selection.get("wildcard")
    concept = primary["concept"]

    # Build context summary for the prompt
    decisions_text = ""
    if context.get("decisions"):
        decision_lines = []
        for d in context["decisions"][:5]:
            agent_display = AGENT_DISPLAY.get(d.get("agent", ""), d.get("agent", ""))
            title = d.get("title", "")
            if title:
                decision_lines.append(f"  - [{agent_display}] {title}")
        if decision_lines:
            decisions_text = "\n".join(decision_lines)

    events_text = ""
    if context.get("events"):
        event_lines = []
        for e in context["events"][:5]:
            source_display = AGENT_DISPLAY.get(e.get("source", ""), e.get("source", ""))
            event_type = e.get("type", "")
            severity = e.get("severity", "")
            if event_type:
                event_lines.append(f"  - [{severity}] {event_type} (from {source_display})")
        if event_lines:
            events_text = "\n".join(event_lines)

    themes_text = ", ".join(context.get("themes", [])[:10])
    challenges_text = ", ".join(context.get("challenges", [])[:5])

    # Build the wildcard teaser
    wildcard_section = ""
    if wildcard:
        wc = wildcard["concept"]
        wildcard_section = f"""

WILDCARD CONCEPT (briefly tease, 2-3 sentences max):
  Name: {wc['name']}
  Domain: {DOMAIN_DISPLAY.get(wc['domain'], wc['domain'])}
  Core idea: {wc['summary']}
  Why it connects: {wildcard['reason']}

End with a teaser like: "Tomorrow we might explore how {wc['name']} connects to what you're building. Something to sit with."
"""

    prompt = f"""You are Sage, Tom's evening reading companion. Your job is to teach one foundational concept per evening, connected DIRECTLY to what Tom dealt with today.

TONIGHT'S CONCEPT:
  Name: {concept['name']}
  Domain: {DOMAIN_DISPLAY.get(concept['domain'], concept['domain'])}
  Thinker: {concept['author']}
  Core idea: {concept['summary']}
  Relevance score: {primary['score']}/14.0
  Why selected: {primary['reason']}

TODAY'S CONTEXT (reference these specifically):
  Active domains: {', '.join(context.get('domains', ['general']))}
  Key themes: {themes_text or 'No specific themes detected'}
  Challenges: {challenges_text or 'No specific challenges detected'}

  Decisions made today:
{decisions_text or '  (No decisions logged today)'}

  Events today:
{events_text or '  (No events logged today)'}
{wildcard_section}
DELIVERY INSTRUCTIONS:
1. Teach the concept in ~500-800 words
2. Start with a hook -- a vivid story, quote, or scenario. Never start with "Today we're going to learn about..."
3. Connect it DIRECTLY to something from Tom's day. Reference a specific decision, event, or challenge by name
4. Make it feel like a conversation between equals, not a lecture
5. Give ONE practical exercise or reflection question Tom can sit with tonight
6. Suggest a deep dive: {concept['deep_dive']}
7. End with the wildcard teaser (if provided above)

FORMAT RULES (Telegram-friendly):
- No markdown tables
- Short paragraphs (2-3 sentences max)
- Use bullet points for lists
- Bold key terms with *asterisks*
- Use line breaks liberally
- No emojis unless they genuinely add meaning
- Conversational tone -- this is 8:30pm, Tom is winding down
- Sign off as Sage"""

    return prompt


# =============================================================================
# MAIN API -- Called by the orchestrator
# =============================================================================

def get_tonight_reading() -> dict:
    """
    Full pipeline: analyse context -> select concepts -> format prompt.

    Returns:
      {
          "prompt": str,           # Ready-to-use prompt for Claude
          "primary_concept": str,  # Name of the primary concept
          "primary_key": str,      # Key for logging
          "primary_domain": str,   # Domain
          "primary_score": float,  # Relevance score
          "wildcard_concept": str, # Name of wildcard (or None)
          "wildcard_key": str,
          "context_summary": str,  # Brief context description
      }
    """
    log = ReadingLog()

    # 1. Analyse today's context
    context = analyse_today_context()

    # 2. Select concepts
    selection = select_evening_reading(context, reading_log=log)

    # 3. Format prompt
    prompt = format_evening_reading(selection, context)

    # 4. Log the reading
    primary = selection["primary"]
    context_summary = f"Domains: {', '.join(context.get('domains', []))}; " \
                      f"Themes: {', '.join(context.get('themes', [])[:5])}; " \
                      f"Decisions: {len(context.get('decisions', []))}; " \
                      f"Events: {len(context.get('events', []))}"

    log.log_reading(
        concept_key=primary["key"],
        concept_name=primary["concept"]["name"],
        domain=primary["concept"]["domain"],
        relevance_score=primary["score"],
        context_summary=context_summary,
        selection_type="primary",
    )

    wildcard = selection.get("wildcard")
    wildcard_concept_name = None
    wildcard_key = None
    if wildcard and wildcard.get("concept"):
        log.log_reading(
            concept_key=wildcard["key"],
            concept_name=wildcard["concept"]["name"],
            domain=wildcard["concept"]["domain"],
            relevance_score=wildcard["score"],
            context_summary=context_summary,
            selection_type="wildcard",
        )
        wildcard_concept_name = wildcard["concept"]["name"]
        wildcard_key = wildcard["key"]

    log.close()

    return {
        "prompt": prompt,
        "primary_concept": primary["concept"]["name"],
        "primary_key": primary["key"],
        "primary_domain": primary["concept"]["domain"],
        "primary_score": primary["score"],
        "wildcard_concept": wildcard_concept_name,
        "wildcard_key": wildcard_key,
        "context_summary": context_summary,
    }


def get_concept_list() -> dict:
    """Return all concepts organised by domain."""
    by_domain = {}
    for key, concept in KNOWLEDGE_LIBRARY.items():
        domain = concept["domain"]
        if domain not in by_domain:
            by_domain[domain] = []
        by_domain[domain].append({
            "key": key,
            "name": concept["name"],
            "author": concept["author"],
            "summary": concept["summary"],
        })
    return by_domain


def get_top_candidates(n: int = 5) -> list:
    """Score all concepts against today's context and return top N with scores."""
    context = analyse_today_context()
    log = ReadingLog()
    recent = log.get_recent_concepts()
    log.close()

    scored = []
    for key, concept in KNOWLEDGE_LIBRARY.items():
        s = score_concept(key, concept, context)
        recently_delivered = key in recent
        scored.append({
            "key": key,
            "name": concept["name"],
            "domain": concept["domain"],
            "author": concept["author"],
            "score": s,
            "recently_delivered": recently_delivered,
        })

    scored.sort(key=lambda x: -x["score"])
    return scored[:n]


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    def print_usage():
        print("Knowledge Engine -- Sage Evening Reading")
        print("=" * 55)
        print("Commands:")
        print("  python -m core.knowledge_engine today       -- What would tonight's reading be?")
        print("  python -m core.knowledge_engine concepts    -- List all concepts by domain")
        print("  python -m core.knowledge_engine history     -- Show reading log")
        print("  python -m core.knowledge_engine suggest     -- Show top 5 candidates with scores")
        print()
        print(f"Library: {len(KNOWLEDGE_LIBRARY)} concepts across {len(DOMAIN_DISPLAY)} domains")
        print(f"Database: {DB_PATH}")

    if len(sys.argv) < 2:
        print_usage()
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "today":
        print("Analysing today's context...")
        print()
        result = get_tonight_reading()

        print(f"PRIMARY CONCEPT: {result['primary_concept']}")
        print(f"  Domain:    {DOMAIN_DISPLAY.get(result['primary_domain'], result['primary_domain'])}")
        print(f"  Score:     {result['primary_score']}/14.0")
        if result["wildcard_concept"]:
            print(f"  Wildcard:  {result['wildcard_concept']}")
        print(f"  Context:   {result['context_summary']}")
        print()
        print("-" * 55)
        print("GENERATED PROMPT:")
        print("-" * 55)
        print(result["prompt"])

    elif cmd == "concepts":
        by_domain = get_concept_list()
        total = 0
        for domain_key in DOMAIN_DISPLAY:
            concepts = by_domain.get(domain_key, [])
            display_name = DOMAIN_DISPLAY[domain_key]
            print(f"\n{'=' * 50}")
            print(f"  {display_name} ({len(concepts)} concepts)")
            print(f"{'=' * 50}")
            for c in concepts:
                print(f"  {c['key']:30s} | {c['name']}")
                print(f"  {'':30s} | {c['author']}")
                print(f"  {'':30s} | {c['summary'][:80]}...")
                print()
                total += 1
        print(f"Total: {total} concepts across {len(DOMAIN_DISPLAY)} domains")

    elif cmd == "history":
        log = ReadingLog()
        history = log.get_history()
        stats = log.get_stats()

        if not history:
            print("No readings delivered yet.")
            print("Run 'python -m core.knowledge_engine today' to generate the first one.")
        else:
            print("Reading History")
            print("=" * 60)
            for r in history:
                rating_str = f" [rated {r['rating']}/5]" if r.get("rating") else ""
                domain_display = DOMAIN_DISPLAY.get(r["domain"], r["domain"])
                print(f"  {r['date']} | {r['concept_name']:30s} | {domain_display}")
                print(f"           | Score: {r['relevance_score']:.1f} | {r['selection_type']}{rating_str}")
                if r.get("feedback_notes"):
                    print(f"           | Feedback: {r['feedback_notes']}")
                print()

            print("-" * 60)
            print(f"Total readings: {stats['total_readings']}")
            print(f"Unique concepts: {stats['unique_concepts']}")
            avg = stats.get('avg_rating')
            if avg:
                print(f"Average rating: {avg:.1f}/5")
            if stats.get("readings_by_domain"):
                print("Readings by domain:")
                for domain, count in stats["readings_by_domain"].items():
                    print(f"  {DOMAIN_DISPLAY.get(domain, domain):30s} {count:>4d}")

        # Show engagement data
        engagement = log.get_domain_engagement()
        if engagement:
            print()
            print("Domain Engagement (from feedback):")
            for domain, data in engagement.items():
                print(f"  {DOMAIN_DISPLAY.get(domain, domain):30s} "
                      f"avg rating: {data['avg_rating']:.1f} "
                      f"({data['feedback_count']} ratings)")

        log.close()

    elif cmd == "suggest":
        print("Scoring all concepts against today's context...")
        print()
        candidates = get_top_candidates(n=10)

        log = ReadingLog()
        recent = log.get_recent_concepts()
        log.close()

        print(f"{'Rank':>4s} | {'Score':>5s} | {'Concept':30s} | {'Domain':25s} | {'Status'}")
        print("-" * 100)
        for i, c in enumerate(candidates, 1):
            domain_display = DOMAIN_DISPLAY.get(c["domain"], c["domain"])
            status = "COOLDOWN" if c["recently_delivered"] else "available"
            marker = ">>>" if i == 1 and not c["recently_delivered"] else "   "
            print(f"{marker}{i:>2d}. | {c['score']:>5.1f} | {c['name']:30s} | {domain_display:25s} | {status}")

        print()
        print(f"Library: {len(KNOWLEDGE_LIBRARY)} concepts | "
              f"On cooldown: {len(recent)} | "
              f"Available: {len(KNOWLEDGE_LIBRARY) - len(recent)}")

    else:
        print(f"Unknown command: {cmd}")
        print()
        print_usage()
