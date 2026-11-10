#!/usr/bin/env python3
"""Recover BabyBot crawl chunks from already saved web_sources files and index additively."""
import argparse, csv, hashlib, json, re, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "web_sources"
DB = OUT / "registry.sqlite3"
CHUNKS = OUT / "chunks_recovered.jsonl"
REPORT = OUT / "recovery_report.txt"

def chunk_text(text, size=850, overlap=120):
    words = re.findall(r"\S+", text)
    result, start = [], 0
    while start < len(words):
        end = min(start + size, len(words))
        result.append(" ".join(words[start:end]))
        if end == len(words):
            break
        start = max(end - overlap, start + 1)
    return result

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index", action="store_true",
                    help="Add recovered chunks to existing ../chroma_db collection; never deletes existing vectors")
    args = ap.parse_args()

    if not DB.exists():
        raise SystemExit(f"Missing {DB}. Do not rerun crawler; send me this error.")
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute("""
        SELECT url, final_url, title, category, priority, source_type, status,
               local_path, text_path, fetched_at, depth, word_count
        FROM documents
        WHERE text_path IS NOT NULL AND text_path <> ''
          AND status IN ('downloaded_extracted','html_extracted','extracted','success')
        ORDER BY priority DESC, url
    """).fetchall()

    output, skipped, sources = [], [], 0
    for row in rows:
        text_path = ROOT / row["text_path"]
        if not text_path.exists():
            skipped.append(f"{row['url']} | missing text file: {row['text_path']}")
            continue
        try:
            text = text_path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception as e:
            skipped.append(f"{row['url']} | read error: {e}")
            continue
        if len(text.split()) < 15:
            skipped.append(f"{row['url']} | too little extracted text")
            continue
        pieces = chunk_text(text)
        if not pieces:
            continue
        sources += 1
        for i, piece in enumerate(pieces):
            cid = hashlib.sha256(f"{row['url']}|{i}".encode()).hexdigest()
            output.append({
                "chunk_id": cid, "text": piece,
                "source_title": row["title"] or row["url"],
                "source_file": Path(row["local_path"] or "").name,
                "source_url": row["url"], "final_url": row["final_url"] or row["url"],
                "source_type": row["source_type"] or "unknown",
                "source_category": row["category"] or "official_iitk_other",
                "priority": int(row["priority"] or 0),
                "chunk_index": i, "content_hash": hashlib.sha256(piece.encode()).hexdigest(),
                "fetched_at": row["fetched_at"] or ""
            })

    with CHUNKS.open("w", encoding="utf-8") as f:
        for item in output:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    with REPORT.open("w", encoding="utf-8") as f:
        f.write("BABYBOT CRAWL RECOVERY REPORT\n")
        f.write(f"Registry documents with extracted text: {len(rows)}\n")
        f.write(f"Sources recovered: {sources}\n")
        f.write(f"Chunks rebuilt: {len(output)}\n")
        f.write(f"Skipped/missing: {len(skipped)}\n")
        if skipped:
            f.write("\nSKIPPED\n" + "\n".join(skipped) + "\n")
    con.close()
    print(f"RECOVERY COMPLETE: {sources} sources, {len(output)} chunks.")
    print(f"Recovered chunks: {CHUNKS}")
    print(f"Report: {REPORT}")

    if args.index:
        try:
            import chromadb
            from sentence_transformers import SentenceTransformer
        except Exception as e:
            raise SystemExit("Chunks recovered successfully, but indexing dependencies are missing: " + str(e))
        db_path = ROOT.parent / "chroma_db"
        if not db_path.exists():
            raise SystemExit(f"Chunks recovered, but existing ChromaDB not found at {db_path}.")
        client = chromadb.PersistentClient(path=str(db_path))
        collection = client.get_or_create_collection("iitk_knowledge_v1")
        model = SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")
        for start in range(0, len(output), 48):
            batch = output[start:start+48]
            embeddings = model.encode([x["text"] for x in batch], normalize_embeddings=True).tolist()
            metas = [{k:v for k,v in x.items() if k not in ("text","chunk_id") and v is not None}
                     for x in batch]
            collection.upsert(ids=[x["chunk_id"] for x in batch],
                              documents=[x["text"] for x in batch],
                              metadatas=metas, embeddings=embeddings)
            print(f"Indexed {min(start+len(batch), len(output))}/{len(output)}")
        print("INDEXING COMPLETE. Existing vectors were NOT deleted.")

if __name__ == "__main__":
    main()
