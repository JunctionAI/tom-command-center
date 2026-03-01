#!/usr/bin/env python3
"""
Obsidian Vault Indexer -- Indexes Tom's Obsidian vault into SQLite FTS5
for full-text search by command center agents.

Scans the vault directory, parses markdown files, extracts metadata
(tags, wiki-links, folder), and stores in a searchable database.

Runs as a nightly cron or on-demand. Agents query this to inject
relevant foundational knowledge into their context.

Vault path: ~/Library/Mobile Documents/iCloud~md~obsidian/Documents/Junction AI/

Usage:
    python -m core.vault_indexer sync        # Full vault sync
    python -m core.vault_indexer search "email marketing segmentation"
    python -m core.vault_indexer stats
    python -m core.vault_indexer folder eCommerce
"""

import os
import re
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "data" / "vault_index.db"

# Obsidian vault path (iCloud sync on macOS)
VAULT_PATH = Path.home() / "Library" / "Mobile Documents" / "iCloud~md~obsidian" / "Documents" / "Junction AI"


class VaultIndexer:
    """Indexes Obsidian vault into SQLite with FTS5 search."""

    def __init__(self, db_path: str = None, vault_path: str = None):
        self.db_path = db_path or str(DB_PATH)
        self.vault_path = Path(vault_path) if vault_path else VAULT_PATH
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self):
        """Create tables and FTS5 virtual table."""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS vault_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                folder TEXT NOT NULL,
                content TEXT NOT NULL,
                tags TEXT DEFAULT '[]',
                wiki_links TEXT DEFAULT '[]',
                word_count INTEGER DEFAULT 0,
                modified_at TEXT,
                indexed_at TEXT NOT NULL
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS vault_fts USING fts5(
                title, folder, content, tags,
                content='vault_notes',
                content_rowid='id',
                tokenize='porter unicode61'
            );

            -- Triggers to keep FTS in sync
            CREATE TRIGGER IF NOT EXISTS vault_ai AFTER INSERT ON vault_notes BEGIN
                INSERT INTO vault_fts(rowid, title, folder, content, tags)
                VALUES (new.id, new.title, new.folder, new.content, new.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS vault_ad AFTER DELETE ON vault_notes BEGIN
                INSERT INTO vault_fts(vault_fts, rowid, title, folder, content, tags)
                VALUES('delete', old.id, old.title, old.folder, old.content, old.tags);
            END;

            CREATE TRIGGER IF NOT EXISTS vault_au AFTER UPDATE ON vault_notes BEGIN
                INSERT INTO vault_fts(vault_fts, rowid, title, folder, content, tags)
                VALUES('delete', old.id, old.title, old.folder, old.content, old.tags);
                INSERT INTO vault_fts(rowid, title, folder, content, tags)
                VALUES (new.id, new.title, new.folder, new.content, new.tags);
            END;

            CREATE TABLE IF NOT EXISTS sync_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                synced_at TEXT NOT NULL,
                notes_indexed INTEGER DEFAULT 0,
                notes_updated INTEGER DEFAULT 0,
                notes_deleted INTEGER DEFAULT 0,
                duration_ms INTEGER DEFAULT 0
            );
        """)
        self.conn.commit()

    def sync(self) -> dict:
        """
        Full vault sync. Scans all .md files, upserts into DB,
        removes entries for deleted files.
        Returns sync stats.
        """
        import time
        start = time.time()

        if not self.vault_path.exists():
            logger.error(f"Vault path does not exist: {self.vault_path}")
            return {"error": "Vault path not found"}

        stats = {"indexed": 0, "updated": 0, "deleted": 0, "skipped": 0}
        seen_paths = set()

        # Walk vault directory
        for md_file in self.vault_path.rglob("*.md"):
            # Skip .obsidian config and .trash
            rel_path = str(md_file.relative_to(self.vault_path))
            if rel_path.startswith(".obsidian") or rel_path.startswith(".trash"):
                continue

            seen_paths.add(rel_path)

            # Check if already indexed and unchanged
            modified_at = datetime.fromtimestamp(md_file.stat().st_mtime).isoformat()
            existing = self.conn.execute(
                "SELECT modified_at FROM vault_notes WHERE path = ?",
                (rel_path,)
            ).fetchone()

            if existing and existing["modified_at"] == modified_at:
                stats["skipped"] += 1
                continue

            # Parse the file
            try:
                content = md_file.read_text(encoding="utf-8")
            except Exception as e:
                logger.warning(f"Cannot read {rel_path}: {e}")
                continue

            title = md_file.stem
            folder = md_file.parent.relative_to(self.vault_path).parts[0] if md_file.parent != self.vault_path else "root"

            # Extract wiki-links [[...]]
            wiki_links = re.findall(r'\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]', content)

            # Extract tags #tag
            tags = re.findall(r'(?:^|\s)#([a-zA-Z][a-zA-Z0-9_/]+)', content)

            # Extract YAML frontmatter tags
            fm_match = re.match(r'^---\n(.*?)\n---', content, re.DOTALL)
            if fm_match:
                fm = fm_match.group(1)
                fm_tags = re.findall(r'^\s*-\s*(\w+)', fm, re.MULTILINE)
                tags.extend(fm_tags)

            tags = list(set(tags))
            wiki_links = list(set(wiki_links))
            word_count = len(content.split())

            import json
            tags_json = json.dumps(tags)
            links_json = json.dumps(wiki_links)
            now = datetime.now().isoformat()

            if existing:
                self.conn.execute("""
                    UPDATE vault_notes SET
                        title=?, folder=?, content=?, tags=?, wiki_links=?,
                        word_count=?, modified_at=?, indexed_at=?
                    WHERE path=?
                """, (title, folder, content, tags_json, links_json,
                      word_count, modified_at, now, rel_path))
                stats["updated"] += 1
            else:
                self.conn.execute("""
                    INSERT INTO vault_notes
                        (path, title, folder, content, tags, wiki_links,
                         word_count, modified_at, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (rel_path, title, folder, content, tags_json, links_json,
                      word_count, modified_at, now))
                stats["indexed"] += 1

        # Remove entries for deleted files
        all_paths = [row[0] for row in
                     self.conn.execute("SELECT path FROM vault_notes").fetchall()]
        for path in all_paths:
            if path not in seen_paths:
                self.conn.execute("DELETE FROM vault_notes WHERE path = ?", (path,))
                stats["deleted"] += 1

        self.conn.commit()

        duration_ms = int((time.time() - start) * 1000)
        self.conn.execute("""
            INSERT INTO sync_log (synced_at, notes_indexed, notes_updated, notes_deleted, duration_ms)
            VALUES (?, ?, ?, ?, ?)
        """, (datetime.now().isoformat(), stats["indexed"], stats["updated"],
              stats["deleted"], duration_ms))
        self.conn.commit()

        stats["duration_ms"] = duration_ms
        logger.info(f"Vault sync: {stats}")
        return stats

    def search(self, query: str, limit: int = 10) -> list[dict]:
        """
        Full-text search across vault notes.
        Returns matched notes with snippets.
        """
        rows = self.conn.execute("""
            SELECT v.id, v.path, v.title, v.folder, v.word_count, v.tags,
                   snippet(vault_fts, 2, '**', '**', '...', 40) as snippet,
                   rank
            FROM vault_fts
            JOIN vault_notes v ON v.id = vault_fts.rowid
            WHERE vault_fts MATCH ?
            ORDER BY rank
            LIMIT ?
        """, (query, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_folder_notes(self, folder: str) -> list[dict]:
        """Get all notes in a specific folder."""
        rows = self.conn.execute("""
            SELECT id, path, title, folder, word_count, tags
            FROM vault_notes
            WHERE folder = ?
            ORDER BY title
        """, (folder,)).fetchall()
        return [dict(r) for r in rows]

    def get_note(self, path: str) -> Optional[dict]:
        """Get full content of a specific note."""
        row = self.conn.execute(
            "SELECT * FROM vault_notes WHERE path = ?", (path,)
        ).fetchone()
        return dict(row) if row else None

    def get_stats(self) -> dict:
        """Get vault index statistics."""
        total = self.conn.execute("SELECT COUNT(*) FROM vault_notes").fetchone()[0]
        folders = self.conn.execute(
            "SELECT folder, COUNT(*) as count FROM vault_notes GROUP BY folder ORDER BY count DESC"
        ).fetchall()
        total_words = self.conn.execute("SELECT SUM(word_count) FROM vault_notes").fetchone()[0] or 0

        last_sync = self.conn.execute(
            "SELECT * FROM sync_log ORDER BY id DESC LIMIT 1"
        ).fetchone()

        return {
            "total_notes": total,
            "total_words": total_words,
            "folders": {r["folder"]: r["count"] for r in folders},
            "last_sync": dict(last_sync) if last_sync else None,
        }

    def format_search_for_agent(self, query: str, limit: int = 5) -> str:
        """Format search results for injection into agent prompt."""
        results = self.search(query, limit)
        if not results:
            return ""

        lines = [f"=== VAULT KNOWLEDGE: '{query}' ({len(results)} notes found) ==="]
        for r in results:
            lines.append(f"\n--- {r['title']} ({r['folder']}) ---")
            lines.append(f"  {r['snippet']}")
        return "\n".join(lines)

    def close(self):
        self.conn.close()


# --- CLI ---

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    indexer = VaultIndexer()

    if len(sys.argv) < 2:
        print("Usage: python -m core.vault_indexer [sync|search|stats|folder]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "sync":
        stats = indexer.sync()
        print(f"Vault sync complete: {stats}")

    elif cmd == "search" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        results = indexer.search(query)
        for r in results:
            print(f"\n[{r['folder']}] {r['title']}")
            print(f"  {r['snippet']}")

    elif cmd == "stats":
        stats = indexer.get_stats()
        print(f"Total notes: {stats['total_notes']}")
        print(f"Total words: {stats['total_words']:,}")
        print(f"\nFolders:")
        for folder, count in stats["folders"].items():
            print(f"  {folder}: {count}")
        if stats["last_sync"]:
            print(f"\nLast sync: {stats['last_sync']['synced_at']}")

    elif cmd == "folder" and len(sys.argv) > 2:
        folder = sys.argv[2]
        notes = indexer.get_folder_notes(folder)
        for n in notes:
            print(f"  {n['title']} ({n['word_count']} words)")

    else:
        print("Unknown command. Use: sync, search, stats, folder")

    indexer.close()
