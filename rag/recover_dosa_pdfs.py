"""
BabyBot DOSA PDF recovery
Run from the rag folder:
    python recover_dosa_pdfs.py

Only processes the specific DOSA PDFs that the previous bounded ingestion report
marked SKIPPED_TOO_LITTLE_TEXT. It does not crawl the website or modify existing chunks.
Outputs:
    chunks/dosa_recovered_chunks.jsonl
    web_sources/dosa_recovery_report.txt
    web_sources/dosa_recovered_files/
"""
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse, unquote
import hashlib
import json
import re
import sys

try:
    import requests
except ImportError:
    print("Missing requests. Run: python -m pip install requests")
    sys.exit(1)

try:
    import pymupdf
    def open_pdf(path):
        return pymupdf.open(path)
except ImportError:
    try:
        import fitz
        def open_pdf(path):
            return fitz.open(path)
    except ImportError:
        print("Missing PyMuPDF. Run: python -m pip install pymupdf")
        sys.exit(1)

ROOT = Path.cwd()
CHUNKS_DIR = ROOT / "chunks"
WEB_DIR = ROOT / "web_sources"
PDF_DIR = WEB_DIR / "dosa_recovered_files"
OUT_JSONL = CHUNKS_DIR / "dosa_recovered_chunks.jsonl"
REPORT = WEB_DIR / "dosa_recovery_report.txt"

URLS = [
"https://iitk.ac.in/dosa/data/Fee_Structure_for_Non-Degree_Students_for_2026-27_1st_semester-16-07-26.pdf",
"https://iitk.ac.in/dosa/data/Fee_Structure_for_Preparatory_Students_for_2026-27_1st_semester-16-07-26.pdf",
"https://iitk.ac.in/dosa/data/Cumulative-Fee-Structure-for-Loan-for-Academic-Session-2026-2027-07-07-26.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-for-New-FN-for-2026-2027-1st-07-07-26.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-for-New-UG-for-2026-2027-1st-07-07-26.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-for-New-PG-for-2026-2027-1st-07-07-26.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-For-Summer-2025-26-06-05-26.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-for-Non-Degree-Students-2025-26-Even-11-12-25.pdf",
"https://iitk.ac.in/dosa/data/Fee_Structure_2025_2026_Even_Sem_New_PG_and_FN_students-28-11-25.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-for-Old-FN-for-2026-2027-1st-07-07-26.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-for-Old-PG-for-2026-2027-1st-07-07-26.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-for-Old-UG-for-2026-2027-1st-07-07-26.pdf",
"https://iitk.ac.in/dosa/data/Fee_Structure_2025_2026_Even_Sem_Old_UG_PG_and_FN_Students-28-11-25.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-for-Summer-2024-25-03-05-25.pdf",
"https://iitk.ac.in/dosa/data/Fee-Structure-for-Old-Students-2025-2026-Odd-Semester-03-05-25.pdf",
"https://iitk.ac.in/dosa/data/Day-Scholar-for-new-students_15-07-24.pdf",
"https://iitk.ac.in/dosa/data/new_Guideline_and_SOP_for_SBF_Scholarship_and_Loan_Reg-13-03-24.pdf",
"https://iitk.ac.in/dosa/data/Students-Ombudsperson.pdf",
]

def safe_name(url):
    name = unquote(Path(urlparse(url).path).name)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)

def chunks(text, size=1100, overlap=160):
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        return []
    paras = [p.strip() for p in text.splitlines() if p.strip()]
    out, buf = [], ""
    for para in paras:
        if len(buf) + len(para) + 1 <= size:
            buf = (buf + "\n" + para).strip()
        else:
            if buf:
                out.append(buf)
            if len(para) > size:
                start = 0
                while start < len(para):
                    out.append(para[start:start+size])
                    start += size-overlap
                buf = ""
            else:
                buf = para
    if buf:
        out.append(buf)
    return out

def main():
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    records, lines = [], []
    lines.append("BABYBOT DOSA PDF RECOVERY REPORT")
    lines.append("Run: " + datetime.now().isoformat(timespec="seconds"))
    lines.append("Scope: only 18 previously skipped DOSA PDFs; no website crawl.")
    lines.append("")

    session = requests.Session()
    session.headers.update({"User-Agent": "BabyBot-IITK-Student-Research/1.0"})
    for i, url in enumerate(URLS, 1):
        filename = safe_name(url)
        path = PDF_DIR / filename
        lines.append(f"[{i}/{len(URLS)}] {filename}")
        try:
            if not path.exists() or path.stat().st_size < 1000:
                response = session.get(url, timeout=35)
                response.raise_for_status()
                if not response.content.startswith(b"%PDF"):
                    raise ValueError("URL response is not a PDF")
                path.write_bytes(response.content)

            doc = open_pdf(path)
            page_texts = []
            for page_no, page in enumerate(doc, 1):
                text = page.get_text("text") or ""
                if len(text.strip()) < 15:
                    # A second native extraction mode can recover some oddly encoded PDFs.
                    blocks = page.get_text("blocks") or []
                    text = "\n".join(str(b[4]) for b in blocks if len(b) > 4)
                page_texts.append(f"\n[Page {page_no}]\n{text}")
            full_text = "\n".join(page_texts).strip()
            word_count = len(full_text.split())
            if word_count < 8:
                lines.append(f"  NEEDS_OCR | {word_count} words | {path}")
                continue

            pieces = chunks(full_text)
            title = Path(filename).stem.replace("_", " ").replace("-", " ")
            for ci, piece in enumerate(pieces):
                digest = hashlib.sha256((url + str(ci) + piece).encode("utf-8")).hexdigest()
                records.append({
                    "chunk_id": digest,
                    "text": piece,
                    "source_title": title,
                    "source_url": url,
                    "final_url": url,
                    "source_category": "dosa_student_affairs",
                    "source_type": "official_dosa_pdf",
                    "priority": 88 if "2026-2027" in url or "2026-27" in url else 78,
                    "chunk_index": ci,
                    "curation_reason": "recovered from previously skipped official DOSA PDF",
                    "fetched_at": datetime.now().isoformat(timespec="seconds"),
                    "local_file": str(path.relative_to(ROOT)).replace("\\", "/"),
                })
            lines.append(f"  EXTRACTED | {word_count} words | {len(pieces)} chunks | {path}")
        except Exception as e:
            lines.append(f"  FAILED | {type(e).__name__}: {e}")

    with OUT_JSONL.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    lines += ["", f"Total recovered chunks: {len(records)}",
              f"Output: {OUT_JSONL.relative_to(ROOT)}",
              "Existing dosa_chunks.jsonl was not changed."]
    REPORT.write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))

if __name__ == "__main__":
    main()
