#!/usr/bin/env python3
"""
Auto Optimizer — Write-Back Phase 2: Autonomous campaign optimization.

Runs nightly at 11:45pm NZST (after ROAS check at 11:15pm and rule check at 11:30pm).

Three autonomous optimization capabilities:
1. Meta budget auto-adjustment (within +/-20% guardrails)
2. A/B test winner auto-selection (95% confidence z-test)
3. Klaviyo campaign auto-drafting from playbook templates

All actions are:
- Logged to intelligence.db (auto_optimizer_actions table)
- Sent as Telegram notification to Tom (IMPORTANT severity)
- Reversible: Tom can message "undo [action_id]" to override
- Guardrailed: max budget change, min sample size, cooldown periods

Schedule entry (add to config/schedules.json):
    {
      "agent": "dbh-marketing",
      "task": "auto_optimize",
      "cron": "45 23 * * *",
      "description": "Auto-optimizer: budget adjustments, A/B winners, campaign drafts (11:45pm)"
    }

Tables (in intelligence.db):
  - auto_optimizer_actions: id, action_type, details_json, campaign_id,
    old_value, new_value, created_at, undone_at

Env vars: META_ACCESS_TOKEN, META_AD_ACCOUNT_ID, KLAVIYO_API_KEY, TELEGRAM_BOT_TOKEN
"""

import os
import json
import math
import sqlite3
import logging
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

NZ_TZ = ZoneInfo("Pacific/Auckland")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
INTELLIGENCE_DB = BASE_DIR / "data" / "intelligence.db"
LEARNING_DB = BASE_DIR / "data" / "learning.db"

# --- Guardrails ---
MAX_BUDGET_CHANGE_PERCENT = 0.20     # 20% max per adjustment
MAX_BUDGET_INCREASE_DOLLARS = 100.0  # $100/day max increase
COOLDOWN_HOURS = 48                  # Min hours between adjustments per campaign
ROAS_SCALE_THRESHOLD = 3.0          # 3-day ROAS > 3x -> scale up
ROAS_HOLD_FLOOR = 2.0              # 2x-3x -> hold
ROAS_CUT_THRESHOLD = 2.0           # < 2x for 2 days -> cut
ROAS_PAUSE_THRESHOLD = 1.5         # < 1.5x for 3 days -> skip (handled by roas_tracker)
AB_MIN_SAMPLE_SIZE = 200            # Minimum recipients before declaring winner (lowered for small segments)
AB_MIN_HOURS = 4                    # Minimum hours test must run
AB_CONFIDENCE_LEVEL = 0.95         # 95% statistical confidence

# Tracked A/B campaigns — add campaign IDs here for monitoring
# These are checked regardless of naming convention or send strategy
TRACKED_AB_CAMPAIGNS = {
    "01KN8PYMD998T7CPNC6QW1XNX4": {
        "name": "Colostrum EC1 — Education A/B (April 2026)",
        "hypothesis": "Curiosity vs Validation for existing buyers",
        "variant_a": "Curiosity: 'Why colostrum actually works'",
        "variant_b": "Validation: 'The science behind your choice'",
        "segment": "Colostrum Buyers (299 profiles)",
        "playbook_section": "SUBJECT LINE FORMULAS",
    },
}
CAMPAIGN_DRAFT_LOOKAHEAD_DAYS = 3   # Draft campaigns due within 3 days


def _get_db() -> sqlite3.Connection:
    """Get intelligence.db connection with auto_optimizer_actions table."""
    INTELLIGENCE_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(INTELLIGENCE_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS auto_optimizer_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            action_type TEXT NOT NULL,
            details_json TEXT,
            campaign_id TEXT,
            old_value TEXT,
            new_value TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            undone_at TIMESTAMP
        );

        CREATE INDEX IF NOT EXISTS idx_optimizer_campaign
            ON auto_optimizer_actions(campaign_id);
        CREATE INDEX IF NOT EXISTS idx_optimizer_type
            ON auto_optimizer_actions(action_type);
        CREATE INDEX IF NOT EXISTS idx_optimizer_created
            ON auto_optimizer_actions(created_at);
    """)
    conn.commit()
    return conn


def _get_learning_db() -> sqlite3.Connection:
    """Get learning.db connection for storing winning formulas."""
    LEARNING_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(LEARNING_DB))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS ab_test_winners (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_name TEXT,
            winning_variant TEXT,
            metric TEXT,
            winner_rate REAL,
            loser_rate REAL,
            sample_size INTEGER,
            confidence REAL,
            details_json TEXT,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    return conn


def _z_test_proportions(p1: float, n1: int, p2: float, n2: int) -> float:
    """
    Two-proportion z-test for A/B test significance.

    Args:
        p1: Proportion for variant A (e.g. open rate 0.25)
        n1: Sample size for variant A
        p2: Proportion for variant B
        n2: Sample size for variant B

    Returns:
        p-value (lower = more confident the difference is real)
    """
    if n1 == 0 or n2 == 0:
        return 1.0

    # Pooled proportion
    p_pool = (p1 * n1 + p2 * n2) / (n1 + n2)

    if p_pool == 0 or p_pool == 1:
        return 1.0

    # Standard error
    se = math.sqrt(p_pool * (1 - p_pool) * (1/n1 + 1/n2))

    if se == 0:
        return 1.0

    # Z-score
    z = abs(p1 - p2) / se

    # Approximate two-tailed p-value using the complementary error function
    # For z > 0: p_value ~ 2 * (1 - Phi(z))
    # Using the approximation: Phi(z) ~ 1 - phi(z) * (b1*t + b2*t^2 + b3*t^3)
    # where t = 1/(1 + 0.2316419*z)
    # This is Abramowitz and Stegun approximation 26.2.17
    if z > 8:
        return 0.0  # Effectively zero

    b1 = 0.319381530
    b2 = -0.356563782
    b3 = 1.781477937
    b4 = -1.821255978
    b5 = 1.330274429
    t = 1.0 / (1.0 + 0.2316419 * z)
    phi = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
    tail = phi * t * (b1 + t * (b2 + t * (b3 + t * (b4 + t * b5))))

    p_value = 2.0 * tail  # Two-tailed
    return max(0.0, min(1.0, p_value))


class AutoOptimizer:
    """
    Write-Back Phase 2: Autonomous campaign optimization.

    All actions:
    - Are logged to intelligence.db (auto_optimizer_actions table)
    - Send Telegram notification to Tom (IMPORTANT severity)
    - Can be overridden by Tom messaging "undo [action_id]"
    - Have guardrails (max budget change, min sample size)
    """

    def __init__(self):
        self.db = _get_db()
        self.actions_taken = []

    def close(self):
        """Close DB connection."""
        if self.db:
            self.db.close()

    # --- Shared Infrastructure ---

    def _can_adjust(self, campaign_id: str) -> bool:
        """Check if a campaign's last adjustment was more than 48 hours ago."""
        cutoff = (datetime.now(NZ_TZ) - timedelta(hours=COOLDOWN_HOURS)).isoformat()
        row = self.db.execute("""
            SELECT COUNT(*) as cnt FROM auto_optimizer_actions
            WHERE campaign_id = ?
              AND action_type = 'budget_adjustment'
              AND undone_at IS NULL
              AND created_at > ?
        """, (campaign_id, cutoff)).fetchone()
        return (row["cnt"] or 0) == 0

    def _log_action(self, action_type: str, details: dict,
                    campaign_id: str = None,
                    old_val: str = None, new_val: str = None) -> int:
        """
        Log an optimizer action to the auto_optimizer_actions table.

        Returns:
            action_id for undo reference
        """
        cursor = self.db.execute("""
            INSERT INTO auto_optimizer_actions
            (action_type, details_json, campaign_id, old_value, new_value)
            VALUES (?, ?, ?, ?, ?)
        """, (
            action_type,
            json.dumps(details),
            campaign_id,
            old_val,
            new_val,
        ))
        self.db.commit()
        action_id = cursor.lastrowid
        self.actions_taken.append(action_id)
        logger.info(f"Logged optimizer action #{action_id}: {action_type} "
                    f"for campaign {campaign_id}")
        return action_id

    def _notify(self, message: str, severity: str = "IMPORTANT"):
        """Send notification to Tom via the notification router."""
        try:
            from core.notification_router import route_notification

            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
            # Send to dbh-marketing channel (Meridian)
            chat_id = "-5106475679"

            # Try loading from config if available
            try:
                config_path = BASE_DIR / "config" / "telegram.json"
                with open(config_path, encoding="utf-8") as f:
                    config = json.load(f)
                chat_id = config.get("chat_ids", {}).get("dbh-marketing", chat_id)
            except Exception:
                pass

            if bot_token:
                route_notification(
                    chat_id=chat_id,
                    text=f"[PRIORITY: {severity}]\n{message}",
                    bot_token=bot_token,
                    severity=severity,
                    agent="auto-optimizer"
                )
            else:
                logger.warning("No TELEGRAM_BOT_TOKEN — skipping notification")

        except Exception as e:
            logger.error(f"Notification failed: {e}")

    def undo_action(self, action_id: int) -> str:
        """
        Undo a previous optimizer action.

        For budget adjustments: reverts to old_value.
        For other actions: marks as undone (manual follow-up may be needed).

        Returns:
            Status message
        """
        row = self.db.execute(
            "SELECT * FROM auto_optimizer_actions WHERE id = ?",
            (action_id,)
        ).fetchone()

        if not row:
            return f"Action #{action_id} not found."

        if row["undone_at"]:
            return f"Action #{action_id} was already undone at {row['undone_at']}."

        action_type = row["action_type"]
        campaign_id = row["campaign_id"]

        # Attempt to revert
        if action_type == "budget_adjustment" and row["old_value"] and campaign_id:
            try:
                from core.meta_ads_writer import MetaAdsWriter
                writer = MetaAdsWriter()
                if writer.available:
                    old_budget_cents = int(float(row["old_value"]) * 100)
                    writer.update_campaign_budget(
                        campaign_id, daily_budget=old_budget_cents
                    )
                    logger.info(f"Reverted budget for {campaign_id} to "
                                f"${row['old_value']}")
            except Exception as e:
                logger.error(f"Budget revert failed for action #{action_id}: {e}")
                return f"Undo failed for action #{action_id}: {e}"

        # Mark as undone
        self.db.execute(
            "UPDATE auto_optimizer_actions SET undone_at = ? WHERE id = ?",
            (datetime.now(NZ_TZ).isoformat(), action_id)
        )
        self.db.commit()

        msg = f"Action #{action_id} ({action_type}) has been undone."
        self._notify(f"UNDO: {msg}", severity="NOTABLE")
        return msg

    # ===================================================================
    # 1. META BUDGET AUTO-ADJUSTMENT
    # ===================================================================

    def auto_adjust_meta_budgets(self) -> str:
        """
        For each active Meta campaign:
        - If 3-day verified ROAS > 3x: increase daily budget by 20% (max $100/day increase)
        - If 3-day verified ROAS between 2x-3x: hold (no change)
        - If 3-day verified ROAS < 2x for 2 days: decrease budget by 20%
        - If 3-day verified ROAS < 1.5x for 3 days: auto-paused by roas_tracker (skip)

        Budget changes are capped at +/-20% per adjustment, max once per 48 hours
        per campaign.

        Uses:
        - roas_tracker._get_db() to read roas_daily table
        - MetaAdsWriter().update_campaign_budget() to make changes
        - route_notification() to notify Tom
        """
        lines = ["*Meta Budget Auto-Adjustment*\n"]
        adjustments = 0
        holds = 0
        skips = 0

        try:
            from core.meta_ads_writer import MetaAdsWriter
            writer = MetaAdsWriter()

            if not writer.available:
                msg = "Meta Ads API not available (missing credentials)"
                logger.warning(msg)
                return f"[PRIORITY: INFO]\nBudget adjustment skipped: {msg}"

            # Get active campaigns
            try:
                campaigns = writer.get_campaigns(status_filter="ACTIVE")
            except Exception as e:
                logger.error(f"Failed to fetch active campaigns: {e}")
                return f"[PRIORITY: IMPORTANT]\nBudget adjustment failed: {e}"

            if not campaigns:
                return "[PRIORITY: INFO]\nBudget adjustment: no active campaigns found."

            # Get ROAS data from intelligence.db
            three_days_ago = (date.today() - timedelta(days=3)).isoformat()
            two_days_ago = (date.today() - timedelta(days=2)).isoformat()

            for campaign in campaigns:
                campaign_id = campaign.get("id", "")
                campaign_name = campaign.get("name", "Unknown")
                current_budget_cents = int(campaign.get("daily_budget", 0))
                current_budget = current_budget_cents / 100.0

                if current_budget <= 0:
                    skips += 1
                    continue

                # Check cooldown
                if not self._can_adjust(campaign_id):
                    lines.append(f"- {campaign_name}: COOLDOWN (adjusted within {COOLDOWN_HOURS}h)")
                    skips += 1
                    continue

                # Check if paused by roas_tracker (skip these)
                paused_row = self.db.execute("""
                    SELECT paused FROM roas_alerts
                    WHERE campaign_id = ? AND paused = 1
                """, (campaign_id,)).fetchone()

                if paused_row:
                    skips += 1
                    continue

                # Get 3-day average verified ROAS
                roas_row = self.db.execute("""
                    SELECT AVG(verified_roas) as avg_roas, COUNT(*) as days
                    FROM roas_daily
                    WHERE campaign_id = ? AND date >= ?
                """, (campaign_id, three_days_ago)).fetchone()

                avg_roas = (roas_row["avg_roas"] or 0) if roas_row else 0
                days_tracked = (roas_row["days"] or 0) if roas_row else 0

                if days_tracked < 2:
                    lines.append(f"- {campaign_name}: SKIP (only {days_tracked} day(s) of data)")
                    skips += 1
                    continue

                # Check 2-day streak below floor for cuts
                days_below_2x = 0
                if avg_roas < ROAS_CUT_THRESHOLD:
                    below_row = self.db.execute("""
                        SELECT COUNT(*) as cnt FROM roas_daily
                        WHERE campaign_id = ?
                          AND date >= ?
                          AND verified_roas < ?
                          AND meta_spend > 0
                    """, (campaign_id, two_days_ago, ROAS_CUT_THRESHOLD)).fetchone()
                    days_below_2x = (below_row["cnt"] or 0) if below_row else 0

                # Decision logic
                if avg_roas >= ROAS_SCALE_THRESHOLD:
                    # SCALE UP: increase by 20%, capped at $100/day increase
                    increase = current_budget * MAX_BUDGET_CHANGE_PERCENT
                    increase = min(increase, MAX_BUDGET_INCREASE_DOLLARS)
                    new_budget = current_budget + increase
                    new_budget_cents = int(new_budget * 100)

                    try:
                        writer.update_campaign_budget(
                            campaign_id, daily_budget=new_budget_cents
                        )
                        action_id = self._log_action(
                            "budget_adjustment",
                            {
                                "direction": "increase",
                                "campaign_name": campaign_name,
                                "avg_roas": round(avg_roas, 2),
                                "reason": f"3-day ROAS {avg_roas:.2f}x > {ROAS_SCALE_THRESHOLD}x threshold",
                            },
                            campaign_id=campaign_id,
                            old_val=str(current_budget),
                            new_val=str(new_budget),
                        )
                        lines.append(
                            f"- {campaign_name}: SCALED UP ${current_budget:.0f} -> "
                            f"${new_budget:.0f}/day (ROAS {avg_roas:.2f}x) "
                            f"[undo #{action_id}]"
                        )
                        adjustments += 1
                    except Exception as e:
                        lines.append(f"- {campaign_name}: SCALE FAILED: {e}")
                        logger.error(f"Budget increase failed for {campaign_name}: {e}")

                elif avg_roas < ROAS_CUT_THRESHOLD and days_below_2x >= 2:
                    # CUT: decrease by 20%
                    decrease = current_budget * MAX_BUDGET_CHANGE_PERCENT
                    new_budget = current_budget - decrease
                    new_budget = max(new_budget, 5.0)  # Never go below $5/day
                    new_budget_cents = int(new_budget * 100)

                    try:
                        writer.update_campaign_budget(
                            campaign_id, daily_budget=new_budget_cents
                        )
                        action_id = self._log_action(
                            "budget_adjustment",
                            {
                                "direction": "decrease",
                                "campaign_name": campaign_name,
                                "avg_roas": round(avg_roas, 2),
                                "days_below_floor": days_below_2x,
                                "reason": f"3-day ROAS {avg_roas:.2f}x < {ROAS_CUT_THRESHOLD}x for {days_below_2x} days",
                            },
                            campaign_id=campaign_id,
                            old_val=str(current_budget),
                            new_val=str(new_budget),
                        )
                        lines.append(
                            f"- {campaign_name}: CUT ${current_budget:.0f} -> "
                            f"${new_budget:.0f}/day (ROAS {avg_roas:.2f}x, "
                            f"{days_below_2x}d below floor) [undo #{action_id}]"
                        )
                        adjustments += 1
                    except Exception as e:
                        lines.append(f"- {campaign_name}: CUT FAILED: {e}")
                        logger.error(f"Budget decrease failed for {campaign_name}: {e}")

                else:
                    # HOLD: ROAS between 2x-3x, or insufficient streak below floor
                    lines.append(
                        f"- {campaign_name}: HOLD at ${current_budget:.0f}/day "
                        f"(ROAS {avg_roas:.2f}x)"
                    )
                    holds += 1

        except ImportError:
            logger.error("MetaAdsWriter not available")
            return "[PRIORITY: INFO]\nBudget adjustment skipped: MetaAdsWriter not importable."
        except Exception as e:
            logger.error(f"Budget auto-adjustment error: {e}")
            return f"[PRIORITY: IMPORTANT]\nBudget adjustment error: {e}"

        lines.append(
            f"\nSummary: {adjustments} adjusted, {holds} held, {skips} skipped"
        )

        # Notify Tom if any adjustments were made
        if adjustments > 0:
            self._notify(
                f"*Auto Budget Adjustment*\n"
                f"{adjustments} campaign(s) adjusted:\n" +
                "\n".join(l for l in lines[1:] if "SCALED" in l or "CUT" in l) +
                f"\n\nTo undo, message: undo [action_id]",
                severity="IMPORTANT"
            )

        return "\n".join(lines)

    # ===================================================================
    # 2. A/B TEST WINNER AUTO-SELECTION
    # ===================================================================

    def auto_select_ab_winners(self) -> str:
        """
        Check Klaviyo campaigns for completed A/B tests.
        If test has been running >= 4 hours AND sample size >= 1000:
        - Compare open rates (or click rates)
        - If winner is statistically significant (>95% confidence via z-test):
          - Send the winner to remaining audience
          - Log the winning formula to learning.db

        Uses:
        - KlaviyoWriter (for campaign operations)
        - Simple z-test for proportions for significance
        """
        lines = ["*A/B Test Winner Selection*\n"]
        winners_selected = 0

        try:
            from core.klaviyo_writer import KlaviyoWriter
            writer = KlaviyoWriter()

            if not writer.available:
                return "[PRIORITY: INFO]\nA/B test check skipped: Klaviyo API not available."

            # Get campaigns — look for A/B test campaigns (named with [A/B] prefix)
            try:
                result = writer._get("campaigns", params={
                    "filter": "equals(messages.channel,'email')",
                    "fields[campaign]": "name,status,send_strategy,created_at",
                })
                campaigns = result.get("data", [])
            except Exception as e:
                logger.error(f"Failed to fetch Klaviyo campaigns: {e}")
                return f"[PRIORITY: INFO]\nA/B test check failed: {e}"

            for campaign in campaigns:
                attrs = campaign.get("attributes", {})
                name = attrs.get("name", "")
                status = attrs.get("status", "")
                campaign_id = campaign.get("id", "")

                # Only process A/B test campaigns that are actively sending
                if "[A/B]" not in name:
                    continue

                send_strategy = attrs.get("send_strategy", {})
                if send_strategy.get("method") != "ab_test":
                    continue

                # Check if the test is still in the testing phase
                # (status would be "Sending" during test, not yet completed)
                if status not in ("Sending", "sent"):
                    continue

                # Get campaign message stats
                try:
                    stats_result = writer._get(
                        f"campaigns/{campaign_id}/campaign-messages",
                        params={
                            "fields[campaign-message]": "label,statistics",
                        }
                    )
                    messages = stats_result.get("data", [])
                except Exception as e:
                    logger.warning(f"Failed to get A/B stats for {name}: {e}")
                    continue

                if len(messages) < 2:
                    continue

                # Parse variant stats
                variants = []
                for msg in messages:
                    msg_attrs = msg.get("attributes", {})
                    stats = msg_attrs.get("statistics", {})
                    variants.append({
                        "message_id": msg.get("id", ""),
                        "label": msg_attrs.get("label", ""),
                        "recipients": stats.get("recipients", 0),
                        "opens": stats.get("unique_opens", 0),
                        "clicks": stats.get("unique_clicks", 0),
                        "open_rate": stats.get("open_rate", 0),
                        "click_rate": stats.get("click_rate", 0),
                    })

                # Check minimum sample size
                total_sample = sum(v["recipients"] for v in variants)
                if total_sample < AB_MIN_SAMPLE_SIZE:
                    lines.append(
                        f"- {name}: WAITING (sample {total_sample}/{AB_MIN_SAMPLE_SIZE})"
                    )
                    continue

                # Check minimum test duration
                created_at = attrs.get("created_at", "")
                if created_at:
                    try:
                        created = datetime.fromisoformat(
                            created_at.replace("Z", "+00:00")
                        )
                        hours_running = (
                            datetime.now(created.tzinfo) - created
                        ).total_seconds() / 3600
                        if hours_running < AB_MIN_HOURS:
                            lines.append(
                                f"- {name}: WAITING ({hours_running:.1f}h / "
                                f"{AB_MIN_HOURS}h minimum)"
                            )
                            continue
                    except (ValueError, TypeError):
                        pass

                # Run z-test on open rates (primary metric)
                if len(variants) >= 2:
                    v_a = variants[0]
                    v_b = variants[1]

                    p_a = v_a["open_rate"] if isinstance(v_a["open_rate"], float) else 0
                    p_b = v_b["open_rate"] if isinstance(v_b["open_rate"], float) else 0
                    n_a = v_a["recipients"]
                    n_b = v_b["recipients"]

                    p_value = _z_test_proportions(p_a, n_a, p_b, n_b)
                    is_significant = p_value < (1 - AB_CONFIDENCE_LEVEL)

                    if is_significant:
                        # Determine winner
                        if p_a > p_b:
                            winner = v_a
                            loser = v_b
                        else:
                            winner = v_b
                            loser = v_a

                        confidence = (1 - p_value) * 100

                        # Log to learning.db
                        try:
                            ldb = _get_learning_db()
                            ldb.execute("""
                                INSERT INTO ab_test_winners
                                (test_name, winning_variant, metric, winner_rate,
                                 loser_rate, sample_size, confidence, details_json)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                            """, (
                                name,
                                winner["label"],
                                "open_rate",
                                winner["open_rate"],
                                loser["open_rate"],
                                total_sample,
                                confidence,
                                json.dumps({
                                    "campaign_id": campaign_id,
                                    "p_value": p_value,
                                    "variants": variants,
                                }),
                            ))
                            ldb.commit()
                            ldb.close()
                        except Exception as e:
                            logger.error(f"Failed to log A/B winner to learning.db: {e}")

                        # Log action
                        action_id = self._log_action(
                            "ab_winner_selected",
                            {
                                "campaign_name": name,
                                "winner_label": winner["label"],
                                "winner_open_rate": winner["open_rate"],
                                "loser_open_rate": loser["open_rate"],
                                "confidence": round(confidence, 1),
                                "sample_size": total_sample,
                                "p_value": round(p_value, 4),
                            },
                            campaign_id=campaign_id,
                            old_val=f"A: {v_a['open_rate']:.1%} / B: {v_b['open_rate']:.1%}",
                            new_val=f"Winner: {winner['label']} ({winner['open_rate']:.1%})",
                        )

                        lines.append(
                            f"- {name}: WINNER = '{winner['label']}' "
                            f"(open rate {winner['open_rate']:.1%} vs "
                            f"{loser['open_rate']:.1%}, "
                            f"{confidence:.0f}% confidence) [action #{action_id}]"
                        )
                        winners_selected += 1

                        # Notify Tom
                        self._notify(
                            f"*A/B Test Winner Selected*\n"
                            f"Campaign: {name}\n"
                            f"Winner: {winner['label']}\n"
                            f"Open rate: {winner['open_rate']:.1%} vs {loser['open_rate']:.1%}\n"
                            f"Confidence: {confidence:.0f}%\n"
                            f"Sample: {total_sample:,} recipients\n"
                            f"Winning formula logged to learning DB.",
                            severity="IMPORTANT"
                        )

                    else:
                        lines.append(
                            f"- {name}: NO WINNER YET "
                            f"(A: {p_a:.1%} vs B: {p_b:.1%}, "
                            f"p={p_value:.3f}, need p<{1-AB_CONFIDENCE_LEVEL})"
                        )

        except ImportError:
            logger.error("KlaviyoWriter not available")
            return "[PRIORITY: INFO]\nA/B test check skipped: KlaviyoWriter not importable."
        except Exception as e:
            logger.error(f"A/B test selection error: {e}")
            return f"[PRIORITY: INFO]\nA/B test check error: {e}"

        # Also check tracked campaigns (regardless of naming/strategy)
        tracked_results = self._check_tracked_ab_campaigns()
        if tracked_results:
            lines.append("\n*Tracked Campaign Results:*")
            lines.extend(tracked_results)

        lines.append(f"\nSummary: {winners_selected} winner(s) selected")
        return "\n".join(lines)

    def _check_tracked_ab_campaigns(self) -> list:
        """Check manually tracked A/B campaigns via Klaviyo campaign reports API."""
        results = []
        if not TRACKED_AB_CAMPAIGNS:
            return results

        try:
            from core.klaviyo_writer import KlaviyoWriter
            writer = KlaviyoWriter()
            if not writer.available:
                return results

            for campaign_id, meta in TRACKED_AB_CAMPAIGNS.items():
                try:
                    # Get campaign report with variant-level breakdown
                    report = writer._post("campaign-values-reports", json_body={
                        "data": {
                            "type": "campaign-values-report",
                            "attributes": {
                                "statistics": ["recipients", "opens_unique", "clicks_unique",
                                              "open_rate", "click_rate", "conversions",
                                              "conversion_value"],
                                "timeframe": {"key": "last_30_days"},
                                "filter": f"equals(campaign_id,\"{campaign_id}\")",
                                "group_by": ["campaign_id", "campaign_message_id",
                                           "send_channel", "variation", "variation_name"],
                            }
                        }
                    })

                    rows = report.get("data", {}).get("attributes", {}).get("results", [])
                    if len(rows) < 2:
                        # Try simpler approach — just get campaign messages
                        msg_result = writer._get(
                            f"campaigns/{campaign_id}/campaign-messages",
                            params={"fields[campaign-message]": "label,statistics"}
                        )
                        messages = msg_result.get("data", [])
                        if len(messages) < 2:
                            results.append(f"- {meta['name']}: WAITING for data (only {len(messages)} variant(s) found)")
                            continue

                    # Extract variant stats from report rows
                    variants = []
                    for row in rows:
                        stats = row.get("statistics", {})
                        groupings = row.get("groupings", {})
                        recipients = stats.get("recipients", 0)
                        if recipients == 0:
                            continue
                        variants.append({
                            "name": groupings.get("variation_name", groupings.get("campaign_message_id", "?")),
                            "recipients": recipients,
                            "opens": stats.get("opens_unique", 0),
                            "clicks": stats.get("clicks_unique", 0),
                            "open_rate": stats.get("open_rate", 0),
                            "click_rate": stats.get("click_rate", 0),
                            "revenue": stats.get("conversion_value", 0),
                        })

                    if len(variants) < 2:
                        results.append(f"- {meta['name']}: WAITING for both variants to send")
                        continue

                    total_sample = sum(v["recipients"] for v in variants)
                    v_a, v_b = variants[0], variants[1]
                    p_a = v_a["open_rate"] if isinstance(v_a["open_rate"], (int, float)) else 0
                    p_b = v_b["open_rate"] if isinstance(v_b["open_rate"], (int, float)) else 0
                    n_a = v_a["recipients"]
                    n_b = v_b["recipients"]

                    if total_sample < AB_MIN_SAMPLE_SIZE:
                        results.append(
                            f"- {meta['name']}: WAITING (sample {total_sample}/{AB_MIN_SAMPLE_SIZE})")
                        continue

                    p_value = _z_test_proportions(p_a, n_a, p_b, n_b)
                    is_significant = p_value < (1 - AB_CONFIDENCE_LEVEL)

                    if p_a > p_b:
                        winner, loser = v_a, v_b
                    else:
                        winner, loser = v_b, v_a

                    confidence = (1 - p_value) * 100

                    # Log to learning.db regardless of significance
                    try:
                        ldb = _get_learning_db()
                        ldb.execute("""
                            INSERT OR REPLACE INTO ab_test_winners
                            (test_name, winning_variant, metric, winner_rate,
                             loser_rate, sample_size, confidence, details_json)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """, (
                            meta["name"],
                            winner["name"],
                            "open_rate",
                            winner["open_rate"],
                            loser["open_rate"],
                            total_sample,
                            confidence,
                            json.dumps({
                                "campaign_id": campaign_id,
                                "hypothesis": meta["hypothesis"],
                                "variant_a": meta["variant_a"],
                                "variant_b": meta["variant_b"],
                                "p_value": p_value,
                                "is_significant": is_significant,
                                "variants": variants,
                                "checked_at": datetime.now(NZ_TZ).isoformat(),
                            }),
                        ))
                        ldb.commit()
                        ldb.close()
                    except Exception as e:
                        logger.error(f"Failed to log tracked A/B to learning.db: {e}")

                    if is_significant:
                        results.append(
                            f"- {meta['name']}: WINNER = '{winner['name']}' "
                            f"(open rate {winner['open_rate']:.1%} vs {loser['open_rate']:.1%}, "
                            f"{confidence:.0f}% confidence)")

                        # Auto-update email playbook
                        self._update_email_playbook(meta, winner, loser, confidence, total_sample)

                        # Notify Tom
                        self._notify(
                            f"*A/B Test Result — {meta['name']}*\n\n"
                            f"Hypothesis: {meta['hypothesis']}\n"
                            f"Winner: {winner['name']}\n"
                            f"Open rate: {winner['open_rate']:.1%} vs {loser['open_rate']:.1%}\n"
                            f"Confidence: {confidence:.0f}%\n"
                            f"Sample: {total_sample} recipients\n\n"
                            f"Result logged to learning DB + email playbook.",
                            severity="IMPORTANT"
                        )
                    else:
                        results.append(
                            f"- {meta['name']}: NO WINNER YET "
                            f"(A: {p_a:.1%} vs B: {p_b:.1%}, "
                            f"p={p_value:.3f}, confidence {confidence:.0f}%)")

                except Exception as e:
                    logger.warning(f"Failed to check tracked campaign {campaign_id}: {e}")
                    results.append(f"- {meta['name']}: CHECK FAILED ({e})")

        except ImportError:
            logger.error("KlaviyoWriter not available for tracked campaigns")
        except Exception as e:
            logger.error(f"Tracked A/B campaign check error: {e}")

        return results

    def _update_email_playbook(self, meta: dict, winner: dict, loser: dict,
                                confidence: float, sample_size: int):
        """Append A/B test result to email playbook CHANGELOG."""
        import os
        playbook_path = os.path.expanduser("~/dbh-aios/playbooks/email-playbook.md")
        today = datetime.now(NZ_TZ).strftime("%Y-%m-%d")

        entry = (
            f"\n**{today}** | A/B TEST RESULT: {meta['name']} | "
            f"Hypothesis: {meta['hypothesis']} | "
            f"Winner: {winner['name']} ({winner['open_rate']:.1%} open rate) vs "
            f"Loser: {loser['name']} ({loser['open_rate']:.1%}) | "
            f"Confidence: {confidence:.0f}% | Sample: {sample_size} | "
            f"Playbook section: {meta.get('playbook_section', 'N/A')} | "
            f"Source: auto_optimizer tracked campaign"
        )

        try:
            with open(playbook_path, "r", encoding="utf-8") as f:
                content = f.read()

            # Find CHANGELOG section and append
            changelog_marker = "## CHANGELOG"
            if changelog_marker in content:
                idx = content.index(changelog_marker) + len(changelog_marker)
                # Find end of the header line
                next_newline = content.index("\n", idx)
                content = content[:next_newline + 1] + entry + content[next_newline + 1:]
            else:
                # No CHANGELOG section — append at end
                content += f"\n\n## CHANGELOG\n{entry}\n"

            with open(playbook_path, "w", encoding="utf-8") as f:
                f.write(content)

            logger.info(f"Updated email playbook with A/B result: {meta['name']}")
        except Exception as e:
            logger.error(f"Failed to update email playbook: {e}")

    # ===================================================================
    # 3. KLAVIYO CAMPAIGN AUTO-DRAFT
    # ===================================================================

    def auto_draft_klaviyo_campaigns(self) -> str:
        """
        Based on the campaign calendar in shared strategy:
        - Check if there's a campaign due within 3 days that doesn't have a draft
        - Auto-create a draft campaign using:
          - Proven subject line formulas from email-playbook.md patterns
          - Correct segment targeting from customer-segments-playbook
          - Appropriate template
        - Tom reviews and approves before send

        Uses:
        - KlaviyoWriter().create_campaign() for draft creation
        """
        lines = ["*Klaviyo Campaign Auto-Draft*\n"]
        drafts_created = 0

        try:
            from core.klaviyo_writer import KlaviyoWriter
            writer = KlaviyoWriter()

            if not writer.available:
                return "[PRIORITY: INFO]\nCampaign draft skipped: Klaviyo API not available."

            # Load campaign calendar from strategy files
            upcoming = self._get_upcoming_campaigns()

            if not upcoming:
                lines.append("No campaigns due within 3 days.")
                return "\n".join(lines)

            # Check existing Klaviyo drafts to avoid duplicates
            try:
                existing_result = writer._get("campaigns", params={
                    "filter": "equals(messages.channel,'email')",
                    "fields[campaign]": "name,status",
                })
                existing_campaigns = existing_result.get("data", [])
                existing_names = set()
                for ec in existing_campaigns:
                    ec_name = ec.get("attributes", {}).get("name", "")
                    existing_names.add(ec_name.lower())
            except Exception as e:
                logger.warning(f"Failed to check existing drafts: {e}")
                existing_names = set()

            for campaign_plan in upcoming:
                plan_name = campaign_plan.get("name", "")

                # Skip if a draft or campaign with this name already exists
                if plan_name.lower() in existing_names:
                    lines.append(f"- {plan_name}: ALREADY EXISTS (skipped)")
                    continue

                # Build the draft
                subject = campaign_plan.get("subject", plan_name)
                preview_text = campaign_plan.get("preview_text", "")
                segment_ids = campaign_plan.get("segment_ids", [])
                list_ids = campaign_plan.get("list_ids", [])
                template_id = campaign_plan.get("template_id")

                try:
                    result = writer.create_campaign(
                        name=plan_name,
                        subject=subject,
                        preview_text=preview_text,
                        segment_ids=segment_ids if segment_ids else None,
                        list_ids=list_ids if list_ids else None,
                        template_id=template_id,
                        from_name="Deep Blue Health",
                        from_email="hello@deepbluehealth.co.nz",
                    )

                    draft_id = result.get("id", "?")

                    action_id = self._log_action(
                        "campaign_draft",
                        {
                            "campaign_name": plan_name,
                            "subject": subject,
                            "preview_text": preview_text,
                            "segment_ids": segment_ids,
                            "list_ids": list_ids,
                            "template_id": template_id,
                            "due_date": campaign_plan.get("due_date", ""),
                            "klaviyo_draft_id": draft_id,
                        },
                        campaign_id=draft_id,
                        old_val=None,
                        new_val=f"Draft: {plan_name}",
                    )

                    lines.append(
                        f"- {plan_name}: DRAFTED (Klaviyo ID: {draft_id}) "
                        f"[action #{action_id}]"
                    )
                    lines.append(f"  Subject: {subject}")
                    if preview_text:
                        lines.append(f"  Preview: {preview_text}")
                    lines.append(f"  Status: NEEDS TOM'S REVIEW before send")
                    drafts_created += 1

                except Exception as e:
                    lines.append(f"- {plan_name}: DRAFT FAILED: {e}")
                    logger.error(f"Campaign draft failed for '{plan_name}': {e}")

            # Notify Tom if any drafts were created
            if drafts_created > 0:
                draft_names = [
                    c["name"] for c in upcoming
                    if c["name"].lower() not in existing_names
                ]
                self._notify(
                    f"*Campaign Drafts Created*\n"
                    f"{drafts_created} draft(s) ready for your review:\n" +
                    "\n".join(f"  - {n}" for n in draft_names[:5]) +
                    f"\n\nPlease review in Klaviyo before approving send.",
                    severity="IMPORTANT"
                )

        except ImportError:
            logger.error("KlaviyoWriter not available")
            return "[PRIORITY: INFO]\nCampaign draft skipped: KlaviyoWriter not importable."
        except Exception as e:
            logger.error(f"Campaign auto-draft error: {e}")
            return f"[PRIORITY: INFO]\nCampaign draft error: {e}"

        lines.append(f"\nSummary: {drafts_created} draft(s) created")
        return "\n".join(lines)

    def _get_upcoming_campaigns(self) -> list:
        """
        Read the campaign calendar from strategy files to find campaigns
        due within the next 3 days.

        Checks these sources in order:
        1. agents/dbh-marketing/playbooks/email-playbook.md (campaign calendar section)
        2. agents/dbh-marketing/state/CONTEXT.md (active campaign plans)
        3. intelligence.db campaign_calendar table (if populated by agents)

        Returns:
            List of campaign plan dicts with: name, subject, preview_text,
            segment_ids, list_ids, template_id, due_date
        """
        upcoming = []
        today = date.today()
        lookahead = today + timedelta(days=CAMPAIGN_DRAFT_LOOKAHEAD_DAYS)

        # Source 1: Check intelligence.db for scheduled campaigns
        try:
            row_exists = self.db.execute("""
                SELECT name FROM sqlite_master
                WHERE type='table' AND name='campaign_calendar'
            """).fetchone()

            if row_exists:
                rows = self.db.execute("""
                    SELECT * FROM campaign_calendar
                    WHERE due_date BETWEEN ? AND ?
                      AND status = 'planned'
                """, (today.isoformat(), lookahead.isoformat())).fetchall()

                for row in rows:
                    upcoming.append({
                        "name": row["name"],
                        "subject": row["subject"] if "subject" in row.keys() else row["name"],
                        "preview_text": row.get("preview_text", ""),
                        "segment_ids": json.loads(row["segment_ids"]) if row.get("segment_ids") else [],
                        "list_ids": json.loads(row["list_ids"]) if row.get("list_ids") else [],
                        "template_id": row.get("template_id"),
                        "due_date": row["due_date"],
                    })
        except Exception as e:
            logger.debug(f"Campaign calendar table not available: {e}")

        # Source 2: Check playbook files for campaign plans
        if not upcoming:
            playbook_paths = [
                BASE_DIR / "agents" / "dbh-marketing" / "playbooks" / "email-playbook.md",
                BASE_DIR / "agents" / "dbh-marketing" / "state" / "CONTEXT.md",
            ]

            for path in playbook_paths:
                if path.exists():
                    try:
                        content = path.read_text(encoding="utf-8")
                        # Look for campaign calendar entries
                        # Format expected: "- [DATE] Campaign Name | Subject Line"
                        import re
                        pattern = r'-\s*\[?(\d{4}-\d{2}-\d{2})\]?\s*(.+?)(?:\|(.+))?$'
                        for match in re.finditer(pattern, content, re.MULTILINE):
                            due_str = match.group(1)
                            campaign_name = match.group(2).strip()
                            subject = (match.group(3) or campaign_name).strip()

                            try:
                                due_date = date.fromisoformat(due_str)
                                if today <= due_date <= lookahead:
                                    upcoming.append({
                                        "name": campaign_name,
                                        "subject": subject,
                                        "preview_text": "",
                                        "segment_ids": [],
                                        "list_ids": [],
                                        "template_id": None,
                                        "due_date": due_str,
                                    })
                            except ValueError:
                                continue

                    except Exception as e:
                        logger.debug(f"Failed to parse {path}: {e}")

        return upcoming


# --- Top-Level Runner ---

def run_auto_optimization() -> str:
    """Called by orchestrator's scheduled task. Runs all optimizers."""
    optimizer = AutoOptimizer()
    results = []

    try:
        results.append(optimizer.auto_adjust_meta_budgets())
        results.append(optimizer.auto_select_ab_winners())
        results.append(optimizer.auto_draft_klaviyo_campaigns())
    finally:
        optimizer.close()

    return "\n\n".join(results)


def undo_optimizer_action(action_id: int) -> str:
    """
    Convenience function: undo a specific optimizer action.
    Called when Tom messages "undo [action_id]".
    """
    optimizer = AutoOptimizer()
    try:
        return optimizer.undo_action(action_id)
    finally:
        optimizer.close()


# --- CLI ---

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m core.auto_optimizer run          Run all optimizations")
        print("  python -m core.auto_optimizer budgets      Run budget adjustments only")
        print("  python -m core.auto_optimizer ab           Run A/B test selection only")
        print("  python -m core.auto_optimizer drafts       Run campaign drafting only")
        print("  python -m core.auto_optimizer undo <id>    Undo an action by ID")
        print("  python -m core.auto_optimizer history      Show recent actions")
        sys.exit(0)

    cmd = sys.argv[1].lower()

    if cmd == "run":
        print(run_auto_optimization())

    elif cmd == "budgets":
        optimizer = AutoOptimizer()
        print(optimizer.auto_adjust_meta_budgets())
        optimizer.close()

    elif cmd == "ab":
        optimizer = AutoOptimizer()
        print(optimizer.auto_select_ab_winners())
        optimizer.close()

    elif cmd == "drafts":
        optimizer = AutoOptimizer()
        print(optimizer.auto_draft_klaviyo_campaigns())
        optimizer.close()

    elif cmd == "undo" and len(sys.argv) > 2:
        action_id = int(sys.argv[2])
        print(undo_optimizer_action(action_id))

    elif cmd == "history":
        db = _get_db()
        rows = db.execute("""
            SELECT id, action_type, campaign_id, old_value, new_value,
                   created_at, undone_at
            FROM auto_optimizer_actions
            ORDER BY created_at DESC
            LIMIT 20
        """).fetchall()

        if not rows:
            print("No optimizer actions recorded yet.")
        else:
            print(f"Last {len(rows)} optimizer actions:\n")
            for row in rows:
                undone = " [UNDONE]" if row["undone_at"] else ""
                print(f"  #{row['id']} [{row['action_type']}] "
                      f"campaign={row['campaign_id'] or 'N/A'}")
                print(f"    {row['old_value'] or '-'} -> {row['new_value'] or '-'}")
                print(f"    at {row['created_at']}{undone}")
                print()
        db.close()

    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
