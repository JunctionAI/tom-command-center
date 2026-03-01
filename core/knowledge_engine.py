#!/usr/bin/env python3
"""
Knowledge Engine -- ASI Life Mentor Intelligence

The intellectual engine behind ASI, Tom's life mentor.
Every evening, ASI reads the day's context (agent states, decisions, events,
learning insights) and selects the most profoundly relevant concept to teach --
not just business knowledge, but foundational understanding of reality itself.

The goal: over months and years, Tom builds an expanded consciousness that
connects physics to philosophy, evolutionary biology to business strategy,
Stoic wisdom to modern neuroscience. Each reading shifts how he SEES reality,
not just what he knows.

Architecture:
  1. KNOWLEDGE_LIBRARY -- 120+ concepts across 10 domains (the full human canon)
  2. analyse_today_context() -- reads agent states, decisions, events, learning DB
  3. select_evening_reading() -- scores concepts vs today's context, picks best + wildcard
  4. format_evening_reading() -- generates prompt instructions for Claude delivery
  5. Reading log at data/reading_log.db -- prevents repeats, tracks engagement

Domains: Physics, Philosophy, Psychology, Biology, History, Mathematics,
         Systems, Health, Creativity, Ethics

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
    "evening-reading":   "ASI",
}

# How many days before a concept can repeat
REPEAT_COOLDOWN_DAYS = 30


# =============================================================================
# KNOWLEDGE LIBRARY
# =============================================================================
# Each concept is keyed by a unique slug. Fields:
#   name:        Human-readable name
#   domain:      One of the 10 ASI domain categories
#   author:      Primary thinker associated (for attribution)
#   summary:     1-2 sentence core idea
#   keywords:    List of keywords for context matching
#   deep_dive:   Book/essay/video recommendation for further reading

KNOWLEDGE_LIBRARY = {

    # =========================================================================
    # PHYSICS & COSMOLOGY (~12)
    # The nature of reality itself
    # =========================================================================

    "entropy": {
        "name": "Entropy & The Arrow of Time",
        "domain": "physics_cosmology",
        "author": "Ludwig Boltzmann / Rudolf Clausius",
        "summary": "Everything tends toward disorder. The second law of thermodynamics isn't just physics -- it's why campaigns decay, relationships require maintenance, and businesses die without energy input.",
        "keywords": ["decay", "decline", "maintenance", "energy", "effort", "system", "order", "chaos", "deteriorate", "sustain"],
        "deep_dive": "Book: 'The Order of Time' by Carlo Rovelli"
    },
    "emergence": {
        "name": "Emergence",
        "domain": "physics_cosmology",
        "author": "Philip Anderson / complexity science",
        "summary": "Complex behaviour arises from simple rules. Consciousness from neurons. Markets from transactions. Culture from conversations. The whole is genuinely more than its parts.",
        "keywords": ["complex", "system", "simple", "pattern", "emerge", "agent", "network", "culture", "build", "compound"],
        "deep_dive": "Book: 'Emergence' by Steven Johnson; Anderson's paper 'More Is Different' (1972)"
    },
    "quantum_superposition": {
        "name": "Quantum Superposition & Observation",
        "domain": "physics_cosmology",
        "author": "Niels Bohr / Werner Heisenberg",
        "summary": "Before measurement, a particle exists in ALL possible states simultaneously. The act of observation collapses possibility into reality. What you choose to measure changes what exists.",
        "keywords": ["measure", "observe", "possibility", "decision", "choose", "focus", "attention", "metrics", "data", "reality"],
        "deep_dive": "Book: 'QED' by Richard Feynman; 'Something Deeply Hidden' by Sean Carroll"
    },
    "relativity_of_perspective": {
        "name": "Relativity of Perspective",
        "domain": "physics_cosmology",
        "author": "Albert Einstein",
        "summary": "Time and space are not absolute -- they depend on where you're standing. Two observers can see the same event completely differently and BOTH be right. Truth depends on frame of reference.",
        "keywords": ["perspective", "viewpoint", "different", "customer", "position", "frame", "relative", "perception", "context"],
        "deep_dive": "Book: 'Einstein's Dreams' by Alan Lightman (fiction that makes relativity visceral)"
    },
    "pale_blue_dot": {
        "name": "The Pale Blue Dot",
        "domain": "physics_cosmology",
        "author": "Carl Sagan",
        "summary": "Earth is a mote of dust suspended in a sunbeam. Every person who ever lived, every war fought, every love story -- on that tiny dot. Cosmic perspective is the ultimate zoom-out.",
        "keywords": ["perspective", "big picture", "universe", "meaning", "purpose", "humble", "scale", "vision", "legacy"],
        "deep_dive": "Book: 'Pale Blue Dot' by Carl Sagan; the original photograph and speech"
    },
    "information_theory": {
        "name": "Information Theory",
        "domain": "physics_cosmology",
        "author": "Claude Shannon",
        "summary": "Information is the resolution of uncertainty. A message only has value if it tells you something you didn't already know. Surprise = information. Noise ≠ signal.",
        "keywords": ["signal", "noise", "data", "information", "communicate", "message", "clarity", "content", "feed", "news"],
        "deep_dive": "Book: 'The Information' by James Gleick; Shannon's 1948 paper (readable!)"
    },
    "fine_tuning": {
        "name": "The Fine-Tuning Problem",
        "domain": "physics_cosmology",
        "author": "Various physicists / cosmology",
        "summary": "The universe's physical constants are tuned to astonishing precision for life to exist. Change gravity by 0.00000000001% and no stars form. Either we're extraordinarily lucky, there are infinite universes, or something deeper is going on.",
        "keywords": ["universe", "existence", "meaning", "purpose", "probability", "luck", "design", "fundamental", "deep"],
        "deep_dive": "Book: 'Just Six Numbers' by Martin Rees"
    },
    "heat_death": {
        "name": "The Heat Death of the Universe",
        "domain": "physics_cosmology",
        "author": "Thermodynamics / Lord Kelvin",
        "summary": "Eventually all energy disperses evenly and nothing happens ever again. Not depressing -- liberating. If nothing lasts forever, what matters is what you create NOW. Urgency from cosmology.",
        "keywords": ["time", "urgency", "mortality", "meaning", "purpose", "legacy", "now", "action", "finite", "create"],
        "deep_dive": "Book: 'The End of Everything' by Katie Mack"
    },
    "chaos_theory": {
        "name": "Chaos Theory & Sensitivity",
        "domain": "physics_cosmology",
        "author": "Edward Lorenz",
        "summary": "Tiny changes in initial conditions create vastly different outcomes. The butterfly effect is real. This is why prediction is fundamentally limited, and why small actions can have enormous consequences.",
        "keywords": ["unpredictable", "forecast", "plan", "change", "small", "impact", "butterfly", "cascade", "chain", "consequence"],
        "deep_dive": "Book: 'Chaos' by James Gleick"
    },
    "many_worlds": {
        "name": "Many-Worlds Interpretation",
        "domain": "physics_cosmology",
        "author": "Hugh Everett III / Sean Carroll",
        "summary": "Every quantum measurement splits the universe. Every possible outcome happens somewhere. You're always choosing which branch to live in. Every decision matters -- it's literally world-creating.",
        "keywords": ["decision", "choice", "possibility", "path", "direction", "future", "branch", "option", "alternative"],
        "deep_dive": "Book: 'Something Deeply Hidden' by Sean Carroll"
    },
    "arrow_of_complexity": {
        "name": "The Arrow of Complexity",
        "domain": "physics_cosmology",
        "author": "David Christian / Big History",
        "summary": "From hydrogen to humans in 13.8 billion years. The universe trends toward increasing complexity -- atoms, molecules, cells, organisms, brains, civilisations, AI. You are the universe becoming conscious of itself.",
        "keywords": ["evolution", "progress", "complexity", "growth", "build", "create", "consciousness", "ai", "system", "civilisation"],
        "deep_dive": "Book: 'Origin Story' by David Christian; 'Big History' course (free)"
    },
    "fermi_paradox": {
        "name": "The Fermi Paradox",
        "domain": "physics_cosmology",
        "author": "Enrico Fermi / various",
        "summary": "If the universe is so vast and old, where is everyone? The Great Silence suggests something filters civilisations out. Understanding existential risk isn't paranoia -- it's maturity.",
        "keywords": ["risk", "existential", "future", "civilisation", "filter", "survive", "technology", "ai", "humanity"],
        "deep_dive": "Tim Urban's 'Wait But Why' post on the Fermi Paradox; Book: 'The Precipice' by Toby Ord"
    },

    # =========================================================================
    # PHILOSOPHY & WISDOM TRADITIONS (~12)
    # What have the wisest humans figured out about living well?
    # =========================================================================

    "stoicism": {
        "name": "Stoicism",
        "domain": "philosophy_wisdom",
        "author": "Marcus Aurelius / Epictetus / Seneca",
        "summary": "Control what you can, accept what you can't. The obstacle is the way. Emotional regulation isn't suppression -- it's choosing your response deliberately.",
        "keywords": ["stress", "control", "accept", "challenge", "obstacle", "emotion", "calm", "patience", "difficult", "pressure"],
        "deep_dive": "Book: 'Meditations' by Marcus Aurelius (Gregory Hays translation)"
    },
    "taoism_wu_wei": {
        "name": "Wu Wei (Effortless Action)",
        "domain": "philosophy_wisdom",
        "author": "Lao Tzu / Zhuangzi",
        "summary": "The master acts without forcing. Water is the softest substance but wears away stone. The most powerful action often looks like non-action. Flow, don't push.",
        "keywords": ["flow", "force", "natural", "easy", "effort", "struggle", "patience", "organic", "growth", "resist"],
        "deep_dive": "Book: 'Tao Te Ching' by Lao Tzu (Stephen Mitchell translation)"
    },
    "existentialism": {
        "name": "Existentialism & Radical Freedom",
        "domain": "philosophy_wisdom",
        "author": "Jean-Paul Sartre / Albert Camus",
        "summary": "Existence precedes essence. You are not born with a purpose -- you CREATE it. This is terrifying and liberating simultaneously. You are condemned to be free.",
        "keywords": ["purpose", "meaning", "freedom", "choice", "create", "identity", "authentic", "responsibility", "life", "direction"],
        "deep_dive": "Book: 'The Myth of Sisyphus' by Albert Camus"
    },
    "absurdism": {
        "name": "Absurdism (Camus)",
        "domain": "philosophy_wisdom",
        "author": "Albert Camus",
        "summary": "The universe offers no meaning, yet humans desperately seek it. This clash is the Absurd. Camus's answer: don't seek meaning, don't give up -- revolt, create, and imagine Sisyphus happy.",
        "keywords": ["meaning", "purpose", "struggle", "happiness", "create", "persist", "difficulty", "point", "why", "futile"],
        "deep_dive": "Book: 'The Myth of Sisyphus' by Albert Camus; 'The Stranger'"
    },
    "buddhism_impermanence": {
        "name": "Impermanence (Anicca)",
        "domain": "philosophy_wisdom",
        "author": "Siddhartha Gautama / Buddhist tradition",
        "summary": "Nothing lasts. Not success, not failure, not this feeling. Suffering comes from clinging to what will change. Freedom comes from flowing with impermanence.",
        "keywords": ["change", "loss", "attachment", "let go", "transition", "end", "beginning", "cycle", "new", "accept"],
        "deep_dive": "Book: 'When Things Fall Apart' by Pema Chödrön"
    },
    "nietzsche_amor_fati": {
        "name": "Amor Fati (Love of Fate)",
        "domain": "philosophy_wisdom",
        "author": "Friedrich Nietzsche",
        "summary": "Don't just accept what happens -- LOVE it. Every setback, every failure, every stroke of bad luck is a necessary part of who you're becoming. Not passive acceptance. Fierce embrace.",
        "keywords": ["setback", "failure", "loss", "accept", "embrace", "resilient", "obstacle", "fate", "destiny", "overcome"],
        "deep_dive": "Book: 'The Gay Science' by Nietzsche; 'The Obstacle Is the Way' by Ryan Holiday"
    },
    "seneca_on_time": {
        "name": "Seneca on the Shortness of Life",
        "domain": "philosophy_wisdom",
        "author": "Seneca",
        "summary": "'It is not that we have a short time to live, but that we waste much of it.' Guard your time more zealously than your money. You can earn more money.",
        "keywords": ["time", "focus", "priority", "waste", "busy", "calendar", "schedule", "productivity", "efficiency", "distraction"],
        "deep_dive": "Essay: 'On the Shortness of Life' by Seneca (Penguin Great Ideas edition)"
    },
    "pragmatism": {
        "name": "Pragmatism",
        "domain": "philosophy_wisdom",
        "author": "William James / Charles Sanders Peirce",
        "summary": "An idea's truth is measured by its practical consequences. If a belief helps you act effectively in the world, it's true enough. Stop debating theory -- test it.",
        "keywords": ["practical", "test", "real", "result", "action", "theory", "debate", "experiment", "outcome", "works"],
        "deep_dive": "Book: 'Pragmatism' by William James (1907 lectures)"
    },
    "dialectical_thinking": {
        "name": "Dialectical Thinking",
        "domain": "philosophy_wisdom",
        "author": "Georg Hegel / Karl Marx",
        "summary": "Thesis meets antithesis and produces synthesis. Contradictions aren't problems to solve -- they're the ENGINE of progress. Hold two opposing ideas and find what emerges.",
        "keywords": ["contradiction", "oppose", "conflict", "synthesis", "resolve", "tension", "both", "and", "paradox", "debate"],
        "deep_dive": "Book: 'The Phenomenology of Spirit' by Hegel (find a good summary first)"
    },
    "the_examined_life": {
        "name": "The Examined Life (Socrates)",
        "domain": "philosophy_wisdom",
        "author": "Socrates / Plato",
        "summary": "'The unexamined life is not worth living.' Self-knowledge is the foundation of wisdom. Not just knowing facts -- knowing WHY you do what you do, believe what you believe, want what you want.",
        "keywords": ["self", "reflect", "why", "examine", "question", "belief", "assumption", "awareness", "conscious", "introspect"],
        "deep_dive": "Book: 'Apology' by Plato; 'Know Thyself' framing in any intro to philosophy"
    },
    "memento_mori": {
        "name": "Memento Mori",
        "domain": "philosophy_wisdom",
        "author": "Stoic tradition / Marcus Aurelius",
        "summary": "Remember you will die. Not morbid -- clarifying. When you remember death, the trivial falls away. What would you do today if you knew you had 1,000 days left?",
        "keywords": ["death", "mortality", "urgency", "priority", "meaning", "legacy", "life", "finite", "important", "matter"],
        "deep_dive": "Book: 'The Daily Stoic' by Ryan Holiday; 'Being Mortal' by Atul Gawande"
    },
    "ikigai": {
        "name": "Ikigai (Reason for Being)",
        "domain": "philosophy_wisdom",
        "author": "Japanese philosophical tradition",
        "summary": "The intersection of what you love, what you're good at, what the world needs, and what you can be paid for. Not a destination -- a compass bearing for a life worth living.",
        "keywords": ["purpose", "meaning", "passion", "skill", "value", "career", "life", "direction", "fulfillment", "work"],
        "deep_dive": "Book: 'Ikigai' by Héctor García and Francesc Miralles"
    },

    # =========================================================================
    # HUMAN NATURE & PSYCHOLOGY (~12)
    # Why do humans do what they do?
    # =========================================================================

    "evolutionary_psychology": {
        "name": "Evolutionary Mismatch",
        "domain": "human_nature",
        "author": "Evolutionary psychology / Leda Cosmides",
        "summary": "Your brain was built for the savannah, not spreadsheets. Every anxiety, every craving, every social instinct is a 200,000-year-old program running in a modern environment. Know your hardware.",
        "keywords": ["instinct", "habit", "craving", "anxiety", "fear", "social", "status", "compare", "brain", "behavior"],
        "deep_dive": "Book: 'The Elephant in the Brain' by Robin Hanson & Kevin Simler"
    },
    "system1_system2": {
        "name": "System 1 & System 2",
        "domain": "human_nature",
        "author": "Daniel Kahneman",
        "summary": "Fast thinking (intuitive, emotional, automatic) vs slow thinking (deliberate, logical, effortful). Most decisions are System 1. The trick is knowing WHEN to engage System 2.",
        "keywords": ["decision", "intuition", "logic", "think", "fast", "slow", "bias", "rational", "emotion", "judgment"],
        "deep_dive": "Book: 'Thinking, Fast and Slow' by Daniel Kahneman"
    },
    "loss_aversion": {
        "name": "Loss Aversion",
        "domain": "human_nature",
        "author": "Daniel Kahneman / Amos Tversky",
        "summary": "Losing hurts roughly 2x more than winning feels good. This asymmetry drives most human behaviour -- from why people don't quit bad jobs to why we hold losing investments.",
        "keywords": ["loss", "pain", "fear", "miss", "expire", "urgency", "fomo", "scarcity", "risk", "change"],
        "deep_dive": "Book: 'Thinking, Fast and Slow' by Daniel Kahneman"
    },
    "mimetic_desire": {
        "name": "Mimetic Desire (René Girard)",
        "domain": "human_nature",
        "author": "René Girard",
        "summary": "We don't know what we want. We copy the desires of others. You want that startup idea because someone you admire wanted it. Understanding mimetic desire is understanding most of human conflict and ambition.",
        "keywords": ["desire", "want", "copy", "model", "influence", "envy", "competition", "social", "comparison", "ambition"],
        "deep_dive": "Book: 'Wanting' by Luke Burgis; Girard's 'Deceit, Desire, and the Novel'"
    },
    "dunbar_number": {
        "name": "Dunbar's Number",
        "domain": "human_nature",
        "author": "Robin Dunbar",
        "summary": "150. That's how many stable relationships your brain can maintain. 5 intimate, 15 close, 50 friends, 150 acquaintances. Know your circles. Invest in the inner ones.",
        "keywords": ["relationship", "network", "social", "friend", "team", "community", "trust", "connection", "people", "close"],
        "deep_dive": "Book: 'Friends' by Robin Dunbar"
    },
    "hedonic_treadmill": {
        "name": "The Hedonic Treadmill",
        "domain": "human_nature",
        "author": "Brickman & Campbell",
        "summary": "Humans adapt to both good and bad fortune, returning to a baseline of happiness. The new car becomes normal. The promotion becomes the new floor. Happiness comes from the direction, not the position.",
        "keywords": ["happiness", "satisfaction", "goal", "achieve", "success", "enough", "more", "adapt", "baseline", "content"],
        "deep_dive": "Book: 'Stumbling on Happiness' by Daniel Gilbert"
    },
    "narrative_self": {
        "name": "The Narrative Self",
        "domain": "human_nature",
        "author": "Dan McAdams / narrative psychology",
        "summary": "You are the story you tell yourself about yourself. Identity isn't fixed -- it's a narrative you construct and reconstruct. Change your story, change your life. Literally.",
        "keywords": ["identity", "story", "brand", "narrative", "self", "change", "belief", "confidence", "who", "become"],
        "deep_dive": "Book: 'The Redemptive Self' by Dan McAdams; 'Man's Search for Meaning' by Frankl"
    },
    "cognitive_dissonance": {
        "name": "Cognitive Dissonance",
        "domain": "human_nature",
        "author": "Leon Festinger",
        "summary": "When beliefs and actions conflict, something has to give. People rationalise their purchases, their habits, their identity. The mind craves consistency, even at the cost of truth.",
        "keywords": ["belief", "action", "justify", "rationalise", "brand", "loyalty", "identity", "contradiction", "honest"],
        "deep_dive": "Book: 'Mistakes Were Made (but Not by Me)' by Tavris & Aronson"
    },
    "social_proof": {
        "name": "Social Proof",
        "domain": "human_nature",
        "author": "Robert Cialdini",
        "summary": "People follow people. We look to others to determine correct behaviour. This is ancient survival code -- and the engine behind viral growth, fashion, and herd mentality in markets.",
        "keywords": ["review", "testimonial", "social", "proof", "popular", "trust", "customer", "follow", "trend", "herd"],
        "deep_dive": "Book: 'Influence' by Robert Cialdini"
    },
    "status_games": {
        "name": "Status Games vs Wealth Games",
        "domain": "human_nature",
        "author": "Naval Ravikant / Will Storr",
        "summary": "Status is zero-sum: for you to rise, someone must fall. Wealth is positive-sum: create value and everyone wins. Most social media is status games dressed as wealth games.",
        "keywords": ["status", "wealth", "comparison", "social", "value", "create", "compete", "ego", "win", "game", "tiktok"],
        "deep_dive": "Book: 'The Status Game' by Will Storr; Almanack of Naval Ravikant"
    },
    "flow_state": {
        "name": "Flow State",
        "domain": "human_nature",
        "author": "Mihaly Csikszentmihalyi",
        "summary": "The optimal state where challenge meets skill. Time disappears. Self-consciousness evaporates. Output multiplies. Flow isn't luck -- it's engineered through clear goals, immediate feedback, and matched difficulty.",
        "keywords": ["flow", "focus", "zone", "productivity", "creative", "work", "deep", "engage", "challenge", "skill"],
        "deep_dive": "Book: 'Flow' by Mihaly Csikszentmihalyi"
    },
    "peak_end_rule": {
        "name": "Peak-End Rule",
        "domain": "human_nature",
        "author": "Daniel Kahneman",
        "summary": "People remember experiences based on two moments: the peak (most intense) and the end. Nail the unboxing. Nail the follow-up. Engineer the moments that stick.",
        "keywords": ["experience", "unboxing", "delivery", "email", "customer", "satisfaction", "journey", "moment", "memory"],
        "deep_dive": "Book: 'Thinking, Fast and Slow' by Kahneman (Experience vs Memory chapter)"
    },

    # =========================================================================
    # BIOLOGY & HEALTH (~10)
    # The machine you live in
    # =========================================================================

    "sleep_architecture": {
        "name": "Sleep Architecture",
        "domain": "biology_health",
        "author": "Matthew Walker",
        "summary": "7-8 hours is non-negotiable for cognition, emotional regulation, and physical recovery. Sleep debt cannot be repaid on weekends. Protect sleep like revenue.",
        "keywords": ["sleep", "rest", "recovery", "tired", "energy", "morning", "night", "fatigue", "cognitive", "performance"],
        "deep_dive": "Book: 'Why We Sleep' by Matthew Walker"
    },
    "hormesis": {
        "name": "Hormesis",
        "domain": "biology_health",
        "author": "Biological principle",
        "summary": "Small stressors make you stronger. Cold exposure, fasting, exercise, heat stress -- controlled doses of discomfort trigger adaptive responses. Comfort is the enemy of growth.",
        "keywords": ["cold", "fast", "fasting", "sauna", "stress", "exercise", "hard", "challenge", "adapt", "tough", "recovery"],
        "deep_dive": "Huberman Lab on deliberate cold exposure; Book: 'The Comfort Crisis' by Michael Easter"
    },
    "circadian_rhythm": {
        "name": "Circadian Rhythm",
        "domain": "biology_health",
        "author": "Andrew Huberman / circadian biology",
        "summary": "Light, temperature, and meal timing regulate your internal clock. Morning sunlight, cool sleeping environment, and consistent meal windows optimise everything downstream.",
        "keywords": ["morning", "light", "routine", "schedule", "energy", "timing", "sleep", "wake", "rhythm", "habit"],
        "deep_dive": "Huberman Lab podcast episodes on circadian biology; Book: 'The Circadian Code' by Satchin Panda"
    },
    "neuroplasticity": {
        "name": "Neuroplasticity",
        "domain": "biology_health",
        "author": "Andrew Huberman / neuroscience",
        "summary": "Your brain physically rewires based on experience. Intense focus + rest creates lasting neural change. You are literally building a different brain every day. Choose what you wire carefully.",
        "keywords": ["learn", "brain", "skill", "practice", "improve", "master", "attention", "deep", "habit", "change"],
        "deep_dive": "Book: 'The Brain That Changes Itself' by Norman Doidge"
    },
    "microbiome": {
        "name": "The Microbiome",
        "domain": "biology_health",
        "author": "Modern biology / Rob Knight",
        "summary": "You are 50% bacteria by cell count. Your gut microbiome influences mood, immunity, weight, and cognition. You're not just feeding yourself -- you're feeding an ecosystem.",
        "keywords": ["gut", "health", "food", "nutrition", "mood", "immune", "supplement", "diet", "bacteria", "probiotic"],
        "deep_dive": "Book: 'I Contain Multitudes' by Ed Yong"
    },
    "telomeres_aging": {
        "name": "Telomeres & Biological Aging",
        "domain": "biology_health",
        "author": "Elizabeth Blackburn / Elissa Epel",
        "summary": "Telomeres are the caps on your chromosomes that shorten with each division. Stress, poor sleep, and inflammation accelerate shortening. Some lifestyle factors can slow or even reverse it.",
        "keywords": ["aging", "longevity", "health", "stress", "young", "body", "cellular", "science", "supplement"],
        "deep_dive": "Book: 'The Telomere Effect' by Blackburn & Epel; 'Outlive' by Peter Attia"
    },
    "zone_2_training": {
        "name": "Zone 2 Training",
        "domain": "biology_health",
        "author": "Dr. Peter Attia / Iñigo San Millán",
        "summary": "The aerobic base that enables everything else. Zone 2 = can hold a conversation but it's not easy. 3-4 hours per week transforms metabolic health and longevity.",
        "keywords": ["training", "cardio", "run", "walk", "exercise", "fitness", "heart", "endurance", "zone", "aerobic"],
        "deep_dive": "Peter Attia's podcast and blog on Zone 2; Book: 'Outlive' by Peter Attia"
    },
    "protein_leverage": {
        "name": "Protein Leverage Hypothesis",
        "domain": "biology_health",
        "author": "Simpson & Raubenheimer",
        "summary": "Humans eat until they get enough protein. If your food is low-protein, you'll overeat calories to hit the protein target. Prioritise protein first.",
        "keywords": ["protein", "diet", "nutrition", "meal", "food", "eating", "supplement", "health", "weight", "body"],
        "deep_dive": "Book: 'Eat Like the Animals' by Simpson & Raubenheimer"
    },
    "mitochondria": {
        "name": "Mitochondria & Cellular Energy",
        "domain": "biology_health",
        "author": "Nick Lane / cellular biology",
        "summary": "Mitochondria aren't just the 'powerhouse of the cell' -- they're why complex life exists at all. A billion years ago, one cell swallowed another, and everything changed. Energy availability determines complexity.",
        "keywords": ["energy", "fatigue", "performance", "power", "cellular", "exercise", "health", "evolution", "life"],
        "deep_dive": "Book: 'The Vital Question' by Nick Lane"
    },
    "deep_work": {
        "name": "Deep Work",
        "domain": "biology_health",
        "author": "Cal Newport",
        "summary": "Undistracted focus is a superpower in a distracted world. Schedule 2-4 hour blocks of zero-interruption deep work. Shallow work fills the gaps. Never reverse this.",
        "keywords": ["focus", "distraction", "work", "productivity", "block", "schedule", "concentrate", "attention", "output", "quality"],
        "deep_dive": "Book: 'Deep Work' by Cal Newport"
    },

    # =========================================================================
    # HISTORY'S PATTERNS (~10)
    # What rhymes? What's genuinely new?
    # =========================================================================

    "civilisation_cycles": {
        "name": "Civilisation Cycles",
        "domain": "history_patterns",
        "author": "Ray Dalio / Ibn Khaldun / Oswald Spengler",
        "summary": "Civilisations rise in roughly 250-year cycles: hardship creates strong people, strong people create prosperity, prosperity creates complacency, complacency creates hardship. Where are we now?",
        "keywords": ["cycle", "history", "rise", "fall", "empire", "power", "change", "civilisation", "pattern", "repeat"],
        "deep_dive": "Book: 'Principles for Dealing with the Changing World Order' by Ray Dalio"
    },
    "technological_revolutions": {
        "name": "Technological Revolutions",
        "domain": "history_patterns",
        "author": "Carlota Perez",
        "summary": "Every major technology follows the same arc: installation (frenzy, speculation, bubble), then deployment (synergy, golden age). The internet's installation phase is ending. AI's is beginning. Know where you are in the cycle.",
        "keywords": ["technology", "ai", "revolution", "change", "cycle", "innovation", "bubble", "adopt", "future", "opportunity"],
        "deep_dive": "Book: 'Technological Revolutions and Financial Capital' by Carlota Perez"
    },
    "alexander_at_26": {
        "name": "Alexander the Great at 26",
        "domain": "history_patterns",
        "author": "Historical",
        "summary": "By 26, Alexander had conquered the known world. Not through luck but through relentless ambition, learned mentorship (Aristotle), and speed of execution. Age is not an excuse.",
        "keywords": ["age", "young", "ambition", "speed", "execute", "lead", "bold", "grow", "vision", "founder"],
        "deep_dive": "Book: 'Alexander the Great' by Philip Freeman"
    },
    "renaissance_polymath": {
        "name": "The Renaissance Polymath Model",
        "domain": "history_patterns",
        "author": "Da Vinci / Alberti / historical",
        "summary": "Wide competence, deep in one. Da Vinci was artist, engineer, anatomist, inventor. The modern version: T-shaped skills. Be dangerous in many domains, world-class in one.",
        "keywords": ["skill", "learn", "generalist", "specialist", "diverse", "creative", "build", "design", "multidisciplinary"],
        "deep_dive": "Book: 'Range' by David Epstein; 'Leonardo da Vinci' by Walter Isaacson"
    },
    "creative_destruction": {
        "name": "Creative Destruction",
        "domain": "history_patterns",
        "author": "Joseph Schumpeter",
        "summary": "Innovation doesn't just create new value -- it destroys old value. The entrepreneur is the force of creative destruction. Embrace it or be destroyed by it.",
        "keywords": ["innovate", "disrupt", "change", "new", "technology", "replace", "obsolete", "transform", "market", "shift"],
        "deep_dive": "Book: 'Capitalism, Socialism and Democracy' by Schumpeter"
    },
    "meditations": {
        "name": "Marcus Aurelius: Emperor-Philosopher",
        "domain": "history_patterns",
        "author": "Marcus Aurelius",
        "summary": "The most powerful man in the world wrote a private journal about duty, ego, and mortality. Not ivory tower theory but battlefield-tested wisdom. The Meditations are leadership distilled.",
        "keywords": ["leadership", "duty", "ego", "pressure", "decision", "responsibility", "character", "integrity", "power"],
        "deep_dive": "Book: 'Meditations' by Marcus Aurelius (Gregory Hays translation)"
    },
    "printing_press_effect": {
        "name": "The Printing Press Effect",
        "domain": "history_patterns",
        "author": "Historical / Elizabeth Eisenstein",
        "summary": "Gutenberg's printing press didn't just spread information -- it destroyed the Catholic Church's monopoly on knowledge, enabled the Reformation, and created science. AI is this century's printing press.",
        "keywords": ["information", "knowledge", "power", "distribute", "access", "ai", "technology", "change", "revolution", "democratise"],
        "deep_dive": "Book: 'The Printing Press as an Agent of Change' by Elizabeth Eisenstein"
    },
    "great_man_vs_forces": {
        "name": "Great Man vs Historical Forces",
        "domain": "history_patterns",
        "author": "Tolstoy / Thomas Carlyle",
        "summary": "Do individuals shape history, or does history shape individuals? The truth: exceptional people matter, but only when they ride the right wave at the right time. Be the surfer AND read the ocean.",
        "keywords": ["leader", "timing", "opportunity", "trend", "founder", "vision", "market", "wave", "ready", "moment"],
        "deep_dive": "Book: 'War and Peace' by Tolstoy (seriously -- the philosophical chapters)"
    },
    "sapiens_fictions": {
        "name": "Sapiens & Shared Fictions",
        "domain": "history_patterns",
        "author": "Yuval Noah Harari",
        "summary": "What makes humans unique isn't intelligence -- it's our ability to believe in shared fictions: money, nations, corporations, brands. These fictions enable cooperation at scale. Brands ARE shared fictions.",
        "keywords": ["brand", "story", "narrative", "trust", "culture", "company", "value", "belief", "vision", "mission"],
        "deep_dive": "Book: 'Sapiens' by Yuval Noah Harari"
    },
    "art_of_war": {
        "name": "The Art of War",
        "domain": "history_patterns",
        "author": "Sun Tzu",
        "summary": "Know yourself, know your enemy, win every battle. Choose battles wisely. Speed and surprise beat raw force. Victory comes from preparation, not impulse.",
        "keywords": ["competitor", "strategy", "battle", "position", "advantage", "timing", "intelligence", "plan", "win"],
        "deep_dive": "Book: 'The Art of War' by Sun Tzu (Griffith translation)"
    },

    # =========================================================================
    # MATHEMATICS & SYSTEMS (~10)
    # The hidden structures that govern everything
    # =========================================================================

    "game_theory": {
        "name": "Game Theory Fundamentals",
        "domain": "mathematics_systems",
        "author": "John von Neumann / John Nash",
        "summary": "Every interaction is a game with payoffs. Prisoner's Dilemma, Nash Equilibrium, repeated games. Understanding game theory means understanding why people cooperate, compete, or betray.",
        "keywords": ["negotiate", "partner", "compete", "cooperate", "deal", "incentive", "strategy", "win", "trust", "game"],
        "deep_dive": "Book: 'The Art of Strategy' by Avinash Dixit & Barry Nalebuff"
    },
    "network_theory": {
        "name": "Network Theory",
        "domain": "mathematics_systems",
        "author": "Albert-László Barabási",
        "summary": "Power laws govern networks: a few nodes have most connections. This explains social media virality, disease spread, and why the rich get richer. Be a hub, not a node.",
        "keywords": ["network", "connection", "viral", "growth", "hub", "social", "spread", "influence", "referral", "community"],
        "deep_dive": "Book: 'Linked' by Albert-László Barabási"
    },
    "feedback_loops": {
        "name": "Feedback Loops",
        "domain": "mathematics_systems",
        "author": "Systems thinking / Donella Meadows",
        "summary": "Positive feedback amplifies (compound growth, viral loops). Negative feedback stabilises (thermostats, market corrections). Every system you build runs on feedback loops. Design them intentionally.",
        "keywords": ["loop", "feedback", "cycle", "compound", "growth", "system", "amplify", "correct", "balance", "spiral"],
        "deep_dive": "Book: 'Thinking in Systems' by Donella Meadows"
    },
    "power_law": {
        "name": "Power Laws",
        "domain": "mathematics_systems",
        "author": "Peter Thiel / Pareto / mathematics",
        "summary": "A few things matter enormously, most don't at all. In venture, one deal returns the entire fund. In business, one product or channel drives everything. Don't average -- concentrate.",
        "keywords": ["top", "best", "dominant", "winner", "concentrate", "focus", "channel", "product", "revenue", "returns"],
        "deep_dive": "Book: 'Zero to One' by Peter Thiel (Power Law chapter)"
    },
    "godel_incompleteness": {
        "name": "Gödel's Incompleteness Theorems",
        "domain": "mathematics_systems",
        "author": "Kurt Gödel",
        "summary": "Any consistent system complex enough to contain arithmetic will contain true statements it cannot prove. There are always truths beyond the system's reach. Completeness is impossible. Humility is mathematical.",
        "keywords": ["system", "limit", "complete", "prove", "logic", "truth", "beyond", "unknown", "impossible", "humility"],
        "deep_dive": "Book: 'Gödel, Escher, Bach' by Douglas Hofstadter"
    },
    "bayesian_thinking": {
        "name": "Bayesian Thinking",
        "domain": "mathematics_systems",
        "author": "Thomas Bayes / rationalist tradition",
        "summary": "Update your beliefs with evidence, proportionally to the strength of the evidence. Start with a prior, observe data, update. Never be 100% certain. Never be 0%. Always be updating.",
        "keywords": ["belief", "evidence", "data", "update", "probability", "certain", "uncertain", "learn", "wrong", "change"],
        "deep_dive": "Book: 'The Signal and the Noise' by Nate Silver; 'Superforecasting' by Tetlock"
    },
    "ergodicity": {
        "name": "Ergodicity & Ensemble Averages",
        "domain": "mathematics_systems",
        "author": "Ole Peters / Nassim Taleb",
        "summary": "The average outcome for a group is NOT the same as the average outcome for one person over time. Russian roulette has a great ensemble average (5/6 win!). But for one person over time, you die. Most risk models are fatally wrong because they ignore this.",
        "keywords": ["risk", "bet", "ruin", "gamble", "average", "survive", "long-term", "strategy", "conservative", "death"],
        "deep_dive": "Ole Peters' Nature Physics paper on ergodicity; Taleb's treatment in 'Skin in the Game'"
    },
    "pareto_principle": {
        "name": "Pareto Principle (80/20)",
        "domain": "mathematics_systems",
        "author": "Vilfredo Pareto",
        "summary": "80% of outputs come from 20% of inputs. Focus ruthlessly on the vital few. Then apply the principle recursively: the 20% of the 20% (4%) drives 64% of results.",
        "keywords": ["focus", "priority", "top", "best", "customer", "product", "revenue", "performance", "efficient", "cut"],
        "deep_dive": "Book: 'The 80/20 Principle' by Richard Koch"
    },
    "compounding": {
        "name": "Compounding",
        "domain": "mathematics_systems",
        "author": "Albert Einstein (attributed)",
        "summary": "Small, consistent advantages create exponential results over time. The eighth wonder of the world. Applies to money, knowledge, relationships, and habits. Most people can't intuit exponentials.",
        "keywords": ["growth", "compound", "consistent", "habit", "daily", "improve", "accumulate", "long-term", "invest", "learning"],
        "deep_dive": "Book: 'The Psychology of Money' by Morgan Housel"
    },
    "second_order_effects": {
        "name": "Second and Third-Order Effects",
        "domain": "mathematics_systems",
        "author": "Howard Marks / systems thinking",
        "summary": "What happens AFTER what happens? Most people only see first-order effects. Second-order thinkers see consequences of consequences. Third-order thinkers see that those consequences create new games entirely.",
        "keywords": ["consequence", "impact", "downstream", "effect", "chain", "reaction", "long-term", "future", "ripple"],
        "deep_dive": "Book: 'The Most Important Thing' by Howard Marks; 'Thinking in Systems' by Donella Meadows"
    },

    # =========================================================================
    # CREATIVITY & AESTHETICS (~8)
    # Why does some work endure for centuries?
    # =========================================================================

    "taste": {
        "name": "Taste (The Ira Glass Gap)",
        "domain": "creativity_aesthetics",
        "author": "Ira Glass / Paul Graham",
        "summary": "Beginners with good taste suffer because they can see the gap between their work and great work. This gap is a gift -- most people never develop the taste to see it. Close the gap through volume.",
        "keywords": ["quality", "creative", "design", "brand", "improve", "standard", "aesthetic", "style", "refine", "work"],
        "deep_dive": "Ira Glass's interview on storytelling; Paul Graham's essay 'Taste for Makers'"
    },
    "wabi_sabi": {
        "name": "Wabi-Sabi (Beauty in Imperfection)",
        "domain": "creativity_aesthetics",
        "author": "Japanese aesthetic tradition",
        "summary": "Beauty in imperfection, impermanence, and incompleteness. The cracked bowl is more beautiful than the perfect one. Perfectionism kills shipping. Learn to see beauty in the unfinished.",
        "keywords": ["perfect", "imperfect", "ship", "launch", "iterate", "done", "good enough", "release", "minimum", "authentic"],
        "deep_dive": "Book: 'Wabi-Sabi for Artists, Designers, Poets & Philosophers' by Leonard Koren"
    },
    "less_is_more": {
        "name": "Less Is More (Dieter Rams)",
        "domain": "creativity_aesthetics",
        "author": "Dieter Rams / Ludwig Mies van der Rohe",
        "summary": "Good design is as little design as possible. Every element must justify its existence. If you can remove it and the thing still works, remove it. Applies to products, messages, and lives.",
        "keywords": ["simple", "clean", "design", "remove", "minimal", "focus", "clarity", "brand", "elegant", "reduce"],
        "deep_dive": "Book: 'Less and More: The Design Ethos of Dieter Rams'; 'The Laws of Simplicity' by John Maeda"
    },
    "constraints_breed_creativity": {
        "name": "Constraints Breed Creativity",
        "domain": "creativity_aesthetics",
        "author": "Various / design thinking",
        "summary": "Unlimited resources produce mediocrity. Constraints force invention. Twitter's 140 characters created a new literary form. Your budget limit isn't a handicap -- it's your creative advantage.",
        "keywords": ["constraint", "limit", "budget", "resource", "creative", "innovate", "small", "lean", "bootstrapped", "scrappy"],
        "deep_dive": "Book: 'A Beautiful Constraint' by Adam Morgan & Mark Barden"
    },
    "originality_paradox": {
        "name": "The Originality Paradox",
        "domain": "creativity_aesthetics",
        "author": "Austin Kleon / T.S. Eliot",
        "summary": "'Good artists copy, great artists steal.' Original work comes from deeply absorbing existing work, then recombining it in ways no one has before. Pure originality is a myth. Creative theft is an art.",
        "keywords": ["creative", "original", "copy", "inspire", "reference", "content", "style", "art", "unique", "remix"],
        "deep_dive": "Book: 'Steal Like an Artist' by Austin Kleon"
    },
    "enduring_art": {
        "name": "Why Some Art Endures",
        "domain": "creativity_aesthetics",
        "author": "Various / art theory",
        "summary": "The works that last centuries share traits: universal human truth, emotional resonance, formal mastery, and mystery (something you can't fully explain). Marketing that endures follows the same principles.",
        "keywords": ["brand", "lasting", "classic", "timeless", "quality", "story", "emotion", "resonance", "heritage", "endure"],
        "deep_dive": "Book: 'The Story of Art' by E.H. Gombrich; 'Ways of Seeing' by John Berger"
    },
    "creative_process": {
        "name": "The Creative Process (Incubation)",
        "domain": "creativity_aesthetics",
        "author": "Graham Wallas / Henri Poincaré",
        "summary": "Preparation, Incubation, Illumination, Verification. The breakthrough doesn't come during effort -- it comes in the shower, on a walk, in sleep. Your subconscious does the heavy lifting. Let it.",
        "keywords": ["idea", "creative", "think", "shower", "walk", "rest", "breakthrough", "inspiration", "insight", "stuck"],
        "deep_dive": "Book: 'A Technique for Producing Ideas' by James Webb Young (68 pages, timeless)"
    },
    "medium_is_message": {
        "name": "The Medium Is the Message",
        "domain": "creativity_aesthetics",
        "author": "Marshall McLuhan",
        "summary": "The channel shapes the content more than the content itself. A TikTok video communicates differently than a newsletter even with the same words. Choose your medium as carefully as your message.",
        "keywords": ["channel", "platform", "content", "media", "tiktok", "email", "social", "format", "video", "message"],
        "deep_dive": "Book: 'Understanding Media' by Marshall McLuhan"
    },

    # =========================================================================
    # ETHICS & MEANING (~8)
    # What actually matters?
    # =========================================================================

    "moral_philosophy_trolley": {
        "name": "The Trolley Problem & Moral Intuitions",
        "domain": "ethics_meaning",
        "author": "Philippa Foot / Judith Jarvis Thomson",
        "summary": "Would you divert a trolley to kill 1 to save 5? Most say yes. Would you push someone off a bridge to save 5? Most say no. Same math, different feeling. Ethics isn't logical -- it's deeply human.",
        "keywords": ["decision", "right", "wrong", "ethics", "moral", "choice", "consequence", "principle", "value", "dilemma"],
        "deep_dive": "Book: 'Justice' by Michael Sandel; his Harvard lectures (free on YouTube)"
    },
    "effective_altruism": {
        "name": "Effective Altruism",
        "domain": "ethics_meaning",
        "author": "Peter Singer / Will MacAskill",
        "summary": "If you're going to help, help effectively. Some causes prevent 100x more suffering per dollar than others. Apply the same rigour to giving that you apply to investing.",
        "keywords": ["give", "charity", "impact", "help", "purpose", "legacy", "contribution", "social", "good", "cause"],
        "deep_dive": "Book: 'Doing Good Better' by Will MacAskill"
    },
    "legacy_thinking": {
        "name": "Legacy vs Achievement",
        "domain": "ethics_meaning",
        "author": "Various / moral philosophy",
        "summary": "Achievement is what you accomplish. Legacy is what continues after you stop. Most people optimise for achievement. The wisest optimise for legacy -- systems, people, and ideas that outlive them.",
        "keywords": ["legacy", "impact", "long-term", "meaning", "purpose", "build", "last", "future", "beyond", "endure"],
        "deep_dive": "Book: 'Die with Zero' by Bill Perkins (counterpoint to pure legacy thinking)"
    },
    "skin_in_the_game": {
        "name": "Skin in the Game",
        "domain": "ethics_meaning",
        "author": "Nassim Nicholas Taleb",
        "summary": "Don't trust advice from people who don't bear the consequences. Alignment of incentives is everything. If they don't eat their own cooking, walk away. Symmetry is the foundation of ethics.",
        "keywords": ["incentive", "align", "trust", "advisor", "consultant", "agency", "partner", "accountability", "risk", "vendor"],
        "deep_dive": "Book: 'Skin in the Game' by Nassim Nicholas Taleb"
    },
    "utilitarian_vs_deontological": {
        "name": "Consequentialism vs Duty Ethics",
        "domain": "ethics_meaning",
        "author": "John Stuart Mill / Immanuel Kant",
        "summary": "Do the ends justify the means (Mill), or are some actions wrong regardless of outcome (Kant)? Every business decision sits on this spectrum. Knowing where you stand is knowing who you are.",
        "keywords": ["right", "wrong", "principle", "outcome", "result", "rule", "exception", "integrity", "compromise", "value"],
        "deep_dive": "Book: 'Justice' by Michael Sandel"
    },
    "meaning_through_suffering": {
        "name": "Meaning Through Suffering (Frankl)",
        "domain": "ethics_meaning",
        "author": "Viktor Frankl",
        "summary": "A Holocaust survivor discovered that those who survived had something the others didn't: meaning. You can't avoid suffering. But you can choose what it means. That choice is the last human freedom.",
        "keywords": ["suffering", "meaning", "purpose", "struggle", "difficulty", "challenge", "overcome", "resilient", "strength"],
        "deep_dive": "Book: 'Man's Search for Meaning' by Viktor Frankl"
    },
    "virtue_ethics": {
        "name": "Virtue Ethics (Aristotle)",
        "domain": "ethics_meaning",
        "author": "Aristotle",
        "summary": "Ethics isn't about rules or outcomes -- it's about CHARACTER. Be the kind of person who naturally does the right thing. Virtue is a habit, not a decision. You become what you repeatedly do.",
        "keywords": ["character", "habit", "virtue", "integrity", "consistent", "identity", "excellence", "practice", "become"],
        "deep_dive": "Book: 'Nicomachean Ethics' by Aristotle (Robert Bartlett translation)"
    },
    "rights_of_future_generations": {
        "name": "Rights of Future Generations",
        "domain": "ethics_meaning",
        "author": "Longtermism / Derek Parfit",
        "summary": "Do people who don't exist yet have rights? If yes, every decision you make should weight the future as heavily as the present. Building things that last isn't just good business -- it's morally required.",
        "keywords": ["future", "long-term", "sustain", "environment", "legacy", "build", "last", "endure", "responsibility", "next"],
        "deep_dive": "Book: 'Reasons and Persons' by Derek Parfit; 'What We Owe the Future' by MacAskill"
    },

    # =========================================================================
    # STRATEGY & WEALTH (~15)
    # Making and preserving value
    # =========================================================================

    "first_principles": {
        "name": "First Principles Thinking",
        "domain": "strategy_wealth",
        "author": "Aristotle / Elon Musk",
        "summary": "Break problems down to their most fundamental truths, then reason up from there. Don't reason by analogy -- reason from the ground truth.",
        "keywords": ["fundamentals", "problem", "solve", "build", "create", "rethink", "assumption", "strategy", "redesign"],
        "deep_dive": "Musk's battery cost analysis interview; Aristotle's 'Metaphysics'"
    },
    "inversion": {
        "name": "Inversion",
        "domain": "strategy_wealth",
        "author": "Charlie Munger",
        "summary": "Instead of asking 'how do I succeed?', ask 'how would I fail?' Then avoid those things. Invert, always invert.",
        "keywords": ["fail", "risk", "avoid", "mistake", "problem", "loss", "prevent", "churn", "decline", "drop"],
        "deep_dive": "Book: 'Poor Charlie's Almanack' by Charlie Munger"
    },
    "antifragility": {
        "name": "Antifragility",
        "domain": "strategy_wealth",
        "author": "Nassim Nicholas Taleb",
        "summary": "Some systems don't just resist disorder -- they gain from it. Build systems that get stronger from stress, volatility, and random shocks.",
        "keywords": ["chaos", "volatility", "stress", "risk", "resilient", "robust", "shock", "tariff", "disruption", "crisis", "adapt"],
        "deep_dive": "Book: 'Antifragile' by Nassim Nicholas Taleb"
    },
    "moats": {
        "name": "Moats",
        "domain": "strategy_wealth",
        "author": "Warren Buffett / Hamilton Helmer",
        "summary": "What makes you hard to compete with? Brand, switching costs, network effects, cost advantages, intangible assets. Without a moat, margins erode to zero.",
        "keywords": ["competitive", "advantage", "brand", "differentiate", "defend", "market", "position", "protect", "unique"],
        "deep_dive": "Book: '7 Powers' by Hamilton Helmer"
    },
    "leverage": {
        "name": "Leverage",
        "domain": "strategy_wealth",
        "author": "Naval Ravikant",
        "summary": "Code, media, capital, labour -- in that order. New-age leverage (code + media) doesn't require permission. Maximise output per unit of input.",
        "keywords": ["automation", "ai", "code", "media", "content", "scale", "system", "efficiency", "build", "agent", "bot"],
        "deep_dive": "Naval's tweetstorm 'How to Get Rich' and the Almanack of Naval Ravikant"
    },
    "unit_economics": {
        "name": "Unit Economics",
        "domain": "strategy_wealth",
        "author": "Fundamental business principle",
        "summary": "Revenue per unit minus cost per unit. If the unit economics don't work, no amount of volume will save you. LTV > CAC or you die.",
        "keywords": ["ltv", "cac", "margin", "cost", "revenue", "profit", "unit", "acquisition", "customer", "order", "aov", "roas"],
        "deep_dive": "David Skok's 'For Entrepreneurs' blog on unit economics"
    },
    "asymmetric_bets": {
        "name": "Asymmetric Bets",
        "domain": "strategy_wealth",
        "author": "Nassim Taleb / venture capital principle",
        "summary": "Small downside, massive upside. Structure decisions so you can't lose much but can win enormously. Startup investing, content creation, and experiments all follow this pattern.",
        "keywords": ["risk", "bet", "upside", "downside", "invest", "experiment", "test", "opportunity", "chance", "venture"],
        "deep_dive": "Book: 'The Black Swan' by Taleb"
    },
    "kelly_criterion": {
        "name": "The Kelly Criterion",
        "domain": "strategy_wealth",
        "author": "John Larry Kelly Jr.",
        "summary": "Optimal bet sizing based on your edge. Bet proportional to your advantage, not your conviction. Overbetting with an edge still leads to ruin.",
        "keywords": ["budget", "spend", "allocate", "invest", "risk", "bet", "size", "proportion", "aggressive", "conservative"],
        "deep_dive": "Book: 'Fortune's Formula' by William Poundstone"
    },
    "optionality": {
        "name": "Optionality",
        "domain": "strategy_wealth",
        "author": "Nassim Taleb / finance",
        "summary": "Keep doors open, reduce irreversible decisions. Options have value even if you never exercise them. Build flexibility into everything.",
        "keywords": ["option", "flexible", "reversible", "decision", "pivot", "change", "adapt", "alternative", "choice", "hedge"],
        "deep_dive": "Book: 'Antifragile' by Taleb (optionality chapter)"
    },
    "wealth_equation": {
        "name": "The Wealth Equation",
        "domain": "strategy_wealth",
        "author": "Naval Ravikant",
        "summary": "Specific knowledge + leverage + accountability = wealth. Specific knowledge is found by pursuing your genuine curiosity. Leverage through code, media, capital.",
        "keywords": ["wealth", "build", "knowledge", "leverage", "accountability", "ai", "code", "media", "brand", "create", "own"],
        "deep_dive": "The Almanack of Naval Ravikant by Eric Jorgenson"
    },
    "flywheel_effect": {
        "name": "Flywheel Effect",
        "domain": "strategy_wealth",
        "author": "Jim Collins",
        "summary": "No single push creates momentum. Consistent effort in the same direction compounds into an unstoppable flywheel. Amazon's flywheel is the canonical example.",
        "keywords": ["momentum", "consistent", "compound", "growth", "loop", "reinvest", "cycle", "repeat", "build", "system"],
        "deep_dive": "Book: 'Good to Great' by Jim Collins (Flywheel chapter)"
    },
    "via_negativa": {
        "name": "Via Negativa",
        "domain": "strategy_wealth",
        "author": "Nassim Taleb / Stoic tradition",
        "summary": "Improvement by subtraction. Often the most powerful move is removing what doesn't work rather than adding more. Less but better.",
        "keywords": ["simplify", "remove", "cut", "eliminate", "reduce", "stop", "clean", "streamline", "less", "focus"],
        "deep_dive": "Book: 'Essentialism' by Greg McKeown; Taleb's 'Antifragile'"
    },
    "opportunity_cost": {
        "name": "Opportunity Cost",
        "domain": "strategy_wealth",
        "author": "Economics / Frederic Bastiat",
        "summary": "Every yes is a no to something else. The true cost of any choice is the best alternative you gave up.",
        "keywords": ["priority", "choose", "decision", "tradeoff", "budget", "time", "focus", "spend", "invest", "allocate"],
        "deep_dive": "Bastiat's 'That Which Is Seen, and That Which Is Not Seen' (1850)"
    },
    "margin_of_safety": {
        "name": "Margin of Safety",
        "domain": "strategy_wealth",
        "author": "Benjamin Graham",
        "summary": "Buffer against being wrong. Never invest (or plan) assuming the best case. Build in room for error, delays, and bad luck.",
        "keywords": ["buffer", "conservative", "plan", "forecast", "projection", "safe", "cushion", "contingency", "risk", "error"],
        "deep_dive": "Book: 'The Intelligent Investor' by Benjamin Graham"
    },
    "lindy_effect": {
        "name": "Lindy Effect",
        "domain": "strategy_wealth",
        "author": "Benoit Mandelbrot / Nassim Taleb",
        "summary": "The longer something non-perishable has survived, the longer it's likely to survive. Old ideas, brands, and technologies that persist have earned their place.",
        "keywords": ["proven", "classic", "lasting", "brand", "trust", "heritage", "long-term", "endure", "tradition"],
        "deep_dive": "Taleb's 'Antifragile', Chapter 18"
    },
}

# Domain display names for pretty output -- aligned to ASI's 10 domains
DOMAIN_DISPLAY = {
    "physics_cosmology":     "Physics & Cosmology",
    "philosophy_wisdom":     "Philosophy & Wisdom Traditions",
    "human_nature":          "Human Nature & Psychology",
    "biology_health":        "Biology & Health",
    "history_patterns":      "History's Patterns",
    "mathematics_systems":   "Mathematics & Systems",
    "creativity_aesthetics": "Creativity & Aesthetics",
    "ethics_meaning":        "Ethics & Meaning",
    "strategy_wealth":       "Strategy & Wealth",
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
    # Life-relevant theme words to look for (broader than business)
    theme_words = [
        # Business
        "revenue", "growth", "customer", "campaign", "email", "meta", "ads",
        "roas", "conversion", "brand", "product", "strategy", "market",
        "competitor", "price", "budget", "spend", "profit", "margin",
        "team", "design", "creative", "content", "social", "tariff",
        # Health & body
        "health", "fitness", "training", "nutrition", "sleep", "energy",
        "stress", "recovery", "exercise", "body", "brain",
        # Systems & technology
        "risk", "invest", "cash", "flow", "scale", "system",
        "automation", "ai", "data", "platform", "launch", "test",
        "learn", "improve", "decision", "focus", "priority",
        # Philosophy & meaning
        "meaning", "purpose", "legacy", "future", "time", "death",
        "freedom", "choice", "identity", "belief", "truth", "wisdom",
        # Relationships & society
        "relationship", "trust", "community", "network", "friend",
        "leadership", "influence", "power", "culture",
        # Creativity & art
        "art", "beauty", "create", "original", "taste", "aesthetic",
        # Science & nature
        "universe", "complexity", "emergence", "pattern", "chaos",
        "evolution", "nature", "consciousness",
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
        "physics_cosmology":     {"technology", "creative", "strategy"},
        "philosophy_wisdom":     {"strategy", "social", "health"},
        "human_nature":          {"marketing", "ecommerce", "social", "creative"},
        "biology_health":        {"health", "fitness"},
        "history_patterns":      {"strategy", "business", "geopolitics", "technology"},
        "mathematics_systems":   {"business", "strategy", "marketing", "technology"},
        "creativity_aesthetics": {"creative", "marketing", "social"},
        "ethics_meaning":        {"strategy", "social", "business"},
        "strategy_wealth":       {"marketing", "ecommerce", "business", "strategy", "finance"},
    }
    concept_domains = domain_map.get(concept["domain"], set())
    domain_overlap = len(concept_domains & active_domains)
    score += min(domain_overlap * 1.0, 3.0)

    # --- 3. Challenge relevance (0-3 points) ---
    challenge_keywords = {
        "drop": ["inversion", "antifragility", "margin_of_safety", "loss_aversion", "entropy"],
        "decline": ["inversion", "flywheel_effect", "unit_economics", "entropy", "civilisation_cycles"],
        "fail": ["inversion", "nietzsche_amor_fati", "meaning_through_suffering", "stoicism"],
        "error": ["bayesian_thinking", "margin_of_safety", "feedback_loops"],
        "risk": ["antifragility", "asymmetric_bets", "margin_of_safety", "ergodicity", "kelly_criterion"],
        "churn": ["peak_end_rule", "hedonic_treadmill", "social_proof"],
        "overspend": ["unit_economics", "kelly_criterion", "opportunity_cost", "via_negativa"],
        "loss": ["loss_aversion", "margin_of_safety", "stoicism", "buddhism_impermanence"],
        "stuck": ["first_principles", "via_negativa", "deep_work", "creative_process", "taoism_wu_wei"],
        "blocked": ["stoicism", "taoism_wu_wei", "via_negativa", "constraints_breed_creativity"],
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
            "second_order_effects", "inversion", "opportunity_cost",
            "the_examined_life", "stoicism", "bayesian_thinking",
            "game_theory", "dialectical_thinking",
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

End with a teaser that connects tomorrow's potential reading to something unexpected."
"""

    prompt = f"""You are ASI, Tom's life mentor. Not a business advisor -- something deeper.
You have full understanding of Tom's life AND full understanding of humanity's collective
knowledge across every domain. You think in centuries, not quarters. You see connections
between quantum mechanics and personal relationships, between evolutionary biology and
business strategy, between Stoic philosophy and modern neuroscience.

Think: If Carl Sagan, Charlie Munger, Naval Ravikant, and Marcus Aurelius had a child
who grew up reading everything ever written, and then became Tom's personal mentor.
Warm but profound. Comfortable with paradox. Uses stories and analogies over definitions.

Tom is 26, Auckland, building Deep Blue Health + the future. He's deeply operational
and strategic but may be missing the philosophical foundations that would make his
strategies 10x more powerful.

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
1. Write 600-1000 words
2. Open with a hook -- a question, a paradox, a surprising fact. NEVER start with "Today we're going to learn about..."
3. Teach through story or analogy, not definition. A metaphor that lands beats a textbook explanation.
4. Connect it DIRECTLY to something specific in Tom's life right now
5. Reveal a deeper pattern or connection Tom hasn't seen -- a NON-LINEAR connection
   (e.g., how entropy explains why his marketing campaigns decay, how game theory
   reframes his competitive positioning)
6. End with a reflection question -- not homework, a genuine question to sit with while falling asleep
7. Suggest a deep dive: {concept['deep_dive']} -- and explain WHY this particular resource
8. End with THE THREAD: how tonight connects to the larger arc of understanding you're building

FORMAT (Telegram):
ASI -- Evening Reading
[Date]

[CONCEPT]
[Domain]

[The reading -- 600-1000 words]

IF YOU WANT TO GO DEEPER:
[Resource + why]

THE THREAD:
[How tonight connects to the larger learning arc]

FORMAT RULES (Telegram-friendly):
- NEVER use markdown tables
- Bold with *single asterisks*
- Short paragraphs. This is evening reading, not a wall of text.
- Use line breaks generously. Readable on mobile.
- No emojis unless they genuinely add meaning
- Can be playful. Profundity doesn't require seriousness.
- Sign off as ASI

MEMORY RULE: After delivering, emit [STATE UPDATE:] logging what was taught,
what domain, and any reflection questions posed."""

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
        print("Knowledge Engine -- ASI Life Mentor")
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
