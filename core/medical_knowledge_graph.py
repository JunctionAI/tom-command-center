"""
medical_knowledge_graph.py — Health Ontology in Neo4j
======================================================

Separate from user memory graph. This is a KNOWLEDGE graph, not a user graph.
It holds medical/health domain knowledge that agents query to inform recommendations.

Node types:
  KCondition   — health condition (diagnosed or functional)
  KIntervention — treatment, supplement, lifestyle, or lifestyle approach
  KEvidence    — evidence quality record linking condition → intervention
  KRedFlag     — symptom or pattern that triggers escalation
  KSpecialist  — specialist type and when to refer

Relationships:
  (KCondition)-[:TREATED_BY]->(KIntervention)
  (KCondition)-[:RED_FLAG]->(KRedFlag)
  (KIntervention)-[:SUPPORTED_BY]->(KEvidence)
  (KCondition)-[:REFER_TO]->(KSpecialist)
  (KIntervention)-[:INTERACTS_WITH]->(KIntervention)
  (KCondition)-[:RELATED_TO]->(KCondition)   ← multi-system connections

KEY FUNCTIONS:
  seed_medical_graph()
      Seeds initial 50-condition ontology from data/medical_ontology_seed.json
      Safe to call multiple times (uses MERGE — won't duplicate)

  query_health_context(keywords, user_conditions=None, top_k=5)
      Returns relevant conditions, interventions, red flags, and evidence
      for injection into companion agent context

  get_red_flags_for_symptoms(symptom_text)
      Returns matching KRedFlag nodes for a free-text symptom description

  is_seeded()
      Returns True if the graph has been seeded (KCondition count > 0)

SETUP: Uses same NEO4J_URI/USERNAME/PASSWORD env vars as graph_memory.py
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
SEED_FILE = BASE_DIR / "data" / "medical_ontology_seed.json"

# ─── Connection (reuses graph_memory driver) ────────────────────────────────

def _get_driver():
    """Reuse the graph_memory driver — same credentials."""
    try:
        from core.graph_memory import _get_driver as _gm_driver
        return _gm_driver()
    except Exception:
        return None


# ─── Schema Setup ────────────────────────────────────────────────────────────

def ensure_schema():
    """Create constraints and indexes for medical graph nodes."""
    driver = _get_driver()
    if not driver:
        return

    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:KCondition) REQUIRE c.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (i:KIntervention) REQUIRE i.name IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (r:KRedFlag) REQUIRE r.symptom IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (s:KSpecialist) REQUIRE s.type IS UNIQUE",
        "CREATE INDEX IF NOT EXISTS FOR (c:KCondition) ON (c.category)",
        "CREATE INDEX IF NOT EXISTS FOR (i:KIntervention) ON (i.evidence_tier)",
    ]
    try:
        with driver.session() as session:
            for cypher in constraints:
                try:
                    session.run(cypher)
                except Exception as e:
                    logger.debug(f"Schema setup (non-fatal): {e}")
        logger.info("Medical graph schema ensured")
    except Exception as e:
        logger.warning(f"Medical graph schema setup failed: {e}")


# ─── Seeding ─────────────────────────────────────────────────────────────────

def is_seeded() -> bool:
    """Check if the medical knowledge graph has been seeded."""
    driver = _get_driver()
    if not driver:
        return False
    try:
        with driver.session() as session:
            result = session.run("MATCH (c:KCondition) RETURN count(c) AS n")
            return result.single()["n"] > 0
    except Exception:
        return False


def seed_medical_graph(force: bool = False) -> dict:
    """
    Seed the medical knowledge graph from data/medical_ontology_seed.json.
    Uses MERGE — safe to call multiple times.

    Returns: {"conditions": int, "interventions": int, "red_flags": int, "specialists": int}
    """
    driver = _get_driver()
    if not driver:
        return {"error": "Neo4j not available"}

    if not force and is_seeded():
        logger.info("Medical graph already seeded — skipping (use force=True to re-seed)")
        return {"skipped": True}

    if not SEED_FILE.exists():
        return {"error": f"Seed file not found: {SEED_FILE}"}

    try:
        seed_data = json.loads(SEED_FILE.read_text())
    except Exception as e:
        return {"error": f"Failed to parse seed file: {e}"}

    ensure_schema()

    counts = {"conditions": 0, "interventions": 0, "red_flags": 0, "specialists": 0, "relationships": 0}

    with driver.session() as session:

        # 1. Seed KCondition nodes
        for cond in seed_data.get("conditions", []):
            session.run("""
                MERGE (c:KCondition {name: $name})
                SET c.category = $category,
                    c.description = $description,
                    c.functional_root = $functional_root,
                    c.conventional_approach = $conventional_approach,
                    c.systems_involved = $systems_involved,
                    c.prevalence = $prevalence
            """, name=cond["name"], category=cond.get("category",""),
                 description=cond.get("description",""),
                 functional_root=cond.get("functional_root",""),
                 conventional_approach=cond.get("conventional_approach",""),
                 systems_involved=",".join(cond.get("systems_involved",[])),
                 prevalence=cond.get("prevalence","common"))
            counts["conditions"] += 1

        # 2. Seed KIntervention nodes
        for intv in seed_data.get("interventions", []):
            session.run("""
                MERGE (i:KIntervention {name: $name})
                SET i.type = $type,
                    i.mechanism = $mechanism,
                    i.evidence_tier = $evidence_tier,
                    i.dose_notes = $dose_notes,
                    i.contraindications = $contraindications,
                    i.ladder_level = $ladder_level
            """, name=intv["name"], type=intv.get("type",""),
                 mechanism=intv.get("mechanism",""),
                 evidence_tier=intv.get("evidence_tier","C"),
                 dose_notes=intv.get("dose_notes",""),
                 contraindications=",".join(intv.get("contraindications",[])),
                 ladder_level=intv.get("ladder_level",3))
            counts["interventions"] += 1

        # 3. Seed KRedFlag nodes
        for rf in seed_data.get("red_flags", []):
            session.run("""
                MERGE (r:KRedFlag {symptom: $symptom})
                SET r.urgency_tier = $urgency_tier,
                    r.reason = $reason,
                    r.action = $action
            """, symptom=rf["symptom"], urgency_tier=rf.get("urgency_tier",2),
                 reason=rf.get("reason",""), action=rf.get("action","See GP"))
            counts["red_flags"] += 1

        # 4. Seed KSpecialist nodes
        for spec in seed_data.get("specialists", []):
            session.run("""
                MERGE (s:KSpecialist {type: $type})
                SET s.when_to_refer = $when_to_refer,
                    s.nz_resource = $nz_resource,
                    s.urgency = $urgency
            """, type=spec["type"], when_to_refer=spec.get("when_to_refer",""),
                 nz_resource=spec.get("nz_resource","GP referral"),
                 urgency=spec.get("urgency","routine"))
            counts["specialists"] += 1

        # 5. Seed relationships: Condition → Intervention (TREATED_BY)
        for rel in seed_data.get("condition_interventions", []):
            session.run("""
                MATCH (c:KCondition {name: $condition})
                MATCH (i:KIntervention {name: $intervention})
                MERGE (c)-[r:TREATED_BY]->(i)
                SET r.priority = $priority, r.notes = $notes
            """, condition=rel["condition"], intervention=rel["intervention"],
                 priority=rel.get("priority",2), notes=rel.get("notes",""))
            counts["relationships"] += 1

        # 6. Seed relationships: Condition → RedFlag (RED_FLAG)
        for rel in seed_data.get("condition_red_flags", []):
            session.run("""
                MATCH (c:KCondition {name: $condition})
                MATCH (r:KRedFlag {symptom: $symptom})
                MERGE (c)-[:RED_FLAG]->(r)
            """, condition=rel["condition"], symptom=rel["symptom"])
            counts["relationships"] += 1

        # 7. Seed relationships: Condition → Specialist (REFER_TO)
        for rel in seed_data.get("condition_specialists", []):
            session.run("""
                MATCH (c:KCondition {name: $condition})
                MATCH (s:KSpecialist {type: $specialist})
                MERGE (c)-[:REFER_TO]->(s)
            """, condition=rel["condition"], specialist=rel["specialist"])
            counts["relationships"] += 1

        # 8. Seed cross-system connections: Condition → Condition (RELATED_TO)
        for rel in seed_data.get("condition_relationships", []):
            session.run("""
                MATCH (a:KCondition {name: $from_condition})
                MATCH (b:KCondition {name: $to_condition})
                MERGE (a)-[r:RELATED_TO]->(b)
                SET r.relationship_type = $rel_type
            """, from_condition=rel["from"], to_condition=rel["to"],
                 rel_type=rel.get("type","comorbid"))
            counts["relationships"] += 1

        # 9. Seed drug-supplement interactions: Intervention → Intervention (INTERACTS_WITH)
        for rel in seed_data.get("interactions", []):
            session.run("""
                MERGE (a:KIntervention {name: $from_name})
                MERGE (b:KIntervention {name: $to_name})
                MERGE (a)-[r:INTERACTS_WITH]->(b)
                SET r.severity = $severity, r.mechanism = $mechanism, r.action = $action
            """, from_name=rel["from"], to_name=rel["to"],
                 severity=rel.get("severity","moderate"),
                 mechanism=rel.get("mechanism",""),
                 action=rel.get("action","Monitor"))
            counts["relationships"] += 1

    logger.info(f"Medical graph seeded: {counts}")
    return counts


# ─── Query Functions ─────────────────────────────────────────────────────────

def query_health_context(keywords: list[str], user_conditions: list[str] = None, top_k: int = 5) -> dict:
    """
    Query the medical knowledge graph for conditions, interventions, red flags,
    and cross-system connections relevant to the given keywords.

    Args:
        keywords: List of symptom/condition keywords extracted from the message
        user_conditions: Known conditions for this user (from memory) — used to find related conditions
        top_k: Max results per category

    Returns dict with:
        conditions: [{name, category, description, functional_root, conventional_approach}]
        interventions: [{name, type, evidence_tier, mechanism, dose_notes, ladder_level}]
        red_flags: [{symptom, urgency_tier, reason, action}]
        related_conditions: [{name, relationship_type}]  ← cross-system connections
        interactions: [{from, to, severity, action}]  ← if user has known conditions
    """
    driver = _get_driver()
    if not driver:
        return {}

    if not keywords:
        return {}

    result = {"conditions": [], "interventions": [], "red_flags": [], "related_conditions": [], "interactions": []}

    # Build keyword regex for fuzzy matching in Neo4j
    keyword_pattern = "|".join(re.escape(k.lower()) for k in keywords[:5])

    try:
        with driver.session() as session:

            # 1. Find relevant conditions by keyword match on name/description/category
            cond_result = session.run("""
                MATCH (c:KCondition)
                WHERE toLower(c.name) CONTAINS $kw1
                   OR toLower(c.description) CONTAINS $kw1
                   OR toLower(c.category) CONTAINS $kw1
                   OR toLower(c.functional_root) CONTAINS $kw1
                RETURN c.name AS name, c.category AS category,
                       c.description AS description,
                       c.functional_root AS functional_root,
                       c.conventional_approach AS conventional_approach,
                       c.systems_involved AS systems_involved
                LIMIT $top_k
            """, kw1=keywords[0].lower() if keywords else "", top_k=top_k)
            result["conditions"] = [dict(r) for r in cond_result]

            # If first keyword got nothing, try remaining keywords
            if not result["conditions"] and len(keywords) > 1:
                for kw in keywords[1:]:
                    cond_result2 = session.run("""
                        MATCH (c:KCondition)
                        WHERE toLower(c.name) CONTAINS $kw
                           OR toLower(c.description) CONTAINS $kw
                           OR toLower(c.category) CONTAINS $kw
                        RETURN c.name AS name, c.category AS category,
                               c.description AS description,
                               c.functional_root AS functional_root,
                               c.conventional_approach AS conventional_approach,
                               c.systems_involved AS systems_involved
                        LIMIT $top_k
                    """, kw=kw.lower(), top_k=top_k)
                    result["conditions"] = [dict(r) for r in cond_result2]
                    if result["conditions"]:
                        break

            # 2. For matched conditions, get their interventions
            if result["conditions"]:
                cond_names = [c["name"] for c in result["conditions"][:3]]
                intv_result = session.run("""
                    MATCH (c:KCondition)-[r:TREATED_BY]->(i:KIntervention)
                    WHERE c.name IN $cond_names
                    RETURN DISTINCT i.name AS name, i.type AS type,
                           i.evidence_tier AS evidence_tier,
                           i.mechanism AS mechanism,
                           i.dose_notes AS dose_notes,
                           i.ladder_level AS ladder_level,
                           i.contraindications AS contraindications,
                           r.priority AS priority
                    ORDER BY r.priority ASC, i.evidence_tier ASC
                    LIMIT $top_k
                """, cond_names=cond_names, top_k=top_k * 2)
                result["interventions"] = [dict(r) for r in intv_result]

                # 3. Get red flags for matched conditions
                rf_result = session.run("""
                    MATCH (c:KCondition)-[:RED_FLAG]->(r:KRedFlag)
                    WHERE c.name IN $cond_names
                    RETURN r.symptom AS symptom, r.urgency_tier AS urgency_tier,
                           r.reason AS reason, r.action AS action
                    ORDER BY r.urgency_tier ASC
                    LIMIT 10
                """, cond_names=cond_names)
                result["red_flags"] = [dict(r) for r in rf_result]

                # 4. Cross-system related conditions
                related_result = session.run("""
                    MATCH (c:KCondition)-[r:RELATED_TO]->(related:KCondition)
                    WHERE c.name IN $cond_names
                    RETURN related.name AS name, related.category AS category,
                           r.relationship_type AS relationship_type
                    LIMIT 8
                """, cond_names=cond_names)
                result["related_conditions"] = [dict(r) for r in related_result]

            # 5. If user has known conditions, check for interactions with common interventions
            if user_conditions:
                interaction_result = session.run("""
                    MATCH (a:KIntervention)-[r:INTERACTS_WITH]->(b:KIntervention)
                    WHERE r.severity IN ['high', 'critical']
                    RETURN a.name AS from_intervention, b.name AS to_intervention,
                           r.severity AS severity, r.mechanism AS mechanism, r.action AS action
                    LIMIT 10
                """)
                result["interactions"] = [dict(r) for r in interaction_result]

    except Exception as e:
        logger.warning(f"Medical graph query failed: {e}")

    return result


def get_red_flags_for_symptoms(symptom_text: str) -> list[dict]:
    """
    Check free-text symptom description against KRedFlag nodes.
    Returns list of matching red flags sorted by urgency tier.
    """
    driver = _get_driver()
    if not driver:
        return []

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH (r:KRedFlag)
                WHERE toLower($text) CONTAINS toLower(r.symptom)
                   OR toLower(r.symptom) CONTAINS any(word IN split(toLower($text), ' ') WHERE size(word) > 4)
                RETURN r.symptom AS symptom, r.urgency_tier AS urgency_tier,
                       r.reason AS reason, r.action AS action
                ORDER BY r.urgency_tier ASC
                LIMIT 5
            """, text=symptom_text.lower())
            return [dict(r) for r in result]
    except Exception as e:
        logger.warning(f"Red flag query failed: {e}")
        return []


def format_health_context_for_agent(keywords: list[str], user_conditions: list[str] = None) -> str:
    """
    Format medical graph query results as a string for injection into agent context.
    Returns empty string if graph not available or no relevant results.
    """
    ctx = query_health_context(keywords, user_conditions=user_conditions)
    if not ctx or not any(ctx.values()):
        return ""

    lines = ["=== MEDICAL KNOWLEDGE GRAPH ==="]

    if ctx.get("conditions"):
        lines.append("\nRelevant conditions:")
        for c in ctx["conditions"][:3]:
            lines.append(f"- {c['name']} ({c.get('category','')}):")
            if c.get("functional_root"):
                lines.append(f"  Functional root: {c['functional_root']}")
            if c.get("conventional_approach"):
                lines.append(f"  Conventional approach: {c['conventional_approach']}")

    if ctx.get("interventions"):
        lines.append("\nEvidence-based interventions (Tier A/B first):")
        tier_order = {"A": 0, "B": 1, "C": 2, "D": 3}
        sorted_intvs = sorted(ctx["interventions"], key=lambda x: tier_order.get(x.get("evidence_tier","C"), 2))
        for i in sorted_intvs[:5]:
            tier = i.get("evidence_tier","?")
            level = i.get("ladder_level","?")
            lines.append(f"- {i['name']} [Tier {tier}, Level {level}]: {i.get('mechanism','')}")
            if i.get("dose_notes"):
                lines.append(f"  Dose: {i['dose_notes']}")
            if i.get("contraindications"):
                lines.append(f"  Caution: {i['contraindications']}")

    if ctx.get("red_flags"):
        lines.append("\nRed flags to watch for:")
        for rf in ctx["red_flags"][:3]:
            tier = rf.get("urgency_tier", 2)
            lines.append(f"- Tier {tier}: {rf['symptom']} → {rf.get('action','See GP')}")

    if ctx.get("related_conditions"):
        lines.append("\nCross-system connections:")
        for rc in ctx["related_conditions"][:3]:
            lines.append(f"- Related to {rc['name']} ({rc.get('relationship_type','comorbid')})")

    if ctx.get("interactions"):
        lines.append("\n⚠️ HIGH-RISK interactions to check:")
        for ix in ctx["interactions"][:3]:
            lines.append(f"- {ix['from_intervention']} + {ix['to_intervention']}: {ix.get('action','Monitor')}")

    return "\n".join(lines) if len(lines) > 1 else ""


def extract_health_keywords(message_text: str) -> list[str]:
    """
    Simple keyword extraction for medical graph queries.
    Pulls multi-word health terms and single significant words.
    """
    text = message_text.lower()

    # Common health keyword patterns (multi-word first)
    multi_word = [
        "insulin resistance", "blood sugar", "blood pressure", "heart rate",
        "brain fog", "brain health", "gut health", "mental health", "sleep quality",
        "chronic pain", "chronic fatigue", "adrenal fatigue", "thyroid health",
        "immune system", "nervous system", "digestive health", "hormonal balance",
        "post concussion", "autoimmune", "inflammatory bowel", "irritable bowel",
        "vitamin d", "omega 3", "fish oil", "vitamin b12", "coenzyme q10",
        "leaky gut", "gut microbiome", "hpa axis", "cortisol levels",
        "testosterone", "estrogen", "progesterone", "perimenopause", "menopause",
        "adhd", "anxiety disorder", "depression", "ptsd", "ocd",
        "weight loss", "weight gain", "muscle recovery", "muscle building",
        "zone 2", "vo2 max", "hrv", "heart rate variability",
    ]

    found = []
    for phrase in multi_word:
        if phrase in text:
            found.append(phrase)

    # Single significant health words (>5 chars, not stopwords)
    stopwords = {"about", "after", "again", "their", "there", "where", "which",
                 "would", "could", "should", "these", "those", "being", "having",
                 "going", "doing", "think", "know", "really", "actually", "because"}
    words = re.findall(r'\b[a-z]{5,}\b', text)
    for w in words:
        if w not in stopwords and w not in " ".join(found):
            found.append(w)

    return found[:8]  # Cap at 8 keywords
