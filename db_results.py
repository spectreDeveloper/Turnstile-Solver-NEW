import aiosqlite
import json
import logging
from typing import Dict, Any, Optional, Union

DB_PATH = "results.db"

# PRAGMA настройки для оптимизации БД
PRAGMA_SETTINGS = [
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL", 
    "PRAGMA cache_size=10000",
    "PRAGMA temp_store=MEMORY",
    "PRAGMA busy_timeout=30000"
]

async def _apply_pragma_settings(db):
    """Применить PRAGMA настройки к подключению БД"""
    for pragma in PRAGMA_SETTINGS:
        await db.execute(pragma)

async def init_db():
    """Initialize database with results table in WAL mode"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await _apply_pragma_settings(db)
            
            await db.execute("""
                CREATE TABLE IF NOT EXISTS results (
                    task_id TEXT PRIMARY KEY,
                    type TEXT NOT NULL,
                    data TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            await db.commit()
            logging.getLogger("TurnstileAPIServer").info(f"Database initialized in WAL mode: {DB_PATH}")
    except Exception as e:
        logging.getLogger("TurnstileAPIServer").error(f"Database initialization error: {e}")
        raise

async def save_result(task_id: str, task_type: str, data: Union[Dict[str, Any], str]) -> None:
    """Save result to database"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await _apply_pragma_settings(db)
            
            data_json = json.dumps(data) if isinstance(data, dict) else data
            
            await db.execute(
                "REPLACE INTO results (task_id, type, data) VALUES (?, ?, ?)",
                (task_id, task_type, data_json)
            )
            await db.commit()
    except Exception as e:
        logging.getLogger("TurnstileAPIServer").error(f"Error saving result {task_id}: {e}")
        raise

async def load_result(task_id: str) -> Optional[Union[Dict[str, Any], str]]:
    """Load result from database"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await _apply_pragma_settings(db)
            
            async with db.execute("SELECT data FROM results WHERE task_id = ?", (task_id,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    try:
                        return json.loads(row[0])
                    except json.JSONDecodeError:
                        return row[0]
        return None
    except Exception as e:
        logging.getLogger("TurnstileAPIServer").error(f"Error loading result {task_id}: {e}")
        return None

async def load_all_results() -> Dict[str, Any]:
    """Load all results from database"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await _apply_pragma_settings(db)
            
            results = {}
            async with db.execute("SELECT task_id, data FROM results") as cursor:
                async for row in cursor:
                    try:
                        results[row[0]] = json.loads(row[1])
                    except json.JSONDecodeError:
                        results[row[0]] = row[1]
            return results
    except Exception as e:
        logging.getLogger("TurnstileAPIServer").error(f"Error loading all results: {e}")
        return {}

async def delete_result(task_id: str) -> None:
    """Delete result from database"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await _apply_pragma_settings(db)
            
            await db.execute("DELETE FROM results WHERE task_id = ?", (task_id,))
            await db.commit()
    except Exception as e:
        logging.getLogger("TurnstileAPIServer").error(f"Error deleting result {task_id}: {e}")

async def get_pending_count() -> int:
    """Get count of pending tasks"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await _apply_pragma_settings(db)
            
            async with db.execute("SELECT COUNT(*) FROM results WHERE data LIKE '%CAPTCHA_NOT_READY%'") as cursor:
                row = await cursor.fetchone()
                return row[0] if row else 0
    except Exception as e:
        logging.getLogger("TurnstileAPIServer").error(f"Error getting pending count: {e}")
        return 0

async def cleanup_old_results(days_old: int = 1) -> int:
    """Clean up results older than specified days"""
    try:
        async with aiosqlite.connect(DB_PATH) as db:
            await _apply_pragma_settings(db)
            
            async with db.execute(
                "DELETE FROM results WHERE created_at < datetime('now', '-{} days')".format(days_old)
            ) as cursor:
                deleted_count = cursor.rowcount
                await db.commit()
                logging.getLogger("TurnstileAPIServer").info(f"Cleaned up {deleted_count} old results")
                return deleted_count
    except Exception as e:
        logging.getLogger("TurnstileAPIServer").error(f"Error cleaning up old results: {e}")
        return 0
