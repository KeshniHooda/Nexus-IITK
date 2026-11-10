"""Recover course-code PDFs skipped as duplicate content by the earlier extractor/chunker.
Run from the rag directory: python recover_course_chunks.py
Writes chunks/course_recovered.jsonl and course_recovery_manifest.csv.
Does not modify or delete existing chunks.
"""
from pathlib import Path
import csv, json, re, hashlib

ROOT = Path('.')
CHUNK_MANIFEST = ROOT / 'chunking_manifest.csv'
EXTRACTION_MANIFEST = ROOT / 'extraction_manifest.csv'
EXTRACTED_DIR = ROOT / 'extracted'
DOCUMENTS_DIR = ROOT / 'documents'
OUT_DIR = ROOT / 'chunks'
OUT_JSONL = OUT_DIR / 'course_recovered.jsonl'
OUT_CSV = ROOT / 'course_recovery_manifest.csv'
CHUNK_WORDS = 220
OVERLAP_WORDS = 35


def read_csv(path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def clean_path(value):
    return Path(str(value).replace('\\', '/'))


def split_pages(text):
    # Extractor output normally uses [PAGE n] separators. If absent, treat as one page.
    parts = re.split(r'(?=\[PAGE\s+\d+\])', text)
    pages = []
    for i, part in enumerate(parts, 1):
        part = part.strip()
        if not part:
            continue
        m = re.match(r'\[PAGE\s+(\d+)\]', part)
        page_no = int(m.group(1)) if m else i
        body = re.sub(r'^\[PAGE\s+\d+\]\s*', '', part).strip()
        if body:
            pages.append((page_no, body))
    return pages or ([(1, text.strip())] if text.strip() else [])


def make_chunks(text, source):
    words = text.split()
    if not words:
        return []
    step = max(1, CHUNK_WORDS - OVERLAP_WORDS)
    out = []
    for idx, start in enumerate(range(0, len(words), step)):
        piece = ' '.join(words[start:start + CHUNK_WORDS]).strip()
        if len(piece) < 40:
            continue
        payload = {
            'chunk_id': hashlib.sha1((source['url'] + '|' + str(idx) + '|' + piece).encode('utf-8')).hexdigest(),
            'text': piece,
            'source_title': source['title'],
            'source_url': source['url'],
            'source_file': source['file'],
            'category': source['category'],
            'source_sha256': source.get('sha256', ''),
            'course_codes': [source['course_code']] if source.get('course_code') else [],
            'source_pages': source.get('pages', ''),
            'chunk_index': idx,
            'extraction_status': 'RECOVERED_FROM_IDENTICAL_SOURCE_TEXT',
        }
        out.append(payload)
        if start + CHUNK_WORDS >= len(words):
            break
    return out


def main():
    if not CHUNK_MANIFEST.exists() or not EXTRACTION_MANIFEST.exists():
        raise SystemExit('Missing chunking_manifest.csv or extraction_manifest.csv. Run this from your rag folder.')
    chunk_rows = read_csv(CHUNK_MANIFEST)
    extract_rows = read_csv(EXTRACTION_MANIFEST)
    course_rows = [r for r in chunk_rows if r.get('category') == 'Individual course information (course-code PDF)' and r.get('status') == 'DUPLICATE_CONTENT']

    # For each content hash, find an already-extracted text file. Reusing the text is safe:
    # each output chunk is recreated with the skipped course's own code, title, URL and file.
    extracted_by_hash = {}
    for r in extract_rows:
        if r.get('sha256') and r.get('output_file') and r.get('status') == 'EXTRACTED':
            extracted_by_hash.setdefault(r['sha256'], r)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    recovered, manifest = [], []
    for row in course_rows:
        src_file = row.get('file', '')
        title = (row.get('title') or '').strip()
        code = (row.get('course_codes') or title).strip()
        url = row.get('url', '')
        match = next((r for r in extract_rows if r.get('file') == src_file), None)
        sha = match.get('sha256', '') if match else ''
        text_path = None
        method = ''
        if match and match.get('output_file'):
            p = clean_path(match['output_file'])
            if p.exists():
                text_path, method = p, 'OWN_EXTRACTED_TEXT'
        if text_path is None and sha in extracted_by_hash:
            p = clean_path(extracted_by_hash[sha]['output_file'])
            if p.exists():
                text_path, method = p, 'IDENTICAL_CONTENT_TEXT'
        if text_path is None:
            # Last attempt: extract directly from the original PDF, if present.
            pdf_path = clean_path(src_file)
            if pdf_path.exists():
                try:
                    import pymupdf
                    doc = pymupdf.open(pdf_path)
                    page_text = [f'[PAGE {i+1}]\n{page.get_text()}' for i, page in enumerate(doc)]
                    raw = '\n\n'.join(page_text).strip()
                    if len(raw) <= 80:
                        # Optional OCR fallback for scanned/image-only course PDFs.
                        try:
                            import pytesseract
                            from PIL import Image
                            ocr_pages = []
                            for i, page in enumerate(doc):
                                pix = page.get_pixmap(matrix=pymupdf.Matrix(2, 2), alpha=False)
                                img = Image.frombytes('RGB', [pix.width, pix.height], pix.samples)
                                page_ocr = pytesseract.image_to_string(img)
                                if page_ocr.strip():
                                    ocr_pages.append(f'[PAGE {i+1}]\n{page_ocr.strip()}')
                            raw = '\n\n'.join(ocr_pages).strip()
                            if len(raw) > 80:
                                method = 'TESSERACT_OCR'
                        except Exception:
                            pass
                    doc.close()
                    if len(raw) > 80:
                        temp = OUT_DIR / (re.sub(r'[^A-Za-z0-9_-]+', '_', code) + '_recovered.txt')
                        temp.write_text(raw, encoding='utf-8')
                        text_path = temp
                        if not method:
                            method = 'DIRECT_PDF_EXTRACTION'
                except Exception:
                    pass
        if text_path is None:
            manifest.append({'course_code': code, 'title': title, 'url': url, 'file': src_file, 'status': 'NEEDS_OCR_OR_MANUAL_EXTRACTION', 'chunks': 0, 'method': 'OCR_NOT_AVAILABLE_OR_NO_TEXT_FOUND'})
            continue

        raw = text_path.read_text(encoding='utf-8', errors='ignore')
        pages = split_pages(raw)
        page_chunks = []
        for page_no, page_text in pages:
            for chunk in make_chunks(page_text, {'title': title, 'url': url, 'file': src_file,
                    'category': row.get('category', ''), 'sha256': sha, 'course_code': code,
                    'pages': str(page_no)}):
                page_chunks.append(chunk)
        # If page-wise chunks are too small, chunk the complete extracted text.
        if not page_chunks:
            page_chunks = make_chunks(raw, {'title': title, 'url': url, 'file': src_file,
                    'category': row.get('category', ''), 'sha256': sha, 'course_code': code, 'pages': ''})
        recovered.extend(page_chunks)
        manifest.append({'course_code': code, 'title': title, 'url': url, 'file': src_file,
                         'status': 'RECOVERED', 'chunks': len(page_chunks), 'method': method})

    with OUT_JSONL.open('w', encoding='utf-8') as f:
        for item in recovered:
            f.write(json.dumps(item, ensure_ascii=False) + '\n')
    with OUT_CSV.open('w', encoding='utf-8-sig', newline='') as f:
        fields = ['course_code', 'title', 'url', 'file', 'status', 'chunks', 'method']
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader(); writer.writerows(manifest)
    counts = {}
    for r in manifest: counts[r['status']] = counts.get(r['status'], 0) + 1
    print(f'Course PDFs to recover: {len(course_rows)}')
    print(f'Recovered course PDFs: {counts.get("RECOVERED", 0)}')
    print(f'Need OCR/manual extraction: {counts.get("NEEDS_OCR_OR_MANUAL_EXTRACTION", 0)}')
    print(f'New chunks: {len(recovered)}')
    print(f'Output: {OUT_JSONL}')
    print(f'Manifest: {OUT_CSV}')
    print('Existing chunks.jsonl was NOT changed.')

if __name__ == '__main__':
    main()
