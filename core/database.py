"""
Database module for Knowledge Manager.
Uses SQLite to store vocabulary, application settings, and AI providers.
Vocabulary can also be persisted to JSON files in a dedicated vocab/ directory.
"""
import json
import os
import sys
import sqlite3
from datetime import datetime
from typing import List, Dict, Optional

from core.logger import get_logger

_logger = get_logger()

# Database, vocab, and backups all live in the project root.
# This ensures PyInstaller rebuilds never touch user data.
if getattr(sys, 'frozen', False):
    # exe is at 项目根目录/dist/KnowledgeManager/KnowledgeManager.exe
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(sys.executable)))
else:
    _BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DB_PATH = os.path.join(_BASE_DIR, "data.db")
VOCAB_DIR = os.path.join(_BASE_DIR, "vocab")
BACKUP_DIR = os.path.join(_BASE_DIR, "backup")


def _get_conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        _logger.error(f"[DB] Failed to connect to {DB_PATH}: {e}")
        raise


def backup_database(max_backups: int = 1) -> Optional[str]:
    """
    Backup data.db to the backup/ directory.
    Creates:
      - backup/data.db  (always the latest copy)
      - backup/data_YYYYMMDD_HHMMSS.db  (timestamped history, up to max_backups)
    Returns the path of the timestamped backup, or None if DB does not exist.
    """
    if not os.path.exists(DB_PATH):
        _logger.warning("[DB] backup skipped: database not found")
        return None

    os.makedirs(BACKUP_DIR, exist_ok=True)

    # Always overwrite the latest backup
    latest_backup = os.path.join(BACKUP_DIR, "data.db")
    try:
        import shutil
        shutil.copy2(DB_PATH, latest_backup)
    except Exception as e:
        _logger.error(f"[DB] backup copy failed: {e}")

    # Create a timestamped backup
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    timed_backup = os.path.join(BACKUP_DIR, f"data_{timestamp}.db")
    try:
        shutil.copy2(DB_PATH, timed_backup)
        _logger.info(f"[DB] backup created: {timed_backup}")
    except Exception as e:
        _logger.error(f"[DB] timestamped backup failed: {e}")
        return None

    # Clean up old timestamped backups, keep only the most recent max_backups
    try:
        backups = sorted(
            [
                os.path.join(BACKUP_DIR, f)
                for f in os.listdir(BACKUP_DIR)
                if f.startswith("data_") and f.endswith(".db")
            ],
            key=os.path.getmtime,
        )
        for old in backups[:-max_backups]:
            os.remove(old)
    except Exception:
        pass

    return timed_backup


def init_db():
    """Initialize database tables."""
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vocabulary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_path TEXT NOT NULL,
                word TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                context TEXT,
                entry_type TEXT DEFAULT 'word',
                definition TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vocab_files (
                pdf_path TEXT PRIMARY KEY,
                vocab_file_path TEXT NOT NULL,
                last_saved_at TEXT
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS ai_providers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                base_url TEXT NOT NULL,
                api_key TEXT NOT NULL,
                model TEXT NOT NULL,
                proxy TEXT DEFAULT '',
                is_default INTEGER DEFAULT 0,
                streaming INTEGER DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        # Migrate old ai_providers table that lacks new columns
        cursor = conn.execute("PRAGMA table_info(ai_providers)")
        ai_cols = [row['name'] for row in cursor.fetchall()]
        if 'streaming' not in ai_cols:
            conn.execute("ALTER TABLE ai_providers ADD COLUMN streaming INTEGER DEFAULT 1")
        if 'temperature' not in ai_cols:
            conn.execute("ALTER TABLE ai_providers ADD COLUMN temperature REAL DEFAULT 0.7")
        if 'max_tokens' not in ai_cols:
            conn.execute("ALTER TABLE ai_providers ADD COLUMN max_tokens INTEGER DEFAULT 4096")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS explain_cache (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_path TEXT NOT NULL,
                word TEXT NOT NULL,
                explanation TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS page_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_path TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                content TEXT DEFAULT '',
                updated_at TEXT NOT NULL,
                UNIQUE(pdf_path, page_number)
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                messages_json TEXT DEFAULT '[]',
                token_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        # Migrate old tables that lack entry_type
        cursor = conn.execute("PRAGMA table_info(vocabulary)")
        columns = [row['name'] for row in cursor.fetchall()]
        if 'entry_type' not in columns:
            conn.execute("ALTER TABLE vocabulary ADD COLUMN entry_type TEXT DEFAULT 'word'")
        if 'definition' not in columns:
            conn.execute("ALTER TABLE vocabulary ADD COLUMN definition TEXT DEFAULT ''")
        # Quiz mode tables
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_topics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                description TEXT DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                source_file_path TEXT DEFAULT '',
                question_count INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                last_attempt_at TEXT,
                FOREIGN KEY (topic_id) REFERENCES quiz_topics(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                question_number INTEGER NOT NULL,
                question_text TEXT NOT NULL,
                options_json TEXT NOT NULL DEFAULT '[]',
                correct_answer TEXT NOT NULL,
                explanation TEXT DEFAULT '',
                image_paths_json TEXT DEFAULT '[]',
                is_multiple_choice INTEGER DEFAULT 0,
                FOREIGN KEY (batch_id) REFERENCES quiz_batches(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                total_duration_seconds INTEGER DEFAULT 0,
                score INTEGER DEFAULT 0,
                total_questions INTEGER DEFAULT 0,
                correct_count INTEGER DEFAULT 0,
                FOREIGN KEY (batch_id) REFERENCES quiz_batches(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_responses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL,
                question_id INTEGER NOT NULL,
                selected_answer TEXT DEFAULT '',
                is_correct INTEGER DEFAULT 0,
                duration_seconds INTEGER DEFAULT 0,
                confidence_level INTEGER DEFAULT 3,
                FOREIGN KEY (attempt_id) REFERENCES quiz_attempts(id) ON DELETE CASCADE,
                FOREIGN KEY (question_id) REFERENCES quiz_questions(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL UNIQUE,
                note_text TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (question_id) REFERENCES quiz_questions(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_attempt_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                attempt_id INTEGER NOT NULL UNIQUE,
                note_text TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (attempt_id) REFERENCES quiz_attempts(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS quiz_focus_items (
                topic_id INTEGER PRIMARY KEY,
                pinned_order INTEGER DEFAULT 0,
                added_at TEXT NOT NULL,
                FOREIGN KEY (topic_id) REFERENCES quiz_topics(id) ON DELETE CASCADE
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS highlights (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                pdf_path TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                text TEXT,
                x REAL,
                y REAL,
                width REAL,
                height REAL,
                color TEXT DEFAULT '#FFEB3B',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        conn.commit()


# ---------------------------------------------------------------------------
# Quiz Mode CRUD
# ---------------------------------------------------------------------------

def create_quiz_topic(name: str, description: str = "") -> int:
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO quiz_topics (name, description, created_at) VALUES (?, ?, ?)",
            (name, description, datetime.now().isoformat())
        )
        conn.commit()
        return cursor.lastrowid


def rename_quiz_topic(topic_id: int, new_name: str):
    with _get_conn() as conn:
        conn.execute("UPDATE quiz_topics SET name=? WHERE id=?", (new_name, topic_id))
        conn.commit()


def update_quiz_topic_description(topic_id: int, description: str):
    with _get_conn() as conn:
        conn.execute("UPDATE quiz_topics SET description=? WHERE id=?", (description, topic_id))
        conn.commit()


def delete_quiz_topic(topic_id: int):
    with _get_conn() as conn:
        conn.execute("DELETE FROM quiz_topics WHERE id=?", (topic_id,))
        conn.commit()


def get_all_quiz_topics() -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM quiz_topics ORDER BY created_at").fetchall()
        return [dict(row) for row in rows]


def get_quiz_topic(topic_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM quiz_topics WHERE id=?", (topic_id,)).fetchone()
        return dict(row) if row else None


def create_quiz_batch(topic_id: int, title: str, source_file_path: str = "", question_count: int = 0) -> int:
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO quiz_batches (topic_id, title, source_file_path, question_count, created_at) VALUES (?, ?, ?, ?, ?)",
            (topic_id, title, source_file_path, question_count, datetime.now().isoformat())
        )
        conn.commit()
        return cursor.lastrowid


def delete_quiz_batch(batch_id: int):
    with _get_conn() as conn:
        conn.execute("DELETE FROM quiz_batches WHERE id=?", (batch_id,))
        conn.commit()


def get_quiz_batches_by_topic(topic_id: int) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM quiz_batches WHERE topic_id=? ORDER BY created_at",
            (topic_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_quiz_batch(batch_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM quiz_batches WHERE id=?", (batch_id,)).fetchone()
        return dict(row) if row else None


def update_batch_last_attempt(batch_id: int):
    with _get_conn() as conn:
        conn.execute(
            "UPDATE quiz_batches SET last_attempt_at=? WHERE id=?",
            (datetime.now().isoformat(), batch_id)
        )
        conn.commit()


def create_quiz_question(batch_id: int, question_number: int, question_text: str,
                         options: dict, correct_answer: str, explanation: str = "",
                         image_paths: list = None, is_multiple_choice: bool = False) -> int:
    options_json = json.dumps(options, ensure_ascii=False)
    image_paths_json = json.dumps(image_paths or [], ensure_ascii=False)
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO quiz_questions (batch_id, question_number, question_text, options_json, "
            "correct_answer, explanation, image_paths_json, is_multiple_choice) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (batch_id, question_number, question_text, options_json, correct_answer,
             explanation, image_paths_json, 1 if is_multiple_choice else 0)
        )
        conn.commit()
        return cursor.lastrowid


def get_quiz_questions_by_batch(batch_id: int) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM quiz_questions WHERE batch_id=? ORDER BY question_number",
            (batch_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_quiz_question(question_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM quiz_questions WHERE id=?", (question_id,)).fetchone()
        return dict(row) if row else None


def create_quiz_attempt(batch_id: int, total_questions: int) -> int:
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO quiz_attempts (batch_id, started_at, total_questions) VALUES (?, ?, ?)",
            (batch_id, datetime.now().isoformat(), total_questions)
        )
        conn.commit()
        return cursor.lastrowid


def complete_quiz_attempt(attempt_id: int, total_duration: int, score: int, correct_count: int):
    with _get_conn() as conn:
        conn.execute(
            "UPDATE quiz_attempts SET completed_at=?, total_duration_seconds=?, score=?, correct_count=? WHERE id=?",
            (datetime.now().isoformat(), total_duration, score, correct_count, attempt_id)
        )
        conn.commit()


def get_quiz_attempts_by_batch(batch_id: int) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM quiz_attempts WHERE batch_id=? ORDER BY started_at DESC",
            (batch_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def get_quiz_attempt(attempt_id: int) -> Optional[Dict]:
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM quiz_attempts WHERE id=?", (attempt_id,)).fetchone()
        return dict(row) if row else None


def create_quiz_response(attempt_id: int, question_id: int, selected_answer: str,
                         is_correct: bool, duration_seconds: int, confidence_level: int) -> int:
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO quiz_responses (attempt_id, question_id, selected_answer, is_correct, "
            "duration_seconds, confidence_level) VALUES (?, ?, ?, ?, ?, ?)",
            (attempt_id, question_id, selected_answer, 1 if is_correct else 0,
             duration_seconds, confidence_level)
        )
        conn.commit()
        return cursor.lastrowid


def get_quiz_responses_by_attempt(attempt_id: int) -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM quiz_responses WHERE attempt_id=?",
            (attempt_id,)
        ).fetchall()
        return [dict(row) for row in rows]


def save_quiz_note(question_id: int, note_text: str):
    with _get_conn() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO quiz_notes (question_id, note_text, created_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(question_id) DO UPDATE SET note_text=excluded.note_text, updated_at=excluded.updated_at",
            (question_id, note_text, now, now)
        )
        conn.commit()


def get_quiz_note(question_id: int) -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT note_text FROM quiz_notes WHERE question_id=?", (question_id,)).fetchone()
        return row["note_text"] if row else ""


def save_attempt_note(attempt_id: int, note_text: str):
    with _get_conn() as conn:
        now = datetime.now().isoformat()
        conn.execute(
            "INSERT INTO quiz_attempt_notes (attempt_id, note_text, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(attempt_id) DO UPDATE SET note_text=excluded.note_text",
            (attempt_id, note_text, now)
        )
        conn.commit()


def get_attempt_note(attempt_id: int) -> str:
    with _get_conn() as conn:
        row = conn.execute("SELECT note_text FROM quiz_attempt_notes WHERE attempt_id=?", (attempt_id,)).fetchone()
        return row["note_text"] if row else ""


# ---------------------------------------------------------------------------
# Quiz Focus Items (Current Focus)
# ---------------------------------------------------------------------------

def pin_quiz_topic(topic_id: int):
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO quiz_focus_items (topic_id, pinned_order, added_at) VALUES (?, 0, ?) "
            "ON CONFLICT(topic_id) DO UPDATE SET added_at=excluded.added_at",
            (topic_id, now)
        )
        conn.commit()


def unpin_quiz_topic(topic_id: int):
    with _get_conn() as conn:
        conn.execute("DELETE FROM quiz_focus_items WHERE topic_id=?", (topic_id,))
        conn.commit()


def get_focus_topics() -> List[Dict]:
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT t.*, f.pinned_order, f.added_at as pinned_at "
            "FROM quiz_focus_items f JOIN quiz_topics t ON f.topic_id = t.id "
            "ORDER BY f.pinned_order, f.added_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def is_topic_pinned(topic_id: int) -> bool:
    with _get_conn() as conn:
        row = conn.execute("SELECT 1 FROM quiz_focus_items WHERE topic_id=?", (topic_id,)).fetchone()
        return bool(row)


# ---------------------------------------------------------------------------
# Vocabulary CRUD
# ---------------------------------------------------------------------------

def add_vocabulary(pdf_path: str, word: str, page_number: int, context: str = "", entry_type: str = "word", definition: str = "") -> int:
    """Add a word/phrase/sentence to the vocabulary list for a given PDF.
    Returns the inserted row id, or 0 if duplicate.
    """
    with _get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM vocabulary WHERE pdf_path=? AND word=?",
            (pdf_path, word)
        ).fetchone()
        if existing:
            return 0
        cursor = conn.execute(
            "INSERT INTO vocabulary (pdf_path, word, page_number, context, entry_type, definition, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (pdf_path, word, page_number, context, entry_type, definition, datetime.now().isoformat())
        )
        conn.commit()
        return cursor.lastrowid


def get_vocabulary(pdf_path: str) -> List[Dict]:
    """Get all vocabulary entries for a specific PDF."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM vocabulary WHERE pdf_path=? ORDER BY page_number, created_at",
            (pdf_path,)
        ).fetchall()
        return [dict(row) for row in rows]


def remove_vocabulary(entry_id: int):
    """Remove a vocabulary entry by id."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM vocabulary WHERE id=?", (entry_id,))
        conn.commit()


def update_vocabulary(entry_id: int, word: str = None, page_number: int = None, context: str = None, entry_type: str = None, definition: str = None):
    """Update fields of an existing vocabulary entry."""
    fields = []
    params = []
    if word is not None:
        fields.append("word=?")
        params.append(word)
    if page_number is not None:
        fields.append("page_number=?")
        params.append(page_number)
    if context is not None:
        fields.append("context=?")
        params.append(context)
    if entry_type is not None:
        fields.append("entry_type=?")
        params.append(entry_type)
    if definition is not None:
        fields.append("definition=?")
        params.append(definition)
    if not fields:
        return
    params.append(entry_id)
    with _get_conn() as conn:
        conn.execute(f"UPDATE vocabulary SET {', '.join(fields)} WHERE id=?", params)
        conn.commit()


def clear_vocabulary(pdf_path: str):
    """Clear all vocabulary for a PDF."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM vocabulary WHERE pdf_path=?", (pdf_path,))
        conn.commit()


# ---------------------------------------------------------------------------
# Vocab file mapping (pdf_path -> vocab_file_path)
# ---------------------------------------------------------------------------

def get_vocab_file_path(pdf_path: str) -> Optional[str]:
    """Return the mapped vocab JSON file path for a PDF, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT vocab_file_path FROM vocab_files WHERE pdf_path=?",
            (pdf_path,)
        ).fetchone()
        return row["vocab_file_path"] if row else None


def set_vocab_file_path(pdf_path: str, vocab_file_path: str):
    """Insert or update the mapping for a PDF."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO vocab_files (pdf_path, vocab_file_path, last_saved_at) VALUES (?, ?, ?) "
            "ON CONFLICT(pdf_path) DO UPDATE SET vocab_file_path=excluded.vocab_file_path, last_saved_at=excluded.last_saved_at",
            (pdf_path, vocab_file_path, datetime.now().isoformat())
        )
        conn.commit()


def remove_vocab_file_mapping(pdf_path: str):
    """Delete the mapping for a PDF."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM vocab_files WHERE pdf_path=?", (pdf_path,))
        conn.commit()


# ---------------------------------------------------------------------------
# File-based vocabulary persistence
# ---------------------------------------------------------------------------

def _vocab_file_path_for_pdf(pdf_path: str) -> str:
    """Generate a vocab JSON file path based on the PDF name."""
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    safe_name = "".join(c if c.isalnum() or c in "-_ " else "_" for c in base).strip()
    if not safe_name:
        safe_name = "vocab"
    os.makedirs(VOCAB_DIR, exist_ok=True)
    return os.path.join(VOCAB_DIR, f"{safe_name}.json")


def save_vocab_to_file(pdf_path: str) -> str:
    """Save all vocabulary entries for a PDF to a JSON file.
    Returns the file path written.
    """
    entries = get_vocabulary(pdf_path)
    vocab_file_path = _vocab_file_path_for_pdf(pdf_path)
    data = {
        "pdf_path": pdf_path,
        "saved_at": datetime.now().isoformat(),
        "entries": [
            {
                "word": e["word"],
                "page_number": e["page_number"],
                "context": e.get("context", ""),
                "entry_type": e.get("entry_type", "word"),
                "definition": e.get("definition", ""),
            }
            for e in entries
        ],
    }
    with open(vocab_file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    set_vocab_file_path(pdf_path, vocab_file_path)
    return vocab_file_path


def load_vocab_from_file(pdf_path: str) -> bool:
    """Load vocabulary entries from the mapped JSON file into the DB.
    Returns True if loaded successfully.
    """
    vocab_file_path = get_vocab_file_path(pdf_path)
    if not vocab_file_path or not os.path.isfile(vocab_file_path):
        return False
    with open(vocab_file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    entries = data.get("entries", [])
    if not entries:
        return False
    # Clear existing entries for this PDF to avoid duplicates
    clear_vocabulary(pdf_path)
    for e in entries:
        add_vocabulary(
            pdf_path,
            e.get("word", ""),
            e.get("page_number", 0),
            e.get("context", ""),
            e.get("entry_type", "word"),
            e.get("definition", ""),
        )
    return True


# ---------------------------------------------------------------------------
# AI Providers
# ---------------------------------------------------------------------------

def add_ai_provider(name: str, base_url: str, api_key: str, model: str, proxy: str = "", is_default: bool = False, streaming: bool = True, temperature: float = 0.7, max_tokens: int = 4096) -> int:
    """Add a new AI provider. Returns the inserted row id."""
    with _get_conn() as conn:
        if is_default:
            conn.execute("UPDATE ai_providers SET is_default=0")
        cursor = conn.execute(
            "INSERT INTO ai_providers (name, base_url, api_key, model, proxy, is_default, streaming, temperature, max_tokens, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, base_url, api_key, model, proxy, 1 if is_default else 0, 1 if streaming else 0, temperature, max_tokens, datetime.now().isoformat())
        )
        conn.commit()
        return cursor.lastrowid


def update_ai_provider(provider_id: int, name: str = None, base_url: str = None, api_key: str = None, model: str = None, proxy: str = None, is_default: bool = None, streaming: bool = None, temperature: float = None, max_tokens: int = None):
    """Update an AI provider."""
    fields = []
    params = []
    if name is not None:
        fields.append("name=?")
        params.append(name)
    if base_url is not None:
        fields.append("base_url=?")
        params.append(base_url)
    if api_key is not None:
        fields.append("api_key=?")
        params.append(api_key)
    if model is not None:
        fields.append("model=?")
        params.append(model)
    if proxy is not None:
        fields.append("proxy=?")
        params.append(proxy)
    if is_default is not None:
        fields.append("is_default=?")
        params.append(1 if is_default else 0)
    if streaming is not None:
        fields.append("streaming=?")
        params.append(1 if streaming else 0)
    if temperature is not None:
        fields.append("temperature=?")
        params.append(temperature)
    if max_tokens is not None:
        fields.append("max_tokens=?")
        params.append(max_tokens)
    if not fields:
        return
    params.append(provider_id)
    with _get_conn() as conn:
        if is_default:
            conn.execute("UPDATE ai_providers SET is_default=0")
        conn.execute(f"UPDATE ai_providers SET {', '.join(fields)} WHERE id=?", params)
        conn.commit()


def delete_ai_provider(provider_id: int):
    """Delete an AI provider by id."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM ai_providers WHERE id=?", (provider_id,))
        conn.commit()


def get_all_ai_providers() -> List[Dict]:
    """Get all AI providers ordered by id."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT * FROM ai_providers ORDER BY id").fetchall()
        return [dict(row) for row in rows]


def get_default_ai_provider() -> Optional[Dict]:
    """Get the default AI provider, or the first one if no default is set."""
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_providers WHERE is_default=1 LIMIT 1").fetchone()
        if row:
            return dict(row)
        row = conn.execute("SELECT * FROM ai_providers ORDER BY id LIMIT 1").fetchone()
        return dict(row) if row else None


def get_ai_provider(provider_id: int) -> Optional[Dict]:
    """Get a single AI provider by id."""
    with _get_conn() as conn:
        row = conn.execute("SELECT * FROM ai_providers WHERE id=?", (provider_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Explain Cache
# ---------------------------------------------------------------------------

def save_explanation(pdf_path: str, word: str, explanation: str) -> int:
    """Save or overwrite an explanation for a word in a PDF."""
    with _get_conn() as conn:
        conn.execute(
            "DELETE FROM explain_cache WHERE pdf_path=? AND word=?",
            (pdf_path, word)
        )
        cursor = conn.execute(
            "INSERT INTO explain_cache (pdf_path, word, explanation, created_at) VALUES (?, ?, ?, ?)",
            (pdf_path, word, explanation, datetime.now().isoformat())
        )
        conn.commit()
        return cursor.lastrowid


def get_explanation(pdf_path: str, word: str) -> Optional[str]:
    """Get saved explanation for a word, or None."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT explanation FROM explain_cache WHERE pdf_path=? AND word=?",
            (pdf_path, word)
        ).fetchone()
        return row["explanation"] if row else None


def delete_explanation(pdf_path: str, word: str):
    """Delete a saved explanation."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM explain_cache WHERE pdf_path=? AND word=?", (pdf_path, word))
        conn.commit()


# ---------------------------------------------------------------------------
# Page Notes
# ---------------------------------------------------------------------------

def get_page_note(pdf_path: str, page_number: int) -> str:
    """Get note content for a specific page of a PDF."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT content FROM page_notes WHERE pdf_path=? AND page_number=?",
            (pdf_path, page_number)
        ).fetchone()
        return row["content"] if row else ""


def save_page_note(pdf_path: str, page_number: int, content: str):
    """Save or overwrite a page note."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO page_notes (pdf_path, page_number, content, updated_at) "
            "VALUES (?, ?, ?, ?) "
            "ON CONFLICT(pdf_path, page_number) DO UPDATE SET content=excluded.content, updated_at=excluded.updated_at",
            (pdf_path, page_number, content, datetime.now().isoformat())
        )
        conn.commit()


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------

def save_setting(key: str, value: str):
    """Save a setting value."""
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value)
        )
        conn.commit()


def get_setting(key: str, default: str = "") -> str:
    """Retrieve a setting value."""
    with _get_conn() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def get_all_settings() -> Dict[str, str]:
    """Retrieve all settings as a dict."""
    with _get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
        return {row["key"]: row["value"] for row in rows}


# ---------------------------------------------------------------------------
# Chat Sessions
# ---------------------------------------------------------------------------

def get_all_chat_sessions() -> List[Dict]:
    """Get all chat sessions ordered by most recently updated."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, name, messages_json, token_count, created_at, updated_at "
            "FROM chat_sessions ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(row) for row in rows]


def get_chat_session(session_id: int) -> Optional[Dict]:
    """Get a single chat session by ID."""
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT id, name, messages_json, token_count, created_at, updated_at "
            "FROM chat_sessions WHERE id=?",
            (session_id,)
        ).fetchone()
        return dict(row) if row else None


def create_chat_session(name: str) -> int:
    """Create a new chat session and return its ID."""
    now = datetime.now().isoformat()
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO chat_sessions (name, messages_json, token_count, created_at, updated_at) "
            "VALUES (?, '[]', 0, ?, ?)",
            (name, now, now)
        )
        conn.commit()
        return cursor.lastrowid


def update_chat_session(session_id: int, name=None, messages_json=None, token_count=None):
    """Update a chat session's fields."""
    now = datetime.now().isoformat()
    fields = []
    values = []
    if name is not None:
        fields.append("name=?")
        values.append(name)
    if messages_json is not None:
        fields.append("messages_json=?")
        values.append(messages_json)
    if token_count is not None:
        fields.append("token_count=?")
        values.append(token_count)
    if not fields:
        return
    fields.append("updated_at=?")
    values.append(now)
    values.append(session_id)
    with _get_conn() as conn:
        conn.execute(
            f"UPDATE chat_sessions SET {', '.join(fields)} WHERE id=?",
            values
        )
        conn.commit()


def delete_chat_session(session_id: int):
    """Delete a chat session."""
    with _get_conn() as conn:
        conn.execute("DELETE FROM chat_sessions WHERE id=?", (session_id,))
        conn.commit()


# ---------------------------------------------------------------------------
# Token estimation (no external dependency)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Highlights
# ---------------------------------------------------------------------------

def save_highlight(pdf_path: str, page_number: int, text: str,
                   x: float, y: float, width: float, height: float,
                   color: str = '#FFEB3B') -> int:
    """Save a highlight and return its id."""
    with _get_conn() as conn:
        cursor = conn.execute(
            "INSERT INTO highlights (pdf_path, page_number, text, x, y, width, height, color) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (pdf_path, page_number, text, x, y, width, height, color)
        )
        conn.commit()
        return cursor.lastrowid


def get_highlights_by_pdf(pdf_path: str) -> List[Dict]:
    """Get all highlights for a PDF file."""
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT id, pdf_path, page_number, text, x, y, width, height, color, created_at "
            "FROM highlights WHERE pdf_path = ? ORDER BY page_number, y, x",
            (pdf_path,)
        ).fetchall()
        return [dict(row) for row in rows]


def delete_highlight(highlight_id: int) -> bool:
    """Delete a highlight by id."""
    with _get_conn() as conn:
        cursor = conn.execute("DELETE FROM highlights WHERE id = ?", (highlight_id,))
        conn.commit()
        return cursor.rowcount > 0


# ---------------------------------------------------------------------------
# Token estimation (no external dependency)
# ---------------------------------------------------------------------------

def estimate_tokens(text: str) -> int:
    """Rough token estimation.
    ~1 token per English word, ~1.5 per CJK character, ~0.25 for other chars.
    """
    import re
    english = len(re.findall(r'[a-zA-Z]+', text))
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    other = len(text) - english - cjk
    return english + int(cjk * 1.5) + max(0, int(other * 0.25))
