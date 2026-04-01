"""
Escalation Engine — Health Safety Floor for Companion Agents
Runs BEFORE the Claude API call. Pure regex, no LLM cost.

4 tiers:
  Tier 1: Emergency — override entire response, tell them to call 111 NOW
  Tier 2: Urgent GP — agent responds but mandatory 24-48h GP closing
  Tier 3: Routine GP — agent responds but flags 2-week booking suggestion
  Tier 4: Specialist — agent responds, notes specialist value

All Tier 1-2 escalations are logged to escalation_log table in user_memory.db.
"""

import re
import sqlite3
import logging
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent.parent / "data" / "user_memory.db"

# ─────────────────────────────────────────────────────────────
# ESCALATION RESULT
# ─────────────────────────────────────────────────────────────

@dataclass
class EscalationResult:
    tier: int                          # 0 = no escalation
    triggered: bool
    trigger_pattern: str = ""
    message_override: Optional[str] = None   # Tier 1: replaces entire response
    mandatory_suffix: Optional[str] = None   # Tier 2-4: appended to response
    should_log: bool = False


# ─────────────────────────────────────────────────────────────
# TIER 1 — EMERGENCY PATTERNS (call 111 NOW)
# ─────────────────────────────────────────────────────────────

TIER1_PATTERNS = [
    # Cardiac
    (r"chest\s+(pain|pressure|tightness|squeezing|heaviness).{0,60}(arm|jaw|shoulder|neck|radiating|spreading)",
     "chest pain with radiation"),
    (r"(radiating|spreading).{0,40}(chest|arm|jaw|shoulder)",
     "radiating pain pattern"),
    (r"(heart\s+attack|cardiac\s+arrest)",
     "cardiac emergency keywords"),

    # Breathing
    (r"(can'?t\s+breathe|can'?t\s+catch\s+(my\s+)?breath|not\s+breathing|stopped\s+breathing|struggling\s+to\s+breathe)",
     "breathing emergency"),
    (r"(severe|extreme|sudden)\s+(shortness\s+of\s+breath|difficulty\s+breathing)",
     "severe breathing difficulty"),

    # Stroke (FAST)
    (r"(face\s+(drooping|drooping|numb|falling)|arm\s+(weak|numb|tingling|falling)|speech\s+(slurred|garbled|lost)|sudden\s+(confusion|vision\s+loss|severe\s+headache))",
     "stroke symptoms"),
    (r"(having\s+a\s+stroke|think\s+(it'?s|i'?m\s+having)\s+a?\s*stroke|tia|transient\s+ischemic)",
     "stroke keyword"),

    # Suicidal with plan
    (r"(want\s+to\s+(kill|end|take)\s+(myself|my\s+life)|going\s+to\s+(kill|end|take)\s+(myself|my\s+life))",
     "suicidal ideation with intent"),
    (r"(have\s+a\s+plan\s+to\s+end|planning\s+to\s+(kill|end)\s+myself|suicide\s+plan)",
     "suicide plan"),

    # Seizure
    (r"(having\s+a\s+seizure|seizure\s+(right\s+now|happening|started)|convuls(ing|ions?))",
     "active seizure"),

    # Unconscious / unresponsive
    (r"(unconscious|unresponsive|won'?t\s+wake\s+up|collapsed\s+(and|not)\s+moving)",
     "unconscious / collapsed"),

    # Severe allergic
    (r"(anaphylax|throat\s+(closing|swelling)|tongue\s+swelling|epipen|severe\s+allergic\s+reaction)",
     "anaphylaxis"),

    # Overdose
    (r"(overdos(e|ed|ing)|took\s+too\s+many\s+(pills?|tablets?)|swallowed.{0,30}(whole\s+bottle|all\s+of))",
     "overdose"),
]

# ─────────────────────────────────────────────────────────────
# TIER 2 — URGENT GP (24-48 hours)
# ─────────────────────────────────────────────────────────────

TIER2_PATTERNS = [
    (r"blood\s+in\s+(my\s+)?(stool|poo|poop|faeces|urine|pee|wee|vomit|vomiting|spit)",
     "blood in excretions"),
    (r"(coughing|spitting)\s+up\s+blood",
     "coughing blood"),
    (r"(sudden|worst\s+ever|thunderclap)\s+(severe\s+)?headache",
     "sudden severe headache"),
    (r"(unexplained|sudden|significant)\s+weight\s+loss.{0,30}(kg|kilos?|pounds?)",
     "unexplained weight loss"),
    (r"(lost|losing).{0,20}(5|six|seven|eight|nine|ten|\d{2})\s*(kg|kilos?|pounds?).{0,30}(without|unexplained|don'?t\s+know)",
     "significant unexplained weight loss"),
    (r"(sudden|new|rapid)\s+(vision\s+(change|loss|blur|blurry|double)|can'?t\s+see)",
     "sudden vision change"),
    (r"difficulty\s+swallowing.{0,30}(week|getting\s+worse|can'?t\s+eat|solid)",
     "progressive dysphagia"),
    (r"(fever|temperature).{0,40}(3|4|5|6|7)\s*days",
     "prolonged fever"),
    (r"(high\s+fever|fever.{0,20}(39|40|41|42))",
     "high fever"),
    (r"(lump|mass|growth).{0,40}(appeared|new|changed|growing|noticed)",
     "new lump or growth"),
    (r"(severe\s+abdominal|stomach)\s+(pain|cramp).{0,30}(not\s+going\s+away|hours|days)",
     "severe persistent abdominal pain"),
    (r"(yellowing|jaundice).{0,30}(skin|eyes|whites\s+of)",
     "jaundice"),
]

# ─────────────────────────────────────────────────────────────
# TIER 3 — ROUTINE GP (within 2 weeks)
# ─────────────────────────────────────────────────────────────

TIER3_PATTERNS = [
    (r"(symptom|pain|issue|problem).{0,40}(2|two|3|three|4|four)\s*(weeks?|months?)",
     "symptoms persisting 2+ weeks"),
    (r"(been\s+going\s+on|lasted?|for\s+(over\s+)?).{0,20}(2|two|three|four|five|six)\s*weeks?",
     "prolonged symptoms"),
    (r"(taking|on).{0,30}(medication|meds|prescription|drug).{0,60}(interact|mix|safe\s+with|combine)",
     "medication interaction concern"),
    (r"(changed|changed\s+my|new\s+symptom).{0,40}(diabetes|thyroid|blood\s+pressure|autoimmune|crohn|colitis|ibd|ms\b)",
     "new symptom with chronic condition"),
    (r"(my\s+)?(doctor|gp|specialist)\s+(said|diagnosed|told\s+me).{0,80}(but|however|not\s+sure|confused)",
     "confusion about existing diagnosis"),
    (r"(recurring|keeps\s+coming\s+back|happened\s+before|third\s+time).{0,60}(infection|rash|pain|episode)",
     "recurring episodes"),
]

# ─────────────────────────────────────────────────────────────
# TIER 4 — SPECIALIST FLAG
# ─────────────────────────────────────────────────────────────

TIER4_PATTERNS = [
    (r"(cardiologist|heart\s+specialist)",
     "cardiology concern"),
    (r"(endocrinologist|hormone\s+specialist|thyroid\s+specialist)",
     "endocrinology concern"),
    (r"(neurologist|brain\s+specialist|nerve\s+specialist)",
     "neurology concern"),
    (r"(rheumatologist|joint\s+specialist|autoimmune\s+specialist)",
     "rheumatology concern"),
    (r"(gastroenterologist|gut\s+specialist|colonoscopy)",
     "gastroenterology concern"),
    (r"(oncologist|cancer\s+specialist|biopsy\s+result)",
     "oncology concern"),
    (r"(psychiatrist|mental\s+health\s+specialist).{0,40}(refer|should\s+see|need\s+to)",
     "psychiatry referral signal"),
]

# ─────────────────────────────────────────────────────────────
# SUFFIXES
# ─────────────────────────────────────────────────────────────

TIER2_SUFFIX = (
    "\n\n⚠️ One thing I want to flag: what you've described is something a GP should look at "
    "within the next 24-48 hours. Please don't put this off — book in today if you can."
)

TIER3_SUFFIX = (
    "\n\n📋 Worth noting: if this is still going on in two weeks, it's worth getting it checked "
    "with a GP. Symptoms that persist deserve a proper look."
)

TIER4_SUFFIX = (
    "\n\n💡 A specialist opinion would add real value here — your GP can refer you if you feel "
    "like this needs deeper investigation."
)

TIER1_OVERRIDE_TEMPLATE = (
    "🚨 I need to stop you right there.\n\n"
    "What you've described sounds like it could be a medical emergency. "
    "Please call **111** (NZ emergency services) right now, or get someone to take you "
    "to your nearest A&E immediately.\n\n"
    "Do not wait. This is not something I can help you with — you need a doctor now.\n\n"
    "If you're with someone, tell them what's happening. If you're alone, call 111 first."
)


# ─────────────────────────────────────────────────────────────
# DATABASE SETUP
# ─────────────────────────────────────────────────────────────

def _ensure_escalation_table():
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS escalation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                agent_id TEXT NOT NULL,
                tier INTEGER NOT NULL,
                trigger_pattern TEXT,
                message_excerpt TEXT,
                timestamp TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Could not create escalation_log table: {e}")


def _log_escalation(user_id: str, agent_id: str, tier: int, trigger_pattern: str, message_excerpt: str):
    try:
        _ensure_escalation_table()
        conn = sqlite3.connect(DB_PATH)
        conn.execute(
            "INSERT INTO escalation_log (user_id, agent_id, tier, trigger_pattern, message_excerpt, timestamp) VALUES (?,?,?,?,?,?)",
            (user_id, agent_id, tier, trigger_pattern, message_excerpt[:200], datetime.utcnow().isoformat())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Could not log escalation: {e}")


# ─────────────────────────────────────────────────────────────
# MAIN CHECK FUNCTION
# ─────────────────────────────────────────────────────────────

def check(message_text: str, user_id: str = "", agent_id: str = "") -> EscalationResult:
    """
    Check a message for health escalation triggers.
    Returns EscalationResult with tier and any response overrides/suffixes.

    Call this BEFORE the Claude API call for companion agents.
    If result.tier == 1: return result.message_override directly, skip API call.
    If result.tier in (2, 3, 4): append result.mandatory_suffix to the API response.
    If result.tier == 0: proceed normally.
    """
    text = message_text.lower()

    # Tier 1 — Emergency
    for pattern, label in TIER1_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning(f"ESCALATION TIER 1 [{label}] — {agent_id}/{user_id}")
            result = EscalationResult(
                tier=1,
                triggered=True,
                trigger_pattern=label,
                message_override=TIER1_OVERRIDE_TEMPLATE,
                should_log=True,
            )
            _log_escalation(user_id, agent_id, 1, label, message_text)
            return result

    # Tier 2 — Urgent GP
    for pattern, label in TIER2_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.info(f"ESCALATION TIER 2 [{label}] — {agent_id}/{user_id}")
            result = EscalationResult(
                tier=2,
                triggered=True,
                trigger_pattern=label,
                mandatory_suffix=TIER2_SUFFIX,
                should_log=True,
            )
            _log_escalation(user_id, agent_id, 2, label, message_text)
            return result

    # Tier 3 — Routine GP
    for pattern, label in TIER3_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.info(f"ESCALATION TIER 3 [{label}] — {agent_id}/{user_id}")
            return EscalationResult(
                tier=3,
                triggered=True,
                trigger_pattern=label,
                mandatory_suffix=TIER3_SUFFIX,
                should_log=False,
            )

    # Tier 4 — Specialist flag
    for pattern, label in TIER4_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.info(f"ESCALATION TIER 4 [{label}] — {agent_id}/{user_id}")
            return EscalationResult(
                tier=4,
                triggered=True,
                trigger_pattern=label,
                mandatory_suffix=TIER4_SUFFIX,
                should_log=False,
            )

    return EscalationResult(tier=0, triggered=False)
