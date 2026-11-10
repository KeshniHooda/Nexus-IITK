#!/usr/bin/env python3
"""
BabyBot IITK source crawler v2
- Starts from explicit current academic hubs and all 20 current department CoS PDFs
- Uses a priority heap: current curriculum first, student services next, historical committee/Senate material last
- Crawls official IITK domains only; records all discovered links, including excluded links
- Downloads linked PDFs and extracts text where possible
- Keeps source identity per URL; does not content-dedupe different course documents
- Writes a SQLite registry, JSONL chunks, CSV inventories and a coverage report
- Does NOT index into Chroma unless explicitly passed --index
"""
from __future__ import annotations
import argparse, csv, hashlib, json, logging, os, re, sqlite3, sys, time, heapq
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag, urlunparse, parse_qsl, urlencode

import requests
from bs4 import BeautifulSoup
try:
    import fitz
except Exception:
    fitz = None

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "web_sources"
HTML_DIR = OUT / "raw_html"
FILE_DIR = OUT / "files"
TEXT_DIR = OUT / "extracted_text"
for d in (OUT, HTML_DIR, FILE_DIR, TEXT_DIR):
    d.mkdir(parents=True, exist_ok=True)

USER_AGENT = "BabyBotAcademicResearchBot/2.0 (IITK student knowledge project)"
TIMEOUT = 25
DELAY = 0.35
MAX_BYTES = 35 * 1024 * 1024
CHUNK_WORDS = 850
OVERLAP_WORDS = 120
OFFICIAL_ROOT = "iitk.ac.in"

CURRICULUM_TERMS = [
    "curriculum", "course", "courses", "course-of-study", "courses-of-study",
    "minor", "major", "dual-degree", "double-major", "elective", "syllabus",
    "template", "prerequisite", "programme", "program", "under-graduate",
    "post-graduate", "ug-", "pg-", "department", "academic"
]
DOAA_TERMS = [
    "doaa", "academic", "calendar", "timetable", "time-table", "registration",
    "pre-registration", "exam", "examination", "grading", "grade", "summer",
    "sugc", "dugc", "exchange", "manual", "course", "curriculum", "minor",
    "branch", "credit", "semester", "holiday", "internship", "form", "notice"
]
DOSA_TERMS = [
    "dosa", "fee", "fees", "payment", "refund", "scholarship", "financial",
    "aid", "benevolence", "hall", "hostel", "mess", "accommodation",
    "gymkhana", "club", "counselling", "counseling", "medical", "insurance",
    "welfare", "grievance", "ombud", "anti-ragging", "ragging", "student",
    "sports", "facility", "form", "notice", "rule", "faq", "support"
]
GENERAL_TERMS = [
    "student", "academic", "admission", "fee", "fees", "payment", "course",
    "curriculum", "department", "hall", "hostel", "library", "medical",
    "counselling", "counseling", "sports", "scholarship", "policy", "manual",
    "form", "notice", "calendar", "examination", "registration", "welfare"
]
SKIP_EXT = {".jpg",".jpeg",".png",".gif",".svg",".webp",".mp4",".mp3",".zip",
            ".rar",".7z",".css",".js",".ico",".woff",".woff2",".ttf",".eot"}
TRACKING = {"utm_source","utm_medium","utm_campaign","utm_term","utm_content",
            "fbclid","gclid"}

def now():
    return datetime.now(timezone.utc).isoformat()

def norm_url(url):
    url, _ = urldefrag(url.strip())
    p = urlparse(url)
    if p.scheme not in ("http", "https"):
        return None
    host = (p.hostname or "").lower()
    if not (host == OFFICIAL_ROOT or host.endswith("." + OFFICIAL_ROOT)):
        return None
    path = re.sub(r"/{2,}", "/", p.path or "/")
    query = [(k,v) for k,v in parse_qsl(p.query, keep_blank_values=True)
             if k.lower() not in TRACKING]
    query.sort()
    netloc = (p.hostname or "").lower()
    return urlunparse(("https", netloc, path, "", urlencode(query), ""))

def is_pdf(url, content_type=""):
    return urlparse(url).path.lower().endswith(".pdf") or "application/pdf" in content_type.lower()

def url_ext(url):
    return Path(urlparse(url).path.lower()).suffix

def classify(url, anchor="", parent_category=""):
    s = (url + " " + anchor).lower()
    # Keep committee/Senate archives discoverable, but do not let them outrank
    # current curriculum, course catalogues, or student-facing procedures.
    low_priority_terms = ("senate_decision", "senate-decision", "senate minutes",
                          "academic-review-committee", "programme-review-committee",
                          "doaa-archive", "calendar2015", "calendar2016", "2020-21")
    if any(term in s for term in low_priority_terms):
        return "historical_policy_reference", 10
    if "courses-of-study" in s or "cos26" in s or "course-templates" in s:
        return "doaa_curriculum", 120
    if any(t in s for t in CURRICULUM_TERMS):
        return "doaa_curriculum", 100
    if "dosa" in s or any(t in s for t in DOSA_TERMS):
        return "dosa_student_life_finance", 80
    if "doaa" in s or any(t in s for t in DOAA_TERMS):
        return "doaa_academic", 90
    if parent_category in ("doaa_curriculum","doaa_academic") and any(t in s for t in GENERAL_TERMS):
        return "doaa_academic", 75
    if parent_category == "dosa_student_life_finance" and any(t in s for t in GENERAL_TERMS):
        return "dosa_student_life_finance", 75
    if any(t in s for t in GENERAL_TERMS):
        return "general_iitk_student_info", 60
    return "official_iitk_other", 20

def chunk_text(text, size=CHUNK_WORDS, overlap=OVERLAP_WORDS):
    words = re.findall(r"\S+", text)
    if not words:
        return []
    out, start = [], 0
    while start < len(words):
        end = min(start + size, len(words))
        out.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(end - overlap, start + 1)
    return out

def clean_text(s):
    s = s.replace("\xa0", " ")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n[ \t]*\n[ \t]*\n+", "\n\n", s)
    return s.strip()

def extract_html(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script","style","noscript","svg","nav","footer"]):
        tag.decompose()
    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else page_url
    main = soup.find("main") or soup.find(id=re.compile("content|main", re.I)) or soup.body or soup
    # Retain headings, paragraph/list/table content in readable order.
    bits = []
    for el in main.find_all(["h1","h2","h3","h4","p","li","td","th","caption"]):
        t = clean_text(el.get_text(" ", strip=True))
        if t and (not bits or t != bits[-1]):
            bits.append(t)
    if not bits:
        bits = [clean_text(main.get_text("\n", strip=True))]
    text = "\n".join(bits)
    links = []
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"])
        anchor = clean_text(a.get_text(" ", strip=True))[:300]
        links.append((href, anchor))
    return title, text, links

def db_init(path):
    con = sqlite3.connect(path)
    con.execute("""CREATE TABLE IF NOT EXISTS documents(
        url TEXT PRIMARY KEY, final_url TEXT, title TEXT, category TEXT,
        priority INTEGER, source_type TEXT, status TEXT, fetched_at TEXT,
        content_hash TEXT, local_path TEXT, text_path TEXT, word_count INTEGER,
        depth INTEGER, parent_url TEXT, error TEXT)""")
    con.execute("""CREATE TABLE IF NOT EXISTS links(
        source_url TEXT, target_url TEXT, anchor TEXT, category TEXT,
        priority INTEGER, decision TEXT, discovered_at TEXT,
        PRIMARY KEY(source_url,target_url,anchor))""")
    con.commit()
    return con

def save_doc(con, row):
    con.execute("""INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ON CONFLICT(url) DO UPDATE SET final_url=excluded.final_url,title=excluded.title,
    category=excluded.category,priority=excluded.priority,source_type=excluded.source_type,
    status=excluded.status,fetched_at=excluded.fetched_at,content_hash=excluded.content_hash,
    local_path=excluded.local_path,text_path=excluded.text_path,word_count=excluded.word_count,
    depth=excluded.depth,parent_url=excluded.parent_url,error=excluded.error""", row)
    con.commit()

def safe_name(url, suffix):
    digest = hashlib.sha256(url.encode()).hexdigest()[:20]
    stem = re.sub(r"[^a-zA-Z0-9_-]+","_",Path(urlparse(url).path).stem)[:55] or "page"
    return f"{stem}_{digest}{suffix}"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-depth", type=int, default=4,
                    help="Maximum link depth from seed hubs (default 4); direct seed PDFs are always fetched")
    ap.add_argument("--max-pages", type=int, default=0,
                    help="Safety cap for HTML/PDF documents; 0 means no cap (default)")
    ap.add_argument("--delay", type=float, default=DELAY)
    ap.add_argument("--index", action="store_true",
                    help="After crawl, add/update chunks in ChromaDB collection iitk_knowledge_v1")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    seed_file = ROOT / "seed_urls.txt"
    seeds = [norm_url(x) for x in seed_file.read_text(encoding="utf-8").splitlines()
             if x.strip() and not x.lstrip().startswith("#")]
    seeds = list(dict.fromkeys(x for x in seeds if x))
    if not seeds:
        raise SystemExit("No valid seed URLs in seed_urls.txt")

    con = db_init(OUT / "registry.sqlite3")
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    queue = []
    sequence = 0
    for u in seeds:
        cat, pr = classify(u)
        heapq.heappush(queue, (-pr, sequence, u, 0, None, ""))
        sequence += 1
    queued = set(seeds)
    processed = set()
    link_rows, chunk_rows, manifest = [], [], []
    counts = Counter()
    while queue:
        _, _, url, depth, parent, parent_cat = heapq.heappop(queue)
        if url in processed:
            continue
        if args.max_pages and len(processed) >= args.max_pages:
            logging.warning("Reached --max-pages=%s; remaining queue recorded as not_fetched_limit", args.max_pages)
            break
        processed.add(url)
        category, priority = classify(url, "", parent_cat)
        parsed = urlparse(url)
        if url_ext(url) in SKIP_EXT:
            counts["skipped_asset"] += 1
            continue
        try:
            resp = session.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True)
            ctype = resp.headers.get("Content-Type","")
            length = int(resp.headers.get("Content-Length") or 0)
            if length > MAX_BYTES:
                raise ValueError(f"File exceeds {MAX_BYTES} byte safety limit")
            body = resp.content
            if len(body) > MAX_BYTES:
                raise ValueError(f"Response exceeds {MAX_BYTES} byte safety limit")
            resp.raise_for_status()
            final_url = norm_url(resp.url) or resp.url
            fetched = now()
            if is_pdf(url, ctype) or is_pdf(final_url, ctype):
                name = safe_name(url, ".pdf")
                local = FILE_DIR / name
                local.write_bytes(body)
                text = ""
                status = "downloaded_needs_ocr"
                title = Path(urlparse(url).path).name
                if fitz:
                    try:
                        doc = fitz.open(stream=body, filetype="pdf")
                        pages = []
                        for i, page in enumerate(doc):
                            t = clean_text(page.get_text("text"))
                            if t:
                                pages.append(f"[Page {i+1}]\n{t}")
                        text = "\n\n".join(pages)
                        if len(text.split()) >= 30:
                            status = "downloaded_extracted"
                        else:
                            status = "downloaded_needs_ocr"
                        if doc.metadata and doc.metadata.get("title"):
                            title = doc.metadata["title"]
                    except Exception as e:
                        status = "downloaded_extraction_error"
                        logging.warning("PDF extraction failed %s: %s", url, e)
                text_path = ""
                if text:
                    tp = TEXT_DIR / (name[:-4] + ".txt")
                    tp.write_text(text, encoding="utf-8")
                    text_path = str(tp.relative_to(ROOT))
                    chunks = chunk_text(text)
                    for i, chunk in enumerate(chunks):
                        cid = hashlib.sha256(f"{url}|{i}".encode()).hexdigest()
                        chunk_rows.append({
                            "chunk_id": cid, "text": chunk, "source_title": title,
                            "source_file": name, "source_url": url, "final_url": final_url,
                            "source_type": "pdf", "source_category": category,
                            "priority": priority, "page_range": "", "chunk_index": i,
                            "content_hash": hashlib.sha256(chunk.encode()).hexdigest(),
                            "fetched_at": fetched
                        })
                content_hash = hashlib.sha256(body).hexdigest()
                save_doc(con,(url,final_url,title,category,priority,"pdf",status,fetched,
                              content_hash,str(local.relative_to(ROOT)),text_path,
                              len(text.split()),depth,parent,""))
                counts[status] += 1
            elif "text/html" in ctype or not ctype:
                html = body.decode(resp.encoding or "utf-8", errors="replace")
                title, text, links = extract_html(html, final_url)
                category, priority = classify(url, title, parent_cat)
                name = safe_name(url, ".html")
                local = HTML_DIR / name
                local.write_text(html, encoding="utf-8")
                tp = TEXT_DIR / (name[:-5] + ".txt")
                tp.write_text(text, encoding="utf-8")
                content_hash = hashlib.sha256(text.encode()).hexdigest()
                chunks = chunk_text(text)
                for i, chunk in enumerate(chunks):
                    cid = hashlib.sha256(f"{url}|{i}".encode()).hexdigest()
                    chunk_rows.append({
                        "chunk_id": cid, "text": chunk, "source_title": title,
                        "source_file": name, "source_url": url, "final_url": final_url,
                        "source_type": "html", "source_category": category,
                        "priority": priority, "chunk_index": i,
                        "content_hash": hashlib.sha256(chunk.encode()).hexdigest(),
                        "fetched_at": fetched
                    })
                save_doc(con,(url,final_url,title,category,priority,"html","extracted",fetched,
                              content_hash,str(local.relative_to(ROOT)),
                              str(tp.relative_to(ROOT)),len(text.split()),depth,parent,""))
                counts["html_extracted"] += 1
                for target, anchor in links:
                    normalized = norm_url(target)
                    cat, pr = classify(target, anchor, category)
                    if not normalized:
                        decision = "external_or_non_http_recorded_only"
                        target_store = target
                    elif url_ext(normalized) in SKIP_EXT:
                        decision = "asset_recorded_only"
                        target_store = normalized
                    elif depth >= args.max_depth and url_ext(normalized) != ".pdf":
                        decision = "depth_limit_recorded_only"
                        target_store = normalized
                    else:
                        # PDFs linked from the last HTML depth are still fetched;
                        # only further HTML recursion is stopped at the depth boundary.
                        decision = "queued"
                        target_store = normalized
                        if normalized not in queued and normalized not in processed:
                            heapq.heappush(queue, (-pr, sequence, normalized, depth+1, url, category))
                            sequence += 1
                            queued.add(normalized)
                    con.execute("INSERT OR IGNORE INTO links VALUES(?,?,?,?,?,?,?)",
                                (url,target_store,anchor,cat,pr,decision,now()))
                    link_rows.append((url,target_store,anchor,cat,pr,decision,depth+1))
                con.commit()
            else:
                counts["non_html_asset_recorded_only"] += 1
                status = "non_html_asset_recorded_only"
                save_doc(con,(url,final_url,Path(urlparse(url).path).name,category,priority,
                              "asset",status,fetched,"","","",0,depth,parent,""))
            manifest.append({"url":url,"final_url":final_url,"depth":depth,
                             "category":category,"priority":priority,"status":"success"})
            logging.info("[%s] %s", category, url)
        except Exception as e:
            counts["failed"] += 1
            err = str(e)[:800]
            save_doc(con,(url,"",Path(urlparse(url).path).name,category,priority,
                          "unknown","failed",now(),"","","",0,depth,parent,err))
            manifest.append({"url":url,"depth":depth,"category":category,
                             "priority":priority,"status":"failed","error":err})
            logging.warning("FAILED %s: %s",url,err)
        time.sleep(max(0,args.delay))

    # Write chunks from this run only; preserve every URL as a separate identity.
    chunks_path = OUT / "chunks.jsonl"
    with chunks_path.open("w",encoding="utf-8") as f:
        for row in chunk_rows:
            f.write(json.dumps(row,ensure_ascii=False)+"\n")
    with (OUT / "crawl_manifest.csv").open("w",newline="",encoding="utf-8-sig") as f:
        fields = sorted({k for r in manifest for k in r})
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(manifest)
    with (OUT / "link_inventory.csv").open("w",newline="",encoding="utf-8-sig") as f:
        w=csv.writer(f); w.writerow(["source_url","target_url","anchor_text","category","priority","decision","target_depth"])
        w.writerows(link_rows)
    with (OUT / "coverage_report.txt").open("w",encoding="utf-8") as f:
        f.write("BABYBOT IITK TARGETED INGESTION V2.1 — COVERAGE REPORT\n")
        f.write(f"Run time (UTC): {now()}\nSeeds: {len(seeds)}\n")
        f.write(f"Max depth: {args.max_depth}\nProcessed unique URLs: {len(processed)}\n")
        f.write(f"Chunks generated: {len(chunk_rows)}\n\nSTATUS COUNTS\n")
        for k,v in sorted(counts.items()):
            f.write(f"{k}: {v}\n")
        f.write("\nCATEGORY COUNTS (processed document manifest)\n")
        for k,v in sorted(Counter(r.get("category","unknown") for r in manifest).items()):
            f.write(f"{k}: {v}\n")
        f.write("\nReview link_inventory.csv for links not fetched (depth limit, assets, external links).\n")
        f.write("This crawler records discovered links; it does not guarantee every IITK page is relevant or accessible.\n")
    con.close()
    logging.info("Crawl complete. Processed=%d chunks=%d counts=%s",len(processed),len(chunk_rows),dict(counts))
    if args.index:
        index_chunks(chunks_path)

def index_chunks(path):
    try:
        import chromadb
        from sentence_transformers import SentenceTransformer
    except Exception as e:
        raise SystemExit("For --index install chromadb and sentence-transformers in the project environment: "+str(e))
    rag_dir = ROOT.parent
    db_path = rag_dir / "chroma_db"
    if not db_path.exists():
        raise SystemExit(f"Existing ChromaDB not found at {db_path}; refusing to create a new database.")
    client = chromadb.PersistentClient(path=str(db_path))
    collection = client.get_or_create_collection("iitk_knowledge_v1")
    model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    # Remove old chunks for each crawled URL only after all replacement chunks are prepared.
    urls = sorted(set(r["source_url"] for r in rows))
    for start in range(0,len(rows),48):
        batch=rows[start:start+48]
        embeddings=model.encode([r["text"] for r in batch],normalize_embeddings=True).tolist()
        metadatas=[]
        for r in batch:
            metadatas.append({k:v for k,v in r.items() if k not in ("text","chunk_id") and v is not None})
        collection.upsert(ids=[r["chunk_id"] for r in batch],
                          documents=[r["text"] for r in batch],
                          metadatas=metadatas,embeddings=embeddings)
    # Existing stale chunks are not deleted in v2; additive upsert is safest.
    print(f"Added/updated {len(rows)} chunks in {db_path}. No existing chunks were deleted.")

if __name__ == "__main__":
    main()
