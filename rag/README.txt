BABYBOT DOSA BOUNDED INGESTION

1. Extract ingest_dosa_babybot.py into your existing rag folder.
2. Ensure requests, beautifulsoup4 and pymupdf are installed in your .venv.
   If needed: python -m pip install requests beautifulsoup4 pymupdf
3. Run from the rag folder:
   python ingest_dosa_babybot.py

This fetches at most 30 DOSA URLs, using the exact official DOSA homepage,
a short fixed list of student-facing pages, and relevant direct links from
the homepage. It does not recursively crawl, follow login pages, crawl other
IITK sections, or touch existing DoAA chunks / ChromaDB.

Outputs:
  chunks/dosa_chunks.jsonl
  web_sources/dosa_ingestion_report.txt

After running, upload the report. Do not index until it is reviewed.
