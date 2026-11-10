import json
import csv
import sys
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

RAG_DIR = Path(__file__).resolve().parent
BASE = RAG_DIR / 'chunks' / 'chunks.jsonl'
RECOVERED = RAG_DIR / 'chunks' / 'course_recovered.jsonl'
DB_DIR = RAG_DIR / 'chroma_db'
COLLECTION = 'iitk_knowledge_v1'
MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'
BATCH_SIZE = 64


def read_jsonl(path):
    if not path.exists():
        print(f'MISSING: {path}')
        return []
    rows = []
    with path.open('r', encoding='utf-8') as f:
        for line_no, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                print(f'Skipping invalid JSON at {path.name}:{line_no}: {exc}')
                continue
            if row.get('text', '').strip():
                rows.append(row)
    return rows


def scalar_metadata(row):
    result = {}
    for key, value in row.items():
        if key in {'text', 'chunk_id'} or value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
        elif isinstance(value, list):
            result[key] = ', '.join(str(x) for x in value)
        else:
            result[key] = str(value)
    return result


def main():
    print('Reading chunk files...')
    rows = read_jsonl(BASE) + read_jsonl(RECOVERED)
    unique = {}
    for row in rows:
        cid = row.get('chunk_id')
        if cid:
            unique[cid] = row
    rows = list(unique.values())
    if not rows:
        print('No chunks found. Check your rag/chunks folder.')
        sys.exit(1)

    print(f'Chunks ready: {len(rows):,}')
    print(f'Loading local embedding model: {MODEL_NAME}')
    print('First run downloads the model once; this is not a Gemini API call.')
    model = SentenceTransformer(MODEL_NAME)

    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_or_create_collection(
        name=COLLECTION,
        metadata={'description': 'IIT Kanpur BabyBot knowledge base', 'hnsw:space': 'cosine'}
    )

    total = len(rows)
    for start in range(0, total, BATCH_SIZE):
        batch = rows[start:start + BATCH_SIZE]
        texts = [r['text'] for r in batch]
        embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False).tolist()
        collection.upsert(
            ids=[r['chunk_id'] for r in batch],
            documents=texts,
            metadatas=[scalar_metadata(r) for r in batch],
            embeddings=embeddings,
        )
        done = min(start + len(batch), total)
        print(f'Indexed {done:,}/{total:,}')

    print('\nINDEXING COMPLETE')
    print(f'Collection: {COLLECTION}')
    print(f'Vectors in collection: {collection.count():,}')
    print(f'Database folder: {DB_DIR}')

    # Preserve all recovered course identities, including those still awaiting OCR.
    recovery_manifest = RAG_DIR / 'course_recovery_manifest.csv'
    if recovery_manifest.exists():
        print(f'Course recovery registry retained at: {recovery_manifest}')
        print('Note: courses marked NEEDS_OCR_OR_MANUAL_EXTRACTION are registered but do not yet have searchable text.')

if __name__ == '__main__':
    main()
