#!/usr/bin/env python3
"""
Recover Asclepius (and any agent) conversation history from Telegram.

Telegram Bot API Limitations:
- getUpdates: Only returns UNPROCESSED updates (max 24h buffer). Once the polling
  loop acknowledges an update (by sending offset+1), it's gone forever from getUpdates.
- Bot API has NO method to retrieve historical messages from a chat.
- Only the Telegram CLIENT API (using user accounts via Telethon/Pyrogram) can
  fetch chat history. The Bot API cannot.

This script tries two approaches:
1. getUpdates -- grab any unprocessed messages (unlikely to have old ones)
2. getChatHistory via Telegram Client API (MTProto) -- requires user auth (api_id + api_hash)

For approach 2, you need:
- Go to https://my.telegram.org/apps
- Create an app -> get api_id and api_hash
- Run this script with --client mode (will prompt for phone number + OTP once)
"""

import os
import sys
import json
import requests
from datetime import datetime, timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"


def get_bot_token():
    """Get bot token from environment or .env file."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if token:
        return token

    # Try .env file
    env_file = BASE_DIR / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("TELEGRAM_BOT_TOKEN="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")

    # Try Railway-style env
    for env_path in [Path.home() / ".env", BASE_DIR / ".env.local"]:
        if env_path.exists():
            for line in env_path.read_text().splitlines():
                if line.startswith("TELEGRAM_BOT_TOKEN="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")

    return None


def load_telegram_config():
    config_path = CONFIG_DIR / "telegram.json"
    with open(config_path, "r") as f:
        config = json.load(f)
    return config


def try_get_updates(bot_token):
    """
    Attempt 1: Use getUpdates to fetch any pending messages.
    This will only return messages that haven't been acknowledged yet.
    If the bot is running on Railway and polling, this returns nothing.
    """
    print("\n--- Approach 1: getUpdates (unacknowledged messages only) ---")
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates"

    # Don't pass offset -- get everything available
    resp = requests.post(url, json={"timeout": 5, "limit": 100}, timeout=15)
    data = resp.json()

    if not data.get("ok"):
        print(f"  ERROR: {data.get('description', 'Unknown error')}")
        return []

    results = data.get("result", [])
    print(f"  Found {len(results)} pending update(s)")

    messages = []
    for update in results:
        msg = update.get("message", {})
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = msg.get("text", "")
        date = msg.get("date", 0)
        from_user = msg.get("from", {})
        dt = datetime.fromtimestamp(date) if date else None

        messages.append({
            "chat_id": chat_id,
            "text": text,
            "date": dt.isoformat() if dt else "unknown",
            "from": from_user.get("first_name", "unknown"),
            "is_bot": from_user.get("is_bot", False),
        })

        if text:
            print(f"  [{dt}] chat={chat_id} from={from_user.get('first_name', '?')}: {text[:80]}...")

    return messages


def try_forward_messages(bot_token, source_chat_id, target_chat_id=None):
    """
    Attempt 2: Use forwardMessages to test if we can access specific message IDs.
    Bots CAN read messages by ID if they have access to the chat.
    We try sequential message IDs to find recent ones.
    """
    print("\n--- Approach 2: Probe message IDs via copyMessage ---")
    print(f"  Probing chat: {source_chat_id}")

    # Try to get chat info first
    url = f"https://api.telegram.org/bot{bot_token}/getChat"
    resp = requests.post(url, json={"chat_id": source_chat_id}, timeout=10)
    chat_data = resp.json()
    if chat_data.get("ok"):
        chat_info = chat_data["result"]
        print(f"  Chat title: {chat_info.get('title', 'N/A')}")
        print(f"  Chat type: {chat_info.get('type', 'N/A')}")
    else:
        print(f"  Could not get chat info: {chat_data.get('description')}")
        return


def try_get_chat_member_count(bot_token, chat_id):
    """Get member count to verify bot has access."""
    url = f"https://api.telegram.org/bot{bot_token}/getChatMemberCount"
    resp = requests.post(url, json={"chat_id": chat_id}, timeout=10)
    return resp.json()


def scan_all_chats_for_history(bot_token, config):
    """
    Attempt 3: Use getUpdates with a very old offset to try to get historical updates.
    Also test chat access for all configured chats.
    """
    print("\n--- Approach 3: Verify bot access to Asclepius chat ---")
    asclepius_chat_id = config["chat_ids"].get("asclepius-brain")
    if not asclepius_chat_id:
        print("  ERROR: No asclepius-brain chat ID in config")
        return

    # Verify chat access
    result = try_get_chat_member_count(bot_token, asclepius_chat_id)
    if result.get("ok"):
        print(f"  Bot has access to Asclepius chat ({asclepius_chat_id}), {result['result']} members")
    else:
        print(f"  Bot CANNOT access Asclepius chat: {result.get('description')}")

    # Try getChat for more info
    url = f"https://api.telegram.org/bot{bot_token}/getChat"
    resp = requests.post(url, json={"chat_id": asclepius_chat_id}, timeout=10)
    data = resp.json()
    if data.get("ok"):
        chat = data["result"]
        print(f"  Chat title: {chat.get('title', 'N/A')}")
        print(f"  Chat type: {chat.get('type', 'N/A')}")
        # Pinned message might contain useful info
        pinned = chat.get("pinned_message")
        if pinned:
            print(f"  Pinned message: {pinned.get('text', '(no text)')[:200]}")
    else:
        print(f"  getChat failed: {data.get('description')}")


def try_search_messages_via_admin(bot_token, chat_id):
    """
    Attempt 4: Some group admin features. Check if bot is admin.
    """
    print("\n--- Approach 4: Check bot admin status ---")
    # Get bot's own info
    url = f"https://api.telegram.org/bot{bot_token}/getMe"
    resp = requests.get(url, timeout=10)
    me = resp.json()
    if me.get("ok"):
        bot_id = me["result"]["id"]
        bot_name = me["result"].get("username", "unknown")
        print(f"  Bot: @{bot_name} (ID: {bot_id})")

        # Check bot's membership status
        url2 = f"https://api.telegram.org/bot{bot_token}/getChatMember"
        resp2 = requests.post(url2, json={"chat_id": chat_id, "user_id": bot_id}, timeout=10)
        member = resp2.json()
        if member.get("ok"):
            status = member["result"].get("status", "unknown")
            print(f"  Bot status in Asclepius chat: {status}")
            if status == "administrator":
                print("  Bot IS admin -- but Bot API still has no getChatHistory method")
            else:
                print("  Bot is NOT admin -- making it admin won't help for history retrieval")
        else:
            print(f"  Could not check membership: {member.get('description')}")


def print_client_api_instructions():
    """Print instructions for using Telegram Client API (the only way to get history)."""
    print("\n" + "=" * 70)
    print("TELEGRAM CLIENT API -- THE ONLY WAY TO RETRIEVE CHAT HISTORY")
    print("=" * 70)
    print("""
The Telegram BOT API has NO method to retrieve historical messages.
getUpdates only returns unacknowledged messages (already consumed by Railway).

To retrieve the last 9 days of Asclepius conversations, you need the
Telegram CLIENT API (MTProto), which uses your personal Telegram account.

STEPS:

1. Get API credentials:
   - Go to https://my.telegram.org/apps
   - Log in with your phone number
   - Create a new application (any name)
   - Note the api_id (number) and api_hash (string)

2. Install Telethon:
   pip install telethon

3. Run this script with --client flag:
   python scripts/recover_asclepius_history.py --client

   It will prompt for:
   - api_id
   - api_hash
   - Your phone number (for Telegram login)
   - OTP code (sent to your Telegram)

4. The script will then pull ALL messages from the Asclepius chat
   for the last 14 days and save them to:
   agents/asclepius-brain/state/recovered-history.md

NOTE: This uses YOUR personal Telegram account (not the bot).
The session file is saved locally and reused, so you only auth once.
""")


def recover_via_client_api(api_id, api_hash, chat_ids_map, agent_names_map, days_back=14, agents=None):
    """
    Use Telethon (Telegram Client API) to retrieve actual chat history.
    This is the ONLY way to get historical messages.

    agents: list of agent IDs to recover, or None for all.
    """
    try:
        from telethon import TelegramClient
    except ImportError:
        print("ERROR: telethon not installed. Run: pip install telethon")
        return None

    session_path = str(BASE_DIR / "data" / "telegram_recovery_session")
    client = TelegramClient(session_path, api_id, api_hash)

    # Filter to requested agents
    if agents:
        targets = {a: chat_ids_map[a] for a in agents if a in chat_ids_map}
    else:
        targets = dict(chat_ids_map)

    all_recovered = {}

    async def _fetch():
        await client.start()
        me = await client.get_me()
        print(f"  Connected as: {me.first_name}")

        for agent_id, chat_id in targets.items():
            agent_name = agent_names_map.get(agent_id, agent_id)
            print(f"\n  Recovering {agent_name} ({agent_id}) from chat {chat_id}...")

            try:
                entity = await client.get_entity(int(chat_id))
                print(f"    Chat: {getattr(entity, 'title', 'N/A')}")
            except Exception as e:
                print(f"    SKIP -- cannot access chat: {e}")
                continue

            cutoff = datetime.now() - timedelta(days=days_back)
            messages = []

            async for msg in client.iter_messages(entity, offset_date=datetime.now(), reverse=False):
                if msg.date.replace(tzinfo=None) < cutoff:
                    break
                messages.append({
                    "id": msg.id,
                    "date": msg.date.isoformat(),
                    "from_id": msg.sender_id,
                    "text": msg.text or "(media/no text)",
                    "is_bot": getattr(msg.sender, "bot", False) if msg.sender else None,
                })

            messages.reverse()  # Chronological order
            print(f"    Retrieved {len(messages)} messages")
            all_recovered[agent_id] = messages

    import asyncio
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(_fetch())

    # Save each agent's history
    for agent_id, messages in all_recovered.items():
        if not messages:
            continue

        agent_name = agent_names_map.get(agent_id, agent_id)
        state_dir = BASE_DIR / "agents" / agent_id / "state"
        state_dir.mkdir(parents=True, exist_ok=True)
        output_path = state_dir / "recovered-history.md"

        lines = [f"# Recovered {agent_name} Chat History\n"]
        lines.append(f"Retrieved: {datetime.now().isoformat()}")
        lines.append(f"Period: Last {days_back} days ({len(messages)} messages)\n")

        current_date = None
        for msg in messages:
            msg_date = msg["date"][:10]
            if msg_date != current_date:
                current_date = msg_date
                lines.append(f"\n---\n### {current_date}\n")

            sender = f"BOT ({agent_name})" if msg.get("is_bot") else "Tom"
            lines.append(f"**[{msg['date'][11:19]}] {sender}:**\n{msg['text']}\n")

        output_path.write_text("\n".join(lines), encoding="utf-8")
        print(f"  Saved {agent_id}: {output_path} ({len(messages)} msgs)")

    total = sum(len(m) for m in all_recovered.values())
    print(f"\nTotal recovered: {total} messages across {len(all_recovered)} agents")
    return all_recovered


def main():
    bot_token = get_bot_token()
    config = load_telegram_config()

    if not bot_token:
        print("ERROR: No TELEGRAM_BOT_TOKEN found.")
        print("Set it via environment variable or .env file.")
        print("The bot token is stored on Railway -- check Railway dashboard > Variables.")
        sys.exit(1)

    chat_ids = config.get("chat_ids", {})
    agent_names = config.get("agent_names", {})
    asclepius_chat_id = chat_ids.get("asclepius-brain", "")
    print(f"Asclepius chat ID: {asclepius_chat_id}")
    print(f"Bot token: ...{bot_token[-8:]}")

    if "--client" in sys.argv:
        # Client API mode -- the real recovery
        api_id = input("Enter api_id: ").strip()
        api_hash = input("Enter api_hash: ").strip()

        # Recover specific agents or all
        if "--all" in sys.argv:
            print("\nRecovering ALL agent histories...")
            recover_via_client_api(int(api_id), api_hash, chat_ids, agent_names)
        elif "--agent" in sys.argv:
            idx = sys.argv.index("--agent")
            agent_list = sys.argv[idx + 1].split(",")
            print(f"\nRecovering: {', '.join(agent_list)}")
            recover_via_client_api(int(api_id), api_hash, chat_ids, agent_names, agents=agent_list)
        else:
            # Default: just Asclepius
            print("\nRecovering Asclepius history (use --all for all agents)...")
            recover_via_client_api(int(api_id), api_hash, chat_ids, agent_names, agents=["asclepius-brain"])
        return

    # Bot API attempts (limited)
    try_get_updates(bot_token)
    try_forward_messages(bot_token, asclepius_chat_id)
    scan_all_chats_for_history(bot_token, config)
    try_search_messages_via_admin(bot_token, asclepius_chat_id)

    # Print the real solution
    print_client_api_instructions()


if __name__ == "__main__":
    main()
