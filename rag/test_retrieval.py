from pathlib import Path
import re
import sys
from collections import defaultdict

import chromadb
from sentence_transformers import SentenceTransformer

RAG_DIR = Path(__file__).resolve().parent
DB_DIR = RAG_DIR / "chroma_db"
COLLECTION_NAME = "iitk_knowledge_v1"
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
SEMANTIC_CANDIDATES = 100
SHOW_RESULTS = 8

STOP_WORDS = {
    "what", "are", "the", "for", "and", "with", "does", "when", "where",
    "how", "can", "you", "tell", "me", "about", "please", "iitk", "iit",
    "kanpur", "course", "courses", "information"
}


def clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def is_historical_report(meta, text):
    source = " ".join([
        clean(meta.get("source_title")),
        clean(meta.get("source_file")),
        clean(meta.get("source_url")),
    ]).lower()
    # These are planning/review reports, not current course handouts.
    if any(term in source for term in (
        "interimreport", "interim-report", "arc_report", "arcreport",
        "courses_of_study_2008", "courses_of_study_2021"
    )):
        return True
    return False


def year_from_source(meta):
    source = " ".join([
        clean(meta.get("source_title")),
        clean(meta.get("source_file")),
        clean(meta.get("source_url")),
    ])
    years = re.findall(r"\b(20\d{2})\b", source)
    return max(map(int, years)) if years else None


def lexical_score(question, doc, meta):
    q = question.lower()
    text = doc.lower()
    title = clean(meta.get("source_title")).lower()
    filename = clean(meta.get("source_file")).lower()
    category = clean(meta.get("category")).lower()
    score = 0.0

    terms = [t for t in re.findall(r"[a-z0-9]+", q) if t not in STOP_WORDS]
    for term in terms:
        if len(term) < 2:
            continue
        if re.search(rf"\b{re.escape(term)}\b", text):
            score += 1.4
        if term in title:
            score += 2.0
        if term in filename:
            score += 1.5

    # Explicit course-code matching matters much more than a vague semantic match.
    codes = re.findall(r"\b[A-Z]{2,4}\s?\d{3}[A-Z]?\b", question.upper())
    for code in codes:
        compact = re.sub(r"\s+", "", code)
        normalized_text = re.sub(r"\s+", "", doc.upper())
        normalized_title = re.sub(r"\s+", "", title.upper())
        normalized_file = re.sub(r"\s+", "", filename.upper())
        if re.search(rf"\b{re.escape(compact)}\b", normalized_text):
            score += 8.0
        if compact.lower() in normalized_title.lower():
            score += 5.0
        if compact.lower() in normalized_file.lower():
            score += 6.0

    # A question about prerequisites needs chunks that actually discuss prerequisites.
    if any(x in q for x in ("prerequisite", "pre-requisite", "pre requisite")):
        if re.search(r"\b(pre[- ]?requisites?|prerequisites?)\b", text):
            score += 4.0
        if "course catalogue" in category or "courses of study" in title:
            score += 1.0

    # Prefer current sources over old dated catalogues when evidence is otherwise comparable.
    year = year_from_source(meta)
    if year:
        if year >= 2026:
            score += 2.5
        elif year == 2025:
            score += 1.5
        elif year <= 2021:
            score -= 3.0

    if is_historical_report(meta, doc):
        score -= 30.0

    return score


def main():
    if not DB_DIR.exists():
        print(f"ChromaDB folder not found: {DB_DIR}")
        print("Place this script directly inside your existing rag folder.")
        sys.exit(1)

    print("Loading local embedding model...")
    model = SentenceTransformer(MODEL_NAME)
    client = chromadb.PersistentClient(path=str(DB_DIR))
    try:
        collection = client.get_collection(COLLECTION_NAME)
    except Exception:
        print(f"Collection '{COLLECTION_NAME}' not found in {DB_DIR}")
        sys.exit(1)

    print(f"Connected to {COLLECTION_NAME} | vectors: {collection.count():,}")
    print("Hybrid retrieval enabled: semantic candidates + keyword/source ranking.")
    print("Historical planning reports are suppressed from the active results.")
    print("Type 'exit' to stop.\n")

    while True:
        question = input("Your question: ").strip()
        if question.lower() in {"exit", "quit", "q"}:
            break
        if not question:
            continue

        q_embedding = model.encode(
            [question], normalize_embeddings=True, show_progress_bar=False
        ).tolist()

        semantic = collection.query(
            query_embeddings=q_embedding,
            n_results=min(SEMANTIC_CANDIDATES, collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        candidates = {}
        ids = semantic.get("ids", [[]])[0]
        docs = semantic.get("documents", [[]])[0]
        metas = semantic.get("metadatas", [[]])[0]
        distances = semantic.get("distances", [[]])[0]

        for cid, doc, meta, distance in zip(ids, docs, metas, distances):
            candidates[cid] = {
                "doc": doc or "",
                "meta": meta or {},
                "distance": float(distance),
            }

        # Keyword pass over stored text catches exact course-code matches that
        # embeddings can rank poorly. This reads the existing DB; it does not re-index.
        all_data = collection.get(include=["documents", "metadatas"])
        for cid, doc, meta in zip(
            all_data.get("ids", []),
            all_data.get("documents", []),
            all_data.get("metadatas", []),
        ):
            doc = doc or ""
            meta = meta or {}
            if lexical_score(question, doc, meta) > 0:
                if cid not in candidates:
                    candidates[cid] = {
                        "doc": doc,
                        "meta": meta,
                        "distance": 1.0,
                    }

        ranked = []
        for cid, item in candidates.items():
            meta = item["meta"]
            doc = item["doc"]
            lex = lexical_score(question, doc, meta)
            # Convert cosine-style distance into a small semantic contribution.
            semantic_score = max(0.0, 1.0 - item["distance"])
            total = lex + semantic_score
            if is_historical_report(meta, doc):
                continue
            ranked.append((total, lex, semantic_score, cid, item))

        ranked.sort(key=lambda x: x[0], reverse=True)
        if not ranked:
            print("No relevant current-source chunks found.\n")
            continue

        print("\nRANKED MATCHES")
        for rank, (total, lex, sem, cid, item) in enumerate(ranked[:SHOW_RESULTS], 1):
            meta = item["meta"]
            print("\n" + "=" * 78)
            print(
                f"MATCH {rank} | score: {total:.2f} "
                f"(keyword/source: {lex:.2f}, semantic: {sem:.3f})"
            )
            print(f"Title : {meta.get('source_title', 'Unknown title')}")
            print(f"Category: {meta.get('category', 'Unknown category')}")
            print(f"File  : {meta.get('source_file', 'Unknown file')}")
            print(f"URL   : {meta.get('source_url', 'No source URL')}")
            print(f"Course: {meta.get('course_codes', '')}")
            print("\nRetrieved text:")
            print(item["doc"][:1800].strip())

        q_lower = question.lower()
        if "ee200" in q_lower and any(
            word in q_lower for word in ("prerequisite", "pre-requisite", "pre requisite")
        ):
            direct_evidence = [
                item for _, _, _, _, item in ranked
                if re.search(r"\bEE\s?200\b", item["doc"], re.I)
                and re.search(r"\b(pre[- ]?requisites?|prerequisites?)\b", item["doc"], re.I)
                and (
                    "EE200" in clean(item["meta"].get("source_title")).upper().replace(" ", "")
                    or "EE200" in clean(item["meta"].get("source_file")).upper().replace(" ", "")
                )
            ]
            if not direct_evidence:
                print(
                    "\nEVIDENCE CHECK: I did not find a current, course-specific EE200 "
                    "prerequisite statement in the retrieved indexed chunks. "
                    "Do not answer with a prerequisite inferred from another course "
                    "or an old planning report."
                )
        print("\n" + "=" * 78 + "\n")

    print("Retrieval test ended.")


if __name__ == "__main__":
    main()
