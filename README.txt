BABYBOT QUALITY RAG UPGRADE
===========================

WHAT THIS CHANGES
- Routes IITK/course/policy questions through Gemini query understanding,
  local ChromaDB retrieval, and Gemini evidence-grounded answer generation.
- Uses both semantic retrieval and lexical/exact-term retrieval.
- Penalises known historical planning reports that polluted earlier results.
- Prefers newer official course/catalogue sources where appropriate.
- Requires evidence for claims; if the corpus does not support an answer,
  BabyBot must say it cannot verify it.
- Keeps ordinary non-IITK chat on the existing Gemini path.
- Does NOT rebuild, delete, or modify ChromaDB.

INSTALL
1. Back up your current app_backup_integrated.py.
2. Copy the supplied app_backup_integrated.py into your project root.
3. Copy rag_engine.py into the same project root (beside app_backup_integrated.py).
4. Keep your existing rag/chroma_db folder exactly where it is.
5. In the same .venv used to run BabyBot, install if missing:
      python -m pip install chromadb sentence-transformers
6. Run the app as usual:
      streamlit run app_backup_integrated.py

EXPECTED PROJECT STRUCTURE
project/
  app_backup_integrated.py
  rag_engine.py
  .env
  reminder_store.py
  email_monitor.py
  webmail.py
  rag/
    chroma_db/
      ...

IMPORTANT
- The first IITK question may take longer because the local index is loaded into
  memory for hybrid lexical retrieval. Later questions reuse the in-process cache.
- IITK questions use two Gemini calls: query understanding and grounded answer.
- Local embeddings and ChromaDB retrieval do not consume Gemini API quota.
- The app will not fabricate a missing course prerequisite. If the exact source
  is absent, it will explicitly say that it could not verify the answer.
- This is a retrieval/answering upgrade, not a re-indexing job.
