#!/usr/bin/env python3
"""
Slack Client -- Monitors channels, reads activity, posts updates.
Used by Oracle for morning briefings and by agents for cross-team awareness.

Capabilities:
- Read recent messages from monitored channels
- Detect task completions ("done", "shipped", "launched", etc.)
- Post briefings or updates to Slack
- Format overnight activity for morning briefing
"""

import os
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


class SlackClient:
    """Lightweight Slack Web API client using requests."""

    BASE_URL = "https://slack.com/api"

    # Keywords that signal task completion
    DONE_KEYWORDS = [
        "done", "completed", "shipped", "launched", "live", "deployed",
        "finished", "sent", "published", "approved", "signed off",
        "uploaded", "merged", "resolved", "fixed", "built",
    ]

    def __init__(self):
        self.token = os.environ.get("SLACK_BOT_TOKEN")
        # Comma-separated channel IDs to monitor
        self.channel_ids = [
            c.strip() for c in
            os.environ.get("SLACK_CHANNEL_IDS", "").split(",")
            if c.strip()
        ]

    @property
    def available(self) -> bool:
        return bool(self.token)

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json; charset=utf-8"
        }

    def _get(self, method: str, params: dict = None):
        import requests
        resp = requests.get(f"{self.BASE_URL}/{method}",
                           headers=self.headers, params=params, timeout=15)
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Slack API error ({method}): {data.get('error', 'unknown')}")
        return data

    def _post(self, method: str, payload: dict):
        import requests
        resp = requests.post(f"{self.BASE_URL}/{method}",
                            headers=self.headers, json=payload, timeout=15)
        data = resp.json()
        if not data.get("ok"):
            logger.error(f"Slack API error ({method}): {data.get('error', 'unknown')}")
        return data

    # --- Read Channels ---

    def get_channel_history(self, channel_id: str, hours: int = 24, limit: int = 50) -> list:
        """Get recent messages from a channel."""
        if not self.available:
            return []

        oldest = (datetime.utcnow() - timedelta(hours=hours)).timestamp()
        data = self._get("conversations.history", {
            "channel": channel_id,
            "oldest": str(oldest),
            "limit": limit
        })
        return data.get("messages", [])

    def get_channel_info(self, channel_id: str) -> dict:
        """Get channel name and metadata."""
        if not self.available:
            return {}
        data = self._get("conversations.info", {"channel": channel_id})
        return data.get("channel", {})

    def list_channels(self) -> list:
        """List all channels the bot can see."""
        if not self.available:
            return []
        data = self._get("conversations.list", {
            "types": "public_channel,private_channel",
            "limit": 100
        })
        return data.get("channels", [])

    def get_user_name(self, user_id: str) -> str:
        """Resolve a user ID to a display name."""
        if not self.available:
            return user_id
        data = self._get("users.info", {"user": user_id})
        user = data.get("user", {})
        return user.get("real_name") or user.get("name") or user_id

    # --- Post Messages ---

    def post_message(self, channel_id: str, text: str) -> bool:
        """Post a message to a channel."""
        if not self.available:
            return False
        data = self._post("chat.postMessage", {
            "channel": channel_id,
            "text": text
        })
        return data.get("ok", False)

    # --- Activity Analysis ---

    def detect_completions(self, messages: list) -> list:
        """Scan messages for task completion signals."""
        completions = []
        for msg in messages:
            text = msg.get("text", "").lower()
            if any(kw in text for kw in self.DONE_KEYWORDS):
                completions.append({
                    "user": msg.get("user", "unknown"),
                    "text": msg.get("text", ""),
                    "ts": msg.get("ts", ""),
                    "time": datetime.fromtimestamp(float(msg.get("ts", 0))).strftime("%H:%M")
                                if msg.get("ts") else ""
                })
        return completions

    def get_overnight_activity(self, hours: int = 16) -> dict:
        """
        Get activity summary across all monitored channels.
        Default 16 hours = covers from 5pm yesterday to 9am today.
        """
        if not self.available or not self.channel_ids:
            return {}

        activity = {}
        user_cache = {}

        for ch_id in self.channel_ids:
            try:
                info = self.get_channel_info(ch_id)
                ch_name = info.get("name", ch_id)

                messages = self.get_channel_history(ch_id, hours=hours)
                if not messages:
                    continue

                # Resolve user names (with cache)
                for msg in messages:
                    uid = msg.get("user", "")
                    if uid and uid not in user_cache:
                        user_cache[uid] = self.get_user_name(uid)

                completions = self.detect_completions(messages)

                activity[ch_name] = {
                    "message_count": len(messages),
                    "completions": completions,
                    "messages": messages,
                    "user_cache": user_cache
                }
            except Exception as e:
                logger.warning(f"Failed to read channel {ch_id}: {e}")

        return activity

    # --- Briefing Formatter ---

    def format_briefing_summary(self, hours: int = 16) -> str:
        """
        Format Slack activity for the morning briefing.
        Shows: message counts, who's active, task completions detected.
        """
        if not self.available:
            return "[Slack data unavailable -- set SLACK_BOT_TOKEN and SLACK_CHANNEL_IDS]"

        if not self.channel_ids:
            return "[Slack monitoring not configured -- set SLACK_CHANNEL_IDS]"

        try:
            activity = self.get_overnight_activity(hours)

            if not activity:
                return f"SLACK -- No activity in monitored channels (last {hours}hrs)"

            lines = [
                f"SLACK -- Activity Summary (last {hours}hrs)",
            ]

            total_messages = 0
            total_completions = 0
            all_completions = []

            for ch_name, data in activity.items():
                msg_count = data["message_count"]
                completions = data["completions"]
                total_messages += msg_count
                total_completions += len(completions)

                lines.append(f"  #{ch_name}: {msg_count} messages")

                for comp in completions:
                    user = data["user_cache"].get(comp["user"], comp["user"])
                    text_preview = comp["text"][:80]
                    all_completions.append(f"    [{comp['time']}] {user}: {text_preview}")

            lines.insert(1, f"  Total: {total_messages} messages across {len(activity)} channels")

            if all_completions:
                lines.append("")
                lines.append(f"  COMPLETIONS DETECTED ({total_completions}):")
                lines.extend(all_completions)

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Slack summary error: {e}")
            return f"[Slack error: {str(e)}]"


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    client = SlackClient()
    if not client.available:
        print("SLACK_BOT_TOKEN not set")
        print()
        print("Setup:")
        print("1. Go to https://api.slack.com/apps > Create New App")
        print("2. From Scratch > name it 'Tom Command Center' > select workspace")
        print("3. OAuth & Permissions > Bot Token Scopes > add:")
        print("   channels:history, channels:read, chat:write, users:read")
        print("4. Install to Workspace > copy Bot User OAuth Token")
        print("5. Set SLACK_BOT_TOKEN=xoxb-... in Railway env vars")
        print("6. Set SLACK_CHANNEL_IDS=C0123,C0456 (comma-separated channel IDs)")
        print()
        print("To find channel IDs: right-click channel > View channel details > scroll to bottom")
        sys.exit(1)

    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "channels":
            for ch in client.list_channels():
                print(f"  {ch['id']:12s} #{ch['name']}")
        elif cmd == "summary":
            print(client.format_briefing_summary())
        elif cmd == "history" and len(sys.argv) > 2:
            ch_id = sys.argv[2]
            messages = client.get_channel_history(ch_id, hours=24)
            for msg in messages:
                print(f"  [{msg.get('ts', '')}] {msg.get('text', '')[:100]}")
        elif cmd == "post" and len(sys.argv) > 3:
            ch_id = sys.argv[2]
            text = " ".join(sys.argv[3:])
            client.post_message(ch_id, text)
        else:
            print("Commands: channels, summary, history <channel_id>, post <channel_id> <text>")
    else:
        print(client.format_briefing_summary())
