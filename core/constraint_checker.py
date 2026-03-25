"""
Constraint Checker — Pre-send gate for companion agents.

Before any companion agent response reaches the user via Telegram, this module
checks it against the ACTIVE CONSTRAINTS in CURRENT_PLAN.md. If a violation is
detected, the caller can block (scheduled tasks) or alert (user replies).

Cost: ~$0.001 per check (Haiku).
"""

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent.parent
AGENTS_DIR = BASE_DIR / "agents"
HAIKU_MODEL = "claude-haiku-4-5-20251001"


def extract_constraints(agent_name: str) -> list[str]:
    """
    Read CURRENT_PLAN.md for an agent and extract the ACTIVE CONSTRAINTS section.
    Returns a list of constraint strings (one per bullet point).
    Returns empty list if no plan or no constraints section.
    """
    plan_file = AGENTS_DIR / agent_name / "state" / "CURRENT_PLAN.md"
    if not plan_file.exists():
        return []

    try:
        content = plan_file.read_text(encoding="utf-8")
    except Exception:
        return []

    # Find ACTIVE CONSTRAINTS section
    marker = "ACTIVE CONSTRAINTS"
    if marker not in content:
        return []

    start = content.index(marker)
    # Find the end of the section (next --- separator or end of file)
    rest = content[start:]
    end_markers = ["\n---", "\n## "]
    end_pos = len(rest)
    for em in end_markers:
        idx = rest.find(em, len(marker))
        if idx != -1 and idx < end_pos:
            end_pos = idx

    section = rest[:end_pos]

    # Extract bullet points
    constraints = []
    for line in section.split("\n"):
        line = line.strip()
        if line.startswith("- "):
            constraints.append(line[2:].strip())

    return constraints


def check_response(agent_name: str, response_text: str) -> dict:
    """
    Check a companion agent response against ACTIVE CONSTRAINTS.

    Returns:
        {"passed": True} — no violation detected (or no constraints to check)
        {"passed": False, "violation": "description"} — violation found
    """
    constraints = extract_constraints(agent_name)
    if not constraints:
        return {"passed": True}

    # Don't check very short responses (errors, acknowledgments)
    if len(response_text) < 50:
        return {"passed": True}

    # Build constraint list for the prompt
    constraint_list = "\n".join(f"  {i+1}. {c}" for i, c in enumerate(constraints))

    prompt = f"""You are a constraint violation checker for a health coaching bot. Your ONLY job is to check if the bot's response violates the user's active constraints.

ACTIVE CONSTRAINTS (these are rules the bot MUST follow):
{constraint_list}

BOT'S RESPONSE TO CHECK:
{response_text[:3000]}

Does the response violate ANY constraint? Check carefully:
- Does it suggest a food that is eliminated? (rice, nightshades, legumes, sourdough, whey, etc.)
- Does it suggest equipment/exercises that aren't allowed in the current phase?
- Does it ask for data from a device that is broken?
- Does it contradict any explicit rule?

Respond with EXACTLY one of:
- PASS — if no constraints are violated
- VIOLATION: [which constraint number] — [what the response said that violates it]

Be strict. If the response suggests rice in ANY form (rice cakes, white rice, brown rice), that's a violation if rice is eliminated. If it mentions dumbbells/barbells during a bodyweight-only phase, that's a violation."""

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
