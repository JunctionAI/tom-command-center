"""
Constraint Checker — Pre-send gate for companion agents.

Before any companion agent response reaches the user via Telegram, this module
checks it against ACTIVE CONSTRAINTS and today's training schedule from
CURRENT_PLAN.md. If a violation is detected, the caller can block (scheduled
tasks) or alert (user replies).

Checks:
1. ACTIVE CONSTRAINTS — food eliminations, phase restrictions, device status
2. TRAINING SCHEDULE — wrong workout for today's day, training prescribed on rest day

Cost: ~$0.001 per check (Haiku).
"""

import logging
import re
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
AGENTS_DIR = BASE_DIR / "agents"
HAIKU_MODEL = "claude-haiku-4-5-20251001"
NZ_TZ = ZoneInfo("Pacific/Auckland")


def _read_plan(agent_name: str) -> str:
    """Read CURRENT_PLAN.md content. Returns empty string if not found."""
    plan_file = AGENTS_DIR / agent_name / "state" / "CURRENT_PLAN.md"
    if not plan_file.exists():
        return ""
    try:
        return plan_file.read_text(encoding="utf-8")
    except Exception:
        return ""


def extract_constraints(agent_name: str) -> list[str]:
    """
    Extract the ACTIVE CONSTRAINTS section as a list of bullet strings.
    Returns empty list if no plan or no constraints section.
    """
    content = _read_plan(agent_name)
    if not content:
        return []

    marker = "ACTIVE CONSTRAINTS"
    if marker not in content:
        return []

    start = content.index(marker)
    rest = content[start:]
    end_markers = ["\n---", "\n## "]
    end_pos = len(rest)
    for em in end_markers:
        idx = rest.find(em, len(marker))
        if idx != -1 and idx < end_pos:
            end_pos = idx

    section = rest[:end_pos]

    constraints = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            constraints.append(line[2:].strip())

    return constraints


def extract_todays_schedule(agent_name: str) -> str:
    """
    Extract today's training schedule from CURRENT_PLAN.md.

    Looks for lines matching **DayName — Description** in the TRAINING SPLIT section.
    Returns the full day block (e.g., "Thursday — Walk + Breathwork + Mobility\n...details...")
    or empty string if not found.
    """
    content = _read_plan(agent_name)
    if not content:
        return ""

    today_name = datetime.now(NZ_TZ).strftime("%A")  # e.g., "Thursday"

    # Find the training split section
    split_markers = ["CURRENT TRAINING SPLIT", "TRAINING SPLIT", "TRAINING SCHEDULE"]
    split_start = -1
    for marker in split_markers:
        if marker in content:
            split_start = content.index(marker)
            break

    if split_start == -1:
        return ""

    training_section = content[split_start:]

    # Find today's day block — handles both formats:
    # **Thursday — Walk + Breathwork + Mobility**  (Forge format)
    # Thursday — Legs + Zone 2 (20 min)             (Apex format)
    pattern = rf'(?:\*\*)?{today_name}\s*[—\-–]\s*(.+?)(?:\*\*)?$'
    match = re.search(pattern, training_section, re.MULTILINE)
    if not match:
        return ""

    # Extract from the day header to the next day header or section end
    day_start = match.start()
    rest_after_day = training_section[day_start:]

    # Find next day header or section separator (handles bold and non-bold)
    next_day = re.search(r'\n(?:\*\*)?(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s*[—\-–]', rest_after_day[10:])
    section_end = rest_after_day.find("\n---", 10)

    if next_day and section_end > 0:
        end = min(next_day.start() + 10, section_end)
    elif next_day:
        end = next_day.start() + 10
    elif section_end > 0:
        end = section_end
    else:
        end = min(len(rest_after_day), 500)

    return rest_after_day[:end].strip()


def check_response(agent_name: str, response_text: str) -> dict:
    """
    Check a companion agent response against ACTIVE CONSTRAINTS + today's schedule.

    Returns:
        {"passed": True} — no violations detected
        {"passed": False, "violation": "description"} — violation found
    """
    constraints = extract_constraints(agent_name)
    todays_schedule = extract_todays_schedule(agent_name)

    # Nothing to check
    if not constraints and not todays_schedule:
        return {"passed": True}

    # Don't check very short responses (errors, acknowledgments)
    if len(response_text) < 50:
        return {"passed": True}

    # Build constraint list
    constraint_list = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(constraints))

    # Build schedule context
    today_name = datetime.now(NZ_TZ).strftime("%A")
    schedule_block = ""
    if todays_schedule:
        schedule_block = f"""

TODAY'S SCHEDULED WORKOUT ({today_name}):
{todays_schedule}

SCHEDULE VIOLATION CHECK:
- If today is a rest/recovery day and the bot tells the user to go to the gym or prescribes a strength workout, that is a VIOLATION
- If today is a specific workout day (e.g., Push day) and the bot prescribes a different workout (e.g., Pull day or Full Body), that is a VIOLATION
- If the bot prescribes the CORRECT workout for today, that is fine
- If the user ASKS about changing their schedule, the bot discussing options is NOT a violation — only prescribing the wrong workout unprompted is"""

    prompt = f"""You are a constraint and schedule violation checker for a health coaching bot. Check if the bot's response violates any rules.

ACTIVE CONSTRAINTS (rules the bot MUST follow):
{constraint_list}
{schedule_block}

BOT'S RESPONSE TO CHECK:
{response_text[:3000]}

Does the response violate ANY constraint or schedule rule? Check carefully:
- Does it suggest a food that is eliminated? (rice, nightshades, legumes, sourdough, whey, etc.)
- Does it suggest equipment/exercises not allowed in the current phase?
- Does it ask for data from a device that is broken?
- Does it prescribe the WRONG workout for today or tell the user to train on a rest day?
- Does it contradict any explicit rule?

Respond with EXACTLY one of:
- PASS — if no rules are violated
- VIOLATION: [brief description of what rule was violated and what the response said]

Be strict on food and equipment. For schedule violations, only flag if the bot clearly prescribes the wrong workout or tells the user to gym on a rest/recovery day."""

    try:
        import anthropic
        client = anthropic.Anthropic()
        result = client.messages.create(
            model=HAIKU_MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}],
            timeout=30.0,
        )
        response = result.content[0].text.strip()

        if "VIOLATION" in response:
            violation_desc = response.replace("VIOLATION:", "").strip()
            logger.warning(f"Constraint violation for {agent_name}: {violation_desc[:200]}")
            return {"passed": False, "violation": violation_desc}

        return {"passed": True}

    except Exception as e:
        # Fail open — never block a message because the checker broke
        logger.warning(f"Constraint checker failed for {agent_name} (fail-open): {e}")
        return {"passed": True}
