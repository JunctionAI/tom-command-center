#!/usr/bin/env python3
"""
Tom's Command Center -- Core Orchestrator
Routes Telegram messages to specialised agents, each with their own knowledge stack.
Every agent reads its full brain (AGENT.md + skills + playbooks + state) before responding.
"""

import sys
import os

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

    brain = "\n\n".join(brain_parts)

    # Log brain size for monitoring
    token_estimate = len(brain) // 4  # rough estimate
    logger.info(f"Loaded brain for {agent_name}: ~{token_estimate} tokens, "
                f"{len(brain_parts)} sections")

    return brain


def update_agent_state(agent_name: str, new_info: str):
    """Append new information to an agent's state file."""
    state_file = AGENTS_DIR / agent_name / "state" / "CONTEXT.md"
    if state_file.exists():
        current = state_file.read_text(encoding='utf-8')
        # Update the "Last Updated" line
        timestamp = datetime.now().strftime("%B %d, %Y %H:%M")
        if "## Last Updated:" in current:
            lines = current.split("\n")
            for i, line in enumerate(lines):
                if line.startswith("## Last Updated:"):
                    lines[i] = f"## Last Updated: {timestamp}"
                    break
            current = "\n".join(lines)

        # Append new info
        current += f"\n\n## Update {timestamp}\n{new_info}"
        state_file.write_text(current, encoding='utf-8')
        logger.info(f"Updated state for {agent_name}")


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
    if task_type in ("weekly_review", "weekly_deep_dive", "deep_analysis"):
        model = "claude-opus-4-6"

    try:
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}]
        )
        return response.content[0].text
    except Exception as e:
        logger.error(f"Claude API error: {e}")
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
                               task: str = None, input_summary: str = None) -> str:
    """
    After every agent response:
    1. Extract structured insights/decisions/metrics from markers
    2. Log the interaction
    3. Clean markers from the response before sending to Telegram

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
    if task_type in ("weekly_review", "weekly_deep_dive", "deep_analysis"):
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

def send_telegram(chat_id: str, text: str, bot_token: str):
    """Send a message to a Telegram chat."""
    import requests

    if not bot_token:
        logger.error(f"Cannot send to {chat_id}: no bot token")
        return False

    if not text or not text.strip():
        logger.warning(f"Empty message for {chat_id}, skipping")
        return False

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

                status_msg = (
                    f"🔄 *Intelligence Sync Complete*\n"
                    f"Orders today: {order_count}\n"
                    f"DB totals: {total_customers} customers, {total_orders} orders tracked\n"
                    f"_Learning accumulates — next briefing will use updated intelligence._"
                )
                bot_token = telegram_config.get("bot_token", os.environ.get("TELEGRAM_BOT_TOKEN", ""))
                send_telegram(chat_id, status_msg, bot_token)

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
                send_telegram(chat_id, result, bot_token)

            logger.info(f"Replenishment scan complete")
        except Exception as e:
            logger.error(f"Replenishment scan failed: {e}")
        return  # No Claude call needed

    brain = load_agent_brain(agent_name)

    # Build task-specific prompt
    task_prompts = {
        "morning_protocol": "Execute your morning protocol. Generate today's training plan, meal plan, and any notes. Use the format specified in your AGENT.md.",
        "morning_briefing": "Generate the daily master briefing. Read all agent states and synthesise. Use the format specified in your AGENT.md.",
        "morning_brief": "Generate your morning operations brief. Check latest data, flag issues, list priorities. Use the format specified in your AGENT.md.",
        "scan": "Execute your monitoring scan. Search for updates on your watchlist topics. Report only what's NEW since your last scan. Use the format specified in your AGENT.md.",
        "model_scan": "Execute your AI model release scan. Search for new video model announcements, updates to tracked models. If anything could handle action sequences, mark as CRITICAL. Use the format specified in your AGENT.md.",
        "weekly_plan": "Generate your weekly social plan. Review contact list, flag overdue catch-ups, suggest activities. Use the format specified in your AGENT.md.",
        "midweek_checkin": "Mid-week social check-in. Review what was planned, what happened, anything coming up this weekend.",
        "weekly_review": "Execute your weekly performance review. Full data pull, compare to targets, identify patterns, recommend optimisations. Use the format specified in your AGENT.md.",
        "weekly_deep_dive": "Execute your weekly deep analysis. Pick the most important developing story and provide in-depth analysis. Use the format specified in your AGENT.md.",
    }

    task_prompt = task_prompts.get(task_name, f"Execute task: {task_name}")

    # Add cross-agent event and task markers to all scheduled prompts
    task_prompt += """

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
        except Exception as e:
            logger.warning(f"News fetch failed (non-fatal): {e}")

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
        except Exception as e:
            logger.warning(f"Performance data fetch failed (non-fatal): {e}")

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
        except Exception as e:
            logger.warning(f"Order intelligence fetch failed (non-fatal): {e}")

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
        except Exception as e:
            logger.warning(f"Replenishment brief failed (non-fatal): {e}")

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
        except Exception as e:
            logger.warning(f"Exception brief failed (non-fatal): {e}")

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
            dp.close()
        except Exception as e:
            logger.warning(f"Design pipeline status failed (non-fatal): {e}")

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
        except Exception as e:
            logger.warning(f"Asana fetch failed (non-fatal): {e}")

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
        except Exception as e:
            logger.warning(f"Slack fetch failed (non-fatal): {e}")

    # 5. Cross-agent state for Oracle and PREP briefings
    if agent_name in ("daily-briefing", "strategic-advisor") and task_name in ("morning_briefing", "weekly_review"):
        try:
            agent_states = []
            for other_agent in ("global-events", "dbh-marketing", "pure-pets", "new-business",
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
Flag any automation opportunities you spot."""
                else:
                    task_prompt += f"""

=== ALL AGENT STATES (read these to build your cross-domain briefing) ===
{chr(10).join(agent_states)}

Synthesise the above into your unified briefing. Find cross-domain connections.
The daily plan should reference the 90-day execution map from Meridian's intelligence."""
                logger.info(f"Injected {len(agent_states)} agent states for {agent_name} briefing")
        except Exception as e:
            logger.warning(f"Agent state loading failed (non-fatal): {e}")

    # Inject pending cross-agent events
    pending_events = get_pending_events_for_agent(agent_name)
    if pending_events:
        task_prompt += f"\n\n{pending_events}"
        logger.info(f"Injected cross-agent events for {agent_name}")

    # Call Claude with full brain + task
    # PREP always uses Opus -- strategic thinking needs the best model
    effective_task_type = "deep_analysis" if agent_name == "strategic-advisor" else task_name
    response = call_claude(brain, task_prompt, task_type=effective_task_type)

    # Process through learning loop (extract insights, clean markers)
    response = process_response_learning(
        agent_name, response,
        trigger="scheduled",
        task=task_name,
        input_summary=task_prompt
    )

    # Send to Telegram
    chat_id = telegram_config["chat_ids"].get(agent_name)
    if chat_id and chat_id != "CHAT_ID_HERE":
        send_telegram(chat_id, response, telegram_config["bot_token"])
    else:
        logger.warning(f"No chat ID configured for {agent_name}, printing to console:")
        print(f"\n{'='*60}")
        print(f"[{agent_name}] {task_name}")
        print(f"{'='*60}")
        print(response)

    logger.info(f"Completed: {agent_name}/{task_name}")


# --- Message Handler (for two-way chat) ---

def handle_incoming_message(chat_id: str, message_text: str, telegram_config: dict):
    """
    Handle an incoming message from Tom.
    1. Identify which agent based on chat ID
    2. Load that agent's full brain
    3. Call Claude with brain + Tom's message
    4. Run through learning loop
    5. Respond in the same chat
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

    # Load full brain and respond
    brain = load_agent_brain(agent_name)

    # PREP (strategic-advisor) gets all agent states injected -- it sees the full picture
    if agent_name == "strategic-advisor":
        agent_states = []
        for other_agent in ("global-events", "dbh-marketing", "new-business",
                            "health-fitness", "social", "creative-projects", "daily-briefing"):
            state_file = AGENTS_DIR / other_agent / "state" / "CONTEXT.md"
            if state_file.exists():
                content = state_file.read_text(encoding='utf-8')
                agent_states.append(f"--- {other_agent} STATE ---\n{content}")
        if agent_states:
            brain += f"\n\n=== ALL AGENT STATES (you see the full picture) ===\n" + "\n\n".join(agent_states)

        # Also inject live performance data for financial context
        try:
            import signal

            def _timeout_handler(signum, frame):
                raise TimeoutError("Performance data fetch timed out")

            signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(30)  # 30 second timeout
            from core.data_fetcher import fetch_all_performance_data
            perf = fetch_all_performance_data()
            signal.alarm(0)  # Cancel alarm
            brain += f"\n\n=== LIVE PERFORMANCE DATA ===\n{perf}"
        except Exception as e:
            signal.alarm(0)  # Cancel alarm on failure
            logger.warning(f"Performance data fetch failed for PREP (non-fatal): {e}")

        # Use Opus for PREP -- strategic thinking needs the best model
        task_type = "deep_analysis"
    else:
        task_type = "chat"

    # Inject any pending cross-agent events
    pending_events = get_pending_events_for_agent(agent_name)
    events_section = f"\n\n{pending_events}" if pending_events else ""

    user_prompt = f"""Tom says: {message_text}
{events_section}
Respond as your agent character. You have your full context loaded above.
If this message contains information that updates your current state,
note what should be saved at the end of your response with:
[STATE UPDATE: <info to save>]
If you discover something another agent should know, emit:
[EVENT: event.type|SEVERITY|description or json payload]
If something needs to be done, emit:
[TASK: title|priority|description]"""

    response = call_claude(brain, user_prompt, task_type=task_type)

    # Check for API errors before processing
    if response.startswith("API Error:"):
        logger.error(f"Claude API failed for {agent_name}: {response}")
        send_telegram(chat_id, f"PREP is having trouble right now -- API returned an error. Try again in a moment.", telegram_config["bot_token"])
        return

    # Extract and save state updates if present
    if "[STATE UPDATE:" in response:
        parts = response.split("[STATE UPDATE:")
        clean_response = parts[0].strip()
        state_info = parts[1].rstrip("]").strip()
        update_agent_state(agent_name, state_info)
    else:
        clean_response = response

    # Process through learning loop
    clean_response = process_response_learning(
        agent_name, clean_response,
        trigger="message",
        input_summary=message_text
    )

    # Send response
    sent = send_telegram(chat_id, clean_response, telegram_config["bot_token"])
    if sent:
        logger.info(f"Response from {agent_name} delivered to {chat_id}")
    else:
        logger.error(f"FAILED to deliver {agent_name} response to {chat_id}")


def handle_photo_message(chat_id: str, photo_sizes: list, caption: str,
                         bot_token: str, telegram_config: dict):
    """
    Handle a photo sent by Tom.
    Downloads the image, sends it to Claude Vision with the agent's full brain.
    """
    agent_name = identify_agent_from_chat(chat_id, telegram_config)
    if not agent_name:
        logger.warning(f"Photo from unknown chat ID: {chat_id}")
        return

    # Download the photo
    image_b64, media_type = download_telegram_photo(photo_sizes, bot_token)
    if not image_b64:
        send_telegram(chat_id, "[Could not download photo]", bot_token)
        return

    # Load agent brain
    brain = load_agent_brain(agent_name)

    # Build caption prompt
    if caption:
        user_text = f"Tom sent a photo with caption: {caption}"
    else:
        user_text = "Tom sent a photo. Analyse it in the context of your role and expertise."

    # Call Claude with vision
    response = call_claude_vision(brain, image_b64, media_type, user_text)

    # Extract and save state updates if present
    if "[STATE UPDATE:" in response:
        parts = response.split("[STATE UPDATE:")
        clean_response = parts[0].strip()
        state_info = parts[1].rstrip("]").strip()
        update_agent_state(agent_name, state_info)
    else:
        clean_response = response

    # Process through learning loop
    clean_response = process_response_learning(
        agent_name, clean_response,
        trigger="photo",
        input_summary=f"[Photo] {caption}" if caption else "[Photo]"
    )

    send_telegram(chat_id, clean_response, bot_token)


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

        send_telegram(chat_id, "\n".join(status_lines), bot_token)

    elif cmd.startswith("run "):
        agent_to_run = cmd.split("run ", 1)[1].strip()
        if agent_to_run in telegram_config["chat_ids"]:
            run_scheduled_task(agent_to_run, "morning_brief", telegram_config)
            send_telegram(chat_id, f"Triggered {agent_to_run}", bot_token)
        else:
            send_telegram(chat_id, f"Unknown agent: {agent_to_run}", bot_token)

    elif cmd == "db stats":
        # Show learning database statistics
        db = get_learning_db()
        if db:
            lines = ["Learning Database Stats\n"]
            for table in ['insights', 'decisions', 'metrics', 'patterns', 'interactions']:
                count = db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                lines.append(f"  {table}: {count} rows")
            send_telegram(chat_id, "\n".join(lines), bot_token)
        else:
            send_telegram(chat_id, "Learning DB not available", bot_token)

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

        send_telegram(chat_id, "\n".join(lines), bot_token)

    else:
        # Pass to Claude for natural language command handling
        brain = load_agent_brain("command-center")
        response = call_claude(brain, f"Tom's command: {command}")
        response = process_response_learning("command-center", response, trigger="command", input_summary=command)
        send_telegram(chat_id, response, bot_token)


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

                    message = update.get("message", {})
                    text = message.get("text", "")
                    chat_id = str(message.get("chat", {}).get("id", ""))
                    user_id = str(message.get("from", {}).get("id", ""))

                    # Security: only respond to Tom
                    if user_id != str(owner_id):
                        logger.warning(f"Ignoring message from unknown user: {user_id}")
                        continue

                    # Handle voice messages
                    voice = message.get("voice") or message.get("audio")
                    if voice and not text:
                        file_id = voice.get("file_id")
                        if file_id:
                            logger.info(f"Voice message received, transcribing...")
                            text = transcribe_voice(file_id, bot_token)
                            if text and not text.startswith("["):
                                # Prefix so the agent knows it was voice
                                text = f"[Voice message] {text}"

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
