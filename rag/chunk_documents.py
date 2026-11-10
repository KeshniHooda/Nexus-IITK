"""BabyBot RAG chunker. Preserves every source record, including distinct course codes with identical text hashes."""
from pathlib import Path
import csv, re, json, hashlib, argparse

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / 'extraction_manifest.csv'
OUT_DIR = ROOT / 'chunks'
OUT_JSONL = OUT_DIR / 'chunks.jsonl'
OUT_REPORT = ROOT / 'chunking_manifest.csv'

COURSE_RE = re.compile(r'(?<![A-Z0-9])([A-Z]{2,6}\s?\d{3,4}[A-Z]?(?:-[A-Z0-9]+)?)(?![A-Z0-9])', re.I)
HEADING_RE = re.compile(r'^(?:\s{0,8})(.{2,100})(?:\s*)$')

def clean(s):
    s = s.replace('\x00', ' ')
    s = re.sub(r'[ \t]+', ' ', s)
    s = re.sub(r'\n{3,}', '\n\n', s)
    return s.strip()

def infer_course_codes(*values):
    found=[]
    for value in values:
        if not value: continue
        for m in COURSE_RE.findall(str(value).upper()):
            code=re.sub(r'\s+','',m)
            if code not in found: found.append(code)
    return found

def split_sections(text):
    # Keep headings attached to their following paragraphs; PDF page markers remain in text.
    lines=text.splitlines()
    sections=[]; buf=[]
    for line in lines:
        stripped=line.strip()
        is_heading = (len(stripped) > 2 and len(stripped) <= 100 and
                      (stripped.isupper() or stripped.endswith(':') or
                       re.match(r'^(?:\d+(?:\.\d+)*[.)]?|[A-Z][.)])\s+', stripped)))
        if is_heading and buf and len('\n'.join(buf)) >= 700:
            sections.append('\n'.join(buf).strip()); buf=[]
        buf.append(line)
    if buf: sections.append('\n'.join(buf).strip())
    return [x for x in sections if x]

def make_chunks(text, target=1100, overlap=160):
    paras=[]
    for section in split_sections(text):
        parts=re.split(r'\n\s*\n', section)
        paras.extend(p.strip() for p in parts if p.strip())
    chunks=[]; current=''
    for para in paras:
        if len(para) > target*1.6:
            if current:
                chunks.append(current); current=''
            start=0
            while start < len(para):
                end=min(len(para), start+target)
                if end < len(para):
                    cut=para.rfind(' ', start, end)
                    if cut > start+target//2: end=cut
                piece=para[start:end].strip()
                if piece: chunks.append(piece)
                if end >= len(para): break
                start=max(start+1, end-overlap)
            continue
        if not current: current=para
        elif len(current)+2+len(para) <= target: current += '\n\n'+para
        else:
            chunks.append(current)
            tail=current[-overlap:] if overlap else ''
            current=(tail+'\n'+para).strip() if tail else para
    if current: chunks.append(current)
    return chunks

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--target-chars',type=int,default=1100)
    parser.add_argument('--overlap-chars',type=int,default=160)
    args=parser.parse_args()
    if not MANIFEST.exists():
        raise SystemExit(f'Missing {MANIFEST.name}. Put this script beside extraction_manifest.csv.')
    with MANIFEST.open(encoding='utf-8-sig',newline='') as f: rows=list(csv.DictReader(f))
    OUT_DIR.mkdir(exist_ok=True)
    reports=[]; total_chunks=0; readable=0; skipped=0
    # Map content hash to an extracted text file. Duplicate rows reuse text but retain their own identity/metadata.
    hash_to_text={}
    for r in rows:
        if r.get('status')=='EXTRACTED' and r.get('output_file'):
            p=ROOT / r['output_file']
            if p.exists() and r.get('sha256'): hash_to_text.setdefault(r['sha256'],p)
    with OUT_JSONL.open('w',encoding='utf-8') as out:
        for i,r in enumerate(rows,1):
            status=r.get('status','')
            text_path=None
            if r.get('output_file'):
                candidate=ROOT/r['output_file']
                if candidate.exists(): text_path=candidate
            if text_path is None and r.get('sha256') in hash_to_text:
                text_path=hash_to_text[r['sha256']]
            if text_path is None:
                reports.append({'file':r.get('file',''),'title':r.get('title',''),'url':r.get('url',''),'category':r.get('category',''),'status':status,'chunks':0,'course_codes':';'.join(infer_course_codes(r.get('title'),r.get('file'),r.get('url'))),'note':'No extracted text available; OCR or extraction needed.'})
                skipped+=1; continue
            try: text=clean(text_path.read_text(encoding='utf-8',errors='replace'))
            except Exception as e:
                reports.append({'file':r.get('file',''),'title':r.get('title',''),'url':r.get('url',''),'category':r.get('category',''),'status':'READ_ERROR','chunks':0,'course_codes':'','note':str(e)})
                skipped+=1; continue
            if not text:
                reports.append({'file':r.get('file',''),'title':r.get('title',''),'url':r.get('url',''),'category':r.get('category',''),'status':'EMPTY_TEXT','chunks':0,'course_codes':'','note':'Extracted text is empty.'})
                skipped+=1; continue
            readable+=1
            pieces=make_chunks(text,args.target_chars,args.overlap_chars)
            codes=infer_course_codes(r.get('title'),r.get('file'),r.get('url'))
            for j,piece in enumerate(pieces):
                record={
                    'chunk_id':hashlib.sha1(f"{r.get('url','')}|{r.get('sha256','')}|{j}|{r.get('title','')}".encode()).hexdigest(),
                    'text':piece,
                    'source_title':r.get('title',''), 'source_url':r.get('url',''),
                    'source_file':r.get('file',''), 'category':r.get('category',''),
                    'source_sha256':r.get('sha256',''), 'course_codes':codes,
                    'source_pages':r.get('pages',''), 'chunk_index':j,
                    'extraction_status':status,
                }
                out.write(json.dumps(record,ensure_ascii=False)+'\n')
                total_chunks+=1
            reports.append({'file':r.get('file',''),'title':r.get('title',''),'url':r.get('url',''),'category':r.get('category',''),'status':'CHUNKED','chunks':len(pieces),'course_codes':';'.join(codes),'note':f'Text source: {text_path.name}'})
            if i%100==0: print(f'Processed {i}/{len(rows)} | chunks: {total_chunks}')
    with OUT_REPORT.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['file','title','url','category','status','chunks','course_codes','note']); w.writeheader(); w.writerows(reports)
    print('\nChunking complete.')
    print(f'Source records: {len(rows)} | readable records: {readable} | skipped: {skipped} | chunks: {total_chunks}')
    print(f'Chunks: {OUT_JSONL}')
    print(f'Report: {OUT_REPORT}')
    print('Course records are NOT deduplicated: identical text hashes retain separate source/course identities.')

if __name__=='__main__': main()
