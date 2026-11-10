from __future__ import annotations
import re, sqlite3, uuid, shutil
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / 'babybot_resources.db'
UPLOAD_DIR = ROOT / 'community_uploads'
MAX_DEPTH, MAX_ITEMS, TIMEOUT = 6, 1200, 18
MAX_UPLOAD_BYTES = 50 * 1024 * 1024


def db():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute('''CREATE TABLE IF NOT EXISTS resources(
        id INTEGER PRIMARY KEY AUTOINCREMENT, course TEXT NOT NULL,
        department TEXT DEFAULT '', resource_type TEXT DEFAULT '',
        title TEXT NOT NULL, url TEXT NOT NULL, drive_id TEXT DEFAULT '',
        parent_path TEXT DEFAULT '', is_folder INTEGER DEFAULT 0,
        source_folder_url TEXT DEFAULT '', added_at TEXT DEFAULT CURRENT_TIMESTAMP,
        source_kind TEXT DEFAULT 'drive', stored_path TEXT DEFAULT '', original_name TEXT DEFAULT '',
        UNIQUE(course,drive_id,url))''')
    # Migrate databases created by earlier BabyBot versions.
    cols = {r['name'] for r in c.execute('PRAGMA table_info(resources)').fetchall()}
    for name, decl in [('source_kind', "TEXT DEFAULT 'drive'"), ('stored_path', "TEXT DEFAULT ''"), ('original_name', "TEXT DEFAULT ''")]:
        if name not in cols:
            c.execute(f'ALTER TABLE resources ADD COLUMN {name} {decl}')
    c.commit()
    return c


def drive_id(url):
    u = urlparse(url.strip())
    for p in (r'/folders/([\w-]+)', r'/file/d/([\w-]+)', r'/document/d/([\w-]+)', r'/spreadsheets/d/([\w-]+)', r'/presentation/d/([\w-]+)'):
        m = re.search(p, u.path)
        if m: return m.group(1)
    return (parse_qs(u.query).get('id') or [None])[0]


def is_folder(url): return '/folders/' in url or 'embeddedfolderview' in url

def drive_url(fid, folder=False): return f'https://drive.google.com/drive/folders/{fid}' if folder else f'https://drive.google.com/file/d/{fid}/view'


def folder_entries(fid):
    url = f'https://drive.google.com/embeddedfolderview?id={fid}#list'
    res = requests.get(url, timeout=TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
    res.raise_for_status()
    soup = BeautifulSoup(res.text, 'html.parser')
    out, seen = [], set()
    for a in soup.select('a[href]'):
        name = ' '.join(a.get_text(' ', strip=True).split())
        href = a['href']; full = href if href.startswith('http') else 'https://drive.google.com' + href
        ident = drive_id(full)
        if not name or not ident or ident in seen: continue
        seen.add(ident); folder = is_folder(full) or 'folder' in (a.get('class') or [])
        out.append({'id': ident, 'name': name, 'is_folder': folder, 'url': drive_url(ident, folder)})
    return out


def add_drive_resource(link, course, department='', resource_type=''):
    link = (link or '').strip(); course = (course or '').strip()
    if not course: raise ValueError('Course is required (e.g. EE320).')
    u = urlparse(link)
    if u.scheme != 'https' or u.netloc.lower() not in ('drive.google.com', 'www.drive.google.com'):
        raise ValueError('Paste a public Google Drive file or folder link.')
    root = drive_id(link)
    if not root: raise ValueError('Could not recognise a Drive file/folder ID.')
    folder = is_folder(link); root_url = drive_url(root, True) if folder else ''
    found, errors = [], []
    if folder:
        def walk(fid, path, depth):
            if depth > MAX_DEPTH or len(found) >= MAX_ITEMS: return
            try: entries = folder_entries(fid)
            except Exception as e:
                errors.append(f'{path or "root"}: {type(e).__name__}: {e}'); return
            for x in entries:
                if len(found) >= MAX_ITEMS: break
                p = f'{path}/{x["name"]}'.strip('/')
                found.append({**x, 'path': p})
                if x['is_folder']: walk(x['id'], p, depth + 1)
        walk(root, '', 0)
        found.insert(0, {'id': root, 'name': course + ' shared folder', 'is_folder': True, 'url': root_url, 'path': course})
    else:
        found = [{'id': root, 'name': 'Shared Drive file', 'is_folder': False, 'url': drive_url(root), 'path': ''}]
    c = db(); added = 0
    for x in found:
        c.execute('''INSERT OR IGNORE INTO resources(course,department,resource_type,title,url,drive_id,parent_path,is_folder,source_folder_url,source_kind)
                     VALUES(?,?,?,?,?,?,?,?,?,'drive')''',
                  (course, department.strip(), resource_type.strip(), x['name'], x['url'], x['id'], x.get('path', ''), int(x['is_folder']), root_url))
        added += c.execute('SELECT changes()').fetchone()[0]
    c.commit(); c.close()
    return {'discovered': len(found), 'added': added, 'errors': errors, 'is_folder': folder, 'course': course}


def add_uploaded_file(uploaded, course, department='', resource_type=''):
    course = (course or '').strip()
    if not course: raise ValueError('Course is required (e.g. EE320).')
    original = Path(uploaded.name).name
    raw = uploaded.getvalue()
    if not raw: raise ValueError(f'{original} is empty.')
    if len(raw) > MAX_UPLOAD_BYTES: raise ValueError(f'{original} exceeds the 50 MB per-file limit.')
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', original).strip('._') or 'resource'
    stored = f'{rid}_{safe}'
    path = UPLOAD_DIR / stored
    path.write_bytes(raw)
    c = db()
    c.execute('''INSERT INTO resources(course,department,resource_type,title,url,drive_id,parent_path,is_folder,source_kind,stored_path,original_name)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
              (course, (department or '').strip(), (resource_type or '').strip(), original, f'local://{rid}', rid, '', 0, 'upload', str(path), original))
    c.commit(); c.close()
    return {'added': 1, 'course': course, 'title': original, 'id': rid}


def list_resources(course=''):
    c = db()
    rows = c.execute('SELECT * FROM resources WHERE lower(course)=lower(?) ORDER BY is_folder DESC,parent_path,title', (course,)).fetchall() if course else c.execute('SELECT * FROM resources ORDER BY course,is_folder DESC,parent_path,title').fetchall()
    c.close(); return [dict(x) for x in rows]


def get_file_path(item):
    p = Path(item.get('stored_path') or '').resolve()
    root = UPLOAD_DIR.resolve()
    try: p.relative_to(root)
    except ValueError: return None
    return p if p.is_file() else None


def delete_resource(rid):
    c = db(); row = c.execute('SELECT * FROM resources WHERE id=?', (rid,)).fetchone()
    if row and row['source_kind'] == 'upload':
        p = get_file_path(dict(row))
        if p:
            try: p.unlink()
            except OSError: pass
    c.execute('DELETE FROM resources WHERE id=?', (rid,)); c.commit(); c.close()


def parse_request(q, api_key='', model='gemini-3-flash-preview'):
    m = re.search(r'\b([A-Z]{2,5})\s*[- ]?\s*(\d{3,4}[A-Z]?)\b', q, re.I)
    course = (m.group(1) + m.group(2)).upper() if m else ''
    s = q.lower(); kind = ''
    groups = [
        ('PYQ', ['pyq', 'previous year', 'past paper', 'old paper', 'previous papers']),
        ('Midsem', ['midsem', 'mid-sem', 'mid sem', 'mid semester']),
        ('Endsem', ['endsem', 'end-sem', 'end sem', 'end semester']),
        ('Quiz', ['quiz', 'quizzes', 'class test']),
        ('Assignment', ['assignment', 'tutorial sheet']), ('Notes', ['notes', 'lecture notes']),
        ('Lecture', ['lecture', 'slides', 'ppt']), ('Lab', ['lab', 'laboratory', 'experiment'])]
    for k, terms in groups:
        if any(t in s for t in terms): kind = k; break
    if api_key:
        try:
            from google import genai
            import json
            cli = genai.Client(api_key=api_key)
            prompt = "Understand this IITK student query, including Hindi/Hinglish/English. Extract exact course code and resource category. Return JSON with keys course and category. Category: PYQ, Midsem, Endsem, Quiz, Assignment, Notes, Lecture, Lab, or empty. If uncertain, leave empty. Do not guess. Query: " + q
            r = cli.models.generate_content(model=model, contents=prompt, config={'response_mime_type': 'application/json', 'temperature': 0})
            d = json.loads((r.text or '{}').strip().strip('`'))
            if not course and d.get('course'): course = re.sub(r'\s+', '', str(d['course'])).upper()
            if not kind and d.get('category'): kind = str(d['category']).strip()
        except Exception: pass
    return course, kind


def search_resources(question, api_key='', model='gemini-3-flash-preview'):
    course, kind = parse_request(question, api_key, model); rows = list_resources()
    if course:
        matched = [r for r in rows if re.sub(r'\s+', '', r['course']).upper() == course]
        if not matched: matched = [r for r in rows if course.lower() in (r['course'] + ' ' + r['title'] + ' ' + r['parent_path']).lower().replace(' ', '')]
    else: matched = rows
    # Only narrow when the user clearly asks for a category AND matching labels exist.
    if kind and matched:
        subset = [r for r in matched if kind.lower() in (r['resource_type'] + ' ' + r['title'] + ' ' + r['parent_path']).lower()]
        if subset: matched = subset
    return {'course': course, 'category': kind, 'items': matched}


def format_results(result):
    items = result['items']
    if not items: return 'No community resources are catalogued yet for that course. Add the course folder link or upload the files in Community Resources.'
    course = result.get('course') or items[0]['course']; cat = result.get('category')
    out = [f"### Community resources for **{course}**" + (f' · {cat} (all matches)' if cat else ''), 'I am including all matching course resources, including loosely labelled items, so you do not miss useful material.']
    for x in items:
        typ = 'Folder' if x['is_folder'] else ('Uploaded file' if x.get('source_kind') == 'upload' else 'Drive file')
        if x.get('source_kind') == 'upload':
            out.append(f"- **{x['title']}** · {typ} · `{x['course']}`  \n  Download it from the Community Resources library.")
        else:
            out.append(f"- **{x['title']}** · {typ} · `{x['parent_path'] or x['course']}`  \n  [Open in Google Drive]({x['url']})")
    return '\n\n'.join(out)
