#!/usr/bin/env python3
"""Extract searchable text from BabyBot's downloaded IITK knowledge sources."""
from pathlib import Path
import csv, hashlib, json, re, sys
from datetime import datetime, timezone

HERE = Path(__file__).resolve().parent
DOCS = HERE / 'documents'
DOWNLOAD_MANIFEST = HERE / 'download_manifest.csv'
OUT = HERE / 'extracted'
OUT.mkdir(exist_ok=True)

try:
    import fitz  # PyMuPDF
except ImportError:
    print('Missing PyMuPDF. Run: python -m pip install -r requirements.txt')
    sys.exit(1)
try:
    from bs4 import BeautifulSoup
except ImportError:
    print('Missing BeautifulSoup. Run: python -m pip install -r requirements.txt')
    sys.exit(1)


def clean_text(s):
    s = s.replace('\x00', ' ').replace('\r', '\n')
    s = re.sub(r'[\t\f\v]+', ' ', s)
    s = re.sub(r' *\n *', '\n', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def extract_pdf(path):
    doc = fitz.open(path)
    pages = []
    for i, page in enumerate(doc, 1):
        text = clean_text(page.get_text('text', sort=True))
        if text:
            pages.append({'page': i, 'text': text})
    total_pages = len(doc)
    doc.close()
    return pages, total_pages


def extract_html(path):
    raw = path.read_bytes()
    soup = BeautifulSoup(raw, 'html.parser')
    for node in soup(['script', 'style', 'noscript', 'svg', 'nav', 'footer']):
        node.decompose()
    title = clean_text(soup.title.get_text(' ', strip=True)) if soup.title else ''
    main = soup.find('main') or soup.find('article') or soup.body or soup
    text = clean_text(main.get_text('\n', strip=True))
    return title, text


def safe_stem(path):
    return re.sub(r'[^A-Za-z0-9._-]+', '_', path.stem)[:100] or 'document'


def main():
    if not DOCS.exists():
        print('ERROR: documents folder not found:', DOCS)
        print('Place this script inside rag/, alongside documents/ and download_manifest.csv.')
        sys.exit(1)
    manifest_rows = []
    if DOWNLOAD_MANIFEST.exists():
        with DOWNLOAD_MANIFEST.open('r', encoding='utf-8-sig', newline='') as f:
            manifest_rows = list(csv.DictReader(f))
    metadata_by_path = {}
    for row in manifest_rows:
        p = (row.get('local_path') or '').replace('\\', '/')
        if p:
            metadata_by_path[p.lower()] = row

    files = [p for p in DOCS.rglob('*') if p.is_file()]
    print(f'Files found: {len(files)}')
    results, seen_hashes = [], {}
    for n, path in enumerate(files, 1):
        rel = path.relative_to(HERE).as_posix()
        meta = metadata_by_path.get(rel.lower(), {})
        ext = path.suffix.lower()
        row = {
            'file': rel, 'title': meta.get('title') or path.stem,
            'url': meta.get('url', ''), 'category': meta.get('category', ''),
            'sha256': '', 'status': '', 'pages': 0, 'characters': 0,
            'output_file': '', 'notes': ''
        }
        try:
            digest = sha256(path)
            row['sha256'] = digest
            if digest in seen_hashes:
                row['status'] = 'DUPLICATE_CONTENT'
                row['notes'] = 'Same file content as ' + seen_hashes[digest]
                results.append(row)
                continue
            seen_hashes[digest] = rel
            page_records = []
            if ext == '.pdf' or path.read_bytes()[:5] == b'%PDF-':
                page_records, page_count = extract_pdf(path)
                row['pages'] = page_count
                row['status'] = 'EXTRACTED' if page_records else 'NEEDS_OCR'
                if not page_records:
                    row['notes'] = 'No selectable text found; likely scanned/image-only PDF.'
                body = '\n\n'.join(f"[PAGE {p['page']}]\n{p['text']}" for p in page_records)
            elif ext in ('.html', '.htm'):
                html_title, body = extract_html(path)
                if html_title: row['title'] = html_title
                row['status'] = 'EXTRACTED' if body else 'EMPTY'
            elif ext == '.docx':
                from docx import Document
                d = Document(path)
                body = clean_text('\n'.join(p.text for p in d.paragraphs))
                row['status'] = 'EXTRACTED' if body else 'EMPTY'
            elif ext in ('.txt', '.md', '.csv'):
                body = clean_text(path.read_text(encoding='utf-8', errors='replace'))
                row['status'] = 'EXTRACTED' if body else 'EMPTY'
            else:
                row['status'] = 'UNSUPPORTED_FORMAT'
                row['notes'] = f'No extractor configured for {ext or "unknown extension"}.'
                results.append(row)
                continue
            row['characters'] = len(body)
            if body:
                out_name = safe_stem(path) + '_' + digest[:10] + '.txt'
                out_path = OUT / out_name
                out_path.write_text(body, encoding='utf-8')
                row['output_file'] = out_path.relative_to(HERE).as_posix()
            results.append(row)
        except Exception as e:
            row['status'] = 'EXTRACTION_ERROR'
            row['notes'] = str(e)[:500]
            results.append(row)
        if n % 100 == 0 or n == len(files):
            print(f'Processed {n}/{len(files)}')

    fields = ['file','title','url','category','sha256','status','pages','characters','output_file','notes']
    with (HERE / 'extraction_manifest.csv').open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader(); w.writerows(results)
    counts = {}
    for r in results: counts[r['status']] = counts.get(r['status'], 0) + 1
    print('\nExtraction complete.')
    for k, v in sorted(counts.items()): print(f'  {k}: {v}')
    print('Text files:', OUT)
    print('Manifest:', HERE / 'extraction_manifest.csv')
    print('Note: NEEDS_OCR files require OCR before they can be searched properly.')

if __name__ == '__main__':
    main()
