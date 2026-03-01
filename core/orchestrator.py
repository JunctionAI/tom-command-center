#!/usr/bin/env python3
"""
Tom's Command Center â€” Core Orchestrator
Routes Telegram messages to specialised agents, each with their own knowledge stack.
Every agent reads its full brain (AGENT.md + skills + playbooks + state) before responding.
"""

import json
import os
import subprocess
import logging
from pathlib import Path
from datetime import datetime

# â”€â”€â”€ Configuration â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

BASE_DIR = Path(__file__).resolve().parent.parent
AGENTS_DIR = BASE_DIR / "agents"
CONFIG_DIR = BASE_DIR / "config"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(BASE_DIR / "orchestrator.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def load_config():
    """Load telegram and schedule configs."""
    with open(CONFIG_DIR / "telegram.json") as f:
        telegram_config = json.load(f)
    with open(CONFIG_DIR / "schedules.json") as f:
        schedule_config = json.load(f)
    return telegram_config, schedule_config


# â”€â”€â”€ Agent Brain Loader â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# THIS IS THE KEY FUNCTION. Every time an agent speaks, it reads its entire
# knowledge stack first. Same pattern as DBH AIOS CLAUDE.md session startup.

def load_agent_brain(agent_name: str) -> str:
    """
    Load the full brain for an agent. This is the equivalent of the
    CLAUDE.md session startup â€” read identity, skills, playbooks, state.
    
    Returns a complete system prompt that makes the agent fully contextualised.
    """
    agent_dir = AGENTS_DIR / agent_name
    brain_parts = []
    
    # 1. IDENTITY â€” Always read AGENT.md first (equivalent to CLAUDE.md)
    agent_md = agent_dir / "AGENT.md"
    if agent_md.exists():
        brain_parts.append(f"=== AGENT IDENTITY ===\n{agent_md.read_text(encoding='utf-8')}")
    else:
        logger.error(f"No AGENT.md found for {agent_name}")
        return ""
    
    # 2. TRAINING â€” Deep domain knowledge (mental models, frameworks, anti-patterns)
    training_dir = agent_dir / "training"
    if training_dir.exists():
        training_files = sorted(training_dir.glob("*.md"))
        if training_files:
            brain_parts.append("=== TRAINING (WORLD-CLASS DOMAIN KNOWLEDGE) ===")
            for f in training_files:
                brain_parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
    
    # 3. PLAYBOOKS â€” Proven patterns, always load (highest priority knowledge)
    playbooks_dir = agent_dir / "playbooks"
    if playbooks_dir.exists():
        playbook_files = sorted(playbooks_dir.glob("*.md"))
        if playbook_files:
            brain_parts.append("=== PLAYBOOKS (PROVEN PATTERNS â€” HIGHEST PRIORITY) ===")
            for f in playbook_files:
                brain_parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
    
    # 3. SKILLS â€” Domain expertise, load all for this agent
    skills_dir = agent_dir / "skills"
    if skills_dir.exists():
        skill_files = sorted(skills_dir.glob("*.md"))
        if skill_files:
            brain_parts.append("=== SKILLS (DOMAIN EXPERTISE) ===")
            for f in skill_files:
                brain_parts.append(f"--- {f.name} ---\n{f.read_text(encoding='utf-8')}")
    
    # 4. INTELLIGENCE â€” Latest periodic research/reports
    intel_dir = agent_dir / "intelligence"
    if intel_dir.exists():
        intel_files = sorted(intel_dir.glob("*.md"), reverse=True)  # newest first
        if intel_files:
            # Only load the most recent intelligence file to save context
            brain_parts.append(f"=== LATEST INTELLIGENCE ===\n--- {intel_files[0].name} ---\n{intel_files[0].read_text(encoding='utf-8')}")
    
    # 5. STATE â€” Current context, what's happening now (always load)
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
        state_file.write_text(current)
        logger.info(f"Updated state for {agent_name}")


# â”€â”€â”€ Claude API Caller â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
    model = "claude-sonnet-4-5-20250929"
    if task_type in ("weekly_review", "weekly_deep_dive", "deep_analysis"):
        model = "claude-opus-4-5-20250929"
    
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
        return f"âš ï¸ API Error: {str(e)}"


# â”€â”€â”€ Claude Code Caller (Alternative â€” uses local Claude Code CLI) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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
        return "âš ï¸ Claude Code timed out"
    except FileNotFoundError:
        return "âš ï¸ Claude Code CLI not found â€” install with: npm install -g @anthropic-ai/claude-code"
    except Exception as e:
        return f"âš ï¸ Error: {str(e)}"


# â”€â”€â”€ Telegram Handler â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

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


# â”€â”€â”€ Scheduled Task Runner â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def run_scheduled_task(agent_name: str, task_name: str, telegram_config: dict):
    """
    Execute a scheduled task for an agent.
    1. Load agent brain
    2. Build task prompt
    3. Call Claude
    4. Post to Telegram
    5. Update state
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
    
    # Call Claude with full brain + task
    response = call_claude(brain, task_prompt, task_type=task_name)
    
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


# â”€â”€â”€ Message Handler (for two-way chat) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def handle_incoming_message(chat_id: str, message_text: str, telegram_config: dict):
    """
    Handle an incoming message from Tom.
    1. Identify which agent based on chat ID
    2. Load that agent's full brain
    3. Call Claude with brain + Tom's message
    4. Respond in the same chat
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
    
    user_prompt = f"""Tom says: {message_text}

Respond as your agent character. You have your full context loaded above.
If this message contains information that updates your current state, 
note what should be saved at the end of your response with:
[STATE UPDATE: <info to save>]"""
    
    response = call_claude(brain, user_prompt)
    
    # Extract and save state updates if present
    if "[STATE UPDATE:" in response:
        parts = response.split("[STATE UPDATE:")
        response = parts[0].strip()
        state_info = parts[1].rstrip("]").strip()
        update_agent_state(agent_name, state_info)
    
    # Send response
    send_telegram(chat_id, response, telegram_config["bot_token"])


def handle_command(command: str, telegram_config: dict):
    """Handle Nexus command center commands."""
    cmd = command.strip().lower()
    chat_id = telegram_config["chat_ids"].get("command-center")
    bot_token = telegram_config["bot_token"]
    
    if cmd == "status":
        # Show all agent statuses
        status_lines = ["ðŸ¤– NEXUS â€” System Status\n"]
        for agent_name in telegram_config["agent_names"]:
            display_name = telegram_config["agent_names"][agent_name]
            state_file = AGENTS_DIR / agent_name / "state" / "CONTEXT.md"
            if state_file.exists():
                content = state_file.read_text(encoding='utf-8')
                # Extract last updated
                for line in content.split("\n"):
                    if "Last Updated" in line:
                        status_lines.append(f"âœ… {display_name} ({agent_name}): {line.split(':',1)[1].strip()}")
                        break
                else:
                    status_lines.append(f"âšª {display_name} ({agent_name}): No timestamp")
            else:
                status_lines.append(f"âŒ {display_name} ({agent_name}): No state file")
        
        send_telegram(chat_id, "\n".join(status_lines), bot_token)
    
    elif cmd.startswith("run "):
        agent_to_run = cmd.split("run ", 1)[1].strip()
        if agent_to_run in telegram_config["chat_ids"]:
            run_scheduled_task(agent_to_run, "morning_brief", telegram_config)
            send_telegram(chat_id, f"âœ… Triggered {agent_to_run}", bot_token)
        else:
            send_telegram(chat_id, f"âŒ Unknown agent: {agent_to_run}", bot_token)
    
    else:
        # Pass to Claude for natural language command handling
        brain = load_agent_brain("command-center")
        response = call_claude(brain, f"Tom's command: {command}")
        send_telegram(chat_id, response, bot_token)


# â”€â”€â”€ Telegram Polling Loop â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def start_polling(telegram_config: dict):
    """Simple long-polling loop for Telegram updates."""
    import requests
    import time
    
    bot_token = telegram_config["bot_token"]
    owner_id = telegram_config["owner_user_id"]
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"
    offset = 0
    
    logger.info("Starting Telegram polling loop...")
    
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
                    
                    if text:
                        handle_incoming_message(chat_id, text, telegram_config)
        
        except requests.exceptions.Timeout:
            continue
        except Exception as e:
            logger.error(f"Polling error: {e}")
            time.sleep(5)


# â”€â”€â”€ Entry Point â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

if __name__ == "__main__":
    import sys
    
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
        
        else:
            print(f"Unknown command: {command}")
            print("Commands: poll, run <agent> <task>, test <agent>, brains")
    
    else:
        print("Tom's Command Center â€” Orchestrator")
        print("Commands:")
        print("  python orchestrator.py poll              â€” Start Telegram listener")
        print("  python orchestrator.py run <agent> <task> â€” Run a scheduled task")
        print("  python orchestrator.py test <agent>       â€” Test agent brain loading")
        print("  python orchestrator.py brains             â€” Show all agent brain sizes")

