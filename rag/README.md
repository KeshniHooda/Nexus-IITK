# BabyBot RAG — Step 1: DoAA source discovery

This starter project discovers links published on the official IITK DoAA homepage and its archive, then writes them to a CSV inventory.

## What this step does
- Visits the two official DoAA seed pages in `sources.json`.
- Follows links that remain under the `/doaa` section.
- Records each unique IITK link, title, rough content type, and the page where it was found.
- Saves `doaa_source_inventory.csv` for manual review.

## What it does NOT do
- It does not download PDFs.
- It does not extract document text.
- It does not create embeddings or use ChromaDB.
- It does not call Gemini or consume Gemini API quota.

## Run on Windows (VS Code terminal)

```powershell
py -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python discover_sources.py
```

Open `doaa_source_inventory.csv` and review the discovered sources before we choose what to ingest.
