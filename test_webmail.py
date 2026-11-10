
import os
import imaplib
import email
from email.header import decode_header
from html import unescape
from html.parser import HTMLParser
from dotenv import load_dotenv

load_dotenv()

IMAP_SERVER = "qasid.iitk.ac.in"
IMAP_PORT = 993


def decode_text(value):
    if not value:
        return ""

    result = ""

    for part, encoding in decode_header(value):
        if isinstance(part, bytes):
            result += part.decode(
                encoding or "utf-8",
                errors="replace"
            )
        else:
            result += part

    return result


class HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_content = False

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip_content = True

        if tag in ("br", "p", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip_content = False

        if tag in ("p", "div", "tr", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_content:
            self.parts.append(data)

    def get_text(self):
        return unescape("".join(self.parts))


def get_email_body(message):
    plain_versions = []
    html_versions = []

    for part in message.walk():

        if part.get_content_disposition() == "attachment":
            continue

        content_type = part.get_content_type()
        payload = part.get_payload(decode=True)

        if not payload:
            continue

        charset = part.get_content_charset() or "utf-8"

        content = payload.decode(
            charset,
            errors="replace"
        )

        if content_type == "text/plain":
            plain_versions.append(content)

        elif content_type == "text/html":
            parser = HTMLTextExtractor()
            parser.feed(content)

            html_versions.append(parser.get_text())

    # Prefer the HTML version because IITK Webmail
    # appears to contain the actual message there.
    if html_versions:
        body = max(html_versions, key=len)

    elif plain_versions:
        body = max(plain_versions, key=len)

    else:
        return "[No readable email body found]"

    # Remove common Boxbe notification lines
    cleaned_lines = []

    for line in body.splitlines():
        lower_line = line.lower()

        if "eligible for automatic cleanup" in lower_line:
            continue
        if "add cleanup rule" in lower_line:
            continue
        if "boxbe.com/cleanup" in lower_line:
            continue

        cleaned_lines.append(line)

    return "\n".join(cleaned_lines).strip()


def fetch_latest_emails():

    username = os.getenv("IITK_EMAIL")
    password = os.getenv("IITK_EMAIL_PASSWORD")

    if not username or not password:
        raise ValueError("IITK credentials missing from .env")

    mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)

    try:
        mail.login(username, password)
        print("\nConnected to IITK Webmail!")

        status, _ = mail.select("INBOX", readonly=True)

        if status != "OK":
            print("Could not open Inbox.")
            return

        status, data = mail.search(None, "ALL")

        if status != "OK":
            print("Could not retrieve emails.")
            return

        email_ids = data[0].split()

        print(f"\nFound {len(email_ids)} emails.")

        if not email_ids:
            print("Your Inbox is empty!")
            return

        latest_ids = email_ids[-5:][::-1]

        print(f"Displaying the latest {len(latest_ids)} emails:\n")

        for email_id in latest_ids:

            status, message_data = mail.fetch(
                email_id,
                "(RFC822)"
            )

            if status != "OK":
                continue

            raw_email = next(
                item[1]
                for item in message_data
                if isinstance(item, tuple)
            )

            msg = email.message_from_bytes(raw_email)

            sender = decode_text(msg.get("From"))
            subject = decode_text(msg.get("Subject"))
            date = msg.get("Date", "Unknown")

            body = get_email_body(msg)

            print("=" * 70)
            print("FROM:", sender)
            print("SUBJECT:", subject)
            print("DATE:", date)
            print("-" * 70)
            print(body[:4000])
            print("\n")

    finally:
        try:
            mail.logout()
        except Exception:
            pass


if __name__ == "__main__":
    fetch_latest_emails()
