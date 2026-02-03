import sqlite3
import json
from datetime import datetime
from typing import List, Dict
from app.core.config import settings

class HoneyDB:
    def __init__(self):
        self.db_path = settings.DATABASE_PATH
        self._init_db()

    def _init_db(self):
        # Create the database file if it doesn't exist
        # We check the directory in case it was deleted
        import os
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    role TEXT,
                    content TEXT,
                    timestamp DATETIME
                )
            """)

    def add_message(self, session_id: str, role: str, content: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, role, content, datetime.now())
            )

    def get_context(self, session_id: str, limit: int = 10) -> List[Dict]:
        """Returns context formatted for LangChain"""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit)
            )
            rows = cursor.fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def get_turn_count(self, session_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,))
            result = cursor.fetchone()
            return result[0] if result else 0

db = HoneyDB()