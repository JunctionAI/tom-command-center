#!/usr/bin/env python3
"""
Tom's Command Center -- Core Orchestrator
Routes Telegram messages to specialised agents, each with their own knowledge stack.
Every agent reads its full brain (AGENT.md + skills + playbooks + state) before responding.
"""

import sys
import os

# Load environment variables from .env file
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, use system environment variables

# --- Windows encoding fix ---
# Prevents crashes from Unicode characters (arrows, emojis, em-dashes) on Windows terminal
if os.name == 'nt':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')

import json
import subprocess
import logging
from pathlib import Path
from datetime import datetime, date, timedelta

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")

# --- Configuration ---

BASE_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = BASE_DIR / "agents"
CONFIG_DIR = BASE_DIR / "config"

# Human-readable agent names for error messages and display
AGENT_DISPLAY = {
    "global-events":     "Atlas",
    "dbh-marketing":     "Meridian",
    "health-science":    "Helix",
    "health-fitness":    "Titan",
    "social":            "Compass",
    "creative-projects": "Lens",
    "daily-briefing":    "Oracle",
    "command-center":    "Nexus",
    "strategic-advisor": "PREP",
    "evening-reading":   "ASI",
    "beacon":            "Beacon",
    "odysseus-money":    "Odysseus",
    "strategos-pg":      "Strategos",
    "asclepius-brain":   "Asclepius",
    "marcus-stoic":      "Marcus",
    "trajectory":        "Trajectory",
    "customer-science":  "Customer",
    "experiments":       "Experimenter",
    "principles":        "Codifier",
    "efficiency":        "Auditor",
    "sentinel":          "Sentinel",
    "scout":             "Scout",
    "muse":              "Muse",
    "medici":            "Medici",
    "walker-capital":    "Vesper",
    "walker-capital-tom":   "Vesper",
    "walker-capital-trent": "Vesper",
    "prospector":           "Prospector",
    "apex":                 "Apex",
    # "nova":              "Nova",  # UNCOMMENT when Tane is provisioned
}

# Logging configured by entrypoint.py — just get the logger here
logger = logging.getLogger(__name__)
# Fallback for direct CLI usage (python -m core.orchestrator)
if not logger.handlers and not logging.getLogger().handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(BASE_DIR / "orchestrator.log", encoding='utf-8'),
            logging.StreamHandler()
        ]
    )


def load_config():
    """
    Load telegram and schedule configs.
    Secrets come from environment variables (never from git-tracked files).
    Config files only hold non-sensitive data (chat IDs, agent names, schedules).
    """
    with open(CONFIG_DIR / "telegram.json", encoding='utf-8') as f:
        telegram_config = json.load(f)
    with open(CONFIG_DIR / "schedules.json", encoding='utf-8') as f:
        schedule_config = json.load(f)

    # Override secrets from environment variables (required for deployment)
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    owner_id = os.environ.get("TELEGRAM_OWNER_ID")

    if bot_token:
        telegram_config["bot_token"] = bot_token
    if owner_id:
        telegram_config["owner_user_id"] = owner_id

    # Validate: bot_token must exist from either source
    if not telegram_config.get("bot_token") or telegram_config["bot_token"] == "SET_VIA_ENV_VAR":
        logger.error("TELEGRAM_BOT_TOKEN environment variable not set!")
        raise ValueError("Missing TELEGRAM_BOT_TOKEN. Set it as an environment variable.")

    if not telegram_config.get("owner_user_id") or telegram_config["owner_user_id"] == "SET_VIA_ENV_VAR":
        logger.error("TELEGRAM_OWNER_ID environment variable not set!")
        raise ValueError("Missing TELEGRAM_OWNER_ID. Set it as an environment variable.")

    return telegram_config, schedule_config


# --- Learning Database (lazy-loaded) ---

_learning_db = None

def get_learning_db():
    """Lazy-load the learning database to avoid circular imports."""
    global _learning_db
    if _learning_db is None:
        try:
            from core.learning_db import LearningDB
            _learning_db = LearningDB()
            logger.info("Learning database connected")
        except Exception as e:
            logger.warning(f"Learning database unavailable: {e}")
    return _learning_db


# --- Multi-User Support ---
# Map agent names to non-default user_ids (most agents serve Tom)
CHAT_USER_MAP = {
    "aether": "jackson",
    "apex": "tom",
    "forge": "tyler",
    # "nova": "tane",  # UNCOMMENT when Tane is provisioned
}

# --- Agent Brain Loader ---
# THIS IS THE KEY FUNCTION. Every time an agent speaks, it reads its entire
# knowledge stack first. Same pattern as DBH AIOS CLAUDE.md session startup.

def load_agent_brain(agent_name: str, user_id: str = None, current_context: str = "") -> str:
    """
    Load the full brain for an agent. This is the equivalent of the
    CLAUDE.md session startup -- read identity, skills, playbooks, state.

    current_context: Optional — the user's current message or task prompt.
    If provided AND agent is a companion (aether/forge), uses ASMR active
    retrieval instead of flat memory loading.

    Returns a complete system prompt that makes the agent fully contextualised.
    """
    agent_dir = AGENTS_DIR / agent_name
    brain_parts = []

    # 0. CURRENT DATE -- Always inject first so agents NEVER get confused by stale state files.
    #    This is authoritative. Do not rely on CONTEXT.md "Last Updated" for the current date.
    _now = datetime.now(NZ_TZ)
    _date_str = _now.strftime("%A, %B %d, %Y")
    _time_str = _now.strftime("%H:%M")
    brain_parts.append(
        f"=== CURRENT DATE & TIME ===\n"
        f"Today is {_date_str} ({_time_str} NZST). "
        f"This is the authoritative date. Do NOT infer the date from state file timestamps or session log filenames."
    )

    # 1. IDENTITY -- Always read AGENT.md first (equivalent to CLAUDE.md)
    agent_md = agent_dir / "AGENT.md"
    if agent_md.exists():
        brain_parts.append(f"=== AGENT IDENTITY ===\n{agent_md.read_text(encoding='utf-8')}")
    else:
        logger.error(f"No AGENT.md found for {agent_name}")
        return ""

    # 1.5 PERSISTENT KNOWLEDGE -- Learned patterns and constraints about user
    knowledge_file = agent_dir / "knowledge.md"
    if knowledge_file.exists():
        brain_parts.append(f"=== PERSISTENT KNOWLEDGE (Learned Patterns) ===\n{knowledge_file.read_text(encoding='utf-8')}")

    # 1.6 CURRENT PLAN -- The user's ACTUAL current plan (overrides skills file templates)
    # This is the single source of truth for what the user is doing right now.
    # Loaded ABOVE skills files so it takes priority.
    current_plan_file = agent_dir / "state" / "CURRENT_PLAN.md"
    if current_plan_file.exists():
        brain_parts.append(
            f"=== CURRENT PLAN (ACTIVE — OVERRIDES SKILLS TEMPLATES) ===\n"
            f"This is the user's ACTUAL current plan. If it conflicts with skills files below, "
            f"ALWAYS follow this document. Skills files are templates only.\n\n"
            f"{current_plan_file.read_text(encoding='utf-8')}"
        )

    # 1.7 YESTERDAY'S SUMMARY -- If first message of day, load yesterday's session log
    today = datetime.now(NZ_TZ).date().isoformat()
    yesterday = (datetime.now(NZ_TZ).date() - timedelta(days=1)).isoformat()

    # Diary-tracking agents load last 7 days of session logs for continuity.
    # Other agents load yesterday only.
    DIARY_AGENTS = ["apex", "marcus-stoic", "compass", "aether", "forge"]
    if agent_name in DIARY_AGENTS:
        recent_logs = []
        for days_back in range(1, 8):  # Last 7 days
            log_date = (datetime.now(NZ_TZ).date() - timedelta(days=days_back)).isoformat()
            log_file = agent_dir / "state" / f"session-log-{log_date}.md"
            if log_file.exists():
                try:
                    log_content = log_file.read_text(encoding='utf-8')
                    summary = log_content[:2000] if len(log_content) > 2000 else log_content
                    recent_logs.append(f"--- {log_date} ---\n{summary}")
                except Exception:
                    pass
        if recent_logs:
            brain_parts.append(f"=== RECENT DIARY (Last 7 Days) ===\n" + "\n\n".join(recent_logs))
        else:
            # Calculate actual day number from CONTEXT.md start date or LIVE UPDATES,
            # rather than assuming Day 1 (session logs may not persist across deploys).
            day_number = None
            state_file_for_diary = agent_dir / "state" / "CONTEXT.md"
            if state_file_for_diary.exists():
                try:
                    _ctx = state_file_for_diary.read_text(encoding='utf-8')
                    # Check LIVE UPDATES for recent activity (proves agent has been running)
                    _has_live_updates = "## LIVE UPDATES" in _ctx and _ctx.strip().endswith("## LIVE UPDATES") is False
                    _live_section = ""
                    if "## LIVE UPDATES" in _ctx:
                        _live_section = _ctx[_ctx.index("## LIVE UPDATES"):]
                    _has_entries = bool(re.search(r'- \[.+\]', _live_section))

                    # Extract start date from CONTEXT.md (look for "Start Date:" or "Started" or "restarted" date)
                    import re as _re_diary
                    _start_match = _re_diary.search(
                        r'(?:\*?\*?Start(?:ed)? Date?\*?\*?|restarted?|restarts)\s*[:\s—-]*\s*(\w+ \d{1,2},? \d{4})',
                        _ctx, _re_diary.IGNORECASE
                    )
                    if _start_match:
                        from datetime import datetime as _dt_diary
                        try:
                            _start_str = _start_match.group(1).replace(',', '')
                            _start_date = _dt_diary.strptime(_start_str, "%B %d %Y").date()
                            day_number = (datetime.now(NZ_TZ).date() - _start_date).days + 1  # Day 1 = start date
                        except ValueError:
                            pass
                except Exception:
                    pass

            if day_number and day_number > 1:
                brain_parts.append(
                    f"=== RECENT DIARY (Last 7 Days) ===\n"
                    f"No session log files found (may have been cleared on deploy). "
                    f"However, based on the protocol start date in CONTEXT.md, today is Day {day_number} of tracking. "
                    f"Do NOT say 'Day 1'. Check LIVE UPDATES in CONTEXT.md for the most recent state. "
                    f"Continue from where you left off."
                )
            else:
                brain_parts.append(f"=== RECENT DIARY (Last 7 Days) ===\nNo previous session logs found. Today ({today}) is Day 1 of tracking.")
    else:
        yesterday_log = agent_dir / "state" / f"session-log-{yesterday}.md"
        if yesterday_log.exists():
            try:
                yesterday_content = yesterday_log.read_text(encoding='utf-8')
                # Extract just the summary section (first 1000 chars)
                if "## SUMMARY" in yesterday_content:
                    summary_start = yesterday_content.find("## SUMMARY")
                    summary_section = yesterday_content[summary_start:summary_start+1000]
                else:
                    summary_section = yesterday_content[:500]
                brain_parts.append(f"=== YESTERDAY'S SUMMARY ===\n{summary_section}")
            except Exception as e:
                logger.warning(f"Could not load yesterday's session log: {e}")

    # 2. TRAINING -- Deep domain knowledge (mental models, frameworks, anti-patterns)
    training_dir = agent_dir / "training"
    if training_dir.exists():
        training_files = sorted(training_dir.glob("*.md"))
        if training_files:
            brain_parts.append("=== TRAINING (WORLD-CLASS DOMAIN KNOWLEDGE) ===")
            for f in training_files:
                brain_parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")

    # 3. PLAYBOOKS -- Proven patterns, always load (highest priority knowledge)
    playbooks_dir = agent_dir / "playbooks"
    if playbooks_dir.exists():
        playbook_files = sorted(playbooks_dir.glob("*.md"))
        if playbook_files:
            brain_parts.append("=== PLAYBOOKS (PROVEN PATTERNS -- HIGHEST PRIORITY) ===")
            for f in playbook_files:
                brain_parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")

    # 4. SKILLS -- Domain expertise, load all for this agent
    skills_dir = agent_dir / "skills"
    if skills_dir.exists():
        skill_files = sorted(skills_dir.glob("*.md"))
        if skill_files:
            brain_parts.append("=== SKILLS (DOMAIN EXPERTISE) ===")
            for f in skill_files:
                brain_parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")

    # 5. INTELLIGENCE -- Latest periodic research/reports
    intel_dir = agent_dir / "intelligence"
    if intel_dir.exists():
        intel_files = sorted(intel_dir.glob("*.md"), reverse=True)  # newest first
        if intel_files:
            # Only load the most recent intelligence file to save context
            brain_parts.append(f"=== LATEST INTELLIGENCE ===\n--- {intel_files[0].name} ---\n{intel_files[0].read_text(encoding='utf-8')}")

    # 6. STATE -- Current context, what's happening now (always load)
    state_file = agent_dir / "state" / "CONTEXT.md"
    if state_file.exists():
        brain_parts.append(f"=== CURRENT STATE ===\n{state_file.read_text(encoding='utf-8')}")

    # 7. DECISION MEMORY -- Recent decisions with reasoning chains
    try:
        from core.decision_logger import DecisionLogger
        dl = DecisionLogger()
        decision_context = dl.format_decisions_for_agent(agent_name)
        dl.close()
        if decision_context:
            brain_parts.append(decision_context)
    except Exception:
        pass  # Non-fatal, agent works fine without decision memory

    # 8. SHARED STRATEGY -- Load shared context for strategic agents
    STRATEGY_AGENTS = ["dbh-marketing", "strategic-advisor", "daily-briefing", "beacon", "health-science"]
    if agent_name in STRATEGY_AGENTS:
        shared_strategy_dir = AGENTS_DIR / "shared" / "strategy"
        if shared_strategy_dir.exists():
            strategy_files = sorted(shared_strategy_dir.glob("*.md"))
            if strategy_files:
                brain_parts.append("=== SHARED STRATEGY (90-Day Execution Plan) ===")
                for f in strategy_files:
                    brain_parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
                logger.info(f"Loaded {len(strategy_files)} shared strategy files for {agent_name}")

    # 9. USER MEMORY -- Persistent learned knowledge about this user
    # Memory system: ASMR active retrieval for companions, legacy flat loading for others
    if user_id:
        try:
            if agent_name in CHAT_USER_MAP and current_context:
                # ASMR: active retrieval with 3 parallel search agents
                from core.asmr_memory import asmr_load
                user_memory = asmr_load(user_id, agent_name, current_context)
                if user_memory:
                    brain_parts.append(user_memory)
                    logger.info(f"ASMR memory loaded for {agent_name}/{user_id}: {len(user_memory)} chars")
            else:
                # Legacy: flat fact loading for Tom's agents
                from core.user_memory import load_user_memory
                user_memory = load_user_memory(user_id, agent_name)
                if user_memory:
                    brain_parts.append(user_memory)
                    logger.info(f"Legacy memory loaded for {agent_name}/{user_id}: {len(user_memory)} chars")
        except Exception as e:
            logger.warning(f"Memory load failed (non-fatal): {e}")

    brain = "\n\n".join(brain_parts)

    # Log brain size for monitoring
    token_estimate = len(brain) // 4  # rough estimate
    logger.info(f"Loaded brain for {agent_name}: ~{token_estimate} tokens, "
                f"{len(brain_parts)} sections")

    return brain


def update_agent_state(agent_name: str, new_info: str):
    """
    Update an agent's CONTEXT.md with new state information.

    Strategy: CONTEXT.md has two zones:
    1. FOUNDATION (everything above "## LIVE UPDATES") -- manually written, never touched
    2. LIVE UPDATES (below the marker) -- rolling log of recent state updates, max 20 entries

    Also stores the update in intelligence.db for long-term pattern detection.
    """
    state_file = AGENTS_DIR / agent_name / "state" / "CONTEXT.md"
    if not state_file.exists():
        logger.warning(f"No state file for {agent_name}")
        return

    current = state_file.read_text(encoding='utf-8')
    timestamp = datetime.now(NZ_TZ).strftime("%B %d, %Y %H:%M")

    # Update the "Last Updated" line
    if "## Last Updated:" in current:
        lines = current.split("\n")
        for i, line in enumerate(lines):
            if line.startswith("## Last Updated:"):
                lines[i] = f"## Last Updated: {timestamp}"
                break
        current = "\n".join(lines)

    # Split into foundation + live updates
    live_marker = "## LIVE UPDATES"
    if live_marker in current:
        foundation = current[:current.index(live_marker)]
        live_section = current[current.index(live_marker):]
        # Parse existing updates (each starts with "- [")
        existing_updates = [line for line in live_section.split("\n")
                           if line.startswith("- [")]
    else:
        foundation = current
        existing_updates = []

    # Add new update, keep max 20 (rolling window)
    existing_updates.insert(0, f"- [{timestamp}] {new_info.strip()}")
    existing_updates = existing_updates[:20]

    # Rebuild file: foundation stays intact, live updates are rolling
    new_content = foundation.rstrip() + f"\n\n{live_marker}\n" + "\n".join(existing_updates) + "\n"
    state_file.write_text(new_content, encoding='utf-8')
    logger.info(f"Updated state for {agent_name}")

    # Store in intelligence.db learning loop for long-term patterns
    try:
        from core.learning_loop import set_state, log_event
        set_state(agent_name, f"update_{timestamp.replace(' ', '_').replace(',', '')}", new_info.strip()[:500])
        log_event(
            agent=agent_name,
            event_type="state.update",
            severity="INFO",
            title=f"State update from {agent_name}",
            description=new_info.strip()[:500]
        )
    except Exception as e:
        logger.debug(f"Learning loop state store failed (non-fatal): {e}")


# --- Session Logging (NEW) ---

def append_to_session_log(agent_name: str, tom_input: str, agent_response: str, markers_found: dict):
    """
    Append interaction to today's session log.
    Creates session-log-YYYY-MM-DD.md if it doesn't exist.

    markers_found = {
        'metrics': [...],
        'insights': [...],
        'state_updates': [...],
        'events': [...]
    }
    """
    today = datetime.now(NZ_TZ).date().isoformat()

    log_file = AGENTS_DIR / agent_name / "state" / f"session-log-{today}.md"

    # Create log file if it doesn't exist
    if not log_file.exists():
        header = f"# SESSION LOG — {agent_name.title()}\n## Date: {today}\n\n"
        log_file.write_text(header, encoding='utf-8')
        logger.info(f"Created new session log: {log_file}")

    # Append interaction
    timestamp = datetime.now(NZ_TZ).strftime("%H:%M:%S")
    interaction_entry = f"""
### INTERACTION at {timestamp}
**Tom said:** {tom_input[:200]}...

**Markers extracted:**
- Metrics: {', '.join([str(m) for m in markers_found.get('metrics', [])]) or 'None'}
- Insights: {', '.join([str(i) for i in markers_found.get('insights', [])]) or 'None'}
- State updates: {', '.join([str(s) for s in markers_found.get('state_updates', [])]) or 'None'}
- Events: {', '.join([str(e) for e in markers_found.get('events', [])]) or 'None'}

"""

    try:
        current = log_file.read_text(encoding='utf-8')
        current += interaction_entry
        log_file.write_text(current, encoding='utf-8')
        logger.info(f"Appended to session log for {agent_name}")
    except Exception as e:
        logger.warning(f"Failed to append to session log: {e}")


def extract_markers_from_response(response: str) -> dict:
    """
    Extract all structured markers from agent response.
    Returns dict with lists of found markers.
    """
    import re

    markers = {
        'metrics': [],
        'insights': [],
        'state_updates': [],
        'events': [],
        'tasks': []
    }

    # [METRIC: name|value|context]
    for match in re.finditer(r'\[METRIC:\s*([^|]+)\|([^|]+)\|([^\]]+)\]', response):
        markers['metrics'].append({
            'name': match.group(1).strip(),
            'value': match.group(2).strip(),
            'context': match.group(3).strip()
        })

    # [INSIGHT: category|content|evidence]
    for match in re.finditer(r'\[INSIGHT:\s*([^|]+)\|([^|]+)\|([^\]]+)\]', response):
        markers['insights'].append({
            'category': match.group(1).strip(),
            'content': match.group(2).strip(),
            'evidence': match.group(3).strip()
        })

    # [STATE UPDATE: ...]
    for match in re.finditer(r'\[STATE UPDATE:\s*([^\]]+)\]', response):
        markers['state_updates'].append(match.group(1).strip())

    # [EVENT: type|severity|payload]
    for match in re.finditer(r'\[EVENT:\s*([^|]+)\|([^|]+)\|([^\]]+)\]', response):
        markers['events'].append({
            'type': match.group(1).strip(),
            'severity': match.group(2).strip(),
            'payload': match.group(3).strip()
        })

    # [TASK: title|priority|description]
    for match in re.finditer(r'\[TASK:\s*([^|]+)\|([^|]+)\|([^\]]+)\]', response):
        markers['tasks'].append({
            'title': match.group(1).strip(),
            'priority': match.group(2).strip(),
            'description': match.group(3).strip()
        })

    return markers


# --- API Usage Tracking ---

# Global variable to track which agent is currently being served (set before call_claude)
_current_agent_name = None

def _track_api_usage(agent_name: str, model: str, input_tokens: int, output_tokens: int):
    """Track API usage per agent per day to data/api_usage.json"""
    import json
    usage_file = Path(__file__).parent.parent / "data" / "api_usage.json"
    usage_file.parent.mkdir(parents=True, exist_ok=True)

    # Load existing data
    usage = {}
    if usage_file.exists():
        try:
            usage = json.loads(usage_file.read_text(encoding='utf-8'))
        except Exception:
            usage = {}

    today = datetime.now(NZ_TZ).date().isoformat()

    # Ensure agent entry exists
    if agent_name not in usage:
        usage[agent_name] = {"_total_input_tokens": 0, "_total_output_tokens": 0, "_total_cost_usd": 0}

    agent_data = usage[agent_name]

    # Ensure day entry exists
    if today not in agent_data:
        agent_data[today] = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "model": model}

    # Pricing (Sonnet 4.6)
    # Input: $3/M tokens, Output: $15/M tokens (Sonnet)
    # Input: $15/M tokens, Output: $75/M tokens (Opus)
    if "opus" in model:
        cost = (input_tokens * 15.0 / 1_000_000) + (output_tokens * 75.0 / 1_000_000)
    else:  # Sonnet
        cost = (input_tokens * 3.0 / 1_000_000) + (output_tokens * 15.0 / 1_000_000)

    # Update daily
    agent_data[today]["input_tokens"] += input_tokens
    agent_data[today]["output_tokens"] += output_tokens
    agent_data[today]["calls"] += 1

    # Update totals
    agent_data["_total_input_tokens"] += input_tokens
    agent_data["_total_output_tokens"] += output_tokens
    agent_data["_total_cost_usd"] += cost

    # Write back
    usage_file.write_text(json.dumps(usage, indent=2), encoding='utf-8')


# --- Claude API Caller ---

def call_claude(system_prompt: str, user_message: str, task_type: str = "chat",
                conversation_history: list = None, agent_name: str = "unknown") -> str:
    """
    Call Claude API with the full agent brain as system prompt.

    For scheduled tasks, user_message is the task instruction.
    For chat responses, user_message is the user's message.

    conversation_history: Optional list of prior messages [{"role": "user"|"assistant", "content": "..."}]
                          to give the agent multi-turn conversational memory.
    """
    import anthropic

    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var

    # All agents use Sonnet to control costs
    model = "claude-sonnet-4-6"
    api_timeout = 120.0

    # Build messages array: conversation history + current message
    if conversation_history:
        messages = conversation_history + [{"role": "user", "content": user_message}]
    else:
        messages = [{"role": "user", "content": user_message}]

    logger.info(f"Calling Claude API: model={model}, system_len={len(system_prompt)}, user_len={len(user_message)}, history_turns={len(messages)-1}, timeout={api_timeout}s")
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=messages,
            timeout=api_timeout,
        )
        logger.info(f"Claude API responded: {len(response.content[0].text)} chars, stop={response.stop_reason}")

        # Track API usage per agent per day
        try:
            _track_api_usage(agent_name, model, response.usage.input_tokens, response.usage.output_tokens)
        except Exception as track_err:
            logger.warning(f"Usage tracking failed (non-fatal): {track_err}")

        return response.content[0].text
    except Exception as e:
        logger.error(f"Claude API error ({model}): {e}")
        return f"API Error: {str(e)}"


# --- Claude Code Caller (Alternative -- uses local Claude Code CLI) ---

def call_claude_code(agent_name: str, task: str) -> str:
    """
    Alternative: Use Claude Code CLI instead of API.
    This gives you tool use (web search, file operations, etc.)
    """
    brain = load_agent_brain(agent_name)

    prompt = f"""You are operating as agent '{agent_name}' in the Command Center system.

{brain}

=== TASK ===
{task}

Remember: Read your full context above before responding. Your identity, knowledge,
and current state are all there. Respond in character as specified in your AGENT.md.
After responding, if there's new information worth tracking, note what should be
added to your state/CONTEXT.md.
"""

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--no-input"],
            capture_output=True, text=True, timeout=120
        )
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Claude Code timed out"
    except FileNotFoundError:
        return "Claude Code CLI not found -- install with: npm install -g @anthropic-ai/claude-code"
    except Exception as e:
        return f"Error: {str(e)}"


# --- Learning Loop Integration ---

def process_response_learning(agent_name: str, response: str, trigger: str = "chat",
                               task: str = None, input_summary: str = None, full_input: str = None) -> str:
    """
    After every agent response:
    1. Extract structured insights/decisions/metrics from markers
    2. Log the interaction to learning.db
    3. Log to daily session log
    4. Clean markers from the response before sending to Telegram

    full_input: The complete user input (for session logging). If None, input_summary is used.

    Returns the cleaned response.
    """
    db = get_learning_db()
    if db is None:
        # Learning DB not available, just clean and return
        return _clean_markers(response)

    try:
        from core.learning_db import InsightExtractor

        # Extract and log structured data
        InsightExtractor.extract_from_response(agent_name, response, db)

        # Log the interaction
        db.log_interaction(
            agent=agent_name,
            trigger=trigger,
            task=task,
            input_summary=input_summary[:200] if input_summary else None,
            output_summary=response[:500]
        )

        # Extract markers for session log
        markers = extract_markers_from_response(response)

        # Append to today's session log
        tom_input = full_input if full_input else (input_summary or "")
        append_to_session_log(agent_name, tom_input, response, markers)

        # Process cross-agent events from response
        process_events_from_response(agent_name, response)

        # Auto-create Asana tasks from response
        create_asana_tasks_from_response(agent_name, response)

        # Extract structured decisions with reasoning chains
        try:
            from core.decision_logger import DecisionLogger
            dl = DecisionLogger()
            dl.extract_decisions_from_response(agent_name, response)
            dl.close()
        except Exception as e:
            logger.warning(f"Decision logging failed (non-fatal): {e}")

        # Bridge: also store extracted insights in intelligence.db (learning_loop)
        # This is the "real" learning database that feeds regenerate_context_md()
        try:
            if markers.get('insights'):
                from core.learning_loop import add_insight
                for ins in markers['insights']:
                    if isinstance(ins, dict):
                        add_insight(
                            agent=agent_name,
                            domain=ins.get('category', 'general'),
                            insight=ins.get('content', str(ins)),
                            evidence=ins.get('evidence', ''),
                            source=f"{trigger}_{task or 'chat'}",
                        )
                    elif isinstance(ins, str):
                        add_insight(agent=agent_name, domain='general',
                                    insight=ins, source=f"{trigger}_{task or 'chat'}")
        except Exception as e:
            logger.debug(f"Learning loop insight bridge failed (non-fatal): {e}")

        # Clean markers from response
        return InsightExtractor.clean_response(response)
    except Exception as e:
        logger.warning(f"Learning loop error (non-fatal): {e}")
        return _clean_markers(response)


def _clean_markers(response: str) -> str:
    """Fallback marker cleaning without importing learning_db."""
    import re
    response = re.sub(r'\[INSIGHT:[^\]]+\]', '', response)
    response = re.sub(r'\[DECISION:[^\]]+\]', '', response)
    response = re.sub(r'\[METRIC:[^\]]+\]', '', response)
    response = re.sub(r'\[STATE UPDATE:[^\]]+\]', '', response)
    response = re.sub(r'\[EVENT:[^\]]+\]', '', response)
    response = re.sub(r'\[TASK:[^\]]+\]', '', response)
    response = re.sub(r'\[VERIFY:[^\]]+\]', '', response)
    return response.strip()


# --- Event Bus Integration ---

def process_events_from_response(agent_name: str, response: str):
    """
    Extract [EVENT: type|severity|{json}] markers from agent responses
    and publish them to the cross-agent event bus.
    """
    import re
    try:
        from core.event_bus import EventBus
        bus = EventBus()

        # Match [EVENT: type|severity|{payload}] or [EVENT: type|severity|description]
        pattern = r'\[EVENT:\s*([^|]+)\|([^|]+)\|([^\]]+)\]'
        matches = re.findall(pattern, response)

        for event_type, severity, payload_str in matches:
            event_type = event_type.strip()
            severity = severity.strip().upper()
            payload_str = payload_str.strip()

            # Try parsing as JSON, fall back to description string
            try:
                payload = json.loads(payload_str)
            except (json.JSONDecodeError, ValueError):
                payload = {"description": payload_str}

            bus.publish(
                event_type=event_type,
                source_agent=agent_name,
                severity=severity,
                payload=payload
            )
            logger.info(f"Event published: {event_type} from {agent_name} ({severity})")

        bus.close()
    except Exception as e:
        logger.warning(f"Event bus processing failed (non-fatal): {e}")


def get_pending_events_for_agent(agent_name: str) -> str:
    """Get unprocessed events for an agent, formatted for injection into prompts."""
    try:
        from core.event_bus import EventBus
        bus = EventBus()
        events = bus.get_pending_events(agent_name)

        if not events:
            bus.close()
            return ""

        lines = ["=== CROSS-AGENT EVENTS (from other agents) ==="]
        for evt in events:
            lines.append(
                f"- [{evt['severity']}] {evt['event_type']} from {evt['source_agent']}: "
                f"{json.dumps(evt['payload']) if isinstance(evt['payload'], dict) else evt['payload']}"
            )
            # Mark as processed so this agent doesn't see it again
            bus.mark_processed(evt['id'], agent_name)

        bus.close()
        lines.append("React to these events if relevant to your domain. Acknowledge what you've processed.")
        return "\n".join(lines)
    except Exception as e:
        logger.warning(f"Event bus read failed (non-fatal): {e}")
        return ""


# --- Asana Auto-Task Creation ---

def create_asana_tasks_from_response(agent_name: str, response: str):
    """
    Extract [TASK: title|priority|description] markers from agent responses
    and auto-create tasks in Asana.
    """
    import re
    try:
        from core.asana_writer import AsanaWriter
        writer = AsanaWriter()
        if not writer.available:
            return

        pattern = r'\[TASK:\s*([^|]+)\|([^|]+)\|([^\]]+)\]'
        matches = re.findall(pattern, response)

        for title, priority, description in matches:
            title = title.strip()
            priority = priority.strip().lower()
            description = description.strip()

            # Map priority to Asana due date offset
            due_days = {"urgent": 1, "high": 3, "medium": 7, "low": 14}.get(priority, 7)

            due_date = (datetime.now(NZ_TZ) + timedelta(days=due_days)).strftime("%Y-%m-%d")

            writer.create_task(
                name=f"[{agent_name}] {title}",
                notes=f"Auto-created by {agent_name}\n\n{description}",
                due_on=due_date
            )
            logger.info(f"Asana task created: {title} (from {agent_name}, due {due_date})")

    except Exception as e:
        logger.warning(f"Asana auto-task creation failed (non-fatal): {e}")


# --- Voice Transcription (OpenAI Whisper) ---

def transcribe_voice(file_id: str, bot_token: str) -> str:
    """
    Download a Telegram voice message and transcribe it with OpenAI Whisper.
    Returns the transcribed text, or an error message.
    """
    import requests
    import tempfile

    openai_key = os.environ.get("OPENAI_API_KEY")
    if not openai_key:
        return "[Voice message received but OPENAI_API_KEY not set -- cannot transcribe]"

    try:
        # Step 1: Get file path from Telegram
        file_info = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getFile",
            params={"file_id": file_id},
            timeout=10
        ).json()

        if not file_info.get("ok"):
            return "[Could not retrieve voice file from Telegram]"

        file_path = file_info["result"]["file_path"]

        # Step 2: Download the voice file
        file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        audio_data = requests.get(file_url, timeout=30).content

        # Step 3: Save to temp file (Whisper needs a file with extension)
        suffix = ".ogg" if file_path.endswith(".oga") or file_path.endswith(".ogg") else ".mp3"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_data)
            tmp_path = tmp.name

        # Step 4: Transcribe with OpenAI Whisper API
        with open(tmp_path, "rb") as audio_file:
            response = requests.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {openai_key}"},
                files={"file": (f"voice{suffix}", audio_file)},
                data={"model": "whisper-1"},
                timeout=60
            )

        # Clean up temp file
        os.unlink(tmp_path)

        if response.status_code == 200:
            transcript = response.json().get("text", "")
            logger.info(f"Transcribed voice message: {len(transcript)} chars")
            return transcript
        else:
            logger.error(f"Whisper API error: {response.status_code} {response.text}")
            return f"[Transcription failed: {response.status_code}]"

    except Exception as e:
        logger.error(f"Voice transcription error: {e}")
        return f"[Voice transcription error: {str(e)}]"


def download_telegram_photo(photo_sizes: list, bot_token: str) -> tuple:
    """
    Download a photo from Telegram. Takes the photo array (multiple sizes),
    picks the largest, downloads it, returns (base64_data, media_type).
    """
    import requests
    import base64

    # Telegram sends multiple sizes -- last one is highest resolution
    best = photo_sizes[-1]
    file_id = best.get("file_id")

    try:
        # Get file path
        file_info = requests.get(
            f"https://api.telegram.org/bot{bot_token}/getFile",
            params={"file_id": file_id},
            timeout=10
        ).json()

        if not file_info.get("ok"):
            return None, None

        file_path = file_info["result"]["file_path"]

        # Download
        file_url = f"https://api.telegram.org/file/bot{bot_token}/{file_path}"
        image_data = requests.get(file_url, timeout=30).content

        # Determine media type from file extension
        ext = file_path.rsplit(".", 1)[-1].lower() if "." in file_path else "jpg"
        media_types = {
            "jpg": "image/jpeg", "jpeg": "image/jpeg",
            "png": "image/png", "gif": "image/gif",
            "webp": "image/webp"
        }
        media_type = media_types.get(ext, "image/jpeg")

        b64 = base64.standard_b64encode(image_data).decode("utf-8")
        logger.info(f"Downloaded photo: {len(image_data)} bytes, {media_type}")
        return b64, media_type

    except Exception as e:
        logger.error(f"Photo download error: {e}")
        return None, None


def call_claude_vision(system_prompt: str, image_b64: str, media_type: str,
                       caption: str = None, task_type: str = "chat") -> str:
    """
    Call Claude API with an image (vision). Used for photos sent via Telegram.
    """
    import anthropic

    client = anthropic.Anthropic()

    # All agents use Sonnet to control costs
    model = "claude-sonnet-4-6"

    # Build content blocks: image first, then caption text if present
    content = [
        {
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": media_type,
                "data": image_b64
            }
        }
    ]
    if caption:
        content.append({"type": "text", "text": caption})
    else:
        content.append({"type": "text", "text": "What's in this image? Analyse it in the context of your role."})

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": content}]
        )
        # Track API usage (was missing — vision calls weren't counted)
        try:
            _track_api_usage("vision", model,
                             response.usage.input_tokens if hasattr(response, 'usage') else 0,
                             response.usage.output_tokens if hasattr(response, 'usage') else 0)
        except Exception:
            pass
        return response.content[0].text
    except Exception as e:
        logger.error(f"Claude Vision API error: {e}")
        return f"API Error: {str(e)}"


# --- System Health Gatherer (for Sentinel) ---

def _gather_system_health(telegram_config: dict) -> str:
    """
    Gather real system health data for Sentinel to analyse.
    Checks: agent state file freshness, database sizes, log errors, schedule completions.
    """
    import sqlite3
    lines = []
    now = datetime.now(NZ_TZ)

    # 1. Agent state file freshness
    lines.append("AGENT STATE FILE FRESHNESS:")
    agents_dir = os.path.join(BASE_DIR, "agents")
    for agent_dir in sorted(os.listdir(agents_dir)):
        state_path = os.path.join(agents_dir, agent_dir, "state", "CONTEXT.md")
        if os.path.exists(state_path):
            mtime = datetime.fromtimestamp(os.path.getmtime(state_path))
            age_hours = (now - mtime).total_seconds() / 3600
            status = "HEALTHY" if age_hours < 24 else "STALE" if age_hours < 72 else "DEAD"
            lines.append(f"  {agent_dir}: updated {age_hours:.1f}h ago [{status}]")
        elif os.path.isdir(os.path.join(agents_dir, agent_dir)):
            lines.append(f"  {agent_dir}: NO state/CONTEXT.md [MISSING]")

    # 2. Database health
    lines.append("\nDATABASE STATUS:")
    data_dir = os.path.join(BASE_DIR, "data")
    if os.path.isdir(data_dir):
        for db_file in sorted(os.listdir(data_dir)):
            if db_file.endswith(".db"):
                db_path = os.path.join(data_dir, db_file)
                size_kb = os.path.getsize(db_path) / 1024
                mtime = datetime.fromtimestamp(os.path.getmtime(db_path))
                age_hours = (now - mtime).total_seconds() / 3600
                row_counts = {}
                try:
                    conn = sqlite3.connect(db_path)
                    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                    for (table,) in tables[:5]:
                        count = conn.execute(f"SELECT COUNT(*) FROM [{table}]").fetchone()[0]
                        row_counts[table] = count
                    conn.close()
                except Exception as e:
                    row_counts = {"error": str(e)}
                lines.append(f"  {db_file}: {size_kb:.0f}KB, updated {age_hours:.1f}h ago, tables: {row_counts}")

    # 3. Recent orchestrator log errors (last 100 lines)
    lines.append("\nRECENT LOG ERRORS (last 100 lines):")
    log_path = os.path.join(BASE_DIR, "orchestrator.log")
    error_count = 0
    if os.path.exists(log_path):
        try:
            with open(log_path, "r") as f:
                log_lines = f.readlines()[-100:]
            for line in log_lines:
                if "ERROR" in line or "CRASHED" in line or "FAILED" in line:
                    lines.append(f"  {line.strip()[:200]}")
                    error_count += 1
            if error_count == 0:
                lines.append("  No errors in last 100 log lines")
        except Exception:
            lines.append("  Could not read orchestrator.log")
    else:
        lines.append("  orchestrator.log not found")

    # 4. Schedule config summary
    lines.append(f"\nSCHEDULED TASKS:")
    schedules_path = os.path.join(BASE_DIR, "config", "schedules.json")
    try:
        with open(schedules_path, "r") as f:
            import json
            schedules = json.load(f)
        tasks = schedules.get("tasks", [])
        lines.append(f"  Total scheduled: {len(tasks)}")
        agents_scheduled = set(t.get("agent", "?") for t in tasks)
        lines.append(f"  Agents with schedules: {', '.join(sorted(agents_scheduled))}")
    except Exception as e:
        lines.append(f"  Could not read schedules: {e}")

    # 5. Telegram config check (any SETUP_NEEDED?)
    lines.append("\nTELEGRAM CONFIG:")
    tg_path = os.path.join(BASE_DIR, "config", "telegram.json")
    try:
        with open(tg_path, "r") as f:
            import json
            tg = json.load(f)
        chat_ids = tg.get("chat_ids", {})
        configured = [k for k, v in chat_ids.items() if v and str(v) != "SETUP_NEEDED"]
        unconfigured = [k for k, v in chat_ids.items() if not v or str(v) == "SETUP_NEEDED"]
        lines.append(f"  Configured: {len(configured)} agents ({', '.join(sorted(configured))})")
        if unconfigured:
            lines.append(f"  NOT CONFIGURED: {', '.join(unconfigured)}")
    except Exception as e:
        lines.append(f"  Could not read telegram config: {e}")

    # 6. Environment variable check
    lines.append("\nENVIRONMENT VARIABLES:")
    critical_vars = ["TELEGRAM_BOT_TOKEN", "CLAUDE_API_KEY", "SHOPIFY_ACCESS_TOKEN",
                     "KLAVIYO_API_KEY", "META_ACCESS_TOKEN", "ASANA_API_KEY"]
    for var in critical_vars:
        val = os.environ.get(var, "")
        status = "SET" if val else "MISSING"
        lines.append(f"  {var}: {status}")

    return "\n".join(lines)


# --- Telegram Handler ---

def _convert_tables_to_text(text: str) -> str:
    """Convert markdown tables to structured text readable on Telegram."""
    import re

    lines = text.split("\n")
    result = []
    table_rows = []
    headers = []

    def flush_table():
        """Convert accumulated table rows into readable text."""
        if not table_rows:
            return
        if headers:
            for row in table_rows:
                parts = []
                for i, cell in enumerate(row):
                    label = headers[i] if i < len(headers) else ""
                    if label and cell:
                        parts.append(f"{label}: {cell}")
                    elif cell:
                        parts.append(cell)
                if parts:
                    result.append("  ".join(parts))
        else:
            for row in table_rows:
                result.append("  ".join(row))
        table_rows.clear()
        headers.clear()

    for line in lines:
        stripped = line.strip()
        # Detect table separator rows (|---|---|)
        if re.match(r"^\|[\s\-:]+(\|[\s\-:]+)+\|?$", stripped):
            continue  # Skip separator rows
        # Detect table data rows (| cell | cell |)
        if stripped.startswith("|") and stripped.count("|") >= 2:
            cells = [c.strip() for c in stripped.strip("|").split("|")]
            cells = [c for c in cells if c]  # Remove empty
            if not headers and not table_rows:
                headers = cells
            else:
                table_rows.append(cells)
        else:
            flush_table()
            result.append(line)

    flush_table()
    return "\n".join(result)


def _sanitize_telegram_markdown(text: str) -> str:
    """
    Sanitize text for Telegram Markdown (v1) to prevent parse failures.

    Telegram Markdown v1 supports: *bold*, _italic_, `inline code`, [link](url)
    It does NOT support: **double bold**, # headers, ``` code blocks, ---, > blockquotes
    """
    import re

    # 1. Convert **double asterisk bold** → *single* (Claude default, Telegram fails on it)
    text = re.sub(r'\*\*(.+?)\*\*', r'*\1*', text, flags=re.DOTALL)

    # 2. Convert __double underscore italic__ → _single_
    text = re.sub(r'__(.+?)__', r'_\1_', text, flags=re.DOTALL)

    # 3. Replace ``` code blocks — extract content, wrap in single backtick if short, else strip markers
    def handle_code_block(m):
        content = m.group(1).strip()
        if len(content) < 200:
            return '`' + content.replace('`', "'") + '`'
        return content
    text = re.sub(r'```[\w]*\n?(.*?)```', handle_code_block, text, flags=re.DOTALL)
    # Strip any remaining ``` (unclosed blocks)
    text = re.sub(r'```[\w]*', '', text)

    # 4. Strip # headers — remove leading # chars, keep the text
    text = re.sub(r'^#{1,6}\s+', '', text, flags=re.MULTILINE)

    # 5. Strip horizontal rules
    text = re.sub(r'^\s*[-=_]{3,}\s*$', '', text, flags=re.MULTILINE)

    # 6. Strip > blockquote markers
    text = re.sub(r'^>\s*', '', text, flags=re.MULTILINE)

    # 7. Fix unmatched single asterisks (odd count means parse failure)
    asterisk_count = text.count('*')
    if asterisk_count % 2 != 0:
        idx = text.rfind('*')
        text = text[:idx] + text[idx+1:]

    # 8. Fix unmatched single underscores
    underscore_count = text.count('_')
    if underscore_count % 2 != 0:
        idx = text.rfind('_')
        text = text[:idx] + '\\_' + text[idx+1:]

    # 9. Fix unmatched square brackets (broken link syntax)
    if text.count('[') != text.count(']'):
        text = text.replace('[', '(').replace(']', ')')

    return text


def _split_telegram_message(text: str, limit: int = 4000) -> list:
    """Split long messages on paragraph boundaries to avoid cutting Markdown spans."""
    if len(text) <= limit:
        return [text]
    chunks = []
    while len(text) > limit:
        # Find last double-newline before limit
        split_at = text.rfind('\n\n', 0, limit)
        if split_at == -1:
            # No paragraph boundary — fall back to last newline
            split_at = text.rfind('\n', 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at].strip())
        text = text[split_at:].strip()
    if text:
        chunks.append(text)
    return chunks


def send_telegram(chat_id: str, text: str, bot_token: str):
    """Send a message to a Telegram chat."""
    import requests

    if not bot_token:
        logger.error(f"Cannot send to {chat_id}: no bot token")
        return False

    if not text or not text.strip():
        logger.warning(f"Empty message for {chat_id}, skipping")
        return False

    # Convert any markdown tables to structured text (Telegram can't render tables)
    text = _convert_tables_to_text(text)
    # Sanitize markdown to prevent parse failures
    text = _sanitize_telegram_markdown(text)

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def _post(chunk: str) -> bool:
        """Post a single chunk, retry once without Markdown on parse failure."""
        try:
            resp = requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown"
            }, timeout=60)
            data = resp.json()
            if data.get("ok"):
                return True
            # Markdown parse errors -- retry without parse_mode
            desc = str(data.get("description", "")).lower()
            if "can't parse" in desc or "bad request" in desc:
                logger.warning(f"Markdown parse failed for {chat_id}, retrying plain text")
                resp2 = requests.post(url, json={
                    "chat_id": chat_id,
                    "text": chunk,
                }, timeout=60)
                data2 = resp2.json()
                if data2.get("ok"):
                    return True
            logger.error(f"Telegram send failed for {chat_id}: {data.get('description', 'unknown')}")
            return False
        except requests.exceptions.Timeout:
            logger.error(f"Telegram timeout sending to {chat_id}")
            return False
        except Exception as e:
            logger.error(f"Telegram send exception for {chat_id}: {e}")
            return False

    # Split on paragraph boundaries to avoid cutting Markdown spans mid-span
    chunks = _split_telegram_message(text)
    success = all(_post(chunk) for chunk in chunks)

    if success:
        logger.info(f"Message sent to {chat_id} ({len(text)} chars)")
    return success


# Companion agents that also receive voice messages alongside text
# Maps agent_name -> OpenAI TTS voice ID
VOICE_AGENTS = {
    "aether": "onyx",  # Jackson prefers voice — struggles with screen reading
}


def send_telegram_voice(chat_id: str, text: str, bot_token: str, voice_id: str = "onyx"):
    """Send a voice message to a Telegram chat using OpenAI TTS."""
    import requests
    import tempfile
    import os

    if not text or len(text.strip()) < 10:
        return False

    # Strip markdown formatting for cleaner speech
    clean = re.sub(r'\*\*(.+?)\*\*', r'\1', text)
    clean = re.sub(r'\*(.+?)\*', r'\1', clean)
    clean = re.sub(r'`(.+?)`', r'\1', clean)
    clean = re.sub(r'#{1,6}\s*', '', clean)
    clean = re.sub(r'\[(.+?)\]\(.+?\)', r'\1', clean)
    # Truncate to avoid huge audio files (TTS limit ~4096 chars)
    clean = clean[:4000]

    try:
        import openai
        client = openai.OpenAI()
        speech = client.audio.speech.create(
            model="tts-1",
            voice=voice_id,
            input=clean,
        )

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
            f.write(speech.content)
            audio_path = f.name

        url = f"https://api.telegram.org/bot{bot_token}/sendVoice"
        with open(audio_path, "rb") as f:
            resp = requests.post(url, files={"voice": f}, data={"chat_id": chat_id}, timeout=120)

        os.unlink(audio_path)

        data = resp.json()
        if data.get("ok"):
            logger.info(f"Voice message sent to {chat_id} ({len(clean)} chars)")
            return True
        else:
            logger.error(f"Telegram voice send failed: {data.get('description', 'unknown')}")
            return False

    except Exception as e:
        logger.warning(f"Voice message failed for {chat_id} (non-fatal): {e}")
        return False


def identify_agent_from_chat(chat_id: str, telegram_config: dict) -> str:
    """Given a Telegram chat ID, identify which agent handles it."""
    # Some chat IDs map to sub-channels (e.g. walker-capital-tom) that share
    # a single agent folder. Resolve to the canonical agent name.
    CHAT_ALIAS_MAP = {
        "walker-capital-tom": "walker-capital",
        "walker-capital-trent": "walker-capital",
    }
    chat_ids = telegram_config.get("chat_ids", {})
    for agent_name, cid in chat_ids.items():
        if str(cid) == str(chat_id):
            return CHAT_ALIAS_MAP.get(agent_name, agent_name)
    return None


# --- Scheduled Task Runner ---

def run_scheduled_task(agent_name: str, task_name: str, telegram_config: dict):
    """
    Execute a scheduled task for an agent.
    1. Load agent brain
    2. Build task prompt
    3. Call Claude
    4. Run through learning loop
    5. Post to Telegram
    6. Update state
    """
    logger.info(f"Running scheduled task: {agent_name}/{task_name}")
    try:
        _run_scheduled_task_inner(agent_name, task_name, telegram_config)
    except Exception as e:
        logger.error(f"TASK CRASHED: {agent_name}/{task_name}: {e}", exc_info=True)
        # Notify Tom so failures are never silent
        try:
            chat_id = telegram_config.get("chat_ids", {}).get("command-center") or \
                      telegram_config.get("chat_ids", {}).get(agent_name)
            bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
            if chat_id and bot_token:
                from core.notification_router import route_notification
                agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
                route_notification(chat_id,
                    f"TASK FAILED: {agent_display}/{task_name}\n\nError: {str(e)[:300]}\n\nWill retry next schedule.",
                    bot_token, severity="IMPORTANT", agent="command-center")
        except Exception:
            logger.error(f"Could not send failure notification for {agent_name}/{task_name}")


def _run_scheduled_task_inner(agent_name: str, task_name: str, telegram_config: dict):
    """Inner task runner — exceptions bubble up to run_scheduled_task wrapper."""

    # --- Flush DND-held messages (6am daily) ---
    if task_name == "flush_dnd_queue":
        try:
            from core.notification_router import get_router
            bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
            router = get_router(bot_token=bot_token)
            result = router.flush_held()
            logger.info(f"DND flush: delivered {result.get('delivered', 0)} held messages")
        except Exception as e:
            logger.error(f"DND flush failed: {e}")
        return

    # --- Generate daily summaries + compact old messages (3:30am daily) ---
    if task_name == "cleanup_conversation_history":
        try:
            from core.user_memory import generate_all_daily_summaries, compact_old_messages
            generate_all_daily_summaries(telegram_config)
            compact_old_messages(days=30)
            logger.info("Daily memory maintenance complete")
        except Exception as e:
            logger.error(f"Memory maintenance failed: {e}")
        return

    # --- Silent intelligence sync (no Claude call, just DB update) ---
    if task_name == "intelligence_sync":
        try:
            from core.order_intelligence import fetch_order_intelligence, get_customer_db_summary
            # Fetch today's orders and persist to customer intelligence DB
            order_data = fetch_order_intelligence(days=1)
            db_summary = get_customer_db_summary()

            # Count what was synced
            order_count = order_data.count("--- #")
            if "No orders" in order_data:
                order_count = 0

            # Tag new customers with acquisition channel in Shopify
            tagged_count = 0
            try:
                from core.order_intelligence import get_db as get_cust_db
                from core.shopify_writer import ShopifyWriter
                cust_db = get_cust_db()
                writer = ShopifyWriter()
                if writer.available:
                    _nz_now = datetime.now(NZ_TZ).date()
                    today_str = _nz_now.isoformat()
                    month_str = _nz_now.strftime("%Y-%m")

                    # Find today's new customers (first-time buyers with known channel)
                    new_customers = cust_db.execute("""
                        SELECT c.shopify_id, o.channel
                        FROM customers c
                        JOIN orders o ON o.shopify_customer_id = c.shopify_id
                        WHERE c.total_orders = 1
                          AND DATE(o.created_at) = ?
                          AND o.channel != 'unknown'
                          AND o.channel IS NOT NULL
                    """, (today_str,)).fetchall()

                    for row in new_customers:
                        try:
                            channel = row[1]  # sqlite3 without row_factory
                            customer_id = row[0]
                            tags = [
                                f"acquired:{channel}",
                                f"acquired-date:{month_str}",
                                f"cohort:{month_str}-{channel}"
                            ]
                            writer.add_customer_tags(str(customer_id), tags)
                            tagged_count += 1
                        except Exception as tag_err:
                            logger.warning(f"Failed to tag customer {row[0]}: {tag_err}")
                cust_db.close()
            except Exception as tag_e:
                logger.warning(f"Customer tagging failed (non-fatal): {tag_e}")

            # Post brief status to channel
            chat_id = telegram_config.get("chat_ids", {}).get(agent_name, "")
            if chat_id:
                from core.order_intelligence import get_db
                try:
                    db = get_db()
                    total_customers = db.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
                    total_orders = db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
                    db.close()
                except Exception:
                    total_customers = "?"
                    total_orders = "?"

                tag_note = f"\nCustomers tagged: {tagged_count}" if tagged_count > 0 else ""
                status_msg = (
                    f"🔄 *Intelligence Sync Complete*\n"
                    f"Orders today: {order_count}\n"
                    f"DB totals: {total_customers} customers, {total_orders} orders tracked"
                    f"{tag_note}\n"
                    f"_Learning accumulates — next briefing will use updated intelligence._"
                )
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, status_msg, bot_token, severity="INFO", agent=agent_name)

            logger.info(f"Intelligence sync complete: {order_count} orders persisted")
        except Exception as e:
            logger.error(f"Intelligence sync failed: {e}")
        return  # No Claude call needed

    # --- Daily replenishment scan (fires Klaviyo events for customers due to reorder) ---
    if task_name == "replenishment_scan":
        try:
            from core.replenishment_tracker import run_replenishment_scan
            result = run_replenishment_scan()

            chat_id = telegram_config.get("chat_ids", {}).get(agent_name, "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, result, bot_token, severity="INFO", agent=agent_name)

            logger.info(f"Replenishment scan complete")
        except Exception as e:
            logger.error(f"Replenishment scan failed: {e}")
        return  # No Claude call needed

    # --- Thought leader scan (scrapes RSS feeds from AI leaders) ---
    if task_name == "thought_leader_scan":
        try:
            from core.thought_leader_scraper import run_thought_leader_scan
            result = run_thought_leader_scan()
            logger.info(f"Thought leader scan complete: {result[:100]}")
        except Exception as e:
            logger.error(f"Thought leader scan failed: {e}")
        return  # No Claude call needed

    # --- Thought leader insight extraction (processes new content through Claude) ---
    if task_name == "thought_leader_extract":
        try:
            from core.thought_leader_scraper import run_insight_extraction
            result = run_insight_extraction()

            # Notify Nexus channel with summary
            chat_id = telegram_config.get("chat_ids", {}).get(agent_name, "")
            if chat_id and result:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, f"Thought Leader Intelligence\n\n{result}", bot_token,
                                   severity="INFO", agent=agent_name)

            logger.info(f"Thought leader extraction complete")
        except Exception as e:
            logger.error(f"Thought leader extraction failed: {e}")
        return  # No Claude call needed

    # --- ROAS verification check (runs after intelligence_sync) ---
    if task_name == "roas_check":
        try:
            from core.roas_tracker import run_nightly_roas_check
            result = run_nightly_roas_check()

            chat_id = telegram_config.get("chat_ids", {}).get(agent_name, "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, result, bot_token, agent=agent_name)

            logger.info("ROAS check complete")
        except Exception as e:
            logger.error(f"ROAS check failed: {e}")
        return

    # --- Rule-based Asana task creation (runs after ROAS check) ---
    if task_name == "rule_check":
        try:
            from core.rule_engine import run_rule_checks
            result = run_rule_checks()

            chat_id = telegram_config.get("chat_ids", {}).get(agent_name, "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, result, bot_token, agent=agent_name)

            logger.info("Rule check complete")
        except Exception as e:
            logger.error(f"Rule check failed: {e}")
        return

    # --- Tony weekly report (Monday 7am, file-based) ---
    if task_name == "tony_report":
        try:
            from core.tony_report import generate_and_save
            result = generate_and_save()

            # Notify on command-center channel (not the report itself, just a heads-up)
            chat_id = telegram_config.get("chat_ids", {}).get("command-center", "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, result, bot_token,
                                   severity="IMPORTANT", agent="strategic-advisor")

            logger.info("Tony report generated and saved")
        except Exception as e:
            logger.error(f"Tony report generation failed: {e}")
        return

    # --- Vault indexer sync (nightly 2am) ---
    if task_name == "vault_sync":
        try:
            from core.vault_indexer import VaultIndexer
            indexer = VaultIndexer()
            result = indexer.sync()

            chat_id = telegram_config.get("chat_ids", {}).get(agent_name, "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, f"Vault sync: {result}", bot_token,
                                   severity="INFO", agent=agent_name)

            logger.info(f"Vault sync complete: {result}")
        except Exception as e:
            logger.error(f"Vault sync failed: {e}")
        return

    # --- Daily snapshot (11:59pm NZST -- locks calendar day figures) ---
    if task_name == "daily_snapshot":
        try:
            from core.daily_snapshot import run_daily_snapshot
            snapshot = run_daily_snapshot()

            chat_id = telegram_config.get("chat_ids", {}).get("command-center", "")
            if chat_id and snapshot:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                msg = f"""✓ DAILY SNAPSHOT LOCKED -- {snapshot['date']}
Revenue: ${snapshot['revenue']:.2f}
Orders: {snapshot['order_count']}
Customers: {snapshot['new_customers']} new, {snapshot['returning_customers']} returning
"""
                route_notification(chat_id, msg, bot_token, severity="INFO", agent="Nexus")

            logger.info(f"Daily snapshot complete: {snapshot['date']} ${snapshot['revenue']:.2f}")
        except Exception as e:
            logger.error(f"Daily snapshot failed: {e}")
        return

    # --- Monthly CPA:LTV cohort analysis (1st of month) ---
    if task_name == "ltv_analysis":
        try:
            from core.roas_tracker import run_monthly_ltv_analysis
            result = run_monthly_ltv_analysis()

            chat_id = telegram_config.get("chat_ids", {}).get("command-center", "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, result, bot_token,
                                   severity="IMPORTANT", agent="strategic-advisor")

            logger.info("LTV analysis complete")
        except Exception as e:
            logger.error(f"LTV analysis failed: {e}")
        return

    # --- Auto-optimizer (budget adjustments, A/B winners, campaign drafts, 11:45pm) ---
    if task_name == "auto_optimize":
        try:
            from core.auto_optimizer import run_auto_optimization
            result = run_auto_optimization()

            chat_id = telegram_config.get("chat_ids", {}).get(agent_name, "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, result, bot_token, agent=agent_name)

            logger.info("Auto-optimizer complete")
        except Exception as e:
            logger.error(f"Auto-optimizer failed: {e}")
        return

    # --- AI citation monitoring (weekly, checks Perplexity for DBH mentions) ---
    if task_name == "citation_check":
        try:
            from core.citation_monitor import run_citation_check
            result = run_citation_check()

            chat_id = telegram_config.get("chat_ids", {}).get("command-center", "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, result, bot_token,
                                   severity="NOTABLE", agent="beacon")

            logger.info("Citation check complete")
        except Exception as e:
            logger.error(f"Citation check failed: {e}")
        return

    # --- GSC feedback for Beacon (weekly, injects ranking data into Beacon context) ---
    if task_name == "gsc_feedback":
        try:
            from core.gsc_client import GSCClient
            gsc = GSCClient()
            if gsc.available:
                feedback = gsc.get_beacon_feedback()
                briefing = gsc.format_for_briefing()

                # Update Beacon's CONTEXT.md with latest GSC data
                beacon_context = AGENTS_DIR / "beacon" / "state" / "CONTEXT.md"
                if beacon_context.exists():
                    content = beacon_context.read_text(encoding='utf-8')
                    # Append or replace GSC section
                    gsc_marker = "## GSC Performance"
                    if gsc_marker in content:
                        content = content[:content.index(gsc_marker)]
                    content += f"\n{gsc_marker}\n*Updated: {datetime.now(NZ_TZ).strftime('%Y-%m-%d %H:%M')}*\n\n{briefing}\n"
                    beacon_context.write_text(content, encoding='utf-8')

                chat_id = telegram_config.get("chat_ids", {}).get("command-center", "")
                if chat_id:
                    bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                    from core.notification_router import route_notification
                    route_notification(chat_id, f"GSC Feedback Updated\n\n{briefing}", bot_token,
                                       severity="INFO", agent="beacon")

                logger.info("GSC feedback injected into Beacon context")
            else:
                logger.warning("GSC client not available -- credentials missing")
        except Exception as e:
            logger.error(f"GSC feedback failed: {e}")
        return

    # --- Pure Pets ranking tracker (daily 6am, after GSC data refresh) ---
    if task_name == "pure_pets_ranking_check":
        try:
            from core.pure_pets_ranking_tracker import track_rankings, get_alert_severity
            result = track_rankings()

            # Determine alert severity from the report
            from core.pure_pets_ranking_tracker import get_alerts_since
            recent_alerts = get_alerts_since(1)
            severity = get_alert_severity(recent_alerts)

            # Send to Meridian (marketing) channel
            chat_id = telegram_config.get("chat_ids", {}).get("dbh-marketing", "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, result, bot_token, severity=severity, agent="beacon")

            # If severe drops, also alert command-center
            if severity in ("CRITICAL", "IMPORTANT"):
                cc_chat_id = telegram_config.get("chat_ids", {}).get("command-center", "")
                if cc_chat_id and cc_chat_id != chat_id:
                    alert_msg = (
                        f"PURE PETS RANKING ALERT ({severity})\n\n"
                        + "\n".join(
                            f"  - {a['keyword']}: dropped to #{a['position']:.0f} "
                            f"(change: {a['change_from_previous']:.0f})"
                            for a in recent_alerts
                        )
                    )
                    route_notification(cc_chat_id, alert_msg, bot_token,
                                       severity=severity, agent="beacon")

            logger.info(f"Pure Pets ranking check complete (severity: {severity})")
        except Exception as e:
            logger.error(f"Pure Pets ranking check failed: {e}")
        return

    # --- DBH keyword daily ranking check (6:30am daily, all 37 keywords x 3 markets) ---
    if task_name == "dbh_keyword_daily_check":
        try:
            from core.dbh_keyword_tracker import track_rankings, format_for_briefing
            result = track_rankings()
            alerts = result.get("alerts", [])

            # Build report message
            report = f"DBH Keyword Rankings — Daily Check\n\n"
            report += f"Checked {result.get('tracked', 0)} keywords across NZ/AUS/USA\n"
            report += f"With GSC data: {result.get('with_data', 0)}\n"
            report += f"Not ranking: {result.get('not_ranking', 0)}\n\n"
            report += format_for_briefing("NZ")

            severity = "INFO"
            if alerts:
                critical = [a for a in alerts if a.get("severity") == "CRITICAL"]
                severity = "CRITICAL" if critical else "IMPORTANT"
                report += f"\n\nRANKING ALERTS ({len(alerts)}):\n"
                for a in alerts:
                    report += f"  {a['keyword']} ({a['market']}): #{a['old_position']} → #{a['new_position']} ({a['change']:+.0f})\n"

            chat_id = telegram_config.get("chat_ids", {}).get("beacon",
                      telegram_config.get("chat_ids", {}).get("dbh-marketing", ""))
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, report, bot_token, severity=severity, agent="beacon")

            logger.info(f"DBH keyword check complete: {result.get('with_data', 0)} with data, {len(alerts)} alerts")
        except Exception as e:
            logger.error(f"DBH keyword daily check failed: {e}")
        return

    # --- AI visibility weekly check (Sunday 3am, all platforms) ---
    if task_name == "ai_visibility_weekly_check":
        try:
            from core.ai_visibility_tracker import run_ai_visibility_check, get_weekly_report
            result = run_ai_visibility_check()
            report = get_weekly_report()

            chat_id = telegram_config.get("chat_ids", {}).get("beacon",
                      telegram_config.get("chat_ids", {}).get("command-center", ""))
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, report, bot_token, severity="INFO", agent="beacon")

            logger.info(f"AI visibility check complete: {result}")
        except Exception as e:
            logger.error(f"AI visibility weekly check failed: {e}")
        return

    # --- llms.txt regeneration (monthly, regenerates llms.txt for AEO) ---
    if task_name == "llms_txt_update":
        try:
            from core.llms_txt_generator import save_llms_txt
            result = save_llms_txt()

            chat_id = telegram_config.get("chat_ids", {}).get("command-center", "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, f"llms.txt updated\n\n{result}", bot_token,
                                   severity="INFO", agent="beacon")

            logger.info("llms.txt regenerated")
        except Exception as e:
            logger.error(f"llms.txt generation failed: {e}")
        return

    # --- NEXUS health_digest — daily 8:50am summary of what ran/failed yesterday ---
    if task_name == "health_digest" and agent_name == "command-center":
        try:
            db_path = BASE_DIR / "data" / "intelligence.db"
            conn = sqlite3.connect(str(db_path), check_same_thread=False)
            conn.row_factory = sqlite3.Row

            # Tasks that ran in the last 24 hours
            rows = conn.execute("""
                SELECT agent, task, status, elapsed_secs, output_chars, error_msg, ran_at
                FROM task_execution_log
                WHERE ran_at >= datetime('now', '-24 hours')
                ORDER BY ran_at ASC
            """).fetchall()

            total = len(rows)
            successes = [r for r in rows if r["status"] == "success"]
            errors = [r for r in rows if r["status"] != "success"]

            # Build message — no markdown tables (Telegram rules)
            lines = [f"NEXUS — Daily System Report {datetime.now(NZ_TZ).strftime('%a %d %b, %H:%M NZST')}"]
            lines.append(f"\n✅ {len(successes)}/{total} tasks completed successfully")
            if errors:
                lines.append(f"⚠️ {len(errors)} task(s) failed:\n")
                for r in errors:
                    lines.append(f"  ✗ {AGENT_DISPLAY.get(r['agent'], r['agent'])} / {r['task']}")
                    if r["error_msg"]:
                        lines.append(f"    Error: {r['error_msg'][:120]}")
            else:
                lines.append("  No failures. All systems go.")

            lines.append("\n─ What ran ─")
            for r in successes:
                t = r["ran_at"][11:16]  # HH:MM
                name = AGENT_DISPLAY.get(r["agent"], r["agent"])
                lines.append(f"  {t} — {name} / {r['task']} ({r['elapsed_secs']}s)")

            # Check if key automations ran
            ran_tasks = {(r["agent"], r["task"]) for r in rows}
            expected = [
                ("dbh-marketing", "morning_brief", "Meridian morning brief"),
                ("beacon", "write_article", "Beacon SEO article"),
                ("dbh-marketing", "intelligence_sync", "Customer DB sync"),
                ("dbh-marketing", "replenishment_scan", "Replenishment scan"),
                ("command-center", "roas_check", "ROAS check"),
            ]
            missing = [label for (ag, tk, label) in expected if (ag, tk) not in ran_tasks]
            if missing:
                lines.append("\n⚠️ Expected but did NOT run:")
                for m in missing:
                    lines.append(f"  ✗ {m}")

            conn.close()
            msg = "\n".join(lines)

            chat_id = telegram_config.get("chat_ids", {}).get("command-center", "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, msg, bot_token, severity="IMPORTANT", agent="command-center")
            logger.info(f"Health digest sent: {total} tasks, {len(errors)} errors")
        except Exception as e:
            logger.error(f"Health digest failed: {e}")
        return

    # --- SENTINEL health_check (gathers real system data — Python, then Claude analyses) ---
    if task_name == "health_check" and agent_name == "sentinel":
        try:
            health_data = _gather_system_health(telegram_config)
            brain = load_agent_brain(agent_name)
            prompt = (
                "You are Sentinel. Analyse the REAL SYSTEM DATA below and produce your daily health report "
                "following the exact format in your AGENT.md.\n\n"
                "=== LIVE SYSTEM HEALTH DATA ===\n" + health_data
            )
            response = call_claude(prompt, brain, agent_name)

            if response and not response.startswith("API Error:"):
                chat_id = telegram_config.get("chat_ids", {}).get(agent_name) or \
                          telegram_config.get("chat_ids", {}).get("command-center", "")
                if chat_id:
                    bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                    from core.notification_router import route_notification
                    severity = "CRITICAL" if "CRITICAL" in response else "IMPORTANT" if "DEGRADED" in response else "NOTABLE"
                    route_notification(chat_id, response, bot_token, severity=severity, agent=agent_name)
                _extract_state_updates(response)
            logger.info("Sentinel health_check complete")
        except Exception as e:
            logger.error(f"Sentinel health_check failed: {e}")
        return

    # --- WALKER CAPITAL pipeline tasks ---
    if agent_name == "walker-capital":
        try:
            from core.walker_pipeline_db import get_pipeline_summary, get_companies_at_stage, add_company, advance_stage, update_catalyst
            from core.walker_screener import run_discovery_scan, run_quantitative_screen, generate_research_brief
            from core.walker_memo_generator import generate_daily_pipeline_brief

            bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
            chat_id_tom = telegram_config.get("chat_ids", {}).get("walker-capital-tom", "")
            chat_id_trent = telegram_config.get("chat_ids", {}).get("walker-capital-trent", "")

            def send_to_both(message):
                """Send message to both Tom and Trent's Walker Capital channels."""
                for cid in [chat_id_tom, chat_id_trent]:
                    if cid and cid != "SETUP_NEEDED":
                        try:
                            from core.notification_router import route_notification
                            route_notification(cid, message, bot_token, severity="IMPORTANT", agent="walker-capital")
                        except Exception as send_err:
                            logger.error(f"Walker Capital Telegram send error: {send_err}")

            if task_name == "discovery_scan":
                # Stage 1: Find new candidates
                new_discoveries = []
                candidates = run_discovery_scan()
                for c in candidates:
                    if not c.get('ticker') or not c.get('name'):
                        continue
                    company_id = add_company(
                        ticker=c['ticker'], name=c['name'],
                        exchange=c.get('exchange', ''), sector=c.get('sector', ''),
                        discovery_thesis=c.get('discovery_thesis', '')
                    )
                    if company_id:
                        new_discoveries.append(c)
                        # Auto-run screen for new discoveries
                        try:
                            screen = run_quantitative_screen(c['ticker'], c.get('exchange', ''), c['name'])
                            if screen.get('screen_passed'):
                                advance_stage(company_id, 'SCREENED', notes=screen.get('screen_reason'))
                                update_catalyst(company_id, screen.get('catalyst_score', 0), screen.get('catalyst_description', ''))
                            elif screen.get('watchlist'):
                                advance_stage(company_id, 'WATCHING', notes=screen.get('screen_reason'))
                            else:
                                advance_stage(company_id, 'REJECTED', notes=screen.get('screen_reason'))
                        except Exception as screen_err:
                            logger.warning(f"Auto-screen failed for {c['ticker']}: {screen_err}")

                # Stage 3: Research brief for newly screened companies
                screened = get_companies_at_stage('SCREENED')
                for company in screened[:2]:  # Max 2 research briefs per day (cost control)
                    try:
                        brief = generate_research_brief(
                            ticker=company['ticker'], exchange=company['exchange'],
                            name=company['name'], sector=company.get('sector', ''),
                            catalyst_description=company.get('catalyst_description', ''),
                            comparable_companies=[]
                        )
                        if brief.get('brief_text'):
                            from core.walker_pipeline_db import save_research_brief
                            save_research_brief(company['id'], brief)
                            advance_stage(company['id'], 'RESEARCHED')
                    except Exception as brief_err:
                        logger.warning(f"Research brief failed for {company['ticker']}: {brief_err}")

                # Send daily pipeline brief to both channels
                pipeline_summary = get_pipeline_summary()
                brief_text = generate_daily_pipeline_brief(pipeline_summary, new_discoveries)
                send_to_both(brief_text)
                logger.info(f"Walker Capital discovery scan complete: {len(new_discoveries)} new companies")

            elif task_name == "weekly_valuation_report":
                # Friday: Full valuation memos on Stage 4+ companies
                from core.walker_pipeline_db import get_companies_at_stage, get_company_full_profile
                from core.walker_memo_generator import generate_investment_memo

                decision_ready = get_companies_at_stage('DECISION_READY')
                valued = get_companies_at_stage('VALUED')
                memo_companies = decision_ready + valued

                if not memo_companies:
                    send_to_both("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n🏦 WALKER CAPITAL — WEEKLY REPORT\nNo companies ready for valuation memos this week.\nPipeline building — check back next Friday.\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                else:
                    for company in memo_companies[:3]:  # Max 3 memos per week
                        try:
                            profile = get_company_full_profile(company['id'])
                            memo = generate_investment_memo(profile)
                            send_to_both(memo)
                        except Exception as memo_err:
                            logger.error(f"Memo generation failed for {company['ticker']}: {memo_err}")

        except Exception as walker_err:
            logger.error(f"Walker Capital task {task_name} failed: {walker_err}", exc_info=True)
        return

    # --- General task handler (loads brain, calls Claude, sends to Telegram) ---
    _run_scheduled_task_general(agent_name, task_name, telegram_config)

    # --- WALKER CAPITAL command handler (for interactive Telegram messages) ---
    # Note: scheduled tasks (discovery_scan, weekly_valuation_report) are handled
    # above. This block handles live message commands like "Value BHP".
    # (Inserted here so it's available from handle_incoming_message below)


def _handle_walker_command(message_text: str, chat_id: str, telegram_config: dict) -> bool:
    """
    Handle Walker Capital command messages from Telegram.
    Returns True if command was handled (caller should return early).
    Returns False if conversational — let normal chat flow handle it.

    Commands:
      /pipeline | status      → show pipeline summary
      value BHP               → run full Stage 4+5+7 analysis
      /screen BHP ASX         → manually add + screen a company
      buy BHP | watch BHP | avoid BHP  → log Trent's decision
    """
    msg = message_text.strip()
    msg_lower = msg.lower()

    bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    chat_id_tom = telegram_config.get("chat_ids", {}).get("walker-capital-tom", "")
    chat_id_trent = telegram_config.get("chat_ids", {}).get("walker-capital-trent", "")

    def send_both(text: str, severity: str = "IMPORTANT"):
        from core.notification_router import route_notification
        for cid in [chat_id_tom, chat_id_trent]:
            if cid and cid != "SETUP_NEEDED":
                try:
                    route_notification(cid, text, bot_token, severity=severity, agent="walker-capital")
                except Exception as e:
                    logger.error(f"Walker send_both error: {e}")

    def send_reply(text: str, severity: str = "NOTABLE"):
        from core.notification_router import route_notification
        route_notification(chat_id, text, bot_token, severity=severity, agent="walker-capital")

    # ── /pipeline or /status ─────────────────────────────────────────────────
    if msg_lower in ("/pipeline", "pipeline", "/status", "status"):
        try:
            from core.walker_pipeline_db import get_pipeline_summary
            summary = get_pipeline_summary()
            stage_labels = {
                "DISCOVERED": "📍 Discovery",
                "SCREENED":   "🔎 Screened",
                "RESEARCHED": "📝 Research",
                "VALUED":     "💰 Valued",
                "RISK_ASSESSED": "⚠️ Risk Assessed",
                "SIMULATED":  "🌊 MiroFish",
                "DECISION_READY": "✅ Decision Ready",
                "APPROVED":   "🟢 Portfolio",
                "WATCHING":   "👁 Watchlist",
                "REJECTED":   "❌ Rejected",
            }
            lines = [
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                "🏦 WALKER CAPITAL — PIPELINE",
                datetime.now(NZ_TZ).strftime("%d %b %Y, %H:%M"),
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            ]
            total = 0
            for stage, label in stage_labels.items():
                count = summary.get(stage, 0)
                if count > 0:
                    lines.append(f"{label}: {count}")
                    total += count
            if total == 0:
                lines.append("Pipeline empty — next scan at 7am")
            lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
            lines.append("Reply: Value [TICKER] to run full analysis")
            send_reply("\n".join(lines))
        except Exception as e:
            send_reply(f"Pipeline error: {e}")
        return True

    # ── value [TICKER] / analyse [TICKER] ────────────────────────────────────
    value_match = re.match(
        r'^(?:value|analyse|analyze|run|full)\s+([A-Z0-9.]+)',
        msg, re.IGNORECASE
    )
    if value_match:
        ticker = value_match.group(1).upper()
        try:
            from core.walker_pipeline_db import get_companies_at_stage
            all_stages = [
                "RESEARCHED", "SCREENED", "DISCOVERED",
                "VALUED", "RISK_ASSESSED", "SIMULATED",
                "DECISION_READY", "APPROVED", "WATCHING"
            ]
            company = None
            for stage in all_stages:
                for c in get_companies_at_stage(stage):
                    if c["ticker"].upper() == ticker:
                        company = c
                        break
                if company:
                    break

            if not company:
                send_reply(
                    f"⚠️ {ticker} not in pipeline.\n"
                    f"Use /screen {ticker} [EXCHANGE] to add it, or wait for tomorrow's 7am discovery scan."
                )
                return True

            # Run full analysis in background thread
            import threading

            def _run():
                try:
                    _run_walker_full_analysis(company, send_both)
                except Exception as e:
                    logger.error(f"Walker full analysis thread failed for {ticker}: {e}", exc_info=True)
                    send_both(f"❌ Analysis failed for {ticker}: {e}")

            send_both(
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                f"🏦 WALKER CAPITAL\n"
                f"Full analysis starting: {company['name']} ({ticker})\n"
                f"Stage 4 → 5 → Memo — approx 4-6 minutes\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
            )
            threading.Thread(target=_run, daemon=True).start()

        except Exception as e:
            send_reply(f"❌ Error starting analysis for {ticker}: {e}")
        return True

    # ── /screen [TICKER] [EXCHANGE] ──────────────────────────────────────────
    screen_match = re.match(
        r'^/screen\s+([A-Z0-9.]+)(?:\s+([A-Z]+))?',
        msg, re.IGNORECASE
    )
    if screen_match:
        ticker = screen_match.group(1).upper()
        exchange = (screen_match.group(2) or "ASX").upper()
        try:
            from core.walker_screener import run_quantitative_screen
            from core.walker_pipeline_db import add_company, advance_stage, update_catalyst
            send_reply(f"🔎 Screening {ticker} on {exchange}...")
            screen = run_quantitative_screen(ticker, exchange, ticker)
            if screen.get("screen_passed"):
                company_id = add_company(
                    ticker=ticker, name=ticker, exchange=exchange,
                    sector="", discovery_thesis="Manually added via Telegram"
                )
                if company_id:
                    advance_stage(company_id, "SCREENED", notes=screen.get("screen_reason"))
                    update_catalyst(company_id, screen.get("catalyst_score", 0), screen.get("catalyst_description", ""))
                    send_reply(
                        f"✅ {ticker} added to pipeline\n"
                        f"{screen.get('screen_reason', '')}\n\n"
                        f"Reply: Value {ticker} to run full analysis"
                    )
                else:
                    send_reply(f"ℹ️ {ticker} already in pipeline. Reply: Value {ticker}")
            else:
                send_reply(f"❌ {ticker} failed screening\n{screen.get('screen_reason', '')}")
        except Exception as e:
            send_reply(f"Screen error for {ticker}: {e}")
        return True

    # ── BUY / WATCH / AVOID [TICKER] ────────────────────────────────────────
    decision_match = re.match(
        r'^(buy|watch|avoid)\s+([A-Z0-9.]+)',
        msg, re.IGNORECASE
    )
    if decision_match:
        decision = decision_match.group(1).upper()
        ticker = decision_match.group(2).upper()
        try:
            from core.walker_pipeline_db import get_companies_at_stage, log_decision
            company = None
            for stage in ["DECISION_READY", "RISK_ASSESSED", "VALUED", "RESEARCHED"]:
                for c in get_companies_at_stage(stage):
                    if c["ticker"].upper() == ticker:
                        company = c
                        break
                if company:
                    break
            if company:
                log_decision(company["id"], decision, "Trent Walker", "Decision via Telegram")
                emoji = {"BUY": "🟢", "WATCH": "👁", "AVOID": "🔴"}[decision]
                send_both(
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                    f"{emoji} DECISION LOGGED\n"
                    f"{company['name']} ({ticker}): {decision}\n"
                    f"By: Trent Walker | {datetime.now(NZ_TZ).strftime('%d %b %Y, %H:%M')}\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                )
            else:
                send_reply(f"⚠️ {ticker} not found in pipeline at a decision-ready stage.")
        except Exception as e:
            send_reply(f"Decision log error: {e}")
        return True

    # Not a recognised command — let normal Vesper chat flow handle it
    return False


def _run_walker_full_analysis(company: dict, send_both_fn):
    """
    Run Stages 4 + 5 + 7 for a company. Called in a background thread.
    Sends progress updates and final memo to both channels.
    """
    ticker = company["ticker"]
    exchange = company["exchange"]
    name = company["name"]
    company_id = company["id"]
    segment = company.get("segment") or "A"

    # Load research brief from DB
    research_brief = ""
    try:
        from core.walker_pipeline_db import get_company_full_profile
        profile = get_company_full_profile(company_id)
        research_brief = profile.get("research", {}).get("brief_text", "")
    except Exception:
        pass

    # ── Stage 4: Valuation ───────────────────────────────────────────────────
    logger.info(f"Walker Stage 4 running for {ticker}")
    from core.walker_stage4_valuation import run_stage4
    val = run_stage4(ticker, exchange, name, company_id, segment, research_brief)

    if not val.get("success"):
        send_both_fn(f"❌ Stage 4 failed for {ticker}: {val.get('error', 'Unknown error')}")
        return

    currency = val.get("currency", "")
    mos = val["margin_of_safety"]
    mos_pct = mos * 100

    s4_lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"💰 STAGE 4 COMPLETE — {name} ({ticker})",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"Current price: {currency}{val['current_price']:.2f}",
        f"DCF Bull: {currency}{val['dcf_bull']:.2f}",
        f"DCF Base: {currency}{val['dcf_base']:.2f}",
        f"DCF Bear: {currency}{val['dcf_bear']:.2f}",
        f"Weighted value: {currency}{val['weighted_value']:.2f}",
        f"Upside: {val['upside_pct']:.1f}%",
        f"Margin of safety: {mos_pct:.1f}% {'✅' if mos >= 0.20 else '❌ BELOW 20%'}",
        f"Confidence: {val['confidence']}",
    ]
    if val.get("ms_fair_value"):
        s4_lines.append(
            f"Morningstar FV: {currency}{val['ms_fair_value']:.2f} | "
            f"Moat: {val.get('ms_moat', 'N/A')} | "
            f"{val.get('ms_stars', '?')}⭐ | "
            f"Stewardship: {val.get('ms_stewardship', 'N/A')}"
        )
    if val.get("comps_implied"):
        s4_lines.append(f"Comps implied: {currency}{val['comps_implied']:.2f}")

    if mos < 0.20:
        s4_lines.append("")
        s4_lines.append(f"⛔ Margin of safety {mos_pct:.1f}% is below 20% threshold.")
        s4_lines.append(f"{name} moved to WATCHING. Monitor for a better entry point.")
        s4_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        send_both_fn("\n".join(s4_lines))
        return

    s4_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    s4_lines.append("✅ Passes threshold — running Stage 5: Risk Assessment...")
    send_both_fn("\n".join(s4_lines))

    # ── Stage 5: Risk Assessment ─────────────────────────────────────────────
    logger.info(f"Walker Stage 5 running for {ticker}")
    from core.walker_stage5_risk import run_stage5
    risk = run_stage5(ticker, exchange, name, company_id, segment, research_brief, val)

    if not risk.get("success"):
        send_both_fn(f"❌ Stage 5 failed for {ticker}: {risk.get('error', 'Unknown error')}")
        return

    conviction = risk["conviction_score"]

    s5_lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"⚠️ STAGE 5 COMPLETE — Risk Assessment",
        f"{name} ({ticker})",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    if risk.get("var_99") is not None:
        s5_lines.append(f"VaR 99% (1yr): {risk['var_99']:.1f}% | CVaR 99%: {risk.get('cvar_99', '?'):.1f}%" if risk.get('cvar_99') else f"VaR 99% (1yr): {risk['var_99']:.1f}%")
    if risk.get("altman_z") is not None:
        s5_lines.append(f"Altman Z: {risk['altman_z']:.2f} [{risk['altman_zone']}]")
    if risk.get("fcf_conversion") is not None:
        s5_lines.append(f"FCF Conversion: {risk['fcf_conversion']:.1f}% [{risk['fcf_label']}]")
    s5_lines.append(f"Earnings quality flags: {risk['flag_count']}")
    s5_lines.append(f"Fisher Score: {risk['fisher_score']}/75")
    if risk["fisher_strengths"]:
        s5_lines.append(f"Top strength: {risk['fisher_strengths'][0]}")
    if risk["fisher_concerns"]:
        s5_lines.append(f"Top concern: {risk['fisher_concerns'][0]}")
    s5_lines.append(f"Conviction: {conviction}/10 — {risk['conviction_label']}")

    if not risk.get("proceed"):
        s5_lines.append("")
        s5_lines.append(f"⛔ Conviction {conviction}/10 — returning {ticker} to watchlist.")
        s5_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        send_both_fn("\n".join(s5_lines))
        return

    s5_lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    s5_lines.append("✅ Conviction threshold met — generating investment memo...")
    send_both_fn("\n".join(s5_lines))

    # ── Stage 7: Investment Memo ─────────────────────────────────────────────
    logger.info(f"Walker Stage 7 generating memo for {ticker}")
    try:
        from core.walker_pipeline_db import get_company_full_profile, advance_stage
        from core.walker_memo_generator import generate_investment_memo
        advance_stage(company_id, "DECISION_READY")
        full_profile = get_company_full_profile(company_id)
        memo = generate_investment_memo(full_profile)
        send_both_fn(memo)
        logger.info(f"Walker full pipeline complete for {ticker}")
    except Exception as e:
        logger.error(f"Memo generation failed for {ticker}: {e}", exc_info=True)
        send_both_fn(f"❌ Memo generation failed for {ticker}: {e}")


# --- Code below was accidentally placed inside _run_walker_full_analysis ---
# --- It belongs in _run_scheduled_task_inner. Fixed by closing walker function above. ---


def _run_scheduled_task_general(agent_name: str, task_name: str, telegram_config: dict):
    """
    General scheduled task handler: loads agent brain, builds prompt, calls Claude,
    sends to Telegram. Called by _run_scheduled_task_inner for any task that doesn't
    have a dedicated handler (i.e., most agents).
    """
    # --- SCOUT daily scan (scrapes AI creators — needs Python, not Claude) ---
    if task_name == "daily_scan" and agent_name == "scout":
        try:
            from core.scout_scraper import ScoutScraper
            scraper = ScoutScraper(BASE_DIR)
            result = scraper.run_daily_scan()

            # Format results for Telegram
            ideas = result.get("ideas", [])
            summary = f"SCOUT Daily Scan Complete\n\nCreators scanned: {result.get('creators_scanned', 0)}\nIdeas extracted: {len(ideas)}\n"
            for i, idea in enumerate(ideas[:5], 1):
                summary += f"\n{i}. {idea.get('title', 'Untitled')}\n   Score: {idea.get('score', 0)}/10 | Source: {idea.get('source', '?')}\n"

            chat_id = telegram_config.get("chat_ids", {}).get(agent_name) or \
                      telegram_config.get("chat_ids", {}).get("command-center", "")
            if chat_id:
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                from core.notification_router import route_notification
                route_notification(chat_id, summary, bot_token, severity="NOTABLE", agent=agent_name)

            logger.info(f"SCOUT daily scan complete: {len(ideas)} ideas extracted")
        except Exception as e:
            logger.error(f"SCOUT daily scan failed: {e}")
        return

    # Resolve user_id for agents serving non-default users (e.g., Aether → Jackson)
    sched_user_id = CHAT_USER_MAP.get(agent_name)
    # For companions: build richer ASMR context from CURRENT_PLAN.md active constraints + recent state
    sched_context = ""
    if sched_user_id:
        _plan_file = AGENTS_DIR / agent_name / "state" / "CURRENT_PLAN.md"
        if _plan_file.exists():
            try:
                _plan = _plan_file.read_text(encoding='utf-8')
                # Extract ACTIVE CONSTRAINTS section for ASMR context
                if "ACTIVE CONSTRAINTS" in _plan:
                    _constraints_start = _plan.index("ACTIVE CONSTRAINTS")
                    _constraints_end = _plan.index("---", _constraints_start + 20) if "---" in _plan[_constraints_start + 20:] else _constraints_start + 500
                    _constraints = _plan[_constraints_start:_constraints_start + (_constraints_end - _constraints_start)]
                    sched_context = f"Scheduled {task_name} check-in. {_constraints[:500]}"
                else:
                    sched_context = f"Scheduled {task_name} check-in"
            except Exception:
                sched_context = f"Scheduled {task_name} check-in"
        else:
            sched_context = f"Scheduled {task_name} check-in"
    brain = load_agent_brain(agent_name, user_id=sched_user_id, current_context=sched_context)

    # Build task-specific prompt
    task_prompts = {
        "morning_protocol": "Execute your morning protocol. Generate today's training plan, meal plan, and any notes. Use the format specified in your AGENT.md.",
        "morning_briefing": "Generate the daily master briefing NOW. You have all agent states and LIVE DATA injected below this prompt — Shopify revenue, Klaviyo emails, Meta Ads, Asana tasks, financial data. USE THE ACTUAL NUMBERS from the injected data. Do NOT say 'unavailable' or 'not connected' — the data IS below. If a specific source shows an error in brackets like [Shopify error: ...], report that specific error. Deliver the full briefing using the exact format from your AGENT.md. Never ask permission or offer options — just brief.",
        "morning_brief": """Generate your morning operations brief NOW using the LIVE DATA injected below this prompt. The orchestrator has already fetched Shopify, Klaviyo, Meta, and Asana data for you — it appears below. Use ACTUAL NUMBERS from the injected data. Do NOT say 'data unavailable' or 'not yet connected' — the data IS here. If a specific data source shows an error in brackets like [Klaviyo error: ...], report that specific error. Flag issues, list priorities. Use the format specified in your AGENT.md.

CRITICAL — THIS-WEEK.md EXECUTION:
After your performance numbers, check THIS-WEEK.md (in agents/shared/strategy/). For every task assigned to you that has NOT yet been done today:
- PRODUCE the work right now (write the copy, write the brief, write the strategy)
- Emit [TASK:] markers for everything needing Tom's approval before it goes live
- Do NOT recommend. Do NOT say "we should consider". WRITE IT and emit [TASK: Review X|priority|copy pasted in notes]

Priority order from THIS-WEEK.md:
1. Any email copy due to be sent today → write subject, preview text, body copy → [TASK:]
2. Any campaign creative needed → write it → [TASK:]
3. Pure Pets ROAS check → pull number, state verdict (pause/hold/scale)
4. Any Asana tasks for blocked items → emit [TASK:] so Tom sees them

You are the executor. The work gets done in this morning brief, not recommended for later.

If you identify a campaign opportunity or creative need, emit [BRIEF: description of insight] and the system will auto-generate a designer-ready brief for Roie and create an Asana task.""",
        "scan": "Execute your monitoring scan. Search for updates on your watchlist topics. Report only what's NEW since your last scan. Use the format specified in your AGENT.md.",
        "model_scan": "Execute your AI model release scan. Search for new video model announcements, updates to tracked models. If anything could handle action sequences, mark as CRITICAL. Use the format specified in your AGENT.md.",
        "weekly_plan": "Generate your weekly social plan. Review contact list, flag overdue catch-ups, suggest activities. Use the format specified in your AGENT.md.",
        "midweek_checkin": "Mid-week social check-in. Review what was planned, what happened, anything coming up this weekend.",
        "weekly_review": """Execute your weekly performance review. Full data pull, compare to targets, identify patterns.

CRITICAL: This is not an advice session. This IS the execution briefing. After analysing the data:

1. PRODUCE WORK — Do not just recommend. For each email identified as needed this week:
   - Write the subject line and preview text right now
   - Write the opening line of the body copy
   - Emit [TASK: Review email draft: {subject}|urgent|Subject: {subject}\\nPreview: {preview}\\nOpening: {opening}] for Tom to approve in Asana

2. For any Meta ad creative needed:
   - Write the hook (first 3 seconds of video OR headline)
   - Write the body copy
   - Emit [TASK: Ad creative ready for review: {campaign}|high|Hook: {hook}\\nBody: {body}]

3. For any ROAS decisions needed:
   - State the verdict (pause/hold/scale) with the verified number
   - If pausing: emit [TASK: Pause {campaign} — ROAS below floor|urgent|Verified ROAS: {x}x, floor is 2x]
   - If scaling: emit [TASK: Scale {campaign} budget 50%|high|ROAS: {x}x verified]

4. Emit [BRIEF: ...] for any creative need to auto-generate Roie brief.

The system will auto-create Asana tasks from your [TASK:] markers. Tom reviews and approves. You are not a reporter — you are the executor. Do the work.""",
        "weekly_deep_dive": "Execute your weekly deep analysis. Pick the most important developing story and provide in-depth analysis. Use the format specified in your AGENT.md.",
        "evening_reading": "",  # Placeholder -- replaced below with knowledge engine output
        "content_generation": "Generate tonight's SEO/AEO article following your nightly workflow. Check your CONTEXT.md for the current keyword priority, select the next topic, and generate a full article using one of your proven content formulas. Include the complete article HTML, meta description, FAQ section, and JSON-LD schema. Save instructions and Shopify draft details should be in your output. After your article, emit a [STATE UPDATE:] with the article title and next priority keyword.",
        # --- Newer agents (previously hitting generic fallback) ---
        "daily_protocol": "Execute your daily protocol. Follow the exact format and instructions in your AGENT.md. Generate today's output based on the current context and your domain expertise.",
        "evening_checkin": "Execute your evening cognitive check-in. Ask Tom to log today's brain health metrics: focus quality (1-10), mood (1-10), energy (1-10), social ease, any memory lapses, substance use (Y/N), and anything notable about his mental state today. Keep it warm, quick, and easy to respond to. Reference what today's morning protocol recommended and ask how it went. This data is CRITICAL for tracking recovery over time — without it, you cannot spot trends or adjust protocols. After Tom responds, emit [STATE UPDATE:] with ALL the data points, [METRIC:] for each trackable number, and [EVENT: brain.daily_log|INFO|summary] so Titan sees it.",
        "daily_briefing": "Generate your daily briefing. Follow the format in your AGENT.md. Use any live data injected below. Include analysis, recommendations, and actionable items.",
        "daily_micro_action": "Generate today's micro-action. One specific, actionable thing Tom should do today based on your domain. Make it concrete, not abstract. Follow your AGENT.md format.",
        "weekly_reflection": "Execute your weekly reflection. Review the past week through your lens. What patterns emerged? What should change? Follow your AGENT.md format. Be profound and practical.",
        "weekly_lesson": "Deliver this Sunday's Aurelius lesson. Two parts only: (1) ONE cooking skill or dish to focus on for the coming week — specific, tied to Tom's progression track in your AGENT.md, concrete enough to act on tomorrow. (2) ONE personal area to improve this coming week — character, presence, or life skill, with a concrete practice. End with a single Marcus Aurelius quote that ties both together. Keep the whole thing under 200 words. Emit [STATE UPDATE:] with what was assigned for the week.",
        "daily_scan": "Execute your daily ecosystem scan. Follow the workflow in your AGENT.md. Scrape sources, extract ideas, rank by applicability/effort/ROI, and deliver the top actionable insights.",
        "health_check": "Run your system health check. Check all agents, integrations, and data flows. Report what's working, what's failing, and what needs attention. Be specific with error details.",
        "daily_forecast": "Generate your daily 90-day trajectory forecast. Use current data and trend analysis. Where is Tom headed? What needs course correction? Follow your AGENT.md format.",
        "weekly_compilation": "Execute your weekly experiment compilation. Gather all A/B test results and hypothesis outcomes from this week. Analyse patterns and recommend next experiments.",
        "weekly_codification": "Execute your weekly principle extraction. Review this week's decisions, outcomes, and patterns. Extract and codify any new principles. Follow your AGENT.md format.",
        "weekly_audit": "Execute your weekly efficiency audit. Analyse where time and money went, what generated returns, and what should change. Be data-driven. Follow your AGENT.md format.",
        "deep_dive_lesson": "Generate tonight's deep-dive lesson. CRITICAL: Read your CONTEXT.md above — find the 'CURRENT CURRICULUM DAY' field and advance to the NEXT uncompleted day. Do NOT repeat a day that is already marked COMPLETED. Follow the 90-day curriculum in your AGENT.md. Use the exact output format specified. At the end of your lesson, you MUST emit: [STATE UPDATE: CURRENT CURRICULUM DAY: X | COMPLETED: Day X — <topic name> on <today's date> | NEXT: Day X+1 — <next topic>]",
        "reflection_session": "Conduct a therapeutic reflection session. Review Tom's emotional state, relationships, and life direction. Follow your AGENT.md format. Be genuine, not generic.",
        "tony_report": "Generate this week's Tony CEO report. Pull all performance data, decisions made, campaigns launched, and strategic progress. Follow the weekly report format in your AGENT.md. File-based output for Tom to review before sending.",
        "daily_drop": "Execute today's daily cultural drop. CRITICAL: First check CONTEXT.md — if STATUS is ONBOARDING_PHASE_1, do NOT run the standard drop. Instead, send Tom a warm opening message that starts the onboarding discovery (Phase 1: Music questions). If onboarding is complete, check today's day of week and deliver the correct domain drop (Monday=Music, Tuesday=Fashion, Wednesday=Art/Design, Thursday=Music different genre, Friday=Film/Photography, Saturday=Cultural concept, Sunday=skip — weekly_review handles Sunday). Make it specific, personal, and short (150-250 words). Always include one concrete action: listen to THIS, look up THIS, try THIS. Emit [TASTE_PROFILE:] and [STATE UPDATE:] markers after delivering.",
        "weekly_review": "Execute this week's Sunday cultural review. Check CONTEXT.md for what was delivered this week and any resonance signals. Deliver: (1) what we explored this week with one-line reflections, (2) what's landing vs what's not based on Tom's responses, (3) this week's full playlist additions across all 5 playlists — specific songs, artist, why each one. Update knowledge.md playlist tracker. Emit [STATE UPDATE:] with full playlist state.",
        # --- Medici (Global Power Intelligence) ---
        "daily_intelligence": "Execute today's daily power intelligence lesson. CRITICAL: Read CONTEXT.md first — find NEXT field to know which elite/org/figure to cover today. Do NOT repeat one already covered. Use the DAILY LESSON FORMAT in your AGENT.md exactly. Pull live news from the injected feeds to find anything current on today's focus. Use your knowledge.md for the deep structure. Be specific: name names, cite real organisations, real documented events. Distinguish confirmed vs probable vs speculative clearly. End with [STATE UPDATE:] advancing your curriculum position to the next figure.",
        "weekly_deep_dive": "Execute this Sunday's power deep dive. Pick ONE major current event from the live news that connects to elite financial or political interests. Follow the money: who benefits financially, what policy/regulatory angle is in play, which elite nodes are coordinating, what mainstream coverage misses. Use your knowledge.md power map to connect the dots. Include primary source trail — name the specific filings, organisations, people. 1000-1200 words. Dense. This is the lesson Tom reads on Sunday morning with coffee. Emit [STATE UPDATE:] with what was covered and any new watchlist additions.",
        # --- Prospector (First-Principles Opportunity Scanner) ---
        "daily_lesson": "Execute today's daily lesson. Follow the exact format and instructions in your AGENT.md. Read CONTEXT.md first to find your current curriculum position — advance to the NEXT uncompleted topic. Do NOT repeat content already covered. Use any live data injected below. After your lesson, emit [STATE UPDATE:] with your curriculum position and what was covered today.",
        "morning_wisdom": "Deliver today's morning Stoic wisdom. One practical micro-action for today — grounded in Marcus Aurelius, Epictetus, or Seneca but applied to Tom's actual life right now. Reference what you know about his current state from CONTEXT.md. Keep it under 150 words. Concrete, not abstract. Emit [STATE UPDATE:] with the practice assigned.",
        "daily_research": "Execute today's first-principles opportunity analysis. CRITICAL: Read CONTEXT.md first — find the NEXT field to know which human problem to cover today. Do NOT repeat a problem already covered (check LIVE UPDATES in CONTEXT.md for past analyses). Follow the DAILY RESEARCH format in your AGENT.md exactly. Be ruthlessly honest — if the market leader IS the best solution, say so. If supplements aren't the answer for this problem, say so. After your analysis, you MUST emit: [STATE UPDATE: LAST: {problem_name} | DOMAIN: {domain_number} | POS: {position} of 122 | NEXT: {next_problem_name} | SCORE: {X}/10 | TOP_BRAND: {name or 'none'}]",
        "weekly_synthesis": "Execute this Monday's weekly opportunity synthesis. Review your CONTEXT.md for all problems analysed in the past 7 days (check LIVE UPDATES). Follow the WEEKLY SYNTHESIS format in your AGENT.md. Identify cross-cutting patterns, rank the top 3 opportunities, and update the cumulative brands watchlist. ALSO: after the synthesis, run today's daily first-principles analysis on the next problem in your rotation (check NEXT in CONTEXT.md). Emit [STATE UPDATE:] for both the synthesis and the new daily analysis position.",
        # --- Apex (Tom's unified brain + body + life agent) ---
        "morning_protocol": """Execute your morning protocol. Follow the format in your AGENT.md but keep it CONVERSATIONAL — you're a coach checking in, not a system generating a report.

Open warm. Use Tom's name. Reference yesterday if you have diary data (what he trained, how he felt, what he ate).

Then deliver today's plan:
- Phase + day count (one line)
- Ask about sleep (hours, quality, how he feels right now)
- Substance check (quick, no pressure — 'All clean?' is fine after the first few days)
- Today's training plan from training-protocol.md (specific: exercises, sets, reps, weights from knowledge.md)
- Today's nutrition priorities (keep it practical — what to eat, not a lecture)
- Supplement reminders (which ones, when — be specific)
- One brain science insight (rotate from MASTERS.md — mechanism, not motivation. 2-3 sentences max. Teach him something he can think about all day)
- One focus priority for the day

Keep it SHORT. Tom reads this on his phone in 90 seconds. Use line breaks generously. No tables. No walls of text. End with energy — set the tone for a good day.

If it's been 5+ days and bloodwork hasn't been discussed yet, weave in a natural mention based on whatever symptom or metric Tom has been reporting. Don't dump info — just plant the seed.

After delivering, emit [STATE UPDATE:] with the day count and any data collected.""",
        "midday_pulse": """Execute your midday pulse. This is a 30-second touchpoint, not a deep dive.

Tone: Casual, quick, like a mate checking in.

Ask 3-4 things max:
- Have you eaten well? (protein specifically)
- Energy right now? (1-10)
- Any cravings or triggers today?
- Quick reminder of tonight's training

Drop ONE micro-insight — 1-2 sentences of brain science. Something that connects to what he's experiencing right now.

If Tom mentioned something specific in his morning response, reference it. Show you're listening. That's what makes this feel like a relationship, not a system.

Keep the whole message under 100 words.""",
        "evening_debrief": """Execute your evening debrief. This is your PRIMARY data collection session.

Start open: 'How was today, Tom?' or reference something specific from the day.

Then collect (make it feel like a conversation, not a form):
- Focus quality (1-10)
- Mood (1-10)
- Energy (1-10)
- Social ease (1-10)
- Memory lapses (any?)
- Substance use (weed, alcohol, porn — Y/N, zero target)
- Training: what did you do, duration, any PBs, any pain (hip?)
- Nutrition: what did you eat, estimated protein, any skipped meals
- Protocol: cardio done? Supplements taken? Meditation? Cold exposure?
- Anything notable about your thinking or cognitive state today?

After Tom responds, THIS is where you earn your value:
- Connect today's data to the 7-day trend. Name patterns.
- Name wins Tom might not see himself.
- If crash-state mood: flag it as a depleted-day assessment, not a reliable signal.
- Preview tomorrow's training plan.
- Sleep protocol reminder (target bedtime, wind-down, magnesium).

Emit [STATE UPDATE:] with ALL metrics, [METRIC:] for each number, [INSIGHT:] or [PATTERN:] for any trends detected. This data feeds tomorrow's morning protocol.""",
        # --- Aether (Recovery Companion for Jackson) ---
        "weekly_progress_report": "",  # Handled specially below (generates summary for Tom, not Jackson)
        "morning_checkin": "Execute your morning check-in for Jackson. Follow the exact Morning Ground format in your AGENT.md. Be warm and gentle. Ask about sleep (hours, quality, disturbances), current body state (tension level 1-10, locations, POTS symptoms), current mind state (mood 1-10, anxiety, OCD intrusion). Deliver today's micro-practice (rotate based on current phase from CONTEXT.md) and a psychoeducation snippet from one thought leader in MASTERS.md. Include a nutrition reminder. Keep it SHORT — Jackson should read this in 60 seconds and respond in 30 seconds. Check CONTEXT.md first to know which phase he's in and tailor accordingly.",
        "midday_checkin": "Execute your midday check-in for Jackson. Follow the Midday Move format in your AGENT.md. Quick touchpoint only — 3-4 questions max. Did he try this morning's practice? Has he had a shake/meal? Tension right now (1-10)? Any symptom spike? Ask for one micro-win (one thing he did today, even tiny). Keep it SHORT and encouraging. This is a touchpoint, not a deep dive.",
        "evening_checkin": "Execute your evening check-in for Jackson. This is your PRIMARY data collection session. Follow the Evening Reflect format in your AGENT.md exactly. Start with 'How was today overall?' then collect ALL structured metrics: energy (1-10), mood (1-10), tension peak (1-10 + trigger), OCD intrusion frequency, fear-of-damage (1-10), POTS severity (1-10), social interaction type, nutrition (shakes/meals + estimated calories), exercise (type + duration), practice adherence (which techniques used/skipped). After Jackson responds, point out any patterns from the 7-day diary. Name today's wins explicitly. Suggest tomorrow's focus and a wind-down technique. Emit [STATE UPDATE:] with ALL metrics, [METRIC:] for each number, any [INSIGHT:] or [PATTERN:] detected, and [PHASE_CHECK: current_phase|criteria_met_list|criteria_remaining_list].",
    }

    task_prompt = task_prompts.get(task_name, f"Execute task: {task_name}. Follow the instructions and format in your AGENT.md.")

    # Companion agents: load task prompts from agents/[name]/prompts/[task_name].md if present.
    # This means zero orchestrator changes are needed when adding a new companion agent.
    _prompt_file = AGENTS_DIR / agent_name / "prompts" / f"{task_name}.md"
    if _prompt_file.exists():
        try:
            _file_prompt = _prompt_file.read_text(encoding='utf-8').strip()
            if _file_prompt:
                task_prompt = _file_prompt
                logger.debug(f"Loaded prompt from file: {_prompt_file}")
        except Exception as e:
            logger.warning(f"Could not read prompt file {_prompt_file}: {e}")

    # Recovery companion weekly progress report: generates a privacy-respecting summary for Tom
    # All companion agents (any agent in CHAT_USER_MAP) can generate weekly progress reports.
    if task_name == "weekly_progress_report" and agent_name in CHAT_USER_MAP:
        try:
            # Read CONTEXT.md for phase and metrics
            context_file = AGENTS_DIR / agent_name / "state" / "CONTEXT.md"
            context = context_file.read_text(encoding='utf-8') if context_file.exists() else "No state data yet."

            # Count session logs (check-in adherence proxy)
            state_dir = AGENTS_DIR / agent_name / "state"
            log_count = 0
            for days_back in range(1, 8):
                log_date = (datetime.now(NZ_TZ).date() - timedelta(days=days_back)).isoformat()
                if (state_dir / f"session-log-{log_date}.md").exists():
                    log_count += 1

            # Read knowledge.md for patterns
            knowledge_file = AGENTS_DIR / agent_name / "knowledge.md"
            knowledge = knowledge_file.read_text(encoding='utf-8') if knowledge_file.exists() else ""

            # Get memory fact count for the user
            report_user_id = CHAT_USER_MAP.get(agent_name, "unknown")
            report_user_name = CHAT_USER_MAP.get(agent_name, "user").capitalize()
            report_agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
            try:
                from core.user_memory import get_memory_stats
                stats = get_memory_stats(report_user_id)
                fact_count = stats.get('active_facts', 0)
                msg_count = stats.get('total_messages', 0)
            except Exception:
                fact_count = 0
                msg_count = 0

            # Build the summary prompt — sent to Claude to generate, then routed to Tom's command-center
            task_prompt = f"""You are generating a WEEKLY PROGRESS REPORT about {report_user_name}'s recovery for Tom (who set up this agent).

This report goes to Tom's command-center channel. It must be:
- Privacy-respecting: NO personal details, therapy content, or emotional disclosures
- Data-focused: adherence %, metric trends, phase status
- Concise: under 300 words

Here is {report_agent_display}'s current state (CONTEXT.md):
{context[:3000]}

Session logs found for last 7 days: {log_count}/7

Memory system: {fact_count} facts learned, {msg_count} messages archived

Generate the report in this format:

AETHER WEEKLY PROGRESS — [Phase X: Name], Day [N]

ENGAGEMENT
- Check-in days active: X/7
- Messages exchanged: {msg_count} total
- Facts learned: {fact_count}

METRICS TREND (from CONTEXT.md data, use whatever is available)
- List key metrics with 7-day averages and trend direction (up/down/stable)
- If baseline not yet established, say so

PHASE STATUS
- Current phase and days in it
- Which transition criteria are met vs remaining
- Estimated readiness: on track / needs attention / blocked

SYSTEM HEALTH
- Memory system: working / issues
- Agent responding: yes (confirmed by session logs)

Flag anything that needs Tom's attention (e.g., low adherence, no responses for 2+ days, phase transition ready).

Do NOT include any personal health details, therapy discussions, or emotional content."""

            # Override: send to command-center, not aether channel
            chat_id = telegram_config.get("chat_ids", {}).get("command-center", chat_id)

        except Exception as e:
            logger.error(f"Aether weekly report generation failed: {e}")
            return

    # Evening reading: knowledge engine builds the full prompt
    if task_name == "evening_reading":
        try:
            from core.knowledge_engine import get_tonight_reading
            reading = get_tonight_reading()
            task_prompt = reading["prompt"]
            logger.info(f"Evening reading: {reading['primary_concept']} (score: {reading['primary_score']})")
            # Write selected concept to CONTEXT.md immediately -- backup cooldown in case
            # reading_log.db doesn't persist on Railway. This ensures we NEVER repeat.
            _tonight_str = datetime.now(NZ_TZ).date().isoformat()
            update_agent_state("evening-reading",
                f"DELIVERED READING — {_tonight_str}: {reading['primary_concept']} "
                f"(domain: {reading['primary_domain']}, key: {reading['primary_key']}) "
                f"| Do NOT repeat this concept for at least 30 days.")
        except Exception as e:
            logger.error(f"Knowledge engine failed: {e}")
            task_prompt = "Deliver a foundational knowledge lesson for Tom's evening reading. Pick a mental model or strategic concept and connect it to running a DTC health supplement business. 500-800 words, practical, Telegram-friendly."

    # Inject explicit date/day so agents never confuse the day
    _now_nz = datetime.now(NZ_TZ)
    _today_str = _now_nz.strftime("%A, %B %d, %Y")
    _time_str = _now_nz.strftime("%I:%M %p")
    task_prompt += f"""

TODAY IS: {_today_str} (current time: {_time_str} NZST). Always refer to today by this date and day name. Never guess what day it is."""

    # Add formatting rules + cross-agent event and task markers to all scheduled prompts
    task_prompt += """

FORMATTING RULES (Telegram output):
- NEVER use markdown tables (| col | col |). Telegram cannot render them.
- Use bullet points, numbered lists, or "Label: Value" pairs instead.
- Bold with *asterisks*, not **double**. Telegram Markdown uses single asterisks.
- Keep lines under 80 chars where possible for mobile readability.
- Use line breaks and section headers (ALL CAPS or emoji) to separate sections.

SYSTEM CAPABILITIES — use these markers when appropriate:
- To flag something for another agent: [EVENT: event.type|SEVERITY|description or json]
  Example: [EVENT: campaign.performance_drop|IMPORTANT|{"campaign":"GLM March","roas":2.1}]
- To create a task in Asana: [TASK: title|priority|description]
  Example: [TASK: Refresh GLM creative|high|ROAS dropped below 3x, need new ad variants]
- To log a decision with reasoning: [DECISION: type|title|reasoning|confidence]
  Example: [DECISION: tactical|Pause GLM Meta campaign|ROAS below 2x for 3 days|0.85]
  Types: strategy, tactical, operational, creative, financial
- To verify a past decision: [VERIFY: decision_id|positive or negative|outcome notes]
- Severity levels: CRITICAL, IMPORTANT, NOTABLE, INFO
- Task priorities: urgent, high, medium, low
Only emit these when genuinely useful. Do not force them."""

    # --- Inject live data into task prompts ---
    # Track what data was successfully injected vs unavailable
    data_status = {}

    # 1. Live news for scan/briefing tasks
    live_news_tasks = ("scan", "model_scan", "morning_brief", "morning_briefing", "weekly_review", "weekly_deep_dive", "daily_intelligence", "daily_research", "weekly_synthesis")
    if task_name in live_news_tasks:
        try:
            from core.news_fetcher import fetch_news_for_agent
            live_news = fetch_news_for_agent(agent_name)
            if live_news:
                task_prompt += f"""

IMPORTANT: Below are LIVE news headlines fetched just now. Use these as your primary source
of current information. Your training data may be outdated -- trust these headlines for
what is happening RIGHT NOW.

{live_news}

Analyse these headlines through your frameworks. Focus on what's NEW and significant.
Cross-reference with your state/CONTEXT.md to identify changes since your last briefing."""
                logger.info(f"Injected {len(live_news)} chars of live news for {agent_name}/{task_name}")
                data_status["Live News (RSS)"] = "OK"
            else:
                data_status["Live News (RSS)"] = "No headlines returned"
        except Exception as e:
            logger.warning(f"News fetch failed (non-fatal): {e}")
            data_status["Live News (RSS)"] = f"FAILED: {e}"

    # 1b. X live event intelligence for Atlas (global-events) — free via twscrape
    if task_name in live_news_tasks and agent_name == "global-events":
        try:
            from core.x_event_scraper import scrape_all_events, format_events_for_atlas
            x_results = scrape_all_events()
            x_intel = format_events_for_atlas(x_results)
            if x_intel:
                task_prompt += f"""

{x_intel}

Cross-reference the X posts above with the RSS headlines. Viral/high-engagement posts
often signal breaking developments before traditional media catches up. Note sentiment,
key accounts amplifying, and emerging narratives not yet in mainstream coverage."""
                logger.info(f"Injected X event intelligence for Atlas ({sum(len(v['tweets']) for v in x_results.values())} tweets)")
                data_status["X Live Events"] = "OK"
            else:
                data_status["X Live Events"] = "No tweets returned"
        except Exception as e:
            logger.warning(f"X event scrape failed (non-fatal): {e}")
            data_status["X Live Events"] = f"FAILED: {e}"

    # 2. Performance data for business briefings — SINGLE SOURCE OF TRUTH
    # Uses core.data_brief which pulls from the same sources as the dashboard.
    # If the dashboard shows correct data, agents get correct data.
    perf_data_tasks = ("morning_briefing", "morning_brief", "weekly_review", "daily_briefing", "daily_forecast", "weekly_deep_dive", "tony_report")
    if task_name in perf_data_tasks and agent_name in ("daily-briefing", "dbh-marketing", "strategic-advisor", "trajectory", "customer-science"):
        try:
            from core.data_brief import build_data_brief, build_weekly_brief
            days = 7 if task_name == "weekly_review" else 1
            perf_data = build_weekly_brief() if days == 7 else build_data_brief()
            task_prompt += f"""

{perf_data}

Use this real performance data in your briefing. Show actual numbers. Identify attribution
patterns -- what's driving sales? Compare to benchmarks in your playbooks.
These numbers come from the verified dashboard data pipeline -- treat them as ground truth.
The 90-day goal trajectory (Mar $50K → Apr $62.5K → May $77.5K → Jun $87.5K = $277.5K total) must inform every analysis."""
            logger.info(f"Injected DASHBOARD-SOURCED performance data for {agent_name}/{task_name}")
            data_status["Shopify/Klaviyo/Meta Performance"] = "OK (dashboard pipeline)"
        except Exception as e:
            # Fall back to old data_fetcher if data_brief fails
            logger.warning(f"Dashboard data brief failed, falling back to data_fetcher: {e}")
            try:
                from core.data_fetcher import fetch_all_performance_data, fetch_weekly_performance_data
                days = 7 if task_name == "weekly_review" else 1
                perf_data = fetch_weekly_performance_data() if days == 7 else fetch_all_performance_data()
                task_prompt += f"""

{perf_data}

Use this real performance data in your briefing. Show actual numbers. Identify attribution
patterns -- what's driving sales? Compare to benchmarks in your playbooks."""
                logger.info(f"Injected FALLBACK performance data for {agent_name}/{task_name}")
                data_status["Shopify/Klaviyo/Meta Performance"] = "OK (fallback)"
            except Exception as e2:
                logger.warning(f"Performance data fetch failed (non-fatal): {e2}")
                data_status["Shopify/Klaviyo/Meta Performance"] = f"FAILED: {e2}"

    # 2b. Order-level intelligence (per-order attribution + customer analysis)
    if task_name in perf_data_tasks and agent_name in ("daily-briefing", "dbh-marketing", "strategic-advisor", "trajectory", "customer-science"):
        try:
            # PRIORITY: Try to use yesterday's locked snapshot first
            from core.snapshot_reporter import inject_snapshot_data
            snapshot_text = inject_snapshot_data(agent_name, task_name)

            if snapshot_text:
                # Snapshot exists -- use it as ground truth
                task_prompt += f"""

{snapshot_text}

=== SNAPSHOT-BASED ANALYSIS ===
This locked snapshot represents yesterday's complete calendar day (midnight to midnight NZ time).
All agents share this same ground truth."""
                logger.info(f"Injected SNAPSHOT data for {agent_name}/{task_name}")
                data_status["Order Intelligence (Snapshot)"] = "OK"
            else:
                # No snapshot yet (first run of day) -- fall back to live API
                from core.order_intelligence import fetch_order_intelligence, get_customer_db_summary
                days = 7 if task_name == "weekly_review" else 1
                order_data = fetch_order_intelligence(days)
                db_summary = get_customer_db_summary()
                task_prompt += f"""

{order_data}

=== CUMULATIVE CUSTOMER INTELLIGENCE ===
{db_summary}

IMPORTANT: Analyse each individual order. What caused each sale? What does the customer
profile tell us? Identify patterns: which channels drive highest AOV, which bring new vs
returning customers, which campaigns are working. Flag any unattributed orders.
For returning customers, note their LTV trajectory and what product they keep buying.
Use the cumulative intelligence DB summary to spot long-term trends (repeat buyers,
channel shifts, category growth). The DB learns more with every briefing."""
                logger.info(f"Injected live order intelligence (snapshot not yet available) for {agent_name}/{task_name}")
                data_status["Order Intelligence (Live API)"] = "OK"

            logger.info(f"Injected order intelligence for {agent_name}/{task_name}")
        except Exception as e:
            logger.warning(f"Order intelligence fetch failed (non-fatal): {e}")
            data_status["Order Intelligence + Customer DB"] = f"FAILED: {e}"

    # 2b2. Financial data from Xero + Wise for Oracle, PREP, Meridian
    if task_name in perf_data_tasks and agent_name in ("daily-briefing", "strategic-advisor", "dbh-marketing", "odysseus-money"):
        financial_parts = []

        # Xero: P&L, balance sheet, unpaid invoices
        try:
            from core.xero_client import XeroClient
            xero = XeroClient()
            if xero.available:
                snapshot = xero.get_financial_health_snapshot()
                if snapshot:
                    financial_parts.append(snapshot)
                    logger.info(f"Injected Xero financial data for {agent_name}/{task_name}")
                    data_status["Xero Financial"] = "OK"
                else:
                    data_status["Xero Financial"] = "Not configured (ASANA_ACCESS_TOKEN not set)"
            else:
                data_status["Xero Financial"] = "Not configured"
        except Exception as e:
            logger.warning(f"Xero data fetch failed (non-fatal): {e}")
            data_status["Xero Financial"] = f"FAILED: {e}"

        # Wise: Multi-currency balances, recent transfers, exchange rates
        try:
            from core.wise_client import WiseClient
            wise = WiseClient()
            if wise.available:
                wise_snapshot = wise.get_financial_snapshot()
                if wise_snapshot:
                    financial_parts.append(wise_snapshot)
                    logger.info(f"Injected Wise financial data for {agent_name}/{task_name}")
                    data_status["Wise Balances/FX"] = "OK"
            else:
                data_status["Wise Balances/FX"] = "Not configured"
        except Exception as e:
            logger.warning(f"Wise data fetch failed (non-fatal): {e}")
            data_status["Wise Balances/FX"] = f"FAILED: {e}"

        if financial_parts:
            task_prompt += f"""

=== FINANCIAL POSITION ===

⚠️ CRITICAL SEPARATION (PREP, Meridian, Oracle):

**DBH Operations (Xero):**
- P&L, balance sheet, runway, operational metrics
- Handled by Tony (CEO, operations, finance)
- Your role: MARKETING ONLY (ad spend, ROAS, CAC, channel efficiency)
- Do NOT make operational/cash-flow recommendations

**Tom's Personal Balance (Wise):**
- See breakdown below in WISE section
- This is Tom's personal money, NOT DBH operational budget
- DO include in briefing for transparency
- DO NOT flag as a business crisis or operational concern
- DO NOT suggest it impacts DBH spending decisions (it doesn't)

{chr(10).join(financial_parts)}

PREP: Your analysis scope is marketing efficiency (Meta ROAS, email ROI, Google Ads performance).
Do not conflate Tom's personal balance with DBH business decisions. Focus on marketing unit economics.

Meridian: Same scope — marketing performance, channel optimization, campaign ROAS.

Oracle: Include DBH financial health (Xero) in your PERFORMANCE section, but separate from Tom's personal finances."""

    # 2c. Replenishment candidates for Meridian
    if task_name in ("morning_brief", "morning_briefing") and agent_name in ("dbh-marketing", "daily-briefing", "strategic-advisor"):
        try:
            from core.replenishment_tracker import format_replenishment_brief
            repl_brief = format_replenishment_brief()
            if repl_brief:
                task_prompt += f"""

{repl_brief}

Flag customers who are OVERDUE or URGENT for reorder. These are immediate revenue opportunities.
The replenishment system auto-fires Klaviyo events at 10pm daily for eligible customers."""
                logger.info(f"Injected replenishment brief for {agent_name}/{task_name}")
                data_status["Replenishment Candidates"] = "OK"
            else:
                data_status["Replenishment Candidates"] = "No candidates"
        except Exception as e:
            logger.warning(f"Replenishment brief failed (non-fatal): {e}")
            data_status["Replenishment Candidates"] = f"FAILED: {e}"

    # 2d. Open exceptions for briefings (catch and resolve, don't report)
    if task_name in ("morning_brief", "morning_briefing", "weekly_review") and agent_name in ("daily-briefing", "dbh-marketing", "strategic-advisor"):
        try:
            from core.exception_router import ExceptionRouter
            er = ExceptionRouter()
            exception_brief = er.format_exception_brief()
            if exception_brief:
                task_prompt += f"""

{exception_brief}

CRITICAL: These are open exceptions that need resolution. Do NOT just report them.
For each exception: state the problem, what auto-resolution was attempted, and what
specific action you recommend right now. Force resolution, don't create a dashboard."""
                logger.info(f"Injected exception brief for {agent_name}/{task_name}")

            # Weekly review gets the full summary
            if task_name == "weekly_review":
                weekly = er.get_weekly_summary()
                if weekly.get("total", 0) > 0:
                    task_prompt += f"""

=== EXCEPTION HANDLING SUMMARY (Last 7 Days) ===
Total: {weekly.get('total', 0)} | Auto-resolved: {weekly.get('auto_resolved', 0)} | Escalated: {weekly.get('escalated', 0)} | Still open: {weekly.get('still_open', 0)}
Analyse: Are we catching exceptions fast enough? What patterns repeat? What should be automated next?"""

            er.close()
            data_status["Exception Router"] = "OK"
        except Exception as e:
            logger.warning(f"Exception brief failed (non-fatal): {e}")
            data_status["Exception Router"] = f"FAILED: {e}"

    # 2e. Creative pipeline status for Meridian/PREP
    if task_name in ("morning_brief", "morning_briefing", "weekly_review") and agent_name in ("dbh-marketing", "strategic-advisor", "creative-projects"):
        try:
            from core.design_pipeline import DesignPipeline
            dp = DesignPipeline()
            pipeline_status = dp.format_for_briefing()
            if pipeline_status:
                task_prompt += f"""

{pipeline_status}

Review creative pipeline: flag overdue tasks, recommend which briefs should go to AI tools
vs Roie, and identify campaigns that need fresh creative based on performance data."""
                logger.info(f"Injected design pipeline status for {agent_name}/{task_name}")
                data_status["Design Pipeline"] = "OK"
            dp.close()
        except Exception as e:
            logger.warning(f"Design pipeline status failed (non-fatal): {e}")
            data_status["Design Pipeline"] = f"FAILED: {e}"

    # 2f. Thought leader insights for Oracle, PREP, and Venture
    if task_name in ("morning_briefing", "morning_brief", "weekly_review") and agent_name in ("daily-briefing", "strategic-advisor", "health-science"):
        try:
            from core.thought_leader_scraper import format_thought_leader_brief, get_improvement_suggestions
            tl_brief = format_thought_leader_brief()
            if tl_brief:
                task_prompt += f"""

{tl_brief}

Review these thought leader insights. Flag any that suggest improvements to our system or
business strategy. If an insight contradicts our current approach, note the tension."""
                logger.info(f"Injected thought leader brief for {agent_name}/{task_name}")

            # PREP gets improvement suggestions too
            if agent_name == "strategic-advisor":
                suggestions = get_improvement_suggestions()
                if suggestions:
                    task_prompt += f"""

=== SYSTEM IMPROVEMENT SUGGESTIONS (from thought leader analysis) ===
{suggestions}

Evaluate these suggestions against our current architecture. Which are worth implementing?
Which are we already doing? Include the top 1-2 actionable ones in your briefing."""
            data_status["Thought Leader Insights"] = "OK"
        except Exception as e:
            logger.warning(f"Thought leader brief failed (non-fatal): {e}")
            data_status["Thought Leader Insights"] = f"FAILED: {e}"

    # 2g. Clinical evidence micro-learning for Meridian (daily product knowledge)
    if task_name in ("morning_brief", "morning_briefing") and agent_name in ("dbh-marketing", "daily-briefing"):
        try:
            clinical_file = AGENTS_DIR / "dbh-marketing" / "training" / "clinical-evidence.md"
            if clinical_file.exists():
                content = clinical_file.read_text(encoding='utf-8')

                # Parse all evidence entries (### prefixed)
                import re
                entries = re.split(r'\n### ', content)
                entries = [e.strip() for e in entries if e.strip() and '**Source:**' in e]

                if entries:
                    # Determine focus product from active campaigns
                    focus_product = None
                    try:
                        import json as _json
                        config_path = BASE_DIR / "config" / "dbh-campaigns.json"
                        if config_path.exists():
                            camp_config = _json.loads(config_path.read_text(encoding='utf-8'))
                            for camp in camp_config.get("campaigns", []):
                                if camp.get("status") == "active":
                                    prods = camp.get("products", [])
                                    if prods:
                                        focus_product = prods[0]
                                    break
                    except Exception:
                        pass

                    # Map focus product to evidence prefix
                    product_prefixes = {
                        "Pure Pets GLM": "GLM-", "Pure Pets Bi-Active": "GLM-",
                        "Marine Collagen": "MC-", "Colostrum": "CO-",
                        "Deer Velvet": "DV-", "Sea Cucumber": "SC-",
                        "Shark Squalene": "SK-", "Shark Cartilage": "SK-",
                        "Oyster": "OY-", "KUKU Mussel Oil": "KM-",
                        "Joint Care Ultra": "JCU-",
                    }

                    # Filter to focus product entries, or all if no focus
                    prefix = None
                    if focus_product:
                        for key, pfx in product_prefixes.items():
                            if key.lower() in focus_product.lower():
                                prefix = pfx
                                break

                    if prefix:
                        relevant = [e for e in entries if prefix in e[:20]]
                        if not relevant:
                            relevant = entries
                    else:
                        relevant = entries

                    # Daily rotation: pick entry based on day of year
                    from datetime import date as _date
                    day_index = datetime.now(NZ_TZ).date().timetuple().tm_yday % len(relevant)
                    todays_evidence = relevant[day_index]

                    # Clean up the entry text
                    if not todays_evidence.startswith("###"):
                        todays_evidence = "### " + todays_evidence

                    product_label = focus_product or "Deep Blue Health range"
                    task_prompt += f"""

=== CLINICAL EVIDENCE OF THE DAY ===
Focus product: {product_label}

{todays_evidence}

INSTRUCTIONS: Include this clinical evidence in your morning brief under a
"Clinical Knowledge" section. Present the key finding, the source study,
and the sales angle. Tom is building deep product knowledge over time —
each day he learns one new clinical fact that makes him more credible
when selling. Keep it punchy — 3-4 lines max in the brief."""
                    logger.info(f"Injected clinical evidence for {product_label} (day {day_index})")
                    data_status["Clinical Evidence"] = f"OK ({product_label})"
        except Exception as e:
            logger.warning(f"Clinical evidence injection failed (non-fatal): {e}")
            data_status["Clinical Evidence"] = f"FAILED: {e}"

    # 2h. Asclepius ↔ Titan cross-context injection (brain + body integration)
    if agent_name in ("asclepius-brain", "health-fitness"):
        try:
            partner = "health-fitness" if agent_name == "asclepius-brain" else "asclepius-brain"
            partner_display = "Titan (Health & Fitness)" if partner == "health-fitness" else "Asclepius (Brain Health)"
            partner_state = AGENTS_DIR / partner / "state" / "CONTEXT.md"
            if partner_state.exists():
                partner_context = partner_state.read_text(encoding='utf-8')
                # Also grab partner's yesterday session log for recent insights
                yesterday_str = (datetime.now(NZ_TZ).date() - timedelta(days=1)).isoformat()
                partner_session = AGENTS_DIR / partner / "state" / f"session-log-{yesterday_str}.md"
                partner_log = ""
                if partner_session.exists():
                    try:
                        log_text = partner_session.read_text(encoding='utf-8')
                        partner_log = log_text[-1500:] if len(log_text) > 1500 else log_text
                    except Exception:
                        pass

                task_prompt += f"""

=== {partner_display.upper()} — PARTNER AGENT STATE ===
{partner_context}
"""
                if partner_log:
                    task_prompt += f"""
--- {partner_display} Yesterday's Session ---
{partner_log}
"""

                if agent_name == "asclepius-brain":
                    task_prompt += """
INTEGRATION INSTRUCTIONS: Titan's state above shows Tom's current training,
nutrition, sleep, and physical recovery data. Interpret this through your brain
health lens. If training intensity/sleep/nutrition patterns have brain health
implications, flag them. Emit [EVENT: brain.training_adjustment|IMPORTANT|description]
if Titan should adjust anything for brain recovery."""
                else:
                    task_prompt += """
INTEGRATION INSTRUCTIONS: Asclepius's state above shows Tom's cognitive metrics,
mood tracking, and brain recovery phase. Factor this into today's training plan.
If cognitive fatigue or poor sleep is flagged, adjust training intensity accordingly.
Brain health > gains when recovery is compromised."""

                logger.info(f"Injected {partner_display} state into {agent_name} ({len(partner_context)} chars)")
                data_status[f"Partner Agent ({partner_display})"] = "OK"
        except Exception as e:
            logger.warning(f"Cross-agent context injection failed (non-fatal): {e}")
            data_status[f"Partner Agent Context"] = f"FAILED: {e}"

    # 3. Asana task data for briefings
    asana_tasks = ("morning_briefing", "morning_brief")
    if task_name in asana_tasks:
        try:
            from core.asana_client import AsanaClient
            asana = AsanaClient()
            if asana.available:
                task_summary = asana.format_task_summary()
                task_prompt += f"""

{task_summary}

Include task status in the briefing. Flag overdue tasks as urgent. List today's planned tasks."""
                logger.info(f"Injected Asana data for {agent_name}/{task_name}")
                data_status["Asana Tasks"] = "OK"
            else:
                data_status["Asana Tasks"] = "Not configured (set ASANA_ACCESS_TOKEN)"
        except Exception as e:
            logger.warning(f"Asana fetch failed (non-fatal): {e}")
            data_status["Asana Tasks"] = f"FAILED: {e}"

    # 4. Slack activity for briefings
    if task_name in asana_tasks:
        try:
            from core.slack_client import SlackClient
            slack = SlackClient()
            if slack.available:
                slack_summary = slack.format_briefing_summary()
                task_prompt += f"""

{slack_summary}

Include Slack activity in the briefing. Flag any task completions detected.
If someone posted that something is 'done' or 'shipped', note it."""
                logger.info(f"Injected Slack data for {agent_name}/{task_name}")
                data_status["Slack Activity"] = "OK"
            else:
                data_status["Slack Activity"] = "Not configured"
        except Exception as e:
            logger.warning(f"Slack fetch failed (non-fatal): {e}")
            data_status["Slack Activity"] = f"FAILED: {e}"

    # 5. Cross-agent state for Oracle and PREP briefings
    if agent_name in ("daily-briefing", "strategic-advisor") and task_name in ("morning_briefing", "weekly_review"):
        try:
            agent_states = []
            for other_agent in ("global-events", "dbh-marketing", "health-science",
                                "health-fitness", "social", "creative-projects"):
                state_file = AGENTS_DIR / other_agent / "state" / "CONTEXT.md"
                if state_file.exists():
                    content = state_file.read_text(encoding='utf-8')
                    agent_states.append(f"--- {other_agent} STATE ---\n{content}")
            if agent_states:
                if agent_name == "strategic-advisor":
                    task_prompt += f"""

=== ALL AGENT STATES (you see the full picture across every domain) ===
{chr(10).join(agent_states)}

Synthesise everything above into your strategic briefing. Connect the dots.
Your briefing should cover: financial position, DBH performance, macro events
that affect the business, personal health/social status, and the top 3
strategic priorities for today. Challenge anything that needs challenging.
Flag any automation opportunities you spot.

=== SYSTEM CAPABILITIES (for your awareness) ===
Active systems you have data from:
- 9 agents (Atlas, Meridian, Venture, Titan, Compass, Lens, Oracle, Nexus, PREP)
- 16 scheduled tasks (daily + weekly, see all agent states above)
- Customer Intelligence DB: auto-accumulates nightly, per-order attribution
- Replenishment Tracker: fires Klaviyo reorder events at 10pm daily
- Cross-Agent Event Bus: agents trigger each other via [EVENT:] markers
- Decision Logger: tracks reasoning chains, detects contradictions
- Exception Router: auto-resolves (low stock, ROAS drops, churn, etc.)
- Design Pipeline: brief -> design (Roie or AI tools) -> deployment
- Thought Leader Scraper: scrapes 10 AI leaders daily, extracts insights
- Xero: P&L, balance sheet, invoices (data injected above if available)
- Wise: Multi-currency balances, FX rates, transfers (data injected above if available)
- Write-back clients BUILT but not yet autonomous: Shopify, Klaviyo, Meta Ads, Asana, Xero

In your briefing, reference which systems are providing the data you cite.
If a data source is missing, flag it (e.g. "Xero data unavailable -- cannot confirm P&L").
Recommend which waiting systems should be wired next based on current priorities."""
                else:
                    task_prompt += f"""

=== ALL AGENT STATES (read these to build your cross-domain briefing) ===
{chr(10).join(agent_states)}

Synthesise the above into your unified briefing. Find cross-domain connections.
The daily plan should reference the 90-day execution map from Meridian's intelligence."""
                logger.info(f"Injected {len(agent_states)} agent states for {agent_name} briefing")
                data_status["Cross-Agent States"] = f"OK ({len(agent_states)} agents)"
        except Exception as e:
            logger.warning(f"Agent state loading failed (non-fatal): {e}")
            data_status["Cross-Agent States"] = f"FAILED: {e}"

    # Inject pending cross-agent events
    pending_events = get_pending_events_for_agent(agent_name)
    if pending_events:
        task_prompt += f"\n\n{pending_events}"
        logger.info(f"Injected cross-agent events for {agent_name}")

    # Append data availability summary so Claude knows what it has vs doesn't
    if data_status:
        status_lines = ["\n\n=== DATA AVAILABILITY REPORT ==="]
        for source, status in data_status.items():
            icon = "OK" if status == "OK" or status.startswith("OK") else "MISSING"
            status_lines.append(f"  [{icon}] {source}: {status}")
        status_lines.append("\nFor any data marked MISSING or FAILED: say 'not connected yet' rather than")
        status_lines.append("'unavailable'. This helps Tom know what to wire up next.")
        task_prompt += "\n".join(status_lines)

    # CRITICAL: Move all injected data from user message into system prompt.
    # Claude pays far more attention to the system prompt. With 40K tokens of
    # playbooks in the system prompt and data only in the user message, Claude
    # was ignoring the injected data and hallucinating "not connected".
    # Fix: append the data block to the brain (system prompt) and keep the
    # task instruction clean in the user message.
    data_block_marker = "=== LIVE PERFORMANCE DATA"
    if data_block_marker in task_prompt:
        # Split: everything from the first data header onwards goes to brain
        marker_pos = task_prompt.index(data_block_marker)
        data_block = task_prompt[marker_pos:]
        task_instruction = task_prompt[:marker_pos].rstrip()

        brain += f"\n\n{'='*60}\nLIVE DATA — USE THESE NUMBERS IN YOUR RESPONSE\n{'='*60}\n\n{data_block}"
        task_prompt = task_instruction
        logger.info(f"Moved {len(data_block)} chars of live data into system prompt")

    # Send pre-flight data summary to Telegram so Tom can verify what was fetched
    chat_id = telegram_config["chat_ids"].get(agent_name)
    bot_token = telegram_config["bot_token"]
    if data_status and chat_id and chat_id != "CHAT_ID_HERE":
        ok_count = sum(1 for s in data_status.values() if s == "OK" or s.startswith("OK"))
        total = len(data_status)
        if ok_count > 0:
            summary_parts = []
            for source, status in data_status.items():
                icon = "✅" if status == "OK" or status.startswith("OK") else "❌"
                summary_parts.append(f"{icon} {source}")
            data_summary = f"Data loaded ({ok_count}/{total}): " + " | ".join(summary_parts)
            from core.notification_router import route_notification
            route_notification(chat_id, data_summary, bot_token, severity="INFO", agent=agent_name)

    # Call Claude with full brain + task
    # PREP always uses Opus -- strategic thinking needs the best model
    # Beacon (content_generation) uses Opus for quality SEO content
    if agent_name == "strategic-advisor":
        effective_task_type = "deep_analysis"
    elif agent_name == "beacon" and task_name == "content_generation":
        effective_task_type = "deep_analysis"  # Opus for quality content
    elif agent_name == "prospector":
        effective_task_type = "deep_analysis"  # Opus for deep first-principles research
    else:
        effective_task_type = task_name
    logger.info(f"Calling Claude for {agent_name}/{task_name}: brain={len(brain)} chars, prompt={len(task_prompt)} chars")
    response = call_claude(brain, task_prompt, task_type=effective_task_type, agent_name=agent_name)

    # Check for API errors — don't send raw errors to Telegram
    if response and response.startswith("API Error:"):
        logger.error(f"Claude API failed for {agent_name}/{task_name}: {response}")
        chat_id = telegram_config.get("chat_ids", {}).get("command-center") or \
                  telegram_config.get("chat_ids", {}).get(agent_name)
        bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
        if chat_id and bot_token:
            agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
            from core.notification_router import route_notification
            route_notification(chat_id,
                f"{agent_display}/{task_name}: API call failed. Will retry next schedule.\n\nError: {response[11:200]}",
                bot_token, severity="IMPORTANT", agent="command-center")
        return

    # Extract and apply state updates BEFORE learning loop cleans the markers.
    # process_response_learning() strips [STATE UPDATE:] markers, so we must
    # persist them to CONTEXT.md first — otherwise scheduled tasks never update state.
    raw_response_for_state = response
    _, _sched_state_updates = _extract_state_updates(raw_response_for_state)
    for _state_info in _sched_state_updates:
        if _state_info:
            update_agent_state(agent_name, _state_info)
            logger.info(f"State update applied for {agent_name} (scheduled): {_state_info[:80]}")

    # Process through learning loop (extract insights, clean markers)
    response = process_response_learning(
        agent_name, response,
        trigger="scheduled",
        task=task_name,
        input_summary=task_prompt
    )

    # Brief generator: auto-generate design briefs when Meridian detects campaign opportunities
    # Triggers on [BRIEF: insight text] markers in agent responses
    if agent_name in ("dbh-marketing", "strategic-advisor"):
        try:
            import re as _brief_re
            brief_matches = _brief_re.findall(r'\[BRIEF:\s*(.*?)\]', response, _brief_re.DOTALL)
            if brief_matches:
                from core.brief_generator import BriefGenerator
                bg = BriefGenerator()
                for insight in brief_matches:
                    try:
                        brief_id, brief_md = bg.generate_brief_from_insight(
                            insight=insight.strip(),
                            assigned_to="Roie",
                            platforms=["meta_feed", "email_hero"]
                        )
                        logger.info(f"Auto-generated brief {brief_id} from {agent_name} insight")

                        # Create Asana task for Roie
                        try:
                            from core.asana_writer import AsanaWriter
                            aw = AsanaWriter()
                            if aw.available:
                                aw.create_task(
                                    name=f"Design Brief: {insight.strip()[:80]}",
                                    notes=f"Auto-generated from {AGENT_DISPLAY.get(agent_name, agent_name)} intelligence.\n\nBrief ID: {brief_id}\nReview the full brief in briefs.db or run: python brief_generator.py view {brief_id}",
                                    assignee="Roie",
                                    due_on=(datetime.now(NZ_TZ) + timedelta(days=14)).strftime("%Y-%m-%d")
                                )
                        except Exception as asana_e:
                            logger.warning(f"Asana task for brief failed (non-fatal): {asana_e}")

                        # Notify on command-center
                        nexus_chat = telegram_config.get("chat_ids", {}).get("command-center", "")
                        if nexus_chat:
                            from core.notification_router import route_notification
                            route_notification(nexus_chat,
                                               f"Design Brief Auto-Generated\n\nBrief: {brief_id}\nInsight: {insight.strip()[:200]}\nAssigned: Roie\nDeadline: 14 days\n\nReview: python brief_generator.py view {brief_id}",
                                               bot_token, severity="NOTABLE", agent=agent_name)
                    except Exception as brief_e:
                        logger.warning(f"Brief generation failed for insight: {brief_e}")
                bg.close()
                # Clean markers from response before sending to Telegram
                response = _brief_re.sub(r'\[BRIEF:\s*.*?\]', '', response, flags=_brief_re.DOTALL).strip()
        except Exception as bg_e:
            logger.warning(f"Brief generator integration failed (non-fatal): {bg_e}")

    # Order manager: handle [ORDER:] markers from recovery companions
    if agent_name in CHAT_USER_MAP and "[ORDER:" in response:
        try:
            import re as _order_re
            order_matches = _order_re.findall(r'\[ORDER:\s*(.*?)\]', response, _order_re.DOTALL)
            if order_matches:
                from core.order_manager import create_order, get_stack_for_companion, format_order_for_notification, COMPANION_STACKS
                user_id = CHAT_USER_MAP.get(agent_name, "unknown")

                for order_text in order_matches:
                    # Parse: could be "stack" (full phase stack) or "product1,product2,..."
                    order_text = order_text.strip()
                    if "stack" in order_text.lower() or "phase" in order_text.lower():
                        # Order the full phase stack
                        # Extract phase number if present
                        phase_match = _order_re.search(r'phase[_\s]*(\d+)', order_text, _order_re.IGNORECASE)
                        phase = int(phase_match.group(1)) if phase_match else 1
                        stacks = COMPANION_STACKS.get(agent_name, {})
                        stack_key = f"phase_{phase}"
                        stack_products = stacks.get(stack_key, stacks.get("phase_1", {})).get("products", [])
                        order = create_order(user_id, agent_name, stack_products)
                    else:
                        # Individual products
                        product_ids = [p.strip() for p in order_text.split(",") if p.strip()]
                        order = create_order(user_id, agent_name, product_ids)

                    if "error" not in order:
                        # Notify Tom in command-center
                        cc_chat = telegram_config.get("chat_ids", {}).get("command-center", "")
                        if cc_chat:
                            from core.notification_router import route_notification
                            route_notification(cc_chat, format_order_for_notification(order),
                                               bot_token, severity="IMPORTANT", agent=agent_name)
                        logger.info(f"Order created: {order['order_id']} for {user_id} — ${order['total']:.2f}")

                # Clean markers from response
                response = _order_re.sub(r'\[ORDER:\s*.*?\]', '', response, flags=_order_re.DOTALL).strip()
        except Exception as order_e:
            logger.warning(f"Order processing failed (non-fatal): {order_e}")

    # Beacon post-processing: save article + create Shopify draft
    if agent_name == "beacon" and task_name == "content_generation":
        try:
            import re as _re

            today_str = datetime.now(NZ_TZ).date().isoformat()
            # Extract title from response (look for # heading or **Title**)
            title_match = _re.search(r'(?:^#\s+(.+)|Title[:\s]*\*?\*?(.+?)\*?\*?$)', response, _re.MULTILINE)
            title = (title_match.group(1) or title_match.group(2)).strip() if title_match else f"Article {today_str}"
            slug = _re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60]

            # Save to file
            from pathlib import Path as _P
            article_dir = _P.home() / "dbh-aios" / "reports" / "seo-articles"
            article_dir.mkdir(parents=True, exist_ok=True)
            article_path = article_dir / f"{today_str}-{slug}.md"
            article_path.write_text(response, encoding='utf-8')
            logger.info(f"Beacon article saved: {article_path}")

            # Create Shopify blog draft
            try:
                from core.shopify_blog_publisher import ShopifyBlogPublisher
                publisher = ShopifyBlogPublisher()
                if publisher.available:
                    blog_id = publisher.get_default_blog_id()
                    if blog_id:
                        # Extract body HTML if present, otherwise use full response
                        body_match = _re.search(r'<article[^>]*>(.*?)</article>|<div[^>]*class="article[^"]*"[^>]*>(.*?)</div>', response, _re.DOTALL)
                        body_html = (body_match.group(1) or body_match.group(2)) if body_match else response
                        publisher.create_draft_article(blog_id, title, body_html)
                        logger.info(f"Shopify blog draft created: {title}")
            except Exception as pub_e:
                logger.warning(f"Shopify blog draft creation failed (non-fatal): {pub_e}")

        except Exception as beacon_e:
            logger.warning(f"Beacon post-processing failed (non-fatal): {beacon_e}")

    # --- Constraint check for companion agents (pre-send gate) ---
    # Catches constraint violations (wrong food, wrong exercises, broken device questions)
    # BEFORE they reach the user. Blocks scheduled tasks; alerts Tom for user replies.
    if agent_name in CHAT_USER_MAP:
        try:
            from core.constraint_checker import check_response
            check = check_response(agent_name, response)
            if not check.get("passed"):
                violation = check.get("violation", "unknown")
                violation_type = check.get("type", "constraint")
                cc_chat = telegram_config.get("chat_ids", {}).get("command-center", "")
                agent_display = AGENT_DISPLAY.get(agent_name, agent_name)

                if violation_type == "schedule":
                    # Schedule mismatches: ALERT but DON'T BLOCK
                    # Users swap training days — the plan may be outdated
                    logger.warning(f"SCHEDULE MISMATCH {agent_name}/{task_name}: {violation}")
                    if cc_chat:
                        from core.notification_router import route_notification
                        route_notification(cc_chat,
                            f"SCHEDULE MISMATCH: {agent_display}/{task_name}\n\nNote: {violation}\n\nResponse was still sent — user may have swapped days. Check if CURRENT_PLAN.md needs updating.",
                            bot_token, severity="INFO", agent="command-center")
                    # Don't return — let the message through
                else:
                    # Constraint violations: BLOCK
                    logger.warning(f"CONSTRAINT VIOLATION {agent_name}/{task_name}: {violation}")
                    if cc_chat:
                        from core.notification_router import route_notification
                        route_notification(cc_chat,
                            f"BLOCKED: {agent_display}/{task_name}\n\nViolation: {violation}\n\nResponse was not sent to user. Will retry next schedule.",
                            bot_token, severity="IMPORTANT", agent="command-center")
                    return  # Do NOT send the response
        except Exception as cc_e:
            logger.warning(f"Constraint check failed (non-fatal, sending anyway): {cc_e}")

    # Send to Telegram
    # Beacon uses command-center channel (no dedicated channel)
    send_chat_id = chat_id

    # Recovery companions: notify Tom's command-center that check-ins were sent (quiet, no content)
    if agent_name in CHAT_USER_MAP and task_name in ("morning_checkin", "midday_checkin", "evening_checkin"):
        cc_chat = telegram_config.get("chat_ids", {}).get("command-center", "")
        if cc_chat:
            checkin_labels = {"morning_checkin": "Morning", "midday_checkin": "Midday", "evening_checkin": "Evening"}
            agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
            user_display = CHAT_USER_MAP.get(agent_name, "user").capitalize()
            from core.notification_router import route_notification
            route_notification(cc_chat,
                               f"{agent_display} {checkin_labels.get(task_name, task_name)} check-in sent to {user_display}.",
                               bot_token, severity="INFO", agent=agent_name)

    if agent_name == "beacon":
        send_chat_id = telegram_config.get("chat_ids", {}).get("command-center", chat_id)
        # Beacon sends a brief notification, not the full article
        if send_chat_id and send_chat_id != "CHAT_ID_HERE":
            from core.notification_router import route_notification
            route_notification(send_chat_id,
                               f"Beacon: article generated and saved.\nReview drafts in Shopify admin.",
                               bot_token, severity="INFO", agent="beacon")
    elif send_chat_id and send_chat_id != "CHAT_ID_HERE":
        from core.notification_router import route_notification
        # Morning/weekly briefings are IMPORTANT, scans are NOTABLE, other tasks INFO
        _sched_severity = "NOTABLE" if task_name in ("scan", "model_scan", "health_check") else "IMPORTANT"
        route_notification(send_chat_id, response, bot_token, severity=_sched_severity, agent=agent_name)
        # Send voice message for agents that have voice enabled
        if agent_name in VOICE_AGENTS:
            try:
                send_telegram_voice(send_chat_id, response, bot_token, voice_id=VOICE_AGENTS[agent_name])
            except Exception as _ve:
                logger.warning(f"Voice message failed for {agent_name} (non-fatal): {_ve}")
    else:
        logger.warning(f"No chat ID configured for {agent_name}, printing to console:")
        print(f"\n{'='*60}")
        print(f"[{agent_name}] {task_name}")
        print(f"{'='*60}")
        print(response)

    # --- Write THIS-WEEK.md after Meridian or PREP weekly review ---
    # The agent produces this week's priorities in its response.
    # We extract the [THIS-WEEK: ...] block if present and write it to the shared strategy file.
    # If no block present, append a header so the file always gets refreshed.
    if task_name == "weekly_review" and agent_name in ("dbh-marketing", "strategic-advisor"):
        try:
            this_week_path = AGENTS_DIR / "shared" / "strategy" / "THIS-WEEK.md"
            # Check for explicit [THIS-WEEK: ... ] block in response
            tw_match = re.search(r'\[THIS-WEEK:(.*?)\]', response, re.DOTALL)
            if tw_match:
                tw_content = tw_match.group(1).strip()
            else:
                # Use the full response as the THIS-WEEK content (it IS the weekly review)
                tw_content = response.strip()
            week_str = datetime.now(NZ_TZ).strftime("%B %d, %Y")
            header = f"# THIS WEEK — Execution Priorities\n## Week from {week_str}\n**Written by:** {AGENT_DISPLAY.get(agent_name, agent_name)} weekly review\n\n---\n\n"
            this_week_path.write_text(header + tw_content, encoding="utf-8")
            logger.info(f"THIS-WEEK.md updated from {agent_name}/weekly_review")
        except Exception as e:
            logger.warning(f"THIS-WEEK.md write failed (non-fatal): {e}")

    # --- Memory extraction for scheduled tasks (companions + all agents) ---
    # Without this, scheduled check-in content (insights, patterns) is lost.
    # SKIP for weekly_progress_report — it's a Tom-facing summary, not user content.
    # Extracting from it would store Tom-context facts under the companion user's ID.
    if task_name == "weekly_progress_report":
        logger.info(f"Skipping memory extraction for {agent_name}/weekly_progress_report (Tom-facing report)")
    else:
        try:
            sched_user_id_mem = CHAT_USER_MAP.get(agent_name, str(telegram_config.get("owner_user_id", os.environ.get("TELEGRAM_OWNER_ID", "default"))))
            extraction_conv = [
                {"role": "user", "content": task_prompt},
                {"role": "assistant", "content": response}
            ]
            if agent_name in CHAT_USER_MAP:
                from core.asmr_memory import asmr_extract
                asmr_extract(sched_user_id_mem, agent_name, extraction_conv, AGENT_DISPLAY.get(agent_name, agent_name))
                logger.info(f"ASMR memory extracted for {agent_name}/{task_name}")
            else:
                from core.user_memory import extract_and_store_memories
                extract_and_store_memories(sched_user_id_mem, agent_name, extraction_conv, AGENT_DISPLAY.get(agent_name, agent_name))
        except Exception as mem_e:
            logger.warning(f"Scheduled task memory extraction failed (non-fatal): {mem_e}")

    # --- Auto-evolve for companion agents after scheduled tasks ---
    # When a scheduled check-in contains self-corrections (e.g., "sourdough is out",
    # "actually your plan says X not Y"), those corrections must be persisted to
    # CURRENT_PLAN.md. Without this, the next scheduled task loads the uncorrected plan
    # and repeats the same error.
    if agent_name in CHAT_USER_MAP and task_name != "weekly_progress_report":
        try:
            _auto_evolve_plan(agent_name, task_prompt, response, source="scheduled")
        except Exception as ae_e:
            logger.warning(f"Auto-evolution (scheduled) failed (non-fatal): {ae_e}")

    logger.info(f"Completed: {agent_name}/{task_name}")


# --- Message Handler (for two-way chat) ---

def _auto_evolve_plan(agent_name: str, user_message: str, agent_response: str, source: str = "conversation"):
    """
    Auto-evolution for companion agents (Forge, Aether, etc.).
    After every conversation OR scheduled task, uses Haiku to detect if the plan changed.
    If plan-changing content detected, rewrites CURRENT_PLAN.md automatically.

    Sources:
    - "conversation" (default): User message + agent response (two-way chat)
    - "scheduled": Agent-only output from a scheduled task (no user message)

    Cost: ~$0.002 per call (Haiku detection), ~$0.01 if rewrite triggered.
    """
    plan_file = AGENTS_DIR / agent_name / "state" / "CURRENT_PLAN.md"
    if not plan_file.exists():
        return  # No CURRENT_PLAN.md = nothing to evolve

    current_plan = plan_file.read_text(encoding='utf-8')

    # Build context based on source type
    if source == "scheduled":
        conversation_block = f"Agent (scheduled check-in): {agent_response[:3000]}"
    else:
        conversation_block = f"User: {user_message[:1500]}\nAgent: {agent_response[:2000]}"

    # Step 1: Haiku detects if the conversation changed the plan
    detect_prompt = f"""Analyse this exchange from a companion agent system.
Determine if the user's active plan has changed OR if the agent made a correction.

Plan changes include:
- Meal plan modifications (new foods, removed foods, different portions)
- Training schedule changes (different split, rest days, exercises)
- Supplement changes (added, removed, dosage changed)
- New constraints (food elimination, equipment broken, injury, schedule change)
- Removed constraints (got new equipment, reintroduced a food, healed)
- Phase transition (moving to next recovery phase)
- Goal changes (new targets, shifted priorities)

ALSO detect AGENT SELF-CORRECTIONS — cases where the agent corrects itself mid-response:
- "Actually, I was wrong about X — the correct thing is Y"
- "I shouldn't have suggested X because [constraint]"
- "Correction: X is not in your plan, Y is"
- Any statement where the agent acknowledges a previous error and states the correct info
These self-corrections MUST be persisted to the plan to prevent the error from recurring.

{conversation_block}

CURRENT PLAN:
{current_plan[:6000]}

Respond with EXACTLY one of:
- NO_CHANGE — if the exchange is a normal check-in with no plan modifications or corrections
- PLAN_CHANGED: <brief description of what changed> — if any aspect of the plan should be updated

Be conservative. Routine check-ins (how did you sleep, what did you eat) are NOT plan changes.
Only flag actual modifications to what the user is doing going forward, OR agent self-corrections that fix errors."""

    try:
        import anthropic
        _evolve_client = anthropic.Anthropic()
        _HAIKU = "claude-haiku-4-5-20251001"

        # Step 1: Haiku detection (~$0.001)
        detect_result = _evolve_client.messages.create(
            model=_HAIKU,
            max_tokens=200,
            messages=[{"role": "user", "content": detect_prompt}],
            system="You are a plan change detector. Respond only with NO_CHANGE or PLAN_CHANGED: <description>.",
            timeout=30.0,
        )
        detect_response = detect_result.content[0].text.strip()

        if not detect_response or "PLAN_CHANGED" not in detect_response:
            logger.info(f"Auto-evolve {agent_name}: no plan change detected")
            return

        change_description = detect_response.replace("PLAN_CHANGED:", "").strip()
        logger.info(f"Auto-evolve {agent_name}: PLAN CHANGE DETECTED — {change_description[:100]}")

        # Step 2: Haiku rewrite (~$0.003)
        rewrite_prompt = f"""You are maintaining a user's CURRENT_PLAN.md file. A plan change was detected:

CHANGE: {change_description}

CONVERSATION THAT TRIGGERED THE CHANGE:
User: {user_message[:2000]}
Agent: {agent_response[:2000]}

CURRENT PLAN (full):
{current_plan}

YOUR TASK: Output the COMPLETE updated CURRENT_PLAN.md file with the change applied.
Rules:
- Keep the exact same structure and sections
- Update the "Last Updated" date to today
- Apply the specific change to the relevant section(s)
- Keep all other sections unchanged
- If a constraint was added, add it to ACTIVE CONSTRAINTS
- If a constraint was removed, remove it from ACTIVE CONSTRAINTS
- If meals changed, update the CURRENT MEAL PLAN section
- If training changed, update the CURRENT TRAINING SPLIT section
- If supplements changed, update the CURRENT SUPPLEMENT STACK section
- Add a new entry at the top of "WHAT'S NOT WORKING / NEEDS ADJUSTMENT" if relevant

Output ONLY the complete file content, no explanation."""

        rewrite_result = _evolve_client.messages.create(
            model=_HAIKU,
            max_tokens=8000,
            messages=[{"role": "user", "content": rewrite_prompt}],
            system="You maintain a user's plan file. Output only the complete updated file.",
            timeout=60.0,
        )
        rewrite_response = rewrite_result.content[0].text.strip()

        if rewrite_response and len(rewrite_response) > 200 and "CURRENT_PLAN" in rewrite_response:
            # Sanity check: new plan should have key sections
            required_sections = ["ACTIVE CONSTRAINTS", "CURRENT MEAL PLAN", "CURRENT TRAINING SPLIT"]
            if all(section in rewrite_response for section in required_sections):
                plan_file.write_text(rewrite_response, encoding='utf-8')
                logger.info(f"Auto-evolve {agent_name}: CURRENT_PLAN.md rewritten ({len(rewrite_response)} chars)")

                # Also update CONTEXT.md LIVE UPDATES with the change
                timestamp = datetime.now(NZ_TZ).strftime("%B %d")
                update_agent_state(agent_name, f"CURRENT_PLAN.md auto-updated: {change_description[:100]}")
            else:
                logger.warning(f"Auto-evolve {agent_name}: rewrite missing required sections, skipping")
        else:
            logger.warning(f"Auto-evolve {agent_name}: rewrite response too short or invalid, skipping")

    except Exception as e:
        logger.warning(f"Auto-evolve {agent_name}: failed (non-fatal): {e}")


def _extract_state_updates(response: str) -> tuple:
    """
    Extract all [STATE UPDATE: ...] markers from a response.
    Returns (clean_response, list_of_state_updates).
    Handles multiple markers and nested brackets properly.
    """
    import re
    state_updates = []
    # Match [STATE UPDATE: ...] -- non-greedy, handles most cases
    pattern = r'\[STATE UPDATE:\s*(.*?)\]'
    matches = re.findall(pattern, response, re.DOTALL)
    for m in matches:
        state_updates.append(m.strip())
    clean = re.sub(pattern, '', response, flags=re.DOTALL).strip()
    return clean, state_updates


def _inject_prep_context(brain: str) -> str:
    """Inject all agent states + performance data + financial data for PREP.
    Returns the augmented brain. All fetches are individually wrapped."""

    # 1. Agent states
    logger.info("PREP inject: loading agent states...")
    agent_states = []
    for other_agent in ("global-events", "dbh-marketing", "health-science",
                        "health-fitness", "social", "creative-projects", "daily-briefing"):
        state_file = AGENTS_DIR / other_agent / "state" / "CONTEXT.md"
        if state_file.exists():
            try:
                content = state_file.read_text(encoding='utf-8')
                agent_states.append(f"--- {other_agent} STATE ---\n{content}")
            except Exception:
                pass
    if agent_states:
        brain += f"\n\n=== ALL AGENT STATES (you see the full picture) ===\n" + "\n\n".join(agent_states)
    logger.info(f"PREP inject: {len(agent_states)} agent states loaded")

    # 2. Live performance data — from dashboard pipeline (single source of truth)
    logger.info("PREP inject: fetching dashboard data brief...")
    try:
        from core.data_brief import build_data_brief
        perf = build_data_brief()
        brain += f"\n\n=== LIVE BUSINESS DATA (from dashboard pipeline) ===\n{perf}"
        logger.info(f"PREP inject: dashboard data brief OK ({len(perf)} chars)")
    except Exception as e:
        logger.warning(f"PREP inject: dashboard data brief FAILED, trying fallback: {e}")
        try:
            from core.data_fetcher import fetch_all_performance_data
            perf = fetch_all_performance_data()
            brain += f"\n\n=== LIVE PERFORMANCE DATA (fallback) ===\n{perf}"
            logger.info(f"PREP inject: fallback performance data OK ({len(perf)} chars)")
        except Exception as e2:
            logger.warning(f"PREP inject: performance data FAILED (non-fatal): {e2}")

    # 3. Xero financial data
    logger.info("PREP inject: checking Xero...")
    try:
        from core.xero_client import XeroClient
        xero = XeroClient()
        if xero.available:
            fin_snapshot = xero.get_financial_health_snapshot()
            if fin_snapshot:
                brain += f"\n\n=== XERO FINANCIAL DATA ===\n{fin_snapshot}"
                logger.info(f"PREP inject: Xero data OK ({len(fin_snapshot)} chars)")
        else:
            logger.info("PREP inject: Xero not available (skipped)")
    except Exception as e:
        logger.warning(f"PREP inject: Xero FAILED (non-fatal): {e}")

    # 4. Wise multi-currency data
    logger.info("PREP inject: checking Wise...")
    try:
        from core.wise_client import WiseClient
        wise = WiseClient()
        if wise.available:
            wise_snapshot = wise.get_financial_snapshot()
            if wise_snapshot:
                brain += f"\n\n=== WISE BALANCES & FX ===\n{wise_snapshot}"
                logger.info(f"PREP inject: Wise data OK ({len(wise_snapshot)} chars)")
        else:
            logger.info("PREP inject: Wise not available (skipped)")
    except Exception as e:
        logger.warning(f"PREP inject: Wise FAILED (non-fatal): {e}")

    logger.info(f"PREP inject: COMPLETE. Total brain: ~{len(brain)//4} tokens")
    return brain


def handle_incoming_message(chat_id: str, message_text: str, telegram_config: dict):
    """
    Handle an incoming message from a user.
    1. Identify which agent based on chat ID
    2. Load that agent's full brain
    3. Call Claude with brain + Tom's message
    4. Run through learning loop
    5. Respond in the same chat

    CRITICAL: Entire handler is wrapped in try/except so Tom ALWAYS gets a reply,
    even if something fails internally. Silent failures = no response = bad.
    """
    agent_name = identify_agent_from_chat(chat_id, telegram_config)

    if not agent_name:
        logger.warning(f"Unknown chat ID: {chat_id}")
        return

    # Command Center special handling
    if agent_name == "command-center":
        handle_command(message_text, telegram_config)
        return

    # Walker Capital command handling (value BHP, /pipeline, /screen, BUY/WATCH/AVOID)
    if agent_name == "walker-capital":
        if _handle_walker_command(message_text, chat_id, telegram_config):
            return
        # Falls through to normal Vesper chat if not a recognised command

    # /memory command works in ANY agent chat — shows what that agent knows
    msg_lower = message_text.strip().lower()
    if msg_lower in ("/memory", "memory", "/what do you know about me"):
        try:
            user_id = CHAT_USER_MAP.get(agent_name, str(telegram_config.get("owner_user_id", os.environ.get("TELEGRAM_OWNER_ID", "default"))))
            from core.user_memory import format_memory_for_display
            memory_text = format_memory_for_display(user_id, agent_id=agent_name)
            send_telegram(chat_id, memory_text, telegram_config["bot_token"])
        except Exception as e:
            send_telegram(chat_id, f"Memory system error: {e}", telegram_config["bot_token"])
        return

    logger.info(f"Message to {agent_name}: {message_text[:50]}...")

    # Send "typing..." indicator so Tom knows the bot received the message.
    # Especially important for PREP which can take 2+ minutes (Opus + data injection).
    try:
        import requests as _typing_req
        _typing_req.post(
            f"https://api.telegram.org/bot{telegram_config['bot_token']}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )
    except Exception:
        pass  # Non-fatal — just a UX hint

    try:
        # Resolve user_id: most agents serve Tom, but some serve other users (e.g., Aether → Jackson)
        user_id = CHAT_USER_MAP.get(agent_name, str(telegram_config.get("owner_user_id", os.environ.get("TELEGRAM_OWNER_ID", "default"))))

        # Load full brain WITH user memory injected
        # For companions: pass user's message as context for ASMR active retrieval
        brain = load_agent_brain(agent_name, user_id=user_id, current_context=message_text)

        if not brain:
            from core.notification_router import route_notification
            route_notification(chat_id, f"[{agent_name}] Brain failed to load. Check AGENT.md exists.",
                               telegram_config["bot_token"], severity="CRITICAL", agent=agent_name)
            return

        # Load conversation history for multi-turn context (permanent storage)
        from core.user_memory import get_recent_messages as get_memory_messages, save_message as save_memory_message
        conv_history = get_memory_messages(user_id, agent_name, chat_id, max_messages=20, max_age_hours=72)
        # Save incoming message permanently
        save_memory_message(user_id, agent_name, chat_id, "user", message_text)

        # PREP (strategic-advisor) gets all agent states + data injected
        if agent_name == "strategic-advisor":
            logger.info("PREP: injecting cross-agent context...")
            brain = _inject_prep_context(brain)
            logger.info(f"PREP: brain size after injection: ~{len(brain)//4} tokens")
            task_type = "deep_analysis"  # Uses Opus
        else:
            task_type = "chat"

        # Asclepius ↔ Titan: inject partner agent state into chat context
        if agent_name in ("asclepius-brain", "health-fitness"):
            try:
                partner = "health-fitness" if agent_name == "asclepius-brain" else "asclepius-brain"
                partner_state_file = AGENTS_DIR / partner / "state" / "CONTEXT.md"
                if partner_state_file.exists():
                    partner_ctx = partner_state_file.read_text(encoding='utf-8')
                    partner_label = "Titan (Health & Fitness)" if partner == "health-fitness" else "Asclepius (Brain Health)"
                    brain += f"\n\n=== {partner_label.upper()} — PARTNER AGENT STATE ===\n{partner_ctx}"
                    logger.info(f"Chat: injected {partner_label} state into {agent_name}")
            except Exception as e:
                logger.warning(f"Chat cross-agent injection failed (non-fatal): {e}")

        # ASI (evening-reading): conversational by default, new reading only on explicit request
        if agent_name == "evening-reading":
            # Only trigger a NEW reading for very explicit requests
            new_reading_triggers = ["new reading", "next reading", "give me a reading",
                                    "tonight's reading", "new lesson", "next lesson",
                                    "teach me something new", "what should i learn today"]
            msg_lower = message_text.lower().strip()
            is_new_reading = any(t in msg_lower for t in new_reading_triggers)

            if is_new_reading:
                # Trigger a full knowledge-engine reading
                try:
                    from core.knowledge_engine import get_tonight_reading
                    reading = get_tonight_reading()
                    user_prompt = reading["prompt"]
                    logger.info(f"ASI on-demand reading: {reading['primary_concept']} (score: {reading['primary_score']})")
                    task_type = "deep_analysis"  # Use Opus for depth
                    response = call_claude(brain, user_prompt, task_type=task_type, conversation_history=conv_history, agent_name=agent_name)
                except Exception as e:
                    logger.error(f"Knowledge engine failed for on-demand reading: {e}")
                    is_new_reading = False

            if not is_new_reading:
                # Conversational mode -- discuss the last reading, go deeper, mentor chat
                # Load today's session log so ASI knows what was discussed
                recent_context = ""
                today_log = AGENTS_DIR / "evening-reading" / "state" / f"session-log-{datetime.now(NZ_TZ).date().isoformat()}.md"
                if today_log.exists():
                    try:
                        log_content = today_log.read_text(encoding='utf-8')
                        # Last 3000 chars covers the most recent reading + any follow-ups
                        recent_context = log_content[-3000:] if len(log_content) > 3000 else log_content
                    except Exception:
                        pass

                pending_events = get_pending_events_for_agent(agent_name)
                events_section = f"\n\n{pending_events}" if pending_events else ""
                recent_section = f"\n\n=== TONIGHT'S SESSION SO FAR ===\n{recent_context}" if recent_context else ""

                user_prompt = f"""Tom says: {message_text}
{events_section}{recent_section}

Respond as ASI, Tom's wise life mentor. You have your full context loaded above.

CRITICAL: Tom is replying to your most recent reading/lesson. He wants to DISCUSS it,
go deeper, ask questions, or share his thoughts. Do NOT deliver a new lesson unless
he explicitly asks for one. Instead:
- Engage with what he said
- Go deeper on the topic you were discussing
- Ask him probing questions back
- Connect his response to the broader lesson
- Challenge his thinking if appropriate

Be warm but profound. Use stories and analogies. Make non-linear connections.
This is a dialogue, not a lecture.

FORMATTING: Telegram. No tables. Bold with *single asterisks*. Short paragraphs.

After your response, emit [STATE UPDATE: <what to remember from this exchange>]."""
                task_type = "evening_reading"  # Use Opus for depth
                response = call_claude(brain, user_prompt, task_type=task_type, conversation_history=conv_history, agent_name=agent_name)
        else:
            # All other agents -- standard chat flow
            # Inject any pending cross-agent events
            pending_events = get_pending_events_for_agent(agent_name)
            events_section = f"\n\n{pending_events}" if pending_events else ""

            # Resolve display name: companions use their user's name, others default to Tom
            _user_display = CHAT_USER_MAP.get(agent_name, "tom").capitalize()

            # Inject current date/time so agents never get the time wrong
            _reply_now = datetime.now(NZ_TZ)
            _reply_date = _reply_now.strftime("%A, %B %d, %Y")
            _reply_time = _reply_now.strftime("%I:%M %p")
            _time_context = f"\nCURRENT DATE/TIME: {_reply_date}, {_reply_time} NZST. Always use this as the actual time — never guess."

            user_prompt = f"""{_user_display} says: {message_text}
{events_section}{_time_context}
Respond as your agent character. You have your full context loaded above.

FORMATTING: This goes to Telegram. NEVER use markdown tables. Use bullet points,
numbered lists, or "Label: Value" format instead. Bold with *single asterisks*.

IMPORTANT: After EVERY meaningful exchange, you MUST save key learnings.
At the end of your response, emit [STATE UPDATE: <what to remember>].
This is your ONLY long-term memory. If you don't save it, you forget it.
Save: decisions made, preferences learned, context shared, strategy shifts.
If you discover something another agent should know, emit:
[EVENT: event.type|SEVERITY|description or json payload]
If something needs to be done, emit:
[TASK: title|priority|description]
If you identify a campaign opportunity or creative need (Meridian/PREP only), emit:
[BRIEF: description of insight]"""

            response = call_claude(brain, user_prompt, task_type=task_type, conversation_history=conv_history, agent_name=agent_name)

        # Check for API errors before processing
        if response.startswith("API Error:"):
            logger.error(f"Claude API failed for {agent_name}: {response}")
            agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
            from core.notification_router import route_notification
            route_notification(chat_id,
                               f"{agent_display} is having trouble right now -- API returned an error. Try again in a moment.",
                               telegram_config["bot_token"], severity="IMPORTANT", agent=agent_name)
            return

        # Extract and save ALL state updates (handles multiple markers properly)
        clean_response, state_updates = _extract_state_updates(response)
        for state_info in state_updates:
            if state_info:
                update_agent_state(agent_name, state_info)

        # Process through learning loop
        clean_response = process_response_learning(
            agent_name, clean_response,
            trigger="message",
            input_summary=message_text
        )

        # Brief generator: auto-generate briefs from [BRIEF:] markers in chat responses
        if agent_name in ("dbh-marketing", "strategic-advisor"):
            try:
                import re as _brief_re
                brief_matches = _brief_re.findall(r'\[BRIEF:\s*(.*?)\]', clean_response, _brief_re.DOTALL)
                if brief_matches:
                    from core.brief_generator import BriefGenerator
                    bg = BriefGenerator()
                    for insight in brief_matches:
                        try:
                            brief_id, _ = bg.generate_brief_from_insight(insight=insight.strip(), assigned_to="Roie")
                            logger.info(f"Auto-generated brief {brief_id} from chat with {agent_name}")
                            nexus_chat = telegram_config.get("chat_ids", {}).get("command-center", "")
                            if nexus_chat:
                                from core.notification_router import route_notification
                                route_notification(nexus_chat,
                                                   f"Design Brief Auto-Generated\nBrief: {brief_id}\nInsight: {insight.strip()[:200]}",
                                                   telegram_config["bot_token"], severity="NOTABLE", agent=agent_name)
                        except Exception as brief_e:
                            logger.warning(f"Brief generation failed: {brief_e}")
                    bg.close()
                    clean_response = _brief_re.sub(r'\[BRIEF:\s*.*?\]', '', clean_response, flags=_brief_re.DOTALL).strip()
            except Exception as bg_e:
                logger.warning(f"Brief generator integration failed (non-fatal): {bg_e}")

        # Save agent response to permanent memory
        try:
            save_memory_message(user_id, agent_name, chat_id, "assistant", clean_response)
        except Exception as hist_e:
            logger.warning(f"Failed to save message to memory: {hist_e}")

        # --- Constraint check for companion agent replies (alert only, don't block) ---
        if agent_name in CHAT_USER_MAP:
            try:
                from core.constraint_checker import check_response as _check_reply
                _reply_check = _check_reply(agent_name, clean_response)
                if not _reply_check.get("passed"):
                    _violation = _reply_check.get("violation", "unknown")
                    logger.warning(f"CONSTRAINT VIOLATION {agent_name} (reply): {_violation}")
                    cc_chat = telegram_config.get("chat_ids", {}).get("command-center", "")
                    if cc_chat:
                        from core.notification_router import route_notification
                        route_notification(cc_chat,
                            f"CONSTRAINT VIOLATION in {agent_display} reply:\n\n{_violation}\n\nResponse was sent but may contain errors.",
                            telegram_config["bot_token"], severity="IMPORTANT", agent="command-center")
            except Exception as _cc_e:
                logger.warning(f"Constraint check failed (non-fatal): {_cc_e}")

        # Send response
        sent = send_telegram(chat_id, clean_response, telegram_config["bot_token"])
        if sent:
            logger.info(f"Response from {agent_name} delivered to {chat_id}")
            # Send voice message for agents that have voice enabled
            if agent_name in VOICE_AGENTS:
                try:
                    send_telegram_voice(chat_id, clean_response, telegram_config["bot_token"], voice_id=VOICE_AGENTS[agent_name])
                except Exception as _ve:
                    logger.warning(f"Voice message failed for {agent_name} (non-fatal): {_ve}")
        else:
            logger.error(f"FAILED to deliver {agent_name} response to {chat_id}")

        # AUTOMATIC MEMORY EXTRACTION — runs after every conversation
        # Companions use ASMR (3 parallel observer agents, ~$0.003)
        # Other agents use legacy Haiku extraction (~$0.001)
        try:
            agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
            extraction_conv = conv_history + [
                {"role": "user", "content": message_text},
                {"role": "assistant", "content": clean_response}
            ]
            if agent_name in CHAT_USER_MAP:
                from core.asmr_memory import asmr_extract
                asmr_extract(user_id, agent_name, extraction_conv, agent_display)
            else:
                from core.user_memory import extract_and_store_memories
                extract_and_store_memories(user_id, agent_name, extraction_conv, agent_display)
        except Exception as mem_e:
            logger.warning(f"Memory extraction failed (non-fatal): {mem_e}")

        # AUTO-EVOLUTION — Detect plan changes and auto-rewrite CURRENT_PLAN.md
        # Only runs for companion agents that have a CURRENT_PLAN.md
        try:
            if agent_name in CHAT_USER_MAP:
                _auto_evolve_plan(agent_name, message_text, clean_response)
        except Exception as ae_e:
            logger.warning(f"Auto-evolution failed (non-fatal): {ae_e}")

    except Exception as e:
        # CRITICAL: Never silently fail. Tom must ALWAYS get a response.
        logger.error(f"HANDLER CRASH for {agent_name}: {e}", exc_info=True)
        try:
            agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
            # Use send_telegram directly for crash errors -- must always reach Tom immediately
            send_telegram(chat_id,
                          f"{agent_display} encountered an internal error: {str(e)[:200]}\n\nPlease try again.",
                          telegram_config["bot_token"])
        except Exception:
            logger.error(f"Could not even send error message to {chat_id}")


def handle_photo_message(chat_id: str, photo_sizes: list, caption: str,
                         bot_token: str, telegram_config: dict):
    """
    Handle a photo sent to any agent.
    Downloads the image, sends it to Claude Vision with the agent's full brain,
    conversation history, and runs memory extraction afterward.
    Wrapped in try/except so the user ALWAYS gets a reply.
    """
    agent_name = identify_agent_from_chat(chat_id, telegram_config)
    if not agent_name:
        logger.warning(f"Photo from unknown chat ID: {chat_id}")
        return

    try:
        # Download the photo
        image_b64, media_type = download_telegram_photo(photo_sizes, bot_token)
        if not image_b64:
            from core.notification_router import route_notification
            route_notification(chat_id, "[Could not download photo]", bot_token, severity="IMPORTANT", agent=agent_name)
            return

        # Resolve user_id (companions serve different users)
        user_id = CHAT_USER_MAP.get(agent_name, str(telegram_config.get("owner_user_id", os.environ.get("TELEGRAM_OWNER_ID", "default"))))

        # Load agent brain WITH user memory injected
        caption_context = caption if caption else "photo analysis"
        brain = load_agent_brain(agent_name, user_id=user_id, current_context=caption_context)

        # PREP gets full context for photos too
        task_type = "chat"
        if agent_name == "strategic-advisor":
            brain = _inject_prep_context(brain)
            task_type = "deep_analysis"

        # Load conversation history for multi-turn context
        from core.user_memory import get_recent_messages as get_memory_messages, save_message as save_memory_message
        conv_history = get_memory_messages(user_id, agent_name, chat_id, max_messages=20, max_age_hours=72)

        # Save incoming photo message permanently
        photo_msg = f"[Photo] {caption}" if caption else "[Photo sent]"
        save_memory_message(user_id, agent_name, chat_id, "user", photo_msg)

        # Build caption prompt with correct user name
        _user_display = CHAT_USER_MAP.get(agent_name, "tom").capitalize()
        if caption:
            user_text = f"{_user_display} sent a photo with caption: {caption}\n\nFORMATTING: This goes to Telegram. NEVER use markdown tables. Use bullet points and Label: Value pairs.\n\nIMPORTANT: After analysing, emit [STATE UPDATE: <what to remember about this photo>]."
        else:
            user_text = f"{_user_display} sent a photo. Analyse it in the context of your role and expertise.\n\nFORMATTING: This goes to Telegram. NEVER use markdown tables.\n\nIMPORTANT: After analysing, emit [STATE UPDATE: <what to remember about this photo>]."

        # Call Claude with vision
        response = call_claude_vision(brain, image_b64, media_type, user_text, task_type=task_type)

        # Check for API errors
        if response.startswith("API Error:"):
            logger.error(f"Claude Vision API failed for {agent_name}: {response}")
            from core.notification_router import route_notification
            route_notification(chat_id, "Couldn't process that image right now -- API error. Try again.",
                               bot_token, severity="IMPORTANT", agent=agent_name)
            return

        # Extract and save state updates (proper multi-marker handling)
        clean_response, state_updates = _extract_state_updates(response)
        for state_info in state_updates:
            if state_info:
                update_agent_state(agent_name, state_info)

        # Process through learning loop
        clean_response = process_response_learning(
            agent_name, clean_response,
            trigger="photo",
            input_summary=f"[Photo] {caption}" if caption else "[Photo]"
        )

        # Save agent response to permanent memory
        try:
            save_memory_message(user_id, agent_name, chat_id, "assistant", clean_response)
        except Exception as hist_e:
            logger.warning(f"Failed to save photo response to memory: {hist_e}")

        sent = send_telegram(chat_id, clean_response, bot_token)
        if sent:
            logger.info(f"Photo response from {agent_name} delivered")
            if agent_name in VOICE_AGENTS:
                try:
                    send_telegram_voice(chat_id, clean_response, bot_token, voice_id=VOICE_AGENTS[agent_name])
                except Exception as _ve:
                    logger.warning(f"Voice message failed for {agent_name} (non-fatal): {_ve}")
        else:
            logger.error(f"FAILED to deliver {agent_name} photo response")

        # AUTOMATIC MEMORY EXTRACTION (same as text handler)
        try:
            agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
            extraction_conv = conv_history + [
                {"role": "user", "content": photo_msg},
                {"role": "assistant", "content": clean_response}
            ]
            if agent_name in CHAT_USER_MAP:
                from core.asmr_memory import asmr_extract
                asmr_extract(user_id, agent_name, extraction_conv, agent_display)
            else:
                from core.user_memory import extract_and_store_memories
                extract_and_store_memories(user_id, agent_name, extraction_conv, agent_display)
        except Exception as mem_e:
            logger.warning(f"Photo memory extraction failed (non-fatal): {mem_e}")

    except Exception as e:
        logger.error(f"PHOTO HANDLER CRASH for {agent_name}: {e}", exc_info=True)
        try:
            agent_display = AGENT_DISPLAY.get(agent_name, agent_name)
            send_telegram(chat_id,
                          f"{agent_display} couldn't process that photo: {str(e)[:200]}",
                          bot_token)
        except Exception:
            logger.error(f"Could not send photo error message to {chat_id}")


def handle_command(command: str, telegram_config: dict):
    """Handle Nexus command center commands."""
    cmd = command.strip().lower()
    chat_id = telegram_config["chat_ids"].get("command-center")
    bot_token = telegram_config["bot_token"]

    if cmd == "status":
        # Show all agent statuses
        status_lines = ["NEXUS -- System Status\n"]
        for agent_name in telegram_config["agent_names"]:
            display_name = telegram_config["agent_names"][agent_name]
            state_file = AGENTS_DIR / agent_name / "state" / "CONTEXT.md"
            if state_file.exists():
                content = state_file.read_text(encoding='utf-8')
                # Extract last updated
                for line in content.split("\n"):
                    if "Last Updated" in line:
                        status_lines.append(f"[OK] {display_name} ({agent_name}): {line.split(':',1)[1].strip()}")
                        break
                else:
                    status_lines.append(f"[--] {display_name} ({agent_name}): No timestamp")
            else:
                status_lines.append(f"[!!] {display_name} ({agent_name}): No state file")

        # Add learning DB stats if available
        db = get_learning_db()
        if db:
            try:
                for table in ['insights', 'decisions', 'metrics', 'patterns']:
                    count = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                    if count > 0:
                        status_lines.append(f"\nLearning DB: {table} = {count}")
            except Exception:
                pass

        from core.notification_router import route_notification
        route_notification(chat_id, "\n".join(status_lines), bot_token, severity="INFO", agent="command-center")

    elif cmd.startswith("run "):
        agent_to_run = cmd.split("run ", 1)[1].strip()
        if agent_to_run in telegram_config["chat_ids"]:
            # Default task per agent -- not everything is "morning_brief"
            default_tasks = {
                "evening-reading": "evening_reading",
                "global-events": "scan",
                "creative-projects": "model_scan",
                "social": "weekly_plan",
            }
            task_name = default_tasks.get(agent_to_run, "morning_brief")
            send_telegram(chat_id, f"Triggering {agent_to_run}/{task_name}...", bot_token)
            run_scheduled_task(agent_to_run, task_name, telegram_config)
        else:
            from core.notification_router import route_notification
            route_notification(chat_id, f"Unknown agent: {agent_to_run}", bot_token, severity="INFO", agent="command-center")

    elif cmd in ("integrations", "env", "connections"):
        # Show which API integrations are connected -- tests actual availability
        checks = {}
        details = {}
        checks["Shopify"] = bool(os.environ.get("SHOPIFY_STORE_URL") and os.environ.get("SHOPIFY_ACCESS_TOKEN"))
        checks["Klaviyo"] = bool(os.environ.get("KLAVIYO_API_KEY"))
        checks["Meta Ads"] = bool(os.environ.get("META_ACCESS_TOKEN") and os.environ.get("META_AD_ACCOUNT_ID"))
        checks["Google Ads"] = bool(os.environ.get("GOOGLE_ADS_DEVELOPER_TOKEN"))
        checks["Asana"] = bool(os.environ.get("ASANA_ACCESS_TOKEN") and (os.environ.get("ASANA_PROJECT_ID") or os.environ.get("ASANA_WORKSPACE_ID")))
        if os.environ.get("ASANA_ACCESS_TOKEN") and not checks["Asana"]:
            details["Asana"] = "Token set but no PROJECT_ID or WORKSPACE_ID"
        checks["Slack"] = bool(os.environ.get("SLACK_BOT_TOKEN"))
        checks["Wise"] = bool(os.environ.get("WISE_API_TOKEN"))
        checks["OpenAI (voice)"] = bool(os.environ.get("OPENAI_API_KEY"))

        # Xero: check actual token availability, not just env var
        if os.environ.get("XERO_CLIENT_ID") and os.environ.get("XERO_CLIENT_SECRET"):
            try:
                from core.xero_client import XeroClient
                xc = XeroClient()
                if xc.available:
                    checks["Xero"] = True
                    details["Xero"] = "Connected (tokens valid)"
                else:
                    checks["Xero"] = False
                    details["Xero"] = "Credentials set but tokens missing/expired -- needs re-auth"
            except Exception as xe:
                checks["Xero"] = False
                details["Xero"] = f"Error: {str(xe)[:60]}"
        elif os.environ.get("XERO_CLIENT_ID"):
            checks["Xero"] = False
            details["Xero"] = "XERO_CLIENT_SECRET missing"
        else:
            checks["Xero"] = False
            details["Xero"] = "XERO_CLIENT_ID not set"

        lines = ["NEXUS -- Integration Status\n"]
        for name, connected in checks.items():
            icon = "OK" if connected else "!!"
            if name in details:
                lines.append(f"[{icon}] {name}: {details[name]}")
            else:
                status = "Connected" if connected else "NOT SET -- add to Railway env vars"
                lines.append(f"[{icon}] {name}: {status}")
        connected_count = sum(1 for v in checks.values() if v)
        lines.append(f"\n{connected_count}/{len(checks)} integrations active")
        from core.notification_router import route_notification
        route_notification(chat_id, "\n".join(lines), bot_token, severity="INFO", agent="command-center")

    elif cmd == "db stats":
        # Show learning database statistics
        db = get_learning_db()
        if db:
            lines = ["Learning Database Stats\n"]
            for table in ['insights', 'decisions', 'metrics', 'patterns', 'interactions']:
                count = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                lines.append(f"  {table}: {count} rows")
            from core.notification_router import route_notification
            route_notification(chat_id, "\n".join(lines), bot_token, severity="INFO", agent="command-center")
        else:
            from core.notification_router import route_notification
            route_notification(chat_id, "Learning DB not available", bot_token, severity="INFO", agent="command-center")

    elif cmd == "test feeds":
        # Diagnostic: test all data feed connections
        lines = ["NEXUS -- Data Feed Diagnostics\n"]

        # 1. News RSS
        try:
            from core.news_fetcher import fetch_news_for_agent
            headlines = fetch_news_for_agent("global-events")
            count = headlines.count("\n") if headlines else 0
            lines.append(f"[OK] News RSS: {count} headlines fetched")
        except Exception as e:
            lines.append(f"[FAIL] News RSS: {e}")

        # 2. Shopify
        try:
            from core.data_fetcher import fetch_shopify_data
            data = fetch_shopify_data()
            if "unavailable" in data.lower() or "error" in data.lower():
                lines.append(f"[--] Shopify: {data[:80]}")
            else:
                lines.append(f"[OK] Shopify: connected")
        except Exception as e:
            lines.append(f"[FAIL] Shopify: {e}")

        # 3. Klaviyo
        try:
            from core.data_fetcher import fetch_klaviyo_data
            data = fetch_klaviyo_data()
            if "unavailable" in data.lower() or "error" in data.lower():
                lines.append(f"[--] Klaviyo: {data[:80]}")
            else:
                lines.append(f"[OK] Klaviyo: connected")
        except Exception as e:
            lines.append(f"[FAIL] Klaviyo: {e}")

        # 4. Meta Ads
        try:
            from core.data_fetcher import fetch_meta_ads_data
            data = fetch_meta_ads_data()
            if "unavailable" in data.lower() or "error" in data.lower():
                lines.append(f"[--] Meta Ads: {data[:80]}")
            else:
                lines.append(f"[OK] Meta Ads: connected")
        except Exception as e:
            lines.append(f"[FAIL] Meta Ads: {e}")

        # 5. Asana
        try:
            from core.asana_client import AsanaClient
            asana = AsanaClient()
            if not asana.available:
                lines.append("[--] Asana: ASANA_ACCESS_TOKEN not set")
            elif not asana.project_id:
                lines.append("[--] Asana: ASANA_PROJECT_ID not set")
            else:
                tasks = asana.get_incomplete_tasks()
                lines.append(f"[OK] Asana: connected ({len(tasks)} open tasks)")
        except Exception as e:
            lines.append(f"[FAIL] Asana: {e}")

        # 6. Order Intelligence
        try:
            from core.order_intelligence import fetch_order_intelligence
            data = fetch_order_intelligence(1)
            if "unavailable" in data.lower() or "error" in data.lower():
                lines.append(f"[--] Order Intelligence: {data[:80]}")
            elif "No orders" in data:
                lines.append(f"[OK] Order Intelligence: connected (no orders in last 24h)")
            else:
                order_count = data.count("Products:")
                lines.append(f"[OK] Order Intelligence: {order_count} orders analysed")
        except Exception as e:
            lines.append(f"[FAIL] Order Intelligence: {e}")

        # 7. Slack
        try:
            from core.slack_client import SlackClient
            slack = SlackClient()
            if not slack.available:
                lines.append("[--] Slack: SLACK_BOT_TOKEN not set")
            elif not slack.channel_ids:
                lines.append("[--] Slack: SLACK_CHANNEL_IDS not set")
            else:
                # Quick test: list channels
                channels = slack.list_channels()
                lines.append(f"[OK] Slack: connected ({len(channels)} channels visible)")
        except Exception as e:
            lines.append(f"[FAIL] Slack: {e}")

        # Summary
        ok_count = sum(1 for l in lines if "[OK]" in l)
        fail_count = sum(1 for l in lines if "[FAIL]" in l)
        skip_count = sum(1 for l in lines if "[--]" in l)
        lines.append(f"\nSummary: {ok_count} connected, {skip_count} not configured, {fail_count} errors")

        from core.notification_router import route_notification
        route_notification(chat_id, "\n".join(lines), bot_token, severity="INFO", agent="command-center")

    elif cmd == "briefs":
        # List active design briefs
        try:
            from core.brief_generator import BriefGenerator
            bg = BriefGenerator()
            briefs = bg.list_briefs()
            if briefs:
                lines = ["Design Briefs\n"]
                for b in briefs[:10]:
                    title = b["title"][:50] + "..." if len(b["title"]) > 50 else b["title"]
                    lines.append(f"  [{b['status']}] {title}\n  ID: {b['brief_id']}\n  Assigned: {b['assigned_to']}\n")
                from core.notification_router import route_notification
                route_notification(chat_id, "\n".join(lines), bot_token, severity="INFO", agent="command-center")
            else:
                from core.notification_router import route_notification
                route_notification(chat_id, "No design briefs yet. Meridian will auto-generate them when campaign opportunities are detected.", bot_token, severity="INFO", agent="command-center")
            bg.close()
        except Exception as e:
            from core.notification_router import route_notification
            route_notification(chat_id, f"Brief generator error: {e}", bot_token, severity="INFO", agent="command-center")

    elif cmd.startswith("undo "):
        # Undo an auto-optimizer action
        action_id = cmd.split("undo ", 1)[1].strip()
        try:
            from core.auto_optimizer import undo_optimizer_action
            result = undo_optimizer_action(int(action_id))
            from core.notification_router import route_notification
            route_notification(chat_id, f"Undo result: {result}", bot_token, severity="IMPORTANT", agent="command-center")
        except Exception as e:
            from core.notification_router import route_notification
            route_notification(chat_id, f"Undo failed: {e}", bot_token, severity="INFO", agent="command-center")

    elif cmd == "citations":
        # Show latest citation monitoring report
        try:
            from core.citation_monitor import get_weekly_citation_report
            report = get_weekly_citation_report()
            from core.notification_router import route_notification
            route_notification(chat_id, report, bot_token, severity="INFO", agent="command-center")
        except Exception as e:
            from core.notification_router import route_notification
            route_notification(chat_id, f"Citation report error: {e}", bot_token, severity="INFO", agent="command-center")

    elif cmd == "setup pure pets":
        # Build Pure Pets campaign structure via Meta Ads API
        try:
            from core.notification_router import route_notification
            dry_run = "--dry-run" in command
            mode = "DRY RUN" if dry_run else "CREATING"
            route_notification(chat_id, f"Pure Pets campaign setup {mode}...", bot_token, severity="INFO", agent="command-center")
            from core.pure_pets_campaign_builder import build_campaign
            result = build_campaign(dry_run=dry_run)
            if dry_run:
                route_notification(chat_id, "Dry run complete. Run 'setup pure pets' (without --dry-run) to create.", bot_token, severity="INFO", agent="command-center")
            else:
                summary = f"Pure Pets campaign created (ALL PAUSED)\n\nCampaign: {result.get('campaign_id')}\nAd Set: {result.get('adset_id')}\nAds created: {len(result.get('ad_ids', []))}/12\n\nNext: upload creative images in Meta Ads Manager, then activate."
                route_notification(chat_id, summary, bot_token, severity="IMPORTANT", agent="command-center")
        except Exception as e:
            from core.notification_router import route_notification
            route_notification(chat_id, f"Pure Pets setup error: {e}", bot_token, severity="INFO", agent="command-center")

    elif cmd == "memory":
        # Show what the system knows about the user
        try:
            user_id = str(telegram_config.get("owner_user_id", os.environ.get("TELEGRAM_OWNER_ID", "default")))
            from core.user_memory import format_memory_for_display, get_memory_stats
            stats = get_memory_stats(user_id)
            memory_text = format_memory_for_display(user_id)
            stats_line = (f"\n\nMemory Stats: {stats['active_facts']} facts, "
                          f"{stats['total_messages']} messages archived, "
                          f"{stats['session_summaries']} daily summaries, "
                          f"{stats['extraction_runs']} extraction runs")
            from core.notification_router import route_notification
            route_notification(chat_id, memory_text + stats_line, bot_token, severity="INFO", agent="command-center")
        except Exception as e:
            from core.notification_router import route_notification
            route_notification(chat_id, f"Memory system error: {e}", bot_token, severity="INFO", agent="command-center")

    elif cmd.startswith("export "):
        # Export all messages and facts for a companion user to Telegram
        try:
            target = cmd.split("export ", 1)[1].strip().lower()
            user_map = {"tyler": "tyler", "jackson": "jackson", "tom": str(telegram_config.get("owner_user_id", os.environ.get("TELEGRAM_OWNER_ID", "default")))}
            target_user_id = user_map.get(target)
            if not target_user_id:
                from core.notification_router import route_notification
                route_notification(chat_id, f"Unknown user: {target}. Use: export tyler, export jackson, export tom", bot_token, severity="INFO", agent="command-center")
            else:
                import sqlite3 as _exp_sql
                db_path = os.path.join(BASE_DIR, "data", "user_memory.db")
                db = _exp_sql.connect(db_path)
                db.row_factory = _exp_sql.Row

                # Messages
                msgs = db.execute("SELECT role, content, agent_id, created_at FROM messages WHERE user_id = ? ORDER BY created_at ASC", (target_user_id,)).fetchall()

                # Facts
                facts = db.execute("SELECT fact, category, confidence, source_agent, created_at FROM user_facts WHERE user_id = ? AND is_active = 1 ORDER BY created_at DESC", (target_user_id,)).fetchall()

                # ASMR knowledge findings
                asmr_findings = []
                try:
                    asmr_findings = db.execute("SELECT vector, finding, observer, source_date, is_current FROM knowledge_findings WHERE user_id = ? ORDER BY source_date DESC", (target_user_id,)).fetchall()
                except Exception:
                    pass  # Table may not exist

                db.close()

                # Build export
                lines = [f"EXPORT: {target} (user_id: {target_user_id})\n"]
                lines.append(f"Messages: {len(msgs)}")
                lines.append(f"Active facts: {len(facts)}")
                lines.append(f"ASMR findings: {len(asmr_findings)}\n")

                if msgs:
                    lines.append("=== MESSAGES (full history) ===")
                    for m in msgs:
                        ts = m["created_at"][:16] if m["created_at"] else "?"
                        lines.append(f"[{ts}] {m['role'].upper()} ({m['agent_id']}): {m['content']}")
                    lines.append("")

                if facts:
                    lines.append("=== ACTIVE FACTS ===")
                    for f in facts:
                        lines.append(f"[{f['category']}] {f['fact']} (confidence: {f['confidence']}, from: {f['source_agent']}, at: {f['created_at'][:16]})")
                    lines.append("")

                if asmr_findings:
                    lines.append("=== ASMR FINDINGS ===")
                    for af in asmr_findings:
                        current = "CURRENT" if af["is_current"] else "OUTDATED"
                        lines.append(f"[{current}] [{af['vector']}] {af['finding']} (observer: {af['observer']}, date: {af['source_date']})")

                export_text = "\n".join(lines)

                # Write to file and send as Telegram document (avoids message flooding)
                export_path = os.path.join(BASE_DIR, "data", f"export_{target}_{datetime.now(NZ_TZ).strftime('%Y%m%d_%H%M')}.txt")
                with open(export_path, "w", encoding="utf-8") as ef:
                    ef.write(export_text)

                import requests as _exp_req
                with open(export_path, "rb") as ef:
                    _exp_req.post(
                        f"https://api.telegram.org/bot{bot_token}/sendDocument",
                        data={"chat_id": chat_id, "caption": f"Export: {target} -- {len(msgs)} messages, {len(facts)} facts, {len(asmr_findings)} ASMR findings"},
                        files={"document": (f"export_{target}.txt", ef, "text/plain")},
                        timeout=30
                    )

                logger.info(f"Exported {len(msgs)} messages, {len(facts)} facts, {len(asmr_findings)} ASMR findings for {target} -> {export_path}")
        except Exception as e:
            from core.notification_router import route_notification
            route_notification(chat_id, f"Export failed: {e}", bot_token, severity="INFO", agent="command-center")

    elif cmd.startswith("forget "):
        # Delete memories matching text
        try:
            user_id = str(telegram_config.get("owner_user_id", os.environ.get("TELEGRAM_OWNER_ID", "default")))
            search_text = cmd.split("forget ", 1)[1].strip()
            from core.user_memory import delete_facts_by_text, delete_all_facts
            if search_text == "all":
                count = delete_all_facts(user_id)
                msg = f"Deleted all {count} memories. Starting fresh."
            else:
                count = delete_facts_by_text(user_id, search_text)
                msg = f"Deleted {count} memories matching '{search_text}'." if count > 0 else f"No memories found matching '{search_text}'."
            from core.notification_router import route_notification
            route_notification(chat_id, msg, bot_token, severity="INFO", agent="command-center")
        except Exception as e:
            from core.notification_router import route_notification
            route_notification(chat_id, f"Forget failed: {e}", bot_token, severity="INFO", agent="command-center")

    else:
        # Unknown command -- show available commands instead of hallucinating
        help_text = """NEXUS -- Available Commands

System:
  status -- Show all agent statuses
  integrations -- Check API connection status
  test feeds -- Test all data feed connections live
  db stats -- Learning database statistics
  briefs -- List active design briefs
  undo <action_id> -- Undo an auto-optimizer action
  citations -- Latest AI citation monitoring report
  memory -- Show what all agents know about you
  forget <text> -- Delete memories matching text
  forget all -- Delete ALL memories (nuclear option)

Campaigns:
  setup pure pets -- Create Pure Pets campaign via Meta API (PAUSED)

Agents:
  run <agent-name> -- Trigger an agent's default task
  Example: run dbh-marketing

Agent names: global-events, dbh-marketing, health-science,
health-fitness, social, creative-projects, daily-briefing,
strategic-advisor, evening-reading, beacon"""
        from core.notification_router import route_notification
        route_notification(chat_id, help_text, bot_token, severity="INFO", agent="command-center")


# --- Telegram Polling Loop ---

def start_polling(telegram_config: dict):
    """Simple long-polling loop for Telegram updates."""
    import requests
    import time

    bot_token = telegram_config["bot_token"]
    owner_id = telegram_config["owner_user_id"]
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    offset = 0

    logger.info("Starting Telegram polling loop...")
    logger.info(f"Bot token: ...{bot_token[-8:]}")
    logger.info(f"Owner ID: '{owner_id}' (type: {type(owner_id).__name__})")

    # Log registered chat IDs so we can verify
    chat_ids = telegram_config.get("chat_ids", {})
    for agent, cid in chat_ids.items():
        logger.info(f"  Chat mapping: {agent} -> {cid}")

    # Startup self-test: send a brief message to command-center
    nexus_chat = chat_ids.get("command-center")
    if nexus_chat:
        try:
            import requests as _req
            _test_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            _test_resp = _req.post(_test_url, json={
                "chat_id": nexus_chat,
                "text": "System online. Polling active.",
            }, timeout=10)
            if _test_resp.ok:
                logger.info("Startup self-test: message sent to Nexus channel")
            else:
                logger.error(f"Startup self-test failed: {_test_resp.text}")
        except Exception as e:
            logger.error(f"Startup self-test error: {e}")

    # Initialise learning DB on startup
    db = get_learning_db()
    if db:
        logger.info("Learning loop active")
    else:
        logger.warning("Learning loop inactive -- database not available")

    # Initialise event bus with default subscriptions
    try:
        from core.event_bus import EventBus
        bus = EventBus()
        # Default subscriptions -- each agent listens to relevant event patterns
        default_subs = {
            "dbh-marketing":     ["campaign.*", "customer.*", "inventory.*", "market.*"],
            "strategic-advisor": ["*"],  # PREP sees everything
            "daily-briefing":    ["*"],  # Oracle sees everything for synthesis
            "creative-projects": ["campaign.*", "content.*"],
            "global-events":     ["market.*"],
            "health-science":    ["campaign.*", "health.*", "customer.*"],
            "command-center":    ["system.*"],
            "beacon":            ["campaign.*", "content.*"],
            "asclepius-brain":   ["health.*"],   # Receives Titan's sleep/training/recovery events
            "health-fitness":    ["brain.*"],    # Receives Asclepius's cognitive/sleep insights
        }
        for agent, patterns in default_subs.items():
            for pat in patterns:
                bus.subscribe(agent, pat)
        bus.close()
        logger.info("Event bus initialised with default subscriptions")
    except Exception as e:
        logger.warning(f"Event bus init failed (non-fatal): {e}")

    while True:
        try:
            response = requests.get(url, params={
                "offset": offset,
                "timeout": 30
            }, timeout=35)

            data = response.json()

            if data.get("ok") and data.get("result"):
                for update in data["result"]:
                    offset = update["update_id"] + 1

                    message = update.get("message")
                    if not message:
                        # Not a regular message (could be edited_message, callback_query, etc.)
                        logger.debug(f"Non-message update: {list(update.keys())}")
                        continue

                    text = message.get("text", "")
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    user_id = str(message.get("from", {}).get("id", ""))

                    logger.info(f"Update received: chat_id={chat_id}, user_id={user_id}, text={text[:60] if text else '(no text)'}")

                    # Security: only respond to authorised users
                    # 1. Owner (Tom) can message any agent
                    # 2. authorized_users list (explicit extras)
                    # 3. Companion agent chats allow any member (Jackson in Aether, Tyler in Forge)
                    #    — these are private group chats, so only invited members can message
                    authorized = {str(owner_id).strip()}
                    for extra_id in telegram_config.get("authorized_users", []):
                        authorized.add(str(extra_id).strip())

                    # Companion agents: allow any user in their dedicated group chat
                    # The Telegram group itself is the security boundary (invite-only)
                    agent_for_chat = identify_agent_from_chat(chat_id, telegram_config)
                    companion_agents = set(CHAT_USER_MAP.keys())  # aether, forge, etc.
                    is_companion_chat = agent_for_chat in companion_agents

                    if user_id not in authorized and not is_companion_chat:
                        logger.warning(f"Ignoring message from unknown user: user_id='{user_id}'")
                        continue

                    # Handle voice messages
                    voice = message.get("voice") or message.get("audio")
                    if voice and not text:
                        file_id = voice.get("file_id")
                        if file_id:
                            logger.info(f"Voice message received in chat {chat_id}, transcribing...")
                            transcript = transcribe_voice(file_id, bot_token)
                            if transcript and not transcript.startswith("["):
                                # Successful transcription
                                text = f"[Voice message] {transcript}"
                                logger.info(f"Voice transcribed: {text[:80]}...")
                            else:
                                # Transcription failed -- tell Tom
                                logger.warning(f"Voice transcription failed: {transcript}")
                                from core.notification_router import route_notification
                                route_notification(chat_id, f"Could not transcribe your voice message. {transcript or 'Unknown error.'}\n\nPlease type your message instead.", bot_token, severity="INFO", agent="command-center")
                                continue

                    # Handle photo messages
                    photo = message.get("photo")
                    if photo:
                        caption = message.get("caption", "")
                        logger.info(f"Photo received (caption: {caption[:50] if caption else 'none'})")
                        import threading
                        threading.Thread(
                            target=handle_photo_message,
                            args=(chat_id, photo, caption, bot_token, telegram_config),
                            daemon=True,
                        ).start()
                        continue

                    # Handle image documents (screenshots sent as files)
                    doc = message.get("document")
                    if doc and not text:
                        mime = doc.get("mime_type", "")
                        if mime.startswith("image/"):
                            caption = message.get("caption", "")
                            # Wrap as photo-like structure for reuse
                            logger.info(f"Image document received: {doc.get('file_name', 'unknown')}")
                            import threading
                            threading.Thread(
                                target=handle_photo_message,
                                args=(chat_id, [doc], caption, bot_token, telegram_config),
                                daemon=True,
                            ).start()
                            continue

                    if text:
                        # Run message handler in a thread so the polling loop
                        # isn't blocked by slow agents (PREP uses Opus + heavy
                        # data injection and can take 2+ minutes to respond).
                        import threading
                        t = threading.Thread(
                            target=handle_incoming_message,
                            args=(chat_id, text, telegram_config),
                            daemon=True,
                        )
                        t.start()

        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)


# --- Entry Point ---

if __name__ == "__main__":
    telegram_config, schedule_config = load_config()

    if len(sys.argv) > 1:
        command = sys.argv[1]

        if command == "poll":
            # Start Telegram polling loop
            start_polling(telegram_config)

        elif command == "run":
            # Run a specific agent task: python orchestrator.py run atlas scan
            if len(sys.argv) >= 4:
                agent = sys.argv[2]
                task = sys.argv[3]
                run_scheduled_task(agent, task, telegram_config)
            else:
                print("Usage: python orchestrator.py run <agent> <task>")

        elif command == "test":
            # Test: load an agent brain and print it
            if len(sys.argv) >= 3:
                agent = sys.argv[2]
                brain = load_agent_brain(agent)
                print(f"Brain loaded for {agent} (~{len(brain)//4} tokens)")
                print(brain[:2000] + "\n..." if len(brain) > 2000 else brain)
            else:
                print("Usage: python orchestrator.py test <agent>")

        elif command == "brains":
            # Show brain sizes for all agents
            for agent_dir in sorted(AGENTS_DIR.iterdir()):
                if agent_dir.is_dir() and (agent_dir / "AGENT.md").exists():
                    brain = load_agent_brain(agent_dir.name)
                    print(f"{agent_dir.name:25s} ~{len(brain)//4:>6,} tokens")

        elif command == "db":
            # Learning DB commands
            db = get_learning_db()
            if db:
                if len(sys.argv) > 2 and sys.argv[2] == "stats":
                    for table in ['insights', 'decisions', 'metrics', 'patterns', 'interactions']:
                        count = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                        print(f"{table:15s}: {count:>6d} rows")
                else:
                    print("Usage: python orchestrator.py db stats")
            else:
                print("Learning database not available")

        else:
            print(f"Unknown command: {command}")
            print("Commands: poll, run <agent> <task>, test <agent>, brains, db stats")

    else:
        print("Tom's Command Center -- Orchestrator")
        print("Commands:")
        print("  python orchestrator.py poll               -- Start Telegram listener")
        print("  python orchestrator.py run <agent> <task>  -- Run a scheduled task")
        print("  python orchestrator.py test <agent>        -- Test agent brain loading")
        print("  python orchestrator.py brains              -- Show all agent brain sizes")
        print("  python orchestrator.py db stats            -- Show learning DB stats")
