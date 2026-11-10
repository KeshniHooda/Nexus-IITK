"""Download approved IITK knowledge sources for BabyBot.

Run from the project root or the rag directory. The inventory CSV is expected
beside this script by default. Downloads are saved under rag/documents/ and a
manifest is written to rag/download_manifest.csv.
"""
from __future__ import annotations
import csv, hashlib, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import urlparse, unquote
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent
INVENTORY = HERE / "BabyBot_FINAL_IITK_Knowledge_Source_Inventory.csv"
OUT_DIR = HERE / "documents"
MANIFEST = HERE / "download_manifest.csv"
MAX_BYTES = 25 * 1024 * 1024
TIMEOUT = (12, 45)
WORKERS = 6
USER_AGENT = "BabyBot-IITK-KnowledgeCrawler/1.0 (student academic knowledge indexing)"


def clean_name(value: str, limit: int = 90) -> str:
    value = unquote(str(value or "")).strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    value = re.sub(r"_+", "_", value).strip("._-")
    return (value or "source")[:limit]


def session_for_thread() -> requests.Session:
    s = requests.Session()
    retry = Retry(total=3, connect=3, read=2, backoff_factor=0.7,
                  status_forcelist=[429, 500, 502, 503, 504],
                  allowed_methods=["GET"], raise_on_status=False)
    adapter = HTTPAdapter(max_retries=retry, pool_connections=WORKERS, pool_maxsize=WORKERS)
    s.mount("http://", adapter); s.mount("https://", adapter)
    s.headers.update({"User-Agent": USER_AGENT})
    return s


def load_inventory():
    if not INVENTORY.exists():
        raise FileNotFoundError(
            f"Inventory not found: {INVENTORY}\n"
            "Copy BabyBot_FINAL_IITK_Knowledge_Source_Inventory.csv into the rag folder."
        )
    with INVENTORY.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    # Keep entries unless the inventory explicitly says not to keep them.
    rows = [r for r in rows if str(r.get("keep_in_inventory", "YES")).strip().upper() not in {"NO", "FALSE", "0"}]
    seen, unique = set(), []
    for r in rows:
        url = (r.get("url") or "").strip()
        if not url.startswith(("http://", "https://")) or url in seen:
            continue
        seen.add(url); unique.append(r)
    return unique


def download_one(row):
    url = (row.get("url") or "").strip()
    title = row.get("title") or "source"
    category = clean_name(row.get("category") or "other", 45)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:10]
    parsed = urlparse(url)
    tail = Path(unquote(parsed.path)).name
    base = clean_name(Path(tail).stem if tail and "." in tail else title)
    # Keep the original extension only when it is a plausible file extension.
    ext = Path(tail).suffix.lower()
    if ext not in {".pdf", ".html", ".htm", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx"}:
        ext = ".html"
    dest_dir = OUT_DIR / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"{base}_{digest}{ext}"
    if dest.exists() and dest.stat().st_size > 0:
        return {**row, "download_status": "ALREADY_DOWNLOADED", "http_status": "", "content_type": "",
                "local_path": str(dest.relative_to(HERE)), "bytes": dest.stat().st_size, "sha256": sha256_file(dest), "error": ""}
    s = session_for_thread()
    try:
        with s.get(url, timeout=TIMEOUT, stream=True, allow_redirects=True) as resp:
            status = resp.status_code
            if status != 200:
                return result(row, "HTTP_ERROR", status, resp.headers.get("Content-Type", ""), error=f"HTTP {status}")
            ctype = resp.headers.get("Content-Type", "").split(";")[0].strip().lower()
            chunks, size = [], 0
            for chunk in resp.iter_content(128 * 1024):
                if not chunk: continue
                size += len(chunk)
                if size > MAX_BYTES:
                    return result(row, "SKIPPED_TOO_LARGE", status, ctype, error=f"Exceeds {MAX_BYTES} bytes")
                chunks.append(chunk)
            data = b"".join(chunks)
            if not data:
                return result(row, "EMPTY_RESPONSE", status, ctype, error="Empty response")
            # Detect the actual format instead of trusting URL suffix.
            if data[:5] == b"%PDF-":
                ext_actual = ".pdf"
            elif b"<html" in data[:1000].lower() or b"<!doctype html" in data[:1000].lower() or "html" in ctype:
                ext_actual = ".html"
            else:
                ext_actual = ext if ext != ".html" else ".bin"
            dest = dest.with_suffix(ext_actual)
            dest.write_bytes(data)
            return {**row, "download_status": "DOWNLOADED", "http_status": status, "content_type": ctype,
                    "local_path": str(dest.relative_to(HERE)), "bytes": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(), "error": ""}
    except requests.RequestException as e:
        return result(row, "REQUEST_ERROR", "", "", error=str(e)[:500])
    except Exception as e:
        return result(row, "ERROR", "", "", error=str(e)[:500])


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): h.update(block)
    return h.hexdigest()


def result(row, status, http_status, content_type, error=""):
    return {**row, "download_status": status, "http_status": http_status, "content_type": content_type,
            "local_path": "", "bytes": 0, "sha256": "", "error": error}


def main():
    rows = load_inventory()
    print(f"Sources queued: {len(rows)}")
    print("Downloading from official/source URLs. No Gemini API calls are used.")
    results = []
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        futures = {pool.submit(download_one, r): r for r in rows}
        for i, future in enumerate(as_completed(futures), 1):
            r = future.result(); results.append(r)
            if i % 25 == 0 or i == len(rows):
                ok = sum(x.get("download_status") in {"DOWNLOADED", "ALREADY_DOWNLOADED"} for x in results)
                print(f"Processed {i}/{len(rows)} | downloaded/available: {ok}")
    fields = list(dict.fromkeys(k for r in results for k in r.keys()))
    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(results)
    counts = {}
    for r in results: counts[r.get("download_status", "UNKNOWN")] = counts.get(r.get("download_status", "UNKNOWN"), 0) + 1
    print("\nFinished. Status counts:")
    for k, v in sorted(counts.items()): print(f"  {k}: {v}")
    print(f"\nFiles: {OUT_DIR}\nManifest: {MANIFEST}")
    print("Review the manifest for HTTP_ERROR / REQUEST_ERROR entries before indexing.")

if __name__ == "__main__":
    main()
