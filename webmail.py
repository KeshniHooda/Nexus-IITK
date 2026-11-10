"""Read-only IITK Webmail IMAP helpers for BabyBot."""
import email
import imaplib
import os
import re
from email.header import decode_header
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from datetime import date, timedelta
from dotenv import load_dotenv

load_dotenv()
IMAP_SERVER = "qasid.iitk.ac.in"
IMAP_PORT = 993


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = False
    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip = True
        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")
    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = False
        if tag in ("p", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")
    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def decode_header_value(value):
    if not value:
        return ""
    output = []
    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            output.append(part.decode(encoding or "utf-8", errors="replace"))
        else:
            output.append(part)
    return "".join(output)


def extract_body(message):
    plain_versions, html_versions = [], []
    for part in message.walk():
        if part.get_content_disposition() == "attachment":
            continue
        kind = part.get_content_type()
        if kind not in ("text/plain", "text/html"):
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        charset = part.get_content_charset() or "utf-8"
        content = payload.decode(charset, errors="replace")
        if kind == "text/plain":
            plain_versions.append(content)
        else:
            parser = _HTMLTextExtractor()
            parser.feed(content)
            html_versions.append(unescape("".join(parser.parts)))
    body = max(html_versions, key=len) if html_versions else (max(plain_versions, key=len) if plain_versions else "")
    lines = []
    for line in body.splitlines():
        low = line.lower()
        if any(x in low for x in ("eligible for automatic cleanup", "add cleanup rule", "boxbe.com/cleanup")):
            continue
        lines.append(line.strip())
    return "\n".join(line for line in lines if line).strip()


def _message_to_record(uid, raw_bytes):
    msg = email.message_from_bytes(raw_bytes)
    date_value = msg.get("Date", "")
    try:
        date_value = parsedate_to_datetime(date_value).isoformat()
    except Exception:
        pass
    return {"uid": int(uid), "message_id": (msg.get("Message-ID") or "").strip(),
            "sender": decode_header_value(msg.get("From")),
            "subject": decode_header_value(msg.get("Subject")),
            "date": date_value, "body": extract_body(msg)}


def _credentials():
    username, password = os.getenv("IITK_EMAIL"), os.getenv("IITK_EMAIL_PASSWORD")
    if not username or not password:
        raise ValueError("IITK_EMAIL / IITK_EMAIL_PASSWORD missing from .env")
    return username, password


def fetch_recent_emails(limit=25, after_uid=None):
    """Fetch recent messages or UIDs newer than after_uid. Inbox is read-only."""
    username, password = _credentials()
    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT, timeout=30)
    try:
        mail.login(username, password)
        status, _ = mail.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Could not open IITK Inbox in read-only mode")
        criteria = ("ALL",) if after_uid is None else (f"UID {int(after_uid) + 1}:*",)
        status, data = mail.uid("search", None, *criteria)
        if status != "OK":
            raise RuntimeError("Could not search IITK Inbox")
        uids = [int(x) for x in data[0].split()]
        if not uids:
            return [], int(after_uid or 0)
        highest_uid = max(uids)
        selected = uids[-limit:] if after_uid is None else uids[:limit]
        records = []
        for uid in selected:
            status, fetched = mail.uid("fetch", str(uid), "(RFC822)")
            raw = next((item[1] for item in fetched if isinstance(item, tuple)), None) if status == "OK" else None
            if raw:
                records.append(_message_to_record(uid, raw))
        return records, highest_uid
    finally:
        try: mail.logout()
        except Exception: pass


def search_emails(query, limit=12, days_back=180):
    """Search Inbox by sender, subject and body within a bounded date window."""
    username, password = _credentials()
    stop = {"when", "have", "has", "had", "received", "did", "find", "search", "mail", "email", "emails", "inbox", "the", "a", "an", "about", "regarding", "for", "my", "me", "and", "to", "in", "on", "from", "please", "any", "is", "are", "what", "which", "who", "next", "tell", "show"}
    terms = []
    for word in re.findall(r"[A-Za-z0-9@._+-]+", query or ""):
        if len(word) > 1 and word.lower() not in stop and word.lower() not in [x.lower() for x in terms]:
            terms.append(word)
    # Generic event questions such as "when is my next quiz" must still search.
    if not terms and re.search(r"\bquiz\b", (query or "").lower()):
        terms = ["quiz"]
    if not terms:
        raise ValueError("Please include a course code, sender, or topic to search for.")
    terms = terms[:6]
    since = (date.today() - timedelta(days=min(180, max(1, int(days_back))))).strftime("%d-%b-%Y")

    # IMAP OR accepts exactly two search keys. Build a correctly nested OR tree.
    atoms = []
    for term in terms:
        safe = term.replace('\\', '').replace('"', '')
        atoms.extend([["SUBJECT", f'"{safe}"'], ["BODY", f'"{safe}"'], ["FROM", f'"{safe}"']])
    def flatten(node):
        if isinstance(node, list) and len(node) == 3 and node[0] == "OR":
            return ["OR"] + flatten(node[1]) + flatten(node[2])
        return list(node)
    tree = atoms[0]
    for atom in atoms[1:]:
        tree = ["OR", tree, atom]
    criteria = ["SINCE", since] + flatten(tree)

    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT, timeout=45)
    try:
        mail.login(username, password)
        status, _ = mail.select("INBOX", readonly=True)
        if status != "OK":
            raise RuntimeError("Could not open IITK Inbox in read-only mode")
        status, data = mail.uid("search", None, *criteria)
        if status != "OK":
            raise RuntimeError("IITK Webmail search failed")
        uids = [int(x) for x in data[0].split()] if data and data[0] else []
        records = []
        # Newest UIDs first; fetch enough candidates to fill the requested result count.
        for uid in reversed(uids[-max(limit * 4, limit):]):
            status, fetched = mail.uid("fetch", str(uid), "(RFC822)")
            raw = next((item[1] for item in fetched if isinstance(item, tuple)), None) if status == "OK" else None
            if raw:
                records.append(_message_to_record(uid, raw))
            if len(records) >= limit:
                break
        return records
    finally:
        try:
            mail.logout()
        except Exception:
            pass
