"""
BabyBot: bounded IITK DoSA/DOSA ingestion.
- Starts ONLY at https://www.iitk.ac.in/dosa/
- Fetches a small fixed set of known student-facing pages plus relevant direct links on that homepage.
- No recursive crawling, no Senate/manual/tender archive crawling, no login access.
- Writes separate chunks/dosa_chunks.jsonl and web_sources/dosa_ingestion_report.txt.
- Does NOT touch existing chunks, ChromaDB, or DoAA curation.
Requires: requests, beautifulsoup4, pymupdf (already used by the project).
"""
import re, json, hashlib, time
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from datetime import datetime
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
OUT_DIR = ROOT / "chunks"
WEB_DIR = ROOT / "web_sources"
RAW_DIR = WEB_DIR / "dosa_files"
OUT_FILE = OUT_DIR / "dosa_chunks.jsonl"
REPORT = WEB_DIR / "dosa_ingestion_report.txt"
BASE = "https://www.iitk.ac.in/dosa/"
MAX_PAGES = 30
TIMEOUT = 18
HEADERS = {"User-Agent": "BabyBot-IITK-Student-KnowledgeBot/1.0 (educational research)"}

# Verified, useful student-facing landing pages.
SEEDS = [
    "https://www.iitk.ac.in/dosa/",
    "https://www.iitk.ac.in/dosa/faqs",
    "https://www.iitk.ac.in/dosa/fees-matters",
    "https://www.iitk.ac.in/dosa/scholarships",
    "https://iitk.ac.in/dosa/student-medical-insurance",
    "https://www.iitk.ac.in/dosa/contact-us",
]
INCLUDE_TERMS = (
    "fee", "scholar", "hostel", "hall", "counsel", "medical", "insurance",
    "gymkhana", "student", "day-scholar", "day_scholar", "refund", "mess",
    "benevol", "sbf", "anti-rag", "ragging", "certificate", "identity",
    "contact", "ward", "cosha", "health", "welfare", "form"
)
EXCLUDE_TERMS = (
    "senate", "ordinance", "tender", "procurement", "audit", "delegation",
    "former-dean", "archive", "2016", "2017", "2018", "2019", "2020",
    "2021", "2022", "2023"
)

def canonical(url):
    url, _ = urldefrag(url)
    u = urlparse(url)
    host = u.netloc.lower().removeprefix("www.")
    path = re.sub(r"/+", "/", u.path or "/")
    if path != "/" and path.endswith("/"):
        path = path[:-1]
    return f"https://{host}{path}" + (("?" + u.query) if u.query else "")

def relevant(url, anchor=""):
    s = (url + " " + anchor).lower()
    if any(x in s for x in EXCLUDE_TERMS):
        return False
    return any(x in s for x in INCLUDE_TERMS)

def clean_text(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "nav", "footer"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    text = re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))
    return title, text

def chunks(text, size=850, overlap=120):
    words = text.split()
    if not words:
        return []
    out, start = [], 0
    while start < len(words):
        end = min(start + size, len(words))
        out.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = end - overlap
    return out

def main():
    OUT_DIR.mkdir(exist_ok=True)
    WEB_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(HEADERS)

    # One homepage fetch, then only direct relevant links found on it. No recursive traversal.
    homepage_links = []
    try:
        r = session.get(BASE, timeout=TIMEOUT)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for a in soup.find_all("a", href=True):
            href = urljoin(BASE, a["href"])
            text = a.get_text(" ", strip=True)
            u = urlparse(href)
            if u.netloc.lower().removeprefix("www.") != "iitk.ac.in":
                continue
            if not (u.path.lower().startswith("/dosa/") or u.path.lower() == "/dosa"):
                continue
            if relevant(href, text):
                homepage_links.append(canonical(href))
    except Exception as e:
        print(f"Homepage discovery warning: {type(e).__name__}: {e}")

    urls = []
    seen = set()
    for u in SEEDS + homepage_links:
        cu = canonical(u)
        if cu not in seen:
            seen.add(cu)
            urls.append(cu)
        if len(urls) >= MAX_PAGES:
            break

    rows, report, failures = [], [], []
    fetched = 0
    try:
        import fitz
    except Exception:
        fitz = None

    for url in urls:
        try:
            time.sleep(0.25)
            resp = session.get(url, timeout=TIMEOUT)
            resp.raise_for_status()
            ctype = resp.headers.get("content-type", "").lower()
            title = ""
            text = ""
            local = ""
            if "pdf" in ctype or url.lower().endswith(".pdf"):
                name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(urlparse(url).path).name) or "dosa_document.pdf"
                dest = RAW_DIR / name
                dest.write_bytes(resp.content)
                local = str(dest.relative_to(ROOT))
                if fitz:
                    doc = fitz.open(stream=resp.content, filetype="pdf")
                    text = "\n".join(pg.get_text("text") for pg in doc)
                    doc.close()
                title = Path(name).stem.replace("_", " ")
            else:
                title, text = clean_text(resp.text)
            text = re.sub(r"[ \t]+\n", "\n", text).strip()
            if len(text.split()) < 15:
                report.append(f"SKIPPED_TOO_LITTLE_TEXT\t{url}")
                continue
            fetched += 1
            parts = chunks(text)
            for i, part in enumerate(parts):
                cid = hashlib.sha256((url + "|" + str(i)).encode()).hexdigest()
                rows.append({
                    "chunk_id": cid,
                    "text": part,
                    "source_title": title or url,
                    "source_url": url,
                    "final_url": resp.url,
                    "source_category": "dosa_student_affairs",
                    "source_type": "official_dosa_page" if not local else "official_dosa_document",
                    "priority": 90,
                    "chunk_index": i,
                    "curation_reason": "bounded DOSA student-facing source",
                    "fetched_at": datetime.now().isoformat(timespec="seconds"),
                    "local_file": local,
                })
            report.append(f"INCLUDED\t{title or url}\t{url}\t{len(parts)} chunks")
            print(f"[{fetched}/{len(urls)}] {url} -> {len(parts)} chunks")
        except Exception as e:
            failures.append(f"FAILED\t{url}\t{type(e).__name__}: {e}")
            print(f"FAILED: {url} ({type(e).__name__}: {e})")

    with OUT_FILE.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    with REPORT.open("w", encoding="utf-8") as f:
        f.write("BABYBOT DOSA BOUNDED INGESTION REPORT\n")
        f.write(f"Root: {BASE}\nMaximum pages: {MAX_PAGES}\n")
        f.write("Traversal: homepage + fixed seeds + direct relevant homepage links only; no recursion\n")
        f.write(f"URLs selected: {len(urls)}\nSources extracted: {fetched}\nChunks: {len(rows)}\n")
        f.write("\nINCLUDED SOURCES\n" + "\n".join(report))
        f.write("\n\nFAILURES\n" + ("\n".join(failures) if failures else "None"))
        f.write("\n\nOUTPUT\nchunks/dosa_chunks.jsonl\n")

    print("\nDOSA INGESTION COMPLETE")
    print(f"Sources extracted: {fetched}; chunks: {len(rows)}")
    print(f"Chunks: {OUT_FILE}")
    print(f"Report: {REPORT}")
    print("Existing DoAA files and ChromaDB were NOT modified.")

if __name__ == "__main__":
    main()
