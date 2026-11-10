import sqlite3, json, re, hashlib
from urllib.parse import urlsplit, urlunsplit
from pathlib import Path

ROOT=Path(__file__).resolve().parent
DB=ROOT/"web_sources"/"registry.sqlite3"
OUT=ROOT/"web_sources"/"chunks_curated_dosa.jsonl"
REPORT=ROOT/"web_sources"/"curation_report_dosa.txt"

# Explicit high-value curriculum documents
COS_RE=re.compile(r"/doaa/data/courses-of-study/[^/?]+-CoS26\.pdf$", re.I)
INCLUDE_EXACT={
 "https://iitk.ac.in/doaa/courses",
 "https://iitk.ac.in/doaa/courses-of-study-nov-26",
 "https://iitk.ac.in/doaa/course-templates",
 "https://iitk.ac.in/doaa/core-time-table",
 "https://iitk.ac.in/doaa/exam-schedule",
 "https://iitk.ac.in/doaa/academic-calendar",
 "https://iitk.ac.in/doaa/under-graduate-programme",
 "https://iitk.ac.in/doaa/ug-students",
 "https://iitk.ac.in/doaa/forms",
 "https://iitk.ac.in/doaa/institute-holidays",
 "https://iitk.ac.in/doaa/",
 "https://iitk.ac.in/dosa/",
 "https://www.iitk.ac.in/dosa/",
}
# Useful document families; date/version checked conservatively.
INCLUDE_PATTERNS=[
 r"/doaa/data/UG_Manual_Version_1\.4_20\.07\.2026\.pdf$",
 r"/doaa/data/minors-at-iitk-updated\.pdf$",
 r"/doaa/data/Calendar-2026\.pdf$",
 r"/doaa/data/Holidays-2026\.pdf$",
 r"/doaa/data/Code_of_Conducts_Examinations\.pdf$",
 r"/doaa/data/Branch_change\.pdf$",
 r"/doaa/data/Procedure_for_(PhD|MTech|MDes|MSR|BT-MT)_Thesis_Submission\.pdf$",
 r"/doaa/data/Guidelines-for-LHC-Booking\.pdf$",
 r"/doaa/data/courses-of-study/[^/?]+-CoS26\.pdf$",
]
# URLs known to be irrelevant, historical, private/login endpoints, or non-student admin.
EXCLUDE_PATTERNS=[
 r"july14doaan", r"senate", r"committee", r"academic-review", r"programme-review",
 r"statistical-report", r"convocationdata", r"advt-", r"pwd-cell", r"nadcell",
 r"/bau/", r"turnitin", r"technical_infrastructure", r"remote-teaching",
 r"faq-2020", r"201[0-9]", r"2020[-_/]", r"2021[-_/]", r"2014", r"2015",
 r"oars\.iitk\.ac\.in", r"pingala.*login", r"registration_rm", r"studoaiitk",
 r"etd\.iitk\.ac\.in", r"home\.iitk\.ac\.in", r"infocell/announce",
 r"summer_internship_form", r"cer\.iitk\.ac\.in", r"moodle\."
]
def norm(s): return (s or "").strip().lower()

def canonical_url(url):
    """Collapse www/non-www and trailing-slash variants without merging distinct PDFs."""
    p = urlsplit((url or "").strip())
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = p.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit(("https", host, path, p.query, ""))

# DOSA selection is deliberately bounded. This script does NOT crawl or fetch pages.
# It only selects already-downloaded/extracted DOSA pages from registry.sqlite3.
DOSA_MAX_SOURCES = 20
DOSA_RELEVANT_TERMS = (
    "hostel", "hall", "scholarship", "fee", "financial", "aid",
    "medical", "health", "counsel", "wellbeing", "welfare",
    "student", "grievance", "anti-ragging", "ragging", "mess",
    "sports", "gymkhana", "discipline", "emergency", "contact",
    "office", "services", "support"
)

def is_dosa_candidate(url, category="", title=""):
    """Recognise only already-registered DOSA pages; never fetch or crawl."""
    p = urlsplit((url or "").strip())
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "/").lower().rstrip("/") or "/"
    cat = norm(category)
    # The official DOSA section may be hosted under /dosa on iitk.ac.in,
    # or on a DOSA subdomain. Category/title are secondary hints only.
    on_dosa_site = (
        host == "dosa.iitk.ac.in"
        or (host == "iitk.ac.in" and (path == "/dosa" or path.startswith("/dosa/")))
    )
    if not on_dosa_site:
        return False
    if path in ("/", "/dosa"):
        return True
    text = (path + " " + norm(title)).replace("_", "-")
    return any(term in text for term in DOSA_RELEVANT_TERMS)

def selected(url,category,title):
 u=norm(url)
 if any(re.search(p,u,re.I) for p in EXCLUDE_PATTERNS): return False,"excluded historical/irrelevant/private"
 if COS_RE.search(u): return True,"current department CoS26"
 if u in {x.lower() for x in INCLUDE_EXACT}: return True,"priority official landing page"
 if any(re.search(p,u,re.I) for p in INCLUDE_PATTERNS): return True,"approved current student/academic document"
 # Avoid broad category inclusion: classification labels were too noisy.
 return False,"not in curated allowlist"

def chunks(text,size=850,overlap=120):
 words=re.findall(r"\S+",text); start=0
 while start<len(words):
  end=min(start+size,len(words)); yield " ".join(words[start:end])
  if end==len(words): break
  start=max(end-overlap,start+1)

def main():
 if not DB.exists(): raise SystemExit("registry.sqlite3 missing; keep web_sources intact.")
 con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
 rows=con.execute("""SELECT url,final_url,title,category,priority,source_type,status,
 local_path,text_path,fetched_at,depth FROM documents ORDER BY url""").fetchall()
 out=[]; included=[]; excluded={}
 # Pick at most 20 DOSA entries from the existing registry. Homepage first,
 # then shallow pages, higher priority, and shorter URLs. No network access.
 dosa_candidates = []
 seen_dosa = set()
 for r in rows:
  if is_dosa_candidate(r["url"], r["category"], r["title"]):
   key = canonical_url(r["url"])
   if key not in seen_dosa:
    seen_dosa.add(key)
    dosa_candidates.append(r)
 dosa_candidates.sort(key=lambda r: (
  0 if urlsplit(r["url"]).path.rstrip("/") in ("/", "/dosa") else 1,
  int(r["depth"] or 0),
  -int(r["priority"] or 0),
  len(r["url"] or "")
 ))
 allowed_dosa = {canonical_url(r["url"]) for r in dosa_candidates[:DOSA_MAX_SOURCES]}
 seen_urls = set()
 dosa_selected_count = 0
 for r in rows:
  url = r["url"] or ""
  is_dosa = is_dosa_candidate(url, r["category"], r["title"]) and canonical_url(url) in allowed_dosa
  if is_dosa:
   ok,reason = True,"bounded DOSA student information"
  else:
   ok,reason = selected(url,r["category"],r["title"])
  if not ok:
   excluded[reason]=excluded.get(reason,0)+1; continue
  key = canonical_url(url)
  if key in seen_urls:
   excluded["duplicate URL variant"]=excluded.get("duplicate URL variant",0)+1
   continue
  seen_urls.add(key)
  if not r["text_path"] or r["status"] not in ("downloaded_extracted","extracted","html_extracted","success"):
   excluded["approved URL but no extracted text"]=excluded.get("approved URL but no extracted text",0)+1; continue
  tp=ROOT/Path(r["text_path"])
  if not tp.exists():
   excluded["text file missing"]=excluded.get("text file missing",0)+1; continue
  text=tp.read_text(encoding="utf-8",errors="replace").strip()
  if len(text.split())<15:
   excluded["too little extracted text"]=excluded.get("too little extracted text",0)+1; continue
  included.append((r["url"],reason))
  for i,part in enumerate(chunks(text)):
   cid=hashlib.sha256((r["url"]+"|"+str(i)).encode()).hexdigest()
   out.append({"chunk_id":cid,"text":part,"source_title":r["title"] or r["url"],
    "source_url":r["url"],"final_url":r["final_url"] or r["url"],
    "source_category":r["category"] or "official","source_type":r["source_type"] or "unknown",
    "priority":int(r["priority"] or 0),"chunk_index":i,"curation_reason":reason,
    "fetched_at":r["fetched_at"] or ""})
 with OUT.open("w",encoding="utf-8") as f:
  for x in out: f.write(json.dumps(x,ensure_ascii=False)+"\n")
 with REPORT.open("w",encoding="utf-8") as f:
  f.write("BABYBOT CURATED RECOVERY REPORT\n")
  f.write(f"Registry rows examined: {len(rows)}\nApproved sources with extracted text: {len(included)}\nChunks: {len(out)}\n")
  f.write("\nINCLUDED SOURCES\n")
  for u,why in included:f.write(f"{why}\t{u}\n")
  f.write("\nEXCLUDED COUNTS\n")
  for why,n in sorted(excluded.items()):f.write(f"{why}: {n}\n")
 con.close()
 print(f"CURATION COMPLETE: {len(included)} sources, {len(out)} chunks.")
 print(f"Review first: {REPORT}")
 print("This step does NOT crawl, download, or modify ChromaDB.")
 print(f"New outputs: {OUT.name} and {REPORT.name}")
if __name__=="__main__":main()
