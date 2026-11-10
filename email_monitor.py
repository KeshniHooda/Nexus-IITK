"""Scan IITK emails and extract academic reminders and campus events."""
import json, os, time
from datetime import date, datetime
from zoneinfo import ZoneInfo
from google import genai
from dotenv import load_dotenv
from webmail import fetch_recent_emails
from reminder_store import initialise, get_setting, set_setting, is_processed, mark_processed, add_extracted_reminder

load_dotenv()
MODEL = "gemini-3-flash-preview"
REQUEST_GAP_SECONDS = 13
QUOTA_RETRY_SECONDS = 65
MAX_QUOTA_RETRIES = 2
EXTRACTION_PROMPT = """You are BabyBot, an intelligent academic email assistant for IIT Kanpur students.
Identify important student-facing information. Return ONLY JSON: {"items":[{"title":"Short descriptive title","category":"Deadline|Quiz|Exam|Assignment|Registration|Event|Academic notice|Other","item_type":"academic_reminder|campus_event","course":null,"event_date":"YYYY-MM-DD or null","event_time":"HH:MM or null","details":"Concise factual explanation","confidence":"high|medium|low"}]}
Academic reminders: quizzes (including mini/surprise quizzes), tests, exams, assignment/project deadlines, labs/viva, course registration, deadline extensions, important course changes, academic instructions, internship/scholarship deadlines. Optional club/cultural events, workshops, talks and recreational activities are campus_event. Ignore greetings, signatures, generic promotions, newsletters without actionable information, and unrelated messages. Today's date is {today}. Interpret relative dates only when sent date makes them unambiguous. Never invent dates; use null if unclear. Use the NEW date for extensions. Preserve uncertainty. One email may contain multiple distinct items. Return {"items":[]} if nothing useful exists. Never turn tentative proposals into confirmed events.
"""


def generate_with_retry(client, prompt):
    for attempt in range(MAX_QUOTA_RETRIES + 1):
        try:
            return client.models.generate_content(model=MODEL, contents=prompt,
                config=genai.types.GenerateContentConfig(response_mime_type="application/json"))
        except Exception as error:
            message = str(error)
            if ("429" not in message and "RESOURCE_EXHAUSTED" not in message) or attempt >= MAX_QUOTA_RETRIES:
                raise
            time.sleep(QUOTA_RETRY_SECONDS)


def extract_academic_items(client, message):
    today = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
    prompt = (EXTRACTION_PROMPT.replace("{today}", today) + "\nEMAIL METADATA\n"
        + f"From: {message.get('sender', '')}\nSubject: {message.get('subject', '')}\nSent: {message.get('date', '')}\n\n"
        + f"EMAIL BODY\n{message.get('body', '')[:14000]}")
    response = generate_with_retry(client, prompt)
    if not response.text:
        return []
    data = json.loads(response.text)
    items = data.get("items", [])
    if not isinstance(items, list):
        return []
    valid = []
    categories = {"Deadline", "Quiz", "Exam", "Assignment", "Registration", "Event", "Academic notice", "Other"}
    types = {"academic_reminder", "campus_event"}
    for item in items:
        if not isinstance(item, dict) or not item.get("title"):
            continue
        if item.get("category") not in categories:
            item["category"] = "Academic notice"
        if item.get("item_type") not in types:
            item["item_type"] = "campus_event" if item["category"] == "Event" else "academic_reminder"
        if item.get("event_date"):
            try: date.fromisoformat(item["event_date"])
            except (ValueError, TypeError):
                item["event_date"] = None
                item["confidence"] = "low"
        if item.get("event_time"):
            try:
                from datetime import time as datetime_time
                datetime_time.fromisoformat(item["event_time"])
            except (ValueError, TypeError):
                item["event_time"] = None
        valid.append(item)
    return valid


def scan_inbox(max_new_emails=5):
    initialise()
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise ValueError("GEMINI_API_KEY missing from .env")
    client = genai.Client(api_key=api_key)
    last_uid = get_setting("last_scanned_uid")
    messages, highest_uid = fetch_recent_emails(limit=min(max_new_emails, 5), after_uid=int(last_uid) if last_uid is not None else None)
    added = processed = gemini_requests = 0
    for message in messages:
        if is_processed(message["uid"]):
            continue
        if gemini_requests > 0:
            time.sleep(REQUEST_GAP_SECONDS)
        items = extract_academic_items(client, message)
        gemini_requests += 1
        for item in items:
            if add_extracted_reminder(item, message):
                added += 1
        mark_processed(message["uid"], message.get("message_id", ""))
        processed += 1
    if messages:
        set_setting("last_scanned_uid", max(m["uid"] for m in messages))
    elif last_uid is None:
        set_setting("last_scanned_uid", highest_uid)
    return {"emails_checked": processed, "reminders_added": added, "highest_uid": highest_uid}
