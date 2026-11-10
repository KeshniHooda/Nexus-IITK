"""
Build BabyBot's clean IITK-wide index from already curated chunks.
Run from the existing rag folder:
    python build_curated_index.py

Inputs:
    web_sources/chunks_curated_dosa.jsonl  (curated DoAA + bounded DOSA registry output)
    chunks/dosa_chunks.jsonl               (bounded DOSA homepage ingestion)

Outputs:
    chunks/chunks_babybot_curated.jsonl
    ChromaDB collection: iitk_knowledge_curated_v1

The existing iitk_knowledge_v1 collection is NOT modified or deleted.
No crawling or downloading is performed by this script.
"""
from pathlib import Path
import json
import hashlib
import sys

try:
    import chromadb
    from sentence_transformers import SentenceTransformer
except ImportError as exc:
    print(f"Required package is missing: {exc}")
    print("This script expects the same Python environment used for your earlier indexing.")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent
INPUTS = [
    ROOT / "web_sources" / "chunks_curated_dosa.jsonl",
    ROOT / "chunks" / "dosa_chunks.jsonl",
]
OUTPUT = ROOT / "chunks" / "chunks_babybot_curated.jsonl"
DB_DIR = ROOT / "chroma_db"
COLLECTION_NAME = "iitk_knowledge_curated_v1"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
BATCH_SIZE = 64

def read_jsonl(path):
    if not path.exists():
        print(f"MISSING INPUT: {path}")
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f"Skipping invalid JSON {path.name}:{line_no}: {exc}")
                continue
            text = str(row.get("text", "")).strip()
            if not text:
                continue
            row["text"] = text
            rows.append(row)
    print(f"Read {len(rows):,} chunks from {path.relative_to(ROOT)}")
    return rows

def make_id(row):
    existing = str(row.get("chunk_id", "")).strip()
    if existing:
        return existing
    key = str(row.get("source_url", "")) + "|" + str(row.get("chunk_index", "")) + "|" + row["text"]
    return hashlib.sha256(key.encode("utf-8")).hexdigest()

def metadata(row):
    result = {}
    for key, value in row.items():
        if key in ("text", "chunk_id") or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
        elif isinstance(value, list):
            result[key] = ", ".join(str(x) for x in value)
        else:
            result[key] = str(value)
    # Ensure a source label exists for citation display.
    result.setdefault("source_title", str(row.get("source_url", "IITK source")))
    result.setdefault("source_url", "")
    return result

def main():
    all_rows = []
    for path in INPUTS:
        all_rows.extend(read_jsonl(path))

    if not all_rows:
        print("\nNo chunks found. Check that you are running this inside the rag folder.")
        sys.exit(1)

    # Keep one copy of each chunk ID. Do not deduplicate different PDFs by text;
    # separate course/source identities must remain separate.
    unique = {}
    for row in all_rows:
        unique[make_id(row)] = row

    rows = list(unique.values())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as f:
        for row in rows:
            row["chunk_id"] = make_id(row)
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(f"\nCombined unique chunks: {len(rows):,}")
    print(f"Saved combined source file: {OUTPUT.relative_to(ROOT)}")
    print(f"Loading local embedding model: {MODEL_NAME}")
    print("No Gemini API calls are used for indexing.")

    model = SentenceTransformer(MODEL_NAME)
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={
            "description": "Curated IIT Kanpur-wide BabyBot knowledge base",
            "hnsw:space": "cosine"
        }
    )

    total = len(rows)
    for start in range(0, total, BATCH_SIZE):
        batch = rows[start:start+BATCH_SIZE]
        texts = [r["text"] for r in batch]
        embeddings = model.encode(
            texts, normalize_embeddings=True, show_progress_bar=False
        ).tolist()
        ids = [r["chunk_id"] for r in batch]
        collection.upsert(
            ids=ids,
            documents=texts,
            metadatas=[metadata(r) for r in batch],
            embeddings=embeddings
        )
        print(f"Indexed {min(start + len(batch), total):,}/{total:,}")

    print("\n========== INDEXING COMPLETE ==========")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Vectors in new collection: {collection.count():,}")
    print(f"Database: {DB_DIR}")
    print("\nYour old iitk_knowledge_v1 collection has been left untouched.")
    print("Next: connect the BabyBot retrieval code to iitk_knowledge_curated_v1.")

if __name__ == "__main__":
    main()
