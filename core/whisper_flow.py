#!/usr/bin/env python3
"""
Whisper Flow — Audio → Transcription → Insights Pipeline
Records/fetches audio, transcribes with Whisper, chunks by topic, extracts insights.
Creates searchable archive of all thinking/research.
"""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict
import sqlite3

logger = logging.getLogger(__name__)


class WhisperFlow:
    """Transcribe, analyze, and archive audio content."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.audio_archive = base_dir / "data" / "audio_archive"
        self.transcripts_db = base_dir / "data" / "transcripts.db"
        self.audio_archive.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database for transcripts."""
        conn = sqlite3.connect(self.transcripts_db)
        c = conn.cursor()
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS transcripts (
                id INTEGER PRIMARY KEY,
                filename TEXT UNIQUE,
                source TEXT,
                transcribed_at TIMESTAMP,
                duration_seconds INTEGER,
                full_text TEXT,
                summary TEXT,
                topics TEXT,
                searchable BOOLEAN DEFAULT 0
            )
        """
        )
        c.execute(
            """
            CREATE TABLE IF NOT EXISTS insights (
                id INTEGER PRIMARY KEY,
                transcript_id INTEGER,
                timestamp_sec INTEGER,
                insight TEXT,
                category TEXT,
                confidence REAL,
                FOREIGN KEY(transcript_id) REFERENCES transcripts(id)
            )
        """
        )
        conn.commit()
        conn.close()

    def transcribe_audio(
        self,
        audio_source: str,
        source_type: str = "file",
    ) -> Dict:
        """
        Transcribe audio file or URL.

        Args:
            audio_source: File path or URL to audio
            source_type: "file" | "url" | "youtube"

        Returns:
            Dict with transcription result
        """
        try:
            # Import here to avoid hard dependency
            import openai

            client = openai.OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

            # Load audio
            if source_type == "file":
                with open(audio_source, "rb") as f:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f,
                    )
            elif source_type == "url":
                # Download then transcribe
                import requests

                resp = requests.get(audio_source)
                filename = self.audio_archive / f"downloaded_{datetime.now().timestamp()}.mp3"
                with open(filename, "wb") as f:
                    f.write(resp.content)

                with open(filename, "rb") as f:
                    transcript = client.audio.transcriptions.create(
                        model="whisper-1",
                        file=f,
                    )
            else:
                return {"error": f"Unknown source_type: {source_type}"}

            result = {
                "success": True,
                "text": transcript.text,
                "source": audio_source,
                "transcribed_at": datetime.now().isoformat(),
            }

            logger.info(f"Transcribed: {audio_source}")
            return result

        except ImportError:
            logger.error("OpenAI library not installed. Install with: pip install openai")
            return {"error": "OpenAI library required"}
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return {"error": str(e)}

    def chunk_by_topic(self, text: str, chunk_size: int = 500) -> List[Dict]:
        """
        Split transcript into semantic chunks.
        Simple approach: split by paragraph, group into chunks.

        Returns:
            List of chunks with start/end positions
        """
        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = []
        current_length = 0

        for para in paragraphs:
            if current_length + len(para) > chunk_size and current_chunk:
                chunks.append(
                    {
                        "text": "\n\n".join(current_chunk),
                        "length": current_length,
                        "chunk_num": len(chunks) + 1,
                    }
                )
                current_chunk = [para]
                current_length = len(para)
            else:
                current_chunk.append(para)
                current_length += len(para)

        if current_chunk:
            chunks.append(
                {
                    "text": "\n\n".join(current_chunk),
                    "length": current_length,
                    "chunk_num": len(chunks) + 1,
                }
            )

        return chunks

    def extract_insights(self, text: str) -> List[Dict]:
        """
        Extract key insights from transcript.
        In production, use Claude for semantic extraction.

        Returns:
            List of insights with confidence scores
        """
        # Placeholder: simple pattern matching
        # In reality, would use Claude + semantic analysis
        insights = []

        # Look for decision statements
        decision_keywords = ["decided", "commit", "will", "must", "should"]
        for keyword in decision_keywords:
            if keyword in text.lower():
                insights.append(
                    {
                        "type": "decision",
                        "text": f"Contains planning/decision language around '{keyword}'",
                        "confidence": 0.7,
                    }
                )

        # Look for learning statements
        if "learned" in text.lower() or "realised" in text.lower():
            insights.append(
                {
                    "type": "learning",
                    "text": "Contains learning or realization statements",
                    "confidence": 0.8,
                }
            )

        return insights

    def store_transcript(
        self,
        filename: str,
        full_text: str,
        source: str,
        summary: Optional[str] = None,
    ) -> bool:
        """Store transcript in database for search."""
        try:
            conn = sqlite3.connect(self.transcripts_db)
            c = conn.cursor()

            chunks = self.chunk_by_topic(full_text)
            insights = self.extract_insights(full_text)

            c.execute(
                """
                INSERT INTO transcripts
                (filename, source, transcribed_at, full_text, summary, topics, searchable)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    filename,
                    source,
                    datetime.now().isoformat(),
                    full_text,
                    summary or "",
                    json.dumps([c["chunk_num"] for c in chunks]),
                    1,
                ),
            )

            transcript_id = c.lastrowid

            # Store insights
            for insight in insights:
                c.execute(
                    """
                    INSERT INTO insights
                    (transcript_id, insight, category, confidence)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        transcript_id,
                        insight.get("text", ""),
                        insight.get("type", "general"),
                        insight.get("confidence", 0.5),
                    ),
                )

            conn.commit()
            conn.close()

            logger.info(f"Stored transcript: {filename} (ID: {transcript_id})")
            return True

        except sqlite3.IntegrityError:
            logger.warning(f"Transcript already exists: {filename}")
            return False
        except Exception as e:
            logger.error(f"Storage error: {e}")
            return False

    def search_transcripts(self, query: str) -> List[Dict]:
        """Search all stored transcripts."""
        try:
            conn = sqlite3.connect(self.transcripts_db)
            c = conn.cursor()

            c.execute(
                """
                SELECT filename, source, summary, transcribed_at
                FROM transcripts
                WHERE full_text LIKE ? AND searchable = 1
                ORDER BY transcribed_at DESC
            """,
                (f"%{query}%",),
            )

            results = [
                {
                    "filename": row[0],
                    "source": row[1],
                    "summary": row[2],
                    "date": row[3],
                }
                for row in c.fetchall()
            ]

            conn.close()
            return results

        except Exception as e:
            logger.error(f"Search error: {e}")
            return []

    def get_archive_stats(self) -> Dict:
        """Get statistics on transcript archive."""
        try:
            conn = sqlite3.connect(self.transcripts_db)
            c = conn.cursor()

            c.execute("SELECT COUNT(*) FROM transcripts WHERE searchable = 1")
            total = c.fetchone()[0]

            c.execute("SELECT SUM(LENGTH(full_text)) FROM transcripts")
            total_chars = c.fetchone()[0] or 0

            c.execute("SELECT COUNT(*) FROM insights")
            total_insights = c.fetchone()[0]

            conn.close()

            return {
                "total_transcripts": total,
                "total_characters": total_chars,
                "total_insights": total_insights,
                "avg_transcript_length": total_chars // max(total, 1),
            }

        except Exception as e:
            logger.error(f"Stats error: {e}")
            return {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    base_dir = Path(__file__).resolve().parent.parent
    flow = WhisperFlow(base_dir)

    print("\n=== WHISPER FLOW DEMO ===")
    print(f"Archive: {flow.audio_archive}")
    print(f"Database: {flow.transcripts_db}")
    print(f"Stats: {flow.get_archive_stats()}")
