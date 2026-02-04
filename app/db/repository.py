import sqlite3
import json
import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict
from app.core.config import settings

class HoneyDB:
    def __init__(self):
        self.db_path = settings.DATABASE_PATH
        self.executor = ThreadPoolExecutor(max_workers=5)
        self._init_db()

    def _init_db(self):
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
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    is_scam INTEGER DEFAULT 0,
                    created_at DATETIME
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS extracted_intel (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    type TEXT, -- 'upi', 'bank', 'link', 'phone'
                    value TEXT,
                    timestamp DATETIME
                )
            """)

    async def add_message(self, session_id: str, role: str, content: str):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self._add_message_sync, session_id, role, content)

    def _add_message_sync(self, session_id: str, role: str, content: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, role, content, datetime.now())
            )

    async def set_scam_flag(self, session_id: str, is_scam: bool):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self._set_scam_flag_sync, session_id, is_scam)

    def _set_scam_flag_sync(self, session_id: str, is_scam: bool):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO sessions (session_id, is_scam, created_at) VALUES (?, ?, ?)",
                (session_id, 1 if is_scam else 0, datetime.now())
            )

    async def save_intel(self, session_id: str, intel_type: str, value: str):
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(self.executor, self._save_intel_sync, session_id, intel_type, value)

    def _save_intel_sync(self, session_id: str, intel_type: str, value: str):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO extracted_intel (session_id, type, value, timestamp) VALUES (?, ?, ?, ?)",
                (session_id, intel_type, value, datetime.now())
            )

    async def get_context(self, session_id: str, limit: int = 10) -> List[Dict]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._get_context_sync, session_id, limit)

    def _get_context_sync(self, session_id: str, limit: int = 10) -> List[Dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT role, content FROM messages WHERE session_id = ? ORDER BY timestamp DESC LIMIT ?",
                (session_id, limit)
            )
            rows = cursor.fetchall()
            return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    async def get_syndicate_links(self):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._get_syndicate_links_sync)

    def _get_syndicate_links_sync(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            # Find shared identifiers across sessions
            cursor = conn.execute("""
                SELECT value, GROUP_CONCAT(session_id) as sessions, COUNT(session_id) as count
                FROM extracted_intel
                GROUP BY value
                HAVING count > 1
            """)
            shared = cursor.fetchall()
            
            nodes = []
            links = []
            seen_nodes = set()
            
            for row in shared:
                ident_id = f"ident_{row['value']}"
                if ident_id not in seen_nodes:
                    nodes.append({"id": ident_id, "type": "identifier", "label": row['value']})
                    seen_nodes.add(ident_id)
                
                for s_id in row['sessions'].split(','):
                    if s_id not in seen_nodes:
                        nodes.append({"id": s_id, "type": "session", "label": f"Session {s_id[:8]}"})
                        seen_nodes.add(s_id)
                    links.append({"source": s_id, "target": ident_id})
            
            # If no real links, return empty structure instead of fake mock
            if not nodes:
                return {"nodes": [], "links": [], "metadata": "No syndicate patterns detected yet."}
                
            return {
                "nodes": nodes,
                "links": links,
                "metadata": f"Detected {len(shared)} shared identifiers linking {len(nodes) - len(shared)} sessions."
            }

    async def get_stats(self):
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._get_stats_sync)

    def _get_stats_sync(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            total_sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            scams_detected = conn.execute("SELECT COUNT(*) FROM sessions WHERE is_scam = 1").fetchone()[0]
            top_upi = conn.execute("""
                SELECT value, COUNT(*) as count 
                FROM extracted_intel 
                WHERE type = 'upi' 
                GROUP BY value 
                ORDER BY count DESC 
                LIMIT 5
            """).fetchall()
            return {
                "total_sessions": total_sessions,
                "scams_detected": scams_detected,
                "top_upi_ids": [r["value"] for r in top_upi]
            }

    async def get_turn_count(self, session_id: str) -> int:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._get_turn_count_sync, session_id)

    def _get_turn_count_sync(self, session_id: str) -> int:
        with sqlite3.connect(self.db_path) as conn:
            if session_id == "all":
                return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            return conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)).fetchone()[0]

    async def is_scam_session(self, session_id: str) -> bool:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(self.executor, self._is_scam_session_sync, session_id)

    def _is_scam_session_sync(self, session_id: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            res = conn.execute("SELECT is_scam FROM sessions WHERE session_id = ?", (session_id,)).fetchone()
            return bool(res[0]) if res else False

db = HoneyDB()