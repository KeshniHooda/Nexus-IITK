"""SQLite persistence for BabyBot reminders and tasks."""
import hashlib
import sqlite3
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

DB_PATH = Path(__file__).with_name("babybot_data.db")


def connect():
    conn = sqlite3.connect(DB_PATH, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def initialise():
    with connect() as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS processed_emails (uid INTEGER PRIMARY KEY, message_id TEXT, processed_at TEXT DEFAULT CURRENT_TIMESTAMP)")
        conn.execute("""CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, dedupe_key TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL, category TEXT NOT NULL,
            item_type TEXT NOT NULL DEFAULT 'academic_reminder', course TEXT,
            event_date TEXT, event_time TEXT, details TEXT, confidence TEXT DEFAULT 'medium',
            source_subject TEXT, source_sender TEXT, source_date TEXT, source_uid INTEGER,
            completed INTEGER DEFAULT 0, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS manual_reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            event_date TEXT NOT NULL, event_time TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        conn.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
            priority TEXT NOT NULL DEFAULT 'Medium', done INTEGER DEFAULT 0,
            details TEXT, source_subject TEXT, source_sender TEXT, source_date TEXT,
            source_uid INTEGER, created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        cols = {row[1] for row in conn.execute("PRAGMA table_info(reminders)")}
        if "item_type" not in cols:
            conn.execute("ALTER TABLE reminders ADD COLUMN item_type TEXT NOT NULL DEFAULT 'academic_reminder'")
        conn.execute("UPDATE reminders SET item_type='campus_event' WHERE category='Event' AND item_type='academic_reminder'")


def get_setting(key, default=None):
    with connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    with connect() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def is_processed(uid):
    with connect() as conn:
        return conn.execute("SELECT 1 FROM processed_emails WHERE uid=?", (int(uid),)).fetchone() is not None


def mark_processed(uid, message_id=""):
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO processed_emails(uid,message_id) VALUES(?,?)", (int(uid), message_id))


def _normalise(value):
    return " ".join((value or "").lower().split())


def _dedupe_key(item):
    parts = [_normalise(item.get("category")), _normalise(item.get("title")), _normalise(item.get("course")), item.get("event_date") or ""]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def add_extracted_reminder(item, source):
    key = _dedupe_key(item)
    with connect() as conn:
        cursor = conn.execute("""INSERT OR IGNORE INTO reminders
            (dedupe_key,title,category,item_type,course,event_date,event_time,details,confidence,source_subject,source_sender,source_date,source_uid)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (key, item.get("title", "Academic reminder"), item.get("category", "Academic notice"),
             item.get("item_type", "academic_reminder"), item.get("course"), item.get("event_date"),
             item.get("event_time"), item.get("details"), item.get("confidence", "medium"),
             source.get("subject"), source.get("sender"), source.get("date"), source.get("uid")))
        return cursor.rowcount == 1


def list_extracted_reminders(include_completed=False, item_type="academic_reminder", hide_past=False):
    query = "SELECT * FROM reminders WHERE item_type=?"
    params = [item_type]
    if not include_completed:
        query += " AND completed=0"
    if hide_past and item_type == "academic_reminder":
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        query += " AND (event_date IS NULL OR event_date >= ?)"
        params.append(today)
    query += " ORDER BY CASE WHEN event_date IS NULL THEN 1 ELSE 0 END, event_date, event_time"
    with connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def set_completed(reminder_id, completed=True):
    with connect() as conn:
        conn.execute("UPDATE reminders SET completed=? WHERE id=?", (int(completed), int(reminder_id)))


def delete_extracted(reminder_id):
    with connect() as conn:
        conn.execute("DELETE FROM reminders WHERE id=?", (int(reminder_id),))


def add_manual(title, event_date, event_time):
    with connect() as conn:
        conn.execute("INSERT INTO manual_reminders(title,event_date,event_time) VALUES(?,?,?)", (title, str(event_date), str(event_time)))


def list_manual(hide_past=True):
    query = "SELECT * FROM manual_reminders"
    params = []
    if hide_past:
        today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
        query += " WHERE event_date >= ?"
        params.append(today)
    query += " ORDER BY event_date,event_time"
    with connect() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def delete_manual(reminder_id):
    with connect() as conn:
        conn.execute("DELETE FROM manual_reminders WHERE id=?", (int(reminder_id),))


def add_task(title, priority="Medium", source=None, details=None):
    source = source or {}
    with connect() as conn:
        conn.execute("""INSERT INTO tasks(title,priority,details,source_subject,source_sender,source_date,source_uid)
            VALUES(?,?,?,?,?,?,?)""",
            (title, priority, details, source.get("subject"), source.get("sender"), source.get("date"), source.get("uid")))


def list_tasks():
    with connect() as conn:
        return [dict(row) for row in conn.execute("SELECT * FROM tasks ORDER BY done, created_at DESC, id DESC").fetchall()]


def set_task_done(task_id, done=True):
    with connect() as conn:
        conn.execute("UPDATE tasks SET done=? WHERE id=?", (int(done), int(task_id)))


def delete_task(task_id):
    with connect() as conn:
        conn.execute("DELETE FROM tasks WHERE id=?", (int(task_id),))
