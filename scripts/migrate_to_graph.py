#!/usr/bin/env python3
"""
migrate_to_graph.py — One-time backfill of SQLite facts into Neo4j

Run this ONCE after adding NEO4J_URI / NEO4J_USERNAME / NEO4J_PASSWORD to Railway:

    railway run python3 scripts/migrate_to_graph.py

Or trigger via Telegram: send `/sync-graph` to Nexus (command-center)

What it does:
1. Reads ALL active facts from data/user_memory.db
2. Pushes them to Neo4j in batches
3. Builds Supplement/Condition/Goal typed nodes and their relationships
4. Idempotent — safe to re-run (MERGE not INSERT)

After this runs, every new conversation pulls ~50 targeted facts from Neo4j
instead of all 500 from SQLite. SQLite stays as the source of truth — Neo4j
is the retrieval layer only.
"""

import sys
import sqlite3
import logging
from pathlib import Path

# Allow running from repo root or scripts/
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "user_memory.db"

BATCH_SIZE = 50  # facts per Neo4j transaction


def run_migration():
    # 1. Check Neo4j is available
    from core.graph_memory import is_available, sync_facts_to_graph, _ensure_schema
    if not is_available():
        logger.error(
            "Neo4j not available. Add NEO4J_URI, NEO4J_USERNAME, NEO4J_PASSWORD "
            "to Railway env vars first."
        )
        return False

    logger.info("Neo4j connected. Starting migration...")
    _ensure_schema()

    # 2. Read all facts from SQLite
    if not DB_PATH.exists():
        logger.error(f"user_memory.db not found at {DB_PATH}")
        return False

    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row

    rows = conn.execute("""
        SELECT id, user_id, agent_id, fact, category, confidence, created_at, updated_at
        FROM user_facts
        WHERE is_active = 1
        ORDER BY user_id, agent_id, updated_at DESC
    """).fetchall()

    conn.close()

    if not rows:
        logger.info("No facts found in SQLite — nothing to migrate.")
        return True

    logger.info(f"Found {len(rows)} facts to migrate")

    # 3. Group by user/agent and sync in batches
    from itertools import groupby
    total_synced = 0
    errors = 0

    # Group facts by (user_id, agent_id)
    sorted_rows = sorted(rows, key=lambda r: (r["user_id"], r["agent_id"]))
    for (user_id, agent_id), group in groupby(sorted_rows, key=lambda r: (r["user_id"], r["agent_id"])):
        facts = list(group)
        logger.info(f"  Syncing {len(facts)} facts for {user_id}/{agent_id}...")

        # Process in batches
        for i in range(0, len(facts), BATCH_SIZE):
            batch = facts[i:i + BATCH_SIZE]
            batch_dicts = [
                {
                    "fact_id": str(f["id"]),
                    "fact": f["fact"],
                    "category": f["category"],
                    "confidence": float(f["confidence"]),
                    "created_at": f["created_at"],
                    "updated_at": f["updated_at"],
                }
                for f in batch
            ]
            try:
                sync_facts_to_graph(user_id, agent_id, batch_dicts)
                total_synced += len(batch)
                logger.info(f"    Batch {i//BATCH_SIZE + 1}: {len(batch)} facts synced")
            except Exception as e:
                logger.error(f"    Batch failed: {e}")
                errors += len(batch)

    logger.info(f"Migration complete: {total_synced} facts synced, {errors} errors")

    # 4. Print a summary of what's in the graph now
    try:
        from core.graph_memory import _get_driver
        driver = _get_driver()
        if driver:
            with driver.session() as s:
                result = s.run("MATCH (f:Fact) RETURN COUNT(f) AS total").single()
                graph_total = result["total"] if result else 0
                result2 = s.run("MATCH (u:User) RETURN COUNT(u) AS users").single()
                graph_users = result2["users"] if result2 else 0
                result3 = s.run("MATCH (s:Supplement) RETURN COUNT(s) AS supps").single()
                graph_supps = result3["supps"] if result3 else 0
                result4 = s.run("MATCH (c:Condition) RETURN COUNT(c) AS conds").single()
                graph_conds = result4["conds"] if result4 else 0
            logger.info(
                f"\n=== GRAPH SUMMARY ===\n"
                f"  Users:        {graph_users}\n"
                f"  Facts:        {graph_total}\n"
                f"  Supplements:  {graph_supps}\n"
                f"  Conditions:   {graph_conds}\n"
            )
    except Exception as e:
        logger.warning(f"Could not fetch graph summary: {e}")

    return errors == 0


if __name__ == "__main__":
    success = run_migration()
    sys.exit(0 if success else 1)
