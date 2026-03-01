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
    return response.strip()


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

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    # Telegram has a 4096 char limit per message
    if len(text) > 4000:
        # Split into chunks
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            requests.post(url, json={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown"
            })
    else:
        requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "Markdown"
        })


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
    if task_name in perf_data_tasks and agent_name in ("daily-briefing", "dbh-marketing"):
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
    if task_name in perf_data_tasks and agent_name in ("daily-briefing", "dbh-marketing"):
        try:
            from core.order_intelligence import fetch_order_intelligence
            days = 7 if task_name == "weekly_review" else 1
            order_data = fetch_order_intelligence(days)
            task_prompt += f"""

{order_data}

IMPORTANT: Analyse each individual order. What caused each sale? What does the customer
profile tell us? Identify patterns: which channels drive highest AOV, which bring new vs
returning customers, which campaigns are working. Flag any unattributed orders.
For returning customers, note their LTV trajectory and what product they keep buying."""
            logger.info(f"Injected order intelligence for {agent_name}/{task_name}")
        except Exception as e:
            logger.warning(f"Order intelligence fetch failed (non-fatal): {e}")

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

    # 5. Cross-agent state for Oracle master briefing
    if agent_name == "daily-briefing" and task_name == "morning_briefing":
        try:
            agent_states = []
            for other_agent in ("global-events", "dbh-marketing", "new-business",
                                "health-fitness", "social", "creative-projects"):
                state_file = AGENTS_DIR / other_agent / "state" / "CONTEXT.md"
                if state_file.exists():
                    content = state_file.read_text(encoding='utf-8')
                    agent_states.append(f"--- {other_agent} STATE ---\n{content}")
            if agent_states:
                task_prompt += f"""

=== ALL AGENT STATES (read these to build your cross-domain briefing) ===
{chr(10).join(agent_states)}

Synthesise the above into your unified briefing. Find cross-domain connections.
The daily plan should reference the 90-day execution map from Meridian's intelligence."""
                logger.info(f"Injected {len(agent_states)} agent states for Oracle briefing")
        except Exception as e:
            logger.warning(f"Agent state loading failed (non-fatal): {e}")

    # Call Claude with full brain + task
    response = call_claude(brain, task_prompt, task_type=task_name)

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
        for other_agent in ("global-events", "dbh-marketing", "pure-pets", "new-business",
                            "health-fitness", "social", "creative-projects", "daily-briefing"):
            state_file = AGENTS_DIR / other_agent / "state" / "CONTEXT.md"
            if state_file.exists():
                content = state_file.read_text(encoding='utf-8')
                agent_states.append(f"--- {other_agent} STATE ---\n{content}")
        if agent_states:
            brain += f"\n\n=== ALL AGENT STATES (you see the full picture) ===\n" + "\n\n".join(agent_states)

        # Also inject live performance data for financial context
        try:
            from core.data_fetcher import fetch_all_performance_data
            perf = fetch_all_performance_data()
            brain += f"\n\n=== LIVE PERFORMANCE DATA ===\n{perf}"
        except Exception:
            pass

        # Use Opus for PREP -- strategic thinking needs the best model
        task_type = "deep_analysis"
    else:
        task_type = "chat"

    user_prompt = f"""Tom says: {message_text}

Respond as your agent character. You have your full context loaded above.
If this message contains information that updates your current state,
note what should be saved at the end of your response with:
[STATE UPDATE: <info to save>]"""

    response = call_claude(brain, user_prompt, task_type=task_type)

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
    send_telegram(chat_id, clean_response, telegram_config["bot_token"])


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
