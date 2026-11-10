BABYBOT IITK TARGETED INGESTION v2.1

This replaces the generic v2 crawl. It starts with the actual current IITK Courses of Study page AND all 20 department-wise November 2026 CoS PDFs, plus the academic pages/manuals/minors/calendar you asked for.

Important changes:
- Curriculum and current course catalogues are highest priority.
- A real priority queue is used; priority scores now determine what is fetched first.
- Senate decisions, old committee pages and historical archives are still recorded if discovered, but have very low priority.
- DOSA/student-life pages are retained but come after academic sources.
- www/non-www duplicates are normalized to one URL.
- Different course PDFs remain separate source identities; no content-hash deduplication is done by this crawler.
- No login bypass: Pingala/OARS private student records are not crawled.

INSTALL (from your rag folder, with your existing .venv active):
1. Copy ingest_iitk_sources.py, seed_urls.txt and requirements.txt into your rag folder, replacing the old crawler files.
2. Install only if needed: python -m pip install -r requirements.txt
3. Run the full targeted crawl: python ingest_iitk_sources.py --max-depth 3

No --max-pages cap is used, so the full seed list and relevant linked pages are processed. This does not re-run your older download/extraction pipeline and does not overwrite your existing Chroma index unless you explicitly add --index.

OUTPUTS:
rag/web_sources/files/             downloaded PDFs
rag/web_sources/extracted_text/    extracted text
rag/web_sources/chunks.jsonl       chunks from this run
rag/web_sources/crawl_manifest.csv per-source status
rag/web_sources/link_inventory.csv discovered links and priority decisions
rag/web_sources/coverage_report.txt summary
rag/web_sources/registry.sqlite3   source registry

After this crawl, the next step is to merge these new source chunks into BabyBot's existing RAG index, then improve retrieval so exact course codes and actual PDF downloads work reliably.
