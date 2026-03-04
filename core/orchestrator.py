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
from datetime import datetime

# --- Configuration ---

BASE_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = BASE_DIR / "agents"
CONFIG_DIR = BASE_DIR / "config"

# Human-readable agent names for error messages and display
AGENT_DISPLAY = {
    "global-events":     "Atlas",
    "dbh-marketing":     "Meridian",
    "new-business":      "Venture",
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
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "orchestrator.log", encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


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


# --- Agent Brain Loader ---
# THIS IS THE KEY FUNCTION. Every time an agent speaks, it reads its entire
# knowledge stack first. Same pattern as DBH AIOS CLAUDE.md session startup.

def load_agent_brain(agent_name: str) -> str:
    """
    Load the full brain for an agent. This is the equivalent of the
    CLAUDE.md session startup -- read identity, skills, playbooks, state.

    Returns a complete system prompt that makes the agent fully contextualised.
    """
    agent_dir = AGENTS_DIR / agent_name
    brain_parts = []

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

    # 1.7 YESTERDAY'S SUMMARY -- If first message of day, load yesterday's session log
    from datetime import date, timedelta
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
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
    STRATEGY_AGENTS = ["dbh-marketing", "strategic-advisor", "daily-briefing", "beacon"]
    if agent_name in STRATEGY_AGENTS:
        shared_strategy_dir = AGENTS_DIR / "shared" / "strategy"
        if shared_strategy_dir.exists():
            strategy_files = sorted(shared_strategy_dir.glob("*.md"))
            if strategy_files:
                brain_parts.append("=== SHARED STRATEGY (90-Day Execution Plan) ===")
                for f in strategy_files:
                    brain_parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
                logger.info(f"Loaded {len(strategy_files)} shared strategy files for {agent_name}")

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
    timestamp = datetime.now().strftime("%B %d, %Y %H:%M")

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
    from datetime import date
    today = date.today().isoformat()

    log_file = AGENTS_DIR / agent_name / "state" / f"session-log-{today}.md"

    # Create log file if it doesn't exist
    if not log_file.exists():
        header = f"# SESSION LOG — {agent_name.title()}\n## Date: {today}\n\n"
        log_file.write_text(header, encoding='utf-8')
        logger.info(f"Created new session log: {log_file}")

    # Append interaction
    timestamp = datetime.now().strftime("%H:%M:%S")
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


# --- Claude API Caller ---

def call_claude(system_prompt: str, user_message: str, task_type: str = "chat") -> str:
    """
    Call Claude API with the full agent brain as system prompt.

    For scheduled tasks, user_message is the task instruction.
    For chat responses, user_message is Tom's message.
    """
    import anthropic

    client = anthropic.Anthropic()  # Uses ANTHROPIC_API_KEY env var

    # Choose model based on task complexity
    # Use Sonnet for routine tasks, Opus for deep analysis
    model = "claude-sonnet-4-6"
    if task_type in ("weekly_review", "weekly_deep_dive", "deep_analysis", "evening_reading"):
        model = "claude-opus-4-6"

    logger.info(f"Calling Claude API: model={model}, system_len={len(system_prompt)}, user_len={len(user_message)}")
    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
            timeout=120.0,
        )
        logger.info(f"Claude API responded: {len(response.content[0].text)} chars, stop={response.stop_reason}")
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

    prompt = f"""You are operating as agent '{agent_name}' in Tom's Command Center.

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

            from datetime import timedelta
            due_date = (datetime.now() + timedelta(days=due_days)).strftime("%Y-%m-%d")

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

    model = "claude-sonnet-4-6"
    if task_type in ("weekly_review", "weekly_deep_dive", "deep_analysis", "evening_reading"):
        model = "claude-opus-4-6"

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
        return response.content[0].text
    except Exception as e:
        logger.error(f"Claude Vision API error: {e}")
        return f"API Error: {str(e)}"


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

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def _post(chunk: str) -> bool:
        """Post a single chunk, retry once without Markdown on parse failure."""
        try:
            resp = requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown"
            }, timeout=30)
            data = resp.json()
            if data.get("ok"):
                return True
            # Markdown parse errors -- retry without parse_mode
            if "can't parse" in str(data.get("description", "")).lower():
                logger.warning(f"Markdown parse failed for {chat_id}, retrying plain text")
                resp2 = requests.post(url, json={
                    "chat_id": chat_id,
                    "text": chunk,
                }, timeout=30)
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

    # Telegram has a 4096 char limit per message
    if len(text) > 4000:
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        success = all(_post(chunk) for chunk in chunks)
    else:
        success = _post(text)

    if success:
        logger.info(f"Message sent to {chat_id} ({len(text)} chars)")
    return success


def identify_agent_from_chat(chat_id: str, telegram_config: dict) -> str:
    """Given a Telegram chat ID, identify which agent handles it."""
    chat_ids = telegram_config.get("chat_ids", {})
    for agent_name, cid in chat_ids.items():
        if str(cid) == str(chat_id):
            return agent_name
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
                    from datetime import date as _date
                    today_str = _date.today().isoformat()
                    month_str = _date.today().strftime("%Y-%m")

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
                    content += f"\n{gsc_marker}\n*Updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n{briefing}\n"
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

    brain = load_agent_brain(agent_name)

    # Build task-specific prompt
    task_prompts = {
        "morning_protocol": "Execute your morning protocol. Generate today's training plan, meal plan, and any notes. Use the format specified in your AGENT.md.",
        "morning_briefing": "Generate the daily master briefing NOW. You have all agent states and LIVE DATA injected below this prompt — Shopify revenue, Klaviyo emails, Meta Ads, Asana tasks, financial data. USE THE ACTUAL NUMBERS from the injected data. Do NOT say 'unavailable' or 'not connected' — the data IS below. If a specific source shows an error in brackets like [Shopify error: ...], report that specific error. Deliver the full briefing using the exact format from your AGENT.md. Never ask permission or offer options — just brief.",
        "morning_brief": "Generate your morning operations brief NOW using the LIVE DATA injected below this prompt. The orchestrator has already fetched Shopify, Klaviyo, Meta, and Asana data for you — it appears below. Use ACTUAL NUMBERS from the injected data. Do NOT say 'data unavailable' or 'not yet connected' — the data IS here. If a specific data source shows an error in brackets like [Klaviyo error: ...], report that specific error. Flag issues, list priorities. Use the format specified in your AGENT.md.\n\nIMPORTANT: If you identify a campaign opportunity or creative need, emit [BRIEF: description of insight] and the system will auto-generate a designer-ready brief for Roie and create an Asana task.",
        "scan": "Execute your monitoring scan. Search for updates on your watchlist topics. Report only what's NEW since your last scan. Use the format specified in your AGENT.md.",
        "model_scan": "Execute your AI model release scan. Search for new video model announcements, updates to tracked models. If anything could handle action sequences, mark as CRITICAL. Use the format specified in your AGENT.md.",
        "weekly_plan": "Generate your weekly social plan. Review contact list, flag overdue catch-ups, suggest activities. Use the format specified in your AGENT.md.",
        "midweek_checkin": "Mid-week social check-in. Review what was planned, what happened, anything coming up this weekend.",
        "weekly_review": "Execute your weekly performance review. Full data pull, compare to targets, identify patterns, recommend optimisations. Use the format specified in your AGENT.md.\n\nIMPORTANT: If you identify a campaign opportunity or creative need, emit [BRIEF: description of insight] and the system will auto-generate a designer-ready brief for Roie and create an Asana task.",
        "weekly_deep_dive": "Execute your weekly deep analysis. Pick the most important developing story and provide in-depth analysis. Use the format specified in your AGENT.md.",
        "evening_reading": "",  # Placeholder -- replaced below with knowledge engine output
        "content_generation": "Generate tonight's SEO/AEO article following your nightly workflow. Check your CONTEXT.md for the current keyword priority, select the next topic, and generate a full article using one of your proven content formulas. Include the complete article HTML, meta description, FAQ section, and JSON-LD schema. Save instructions and Shopify draft details should be in your output. After your article, emit a [STATE UPDATE:] with the article title and next priority keyword.",
    }

    task_prompt = task_prompts.get(task_name, f"Execute task: {task_name}")

    # Evening reading: knowledge engine builds the full prompt
    if task_name == "evening_reading":
        try:
            from core.knowledge_engine import get_tonight_reading
            reading = get_tonight_reading()
            task_prompt = reading["prompt"]
            logger.info(f"Evening reading: {reading['primary_concept']} (score: {reading['primary_score']})")
        except Exception as e:
            logger.error(f"Knowledge engine failed: {e}")
            task_prompt = "Deliver a foundational knowledge lesson for Tom's evening reading. Pick a mental model or strategic concept and connect it to running a DTC health supplement business. 500-800 words, practical, Telegram-friendly."

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
    live_news_tasks = ("scan", "model_scan", "morning_brief", "morning_briefing", "weekly_review", "weekly_deep_dive")
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

    # 2. Performance data for business briefings
    perf_data_tasks = ("morning_briefing", "morning_brief", "weekly_review")
    if task_name in perf_data_tasks and agent_name in ("daily-briefing", "dbh-marketing", "strategic-advisor"):
        try:
            from core.data_fetcher import fetch_all_performance_data, fetch_weekly_performance_data
            days = 7 if task_name == "weekly_review" else 1
            perf_data = fetch_weekly_performance_data() if days == 7 else fetch_all_performance_data()
            task_prompt += f"""

{perf_data}

Use this real performance data in your briefing. Show actual numbers. Identify attribution
patterns -- what's driving sales? Compare to benchmarks in your playbooks."""
            logger.info(f"Injected performance data for {agent_name}/{task_name}")
            data_status["Shopify/Klaviyo/Meta Performance"] = "OK"
        except Exception as e:
            logger.warning(f"Performance data fetch failed (non-fatal): {e}")
            data_status["Shopify/Klaviyo/Meta Performance"] = f"FAILED: {e}"

    # 2b. Order-level intelligence (per-order attribution + customer analysis)
    if task_name in perf_data_tasks and agent_name in ("daily-briefing", "dbh-marketing", "strategic-advisor"):
        try:
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
            logger.info(f"Injected order intelligence + DB summary for {agent_name}/{task_name}")
            data_status["Order Intelligence + Customer DB"] = "OK"
        except Exception as e:
            logger.warning(f"Order intelligence fetch failed (non-fatal): {e}")
            data_status["Order Intelligence + Customer DB"] = f"FAILED: {e}"

    # 2b2. Financial data from Xero + Wise for Oracle, PREP, Meridian
    if task_name in perf_data_tasks and agent_name in ("daily-briefing", "strategic-advisor", "dbh-marketing"):
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
**DBH Operations (Xero):** Handled by Tony/ops team. Your role: marketing spend vs results only.
**Tom's Personal Balance (Wise):** For visibility. NOT an operational concern for DBH.

{chr(10).join(financial_parts)}

PREP: Focus only on DBH marketing metrics (spend, ROAS, CAC). Tom's personal Wise balance
is informational only — do NOT flag as a business operational issue.
Oracle: Include DBH financial health (via Xero) in the PERFORMANCE section."""

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
    if task_name in ("morning_briefing", "morning_brief", "weekly_review") and agent_name in ("daily-briefing", "strategic-advisor", "new-business"):
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
            for other_agent in ("global-events", "dbh-marketing", "new-business",
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
    else:
        effective_task_type = task_name
    logger.info(f"Calling Claude for {agent_name}/{task_name}: brain={len(brain)} chars, prompt={len(task_prompt)} chars")
    response = call_claude(brain, task_prompt, task_type=effective_task_type)

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
                                    due_days=14
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

    # Beacon post-processing: save article + create Shopify draft
    if agent_name == "beacon" and task_name == "content_generation":
        try:
            from datetime import date as _d
            import re as _re

            today_str = _d.today().isoformat()
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

    # Send to Telegram
    # Beacon uses command-center channel (no dedicated channel)
    send_chat_id = chat_id
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
        _sched_severity = "IMPORTANT" if task_name in ("morning_briefing", "morning_brief", "morning_protocol", "weekly_review", "weekly_deep_dive", "weekly_plan", "evening_reading") else "NOTABLE" if task_name in ("scan", "model_scan") else "INFO"
        route_notification(send_chat_id, response, bot_token, severity=_sched_severity, agent=agent_name)
    else:
        logger.warning(f"No chat ID configured for {agent_name}, printing to console:")
        print(f"\n{'='*60}")
        print(f"[{agent_name}] {task_name}")
        print(f"{'='*60}")
        print(response)

    logger.info(f"Completed: {agent_name}/{task_name}")


# --- Message Handler (for two-way chat) ---

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
    for other_agent in ("global-events", "dbh-marketing", "new-business",
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

    # 2. Live performance data
    logger.info("PREP inject: fetching performance data...")
    try:
        from core.data_fetcher import fetch_all_performance_data
        perf = fetch_all_performance_data()
        brain += f"\n\n=== LIVE PERFORMANCE DATA ===\n{perf}"
        logger.info(f"PREP inject: performance data OK ({len(perf)} chars)")
    except Exception as e:
        logger.warning(f"PREP inject: performance data FAILED (non-fatal): {e}")

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
    Handle an incoming message from Tom.
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

    logger.info(f"Message from Tom to {agent_name}: {message_text[:50]}...")

    try:
        # Load full brain and respond
        brain = load_agent_brain(agent_name)

        if not brain:
            from core.notification_router import route_notification
            route_notification(chat_id, f"[{agent_name}] Brain failed to load. Check AGENT.md exists.",
                               telegram_config["bot_token"], severity="CRITICAL", agent=agent_name)
            return

        # PREP (strategic-advisor) gets all agent states + data injected
        if agent_name == "strategic-advisor":
            logger.info("PREP: injecting cross-agent context...")
            brain = _inject_prep_context(brain)
            logger.info(f"PREP: brain size after injection: ~{len(brain)//4} tokens")
            task_type = "deep_analysis"  # Uses Opus
        else:
            task_type = "chat"

        # ASI (evening-reading): if Tom asks for a reading, trigger the knowledge engine
        # Otherwise ASI can still chat normally as a life mentor
        if agent_name == "evening-reading":
            reading_triggers = ["reading", "teach", "lesson", "read", "tonight",
                                "give me", "first reading", "what should i learn",
                                "hit me", "go", "start"]
            msg_lower = message_text.lower().strip()
            is_reading_request = any(t in msg_lower for t in reading_triggers)

            if is_reading_request:
                # Trigger a full knowledge-engine reading
                try:
                    from core.knowledge_engine import get_tonight_reading
                    reading = get_tonight_reading()
                    user_prompt = reading["prompt"]
                    logger.info(f"ASI on-demand reading: {reading['primary_concept']} (score: {reading['primary_score']})")
                    task_type = "deep_analysis"  # Use Opus for depth
                    response = call_claude(brain, user_prompt, task_type=task_type)
                except Exception as e:
                    logger.error(f"Knowledge engine failed for on-demand reading: {e}")
                    # Fall through to normal chat
                    is_reading_request = False

            if not is_reading_request:
                # Normal ASI conversation -- life mentor chat
                pending_events = get_pending_events_for_agent(agent_name)
                events_section = f"\n\n{pending_events}" if pending_events else ""
                user_prompt = f"""Tom says: {message_text}
{events_section}
Respond as ASI, Tom's life mentor. You have your full context loaded above.
Be warm but profound. Use stories and analogies. Make non-linear connections.

FORMATTING: Telegram. No tables. Bold with *single asterisks*. Short paragraphs.

After your response, emit [STATE UPDATE: <what to remember>]."""
                response = call_claude(brain, user_prompt, task_type=task_type)
        else:
            # All other agents -- standard chat flow
            # Inject any pending cross-agent events
            pending_events = get_pending_events_for_agent(agent_name)
            events_section = f"\n\n{pending_events}" if pending_events else ""

            user_prompt = f"""Tom says: {message_text}
{events_section}
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

            response = call_claude(brain, user_prompt, task_type=task_type)

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

        # Send response
        sent = send_telegram(chat_id, clean_response, telegram_config["bot_token"])
        if sent:
            logger.info(f"Response from {agent_name} delivered to {chat_id}")
        else:
            logger.error(f"FAILED to deliver {agent_name} response to {chat_id}")

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
    Handle a photo sent by Tom.
    Downloads the image, sends it to Claude Vision with the agent's full brain.
    Wrapped in try/except so Tom ALWAYS gets a reply.
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

        # Load agent brain
        brain = load_agent_brain(agent_name)

        # PREP gets full context for photos too
        task_type = "chat"
        if agent_name == "strategic-advisor":
            brain = _inject_prep_context(brain)
            task_type = "deep_analysis"

        # Build caption prompt
        if caption:
            user_text = f"Tom sent a photo with caption: {caption}\n\nFORMATTING: This goes to Telegram. NEVER use markdown tables. Use bullet points and Label: Value pairs."
        else:
            user_text = "Tom sent a photo. Analyse it in the context of your role and expertise.\n\nFORMATTING: This goes to Telegram. NEVER use markdown tables."

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

        sent = send_telegram(chat_id, clean_response, bot_token)
        if sent:
            logger.info(f"Photo response from {agent_name} delivered")
        else:
            logger.error(f"FAILED to deliver {agent_name} photo response")

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

Agents:
  run <agent-name> -- Trigger an agent's default task
  Example: run dbh-marketing

Agent names: global-events, dbh-marketing, new-business,
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
            "new-business":      ["market.*"],
            "command-center":    ["system.*"],
            "beacon":            ["campaign.*", "content.*"],
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

                    # Security: only respond to Tom
                    if user_id != str(owner_id).strip():
                        logger.warning(f"Ignoring message from unknown user: user_id='{user_id}' vs owner_id='{owner_id}'")
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
                        handle_photo_message(chat_id, photo, caption, bot_token, telegram_config)
                        continue

                    # Handle image documents (screenshots sent as files)
                    doc = message.get("document")
                    if doc and not text:
                        mime = doc.get("mime_type", "")
                        if mime.startswith("image/"):
                            caption = message.get("caption", "")
                            # Wrap as photo-like structure for reuse
                            logger.info(f"Image document received: {doc.get('file_name', 'unknown')}")
                            handle_photo_message(chat_id, [doc], caption, bot_token, telegram_config)
                            continue

                    if text:
                        handle_incoming_message(chat_id, text, telegram_config)

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
