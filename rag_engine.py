"""
BabyBot IITK RAG engine.

Uses:
- Gemini to understand/rewrite IITK questions.
- Existing local SentenceTransformer embeddings.
- Existing ChromaDB collection (read-only; no re-indexing).
- Lexical + semantic retrieval with source-quality ranking.
- Gemini to answer strictly from retrieved evidence with citations.

This module never modifies the ChromaDB collection.
"""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import chromadb
from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
COLLECTION_NAME = "iitk_knowledge_curated_v1"
BASE_DIR = Path(__file__).resolve().parent
RAG_DIR = BASE_DIR / "rag"
DB_DIR = RAG_DIR / "chroma_db"

COURSE_RE = re.compile(r"\b[A-Z]{2,5}\s?\d{3,4}[A-Z]?\b", re.I)
TOKEN_RE = re.compile(r"[a-z0-9]+", re.I)

PLANNER_PROMPT = """You are the query-understanding component of BabyBot, an IIT Kanpur assistant.
Convert the user's question into a retrieval plan. Do NOT answer the question.

Return ONLY valid JSON with these keys:
{
  "intent": "course_prerequisite | course_information | academic_calendar | registration | exam_policy | minor_requirement | institute_policy | campus_information | other",
  "entities": ["exact course codes, department names, semester/year, named policy"],
  "search_queries": ["up to 4 short, precise searches that would find the answer"],
  "must_have_terms": ["terms that should occur in useful evidence"],
  "preferred_categories": ["document categories, if identifiable"]
}

Important:
- Preserve directionality. "Prerequisites FOR EE200" means requirements before taking EE200,
  NOT courses that require EE200.
- For questions about a course, include the exact course code and terms such as
  prerequisite, pre-requisite, eligibility, course description, course handout.
- Prefer current official IITK sources. Do not broaden EE200 into all EE courses.
- Do not invent facts. This is a search plan, not an answer.
"""

ANSWER_PROMPT = """You are BabyBot, an accurate IIT Kanpur academic assistant.

Answer the user's question using ONLY the supplied retrieved source excerpts for IITK-specific facts.
Rules:
1. First answer the exact question directly and simply.
2. Never infer a course's prerequisites from another course's prerequisite list.
3. Distinguish "prerequisites FOR course X" from "courses that list X as a prerequisite".
4. Prefer current official IITK sources. Treat historical reports, old proposals and archived documents
   as historical context only; they cannot establish current policy unless the question asks history.
5. If the excerpts do not explicitly establish the answer, say:
   "I couldn't verify this from the available official IITK documents."
   Then briefly say what source/document is missing. Do not guess.
6. Do not claim to have searched Pingala, email, portals, or websites unless supplied as evidence.
7. Cite every factual IITK claim using [1], [2], etc. Only cite the provided source IDs.
8. Keep simple questions concise. No long generic explanations.
9. If sources conflict or dates differ, explain the conflict instead of silently choosing.
10. Do not cite a source that does not support the specific sentence.

Retrieved excerpts:
{context}

Source register:
{source_register}
"""


def is_iitk_question(question: str) -> bool:
    q = question.lower()
    if COURSE_RE.search(question):
        return True
    markers = (
        "iitk", "iit kanpur", "institute", "doaa", "dosa", "gymkhana",
        "course", "minor", "major", "registration", "pre-registration",
        "preregistration", "make-up exam", "makeup exam", "academic calendar",
        "semester", "ug manual", "course of study", "course handout",
        "department", "credit", "sugc", "dugc", "summer term",
        "hostel", "campus", "institute holiday"
    )
    return any(x in q for x in markers)


@lru_cache(maxsize=1)
def _resources():
    if not DB_DIR.exists():
        raise FileNotFoundError(
            f"BabyBot knowledge database not found at {DB_DIR}. "
            "Keep the existing rag/chroma_db folder beside the app."
        )
    client = chromadb.PersistentClient(path=str(DB_DIR))
    collection = client.get_collection(COLLECTION_NAME)
    model = SentenceTransformer(MODEL_NAME)
    return collection, model


def _plan_query(client, model_name: str, question: str) -> dict[str, Any]:
    response = client.models.generate_content(
        model=model_name,
        contents=(
            PLANNER_PROMPT
            + "\n\nUSER QUESTION:\n"
            + question
        ),
        config={"response_mime_type": "application/json", "temperature": 0.0},
    )
    raw = (response.text or "").strip()
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.I)
    try:
        plan = json.loads(raw)
    except Exception:
        plan = {}
    plan.setdefault("intent", "other")
    plan.setdefault("entities", [])
    plan.setdefault("search_queries", [])
    plan.setdefault("must_have_terms", [])
    plan.setdefault("preferred_categories", [])
    if not plan["search_queries"]:
        plan["search_queries"] = [question]
    # Keep the original wording in retrieval to avoid losing directionality.
    plan["search_queries"] = [question] + [
        str(q) for q in plan["search_queries"] if str(q).strip() and str(q).strip() != question
    ]
    return plan


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in TOKEN_RE.findall(text or "") if len(t) > 1]


def _source_penalty(meta: dict[str, Any]) -> float:
    title = str(meta.get("source_title", "")).lower()
    file_name = str(meta.get("source_file", "")).lower()
    url = str(meta.get("source_url", "")).lower()
    combined = " ".join((title, file_name, url))
    # Old curriculum-planning reports repeatedly polluted course searches.
    if any(x in combined for x in (
        "interimreport", "interim_report", "arc_report", "arcreport",
        "courses_of_study_2008", "courses-of-study-2008"
    )):
        return 8.0
    years = [int(y) for y in re.findall(r"(?:19|20)\d{2}", combined)]
    if years and max(years) < 2022:
        return 4.0
    return 0.0


def _source_bonus(meta: dict[str, Any], intent: str, entities: list[str]) -> float:
    title = str(meta.get("source_title", "")).lower()
    file_name = str(meta.get("source_file", "")).lower()
    category = str(meta.get("category", "")).lower()
    url = str(meta.get("source_url", "")).lower()
    combined = " ".join((title, file_name, category, url))
    bonus = 0.0
    if any(x in combined for x in ("courses-of-study", "courses_of_study", "course-approved")):
        bonus += 1.8
    if "2026" in combined:
        bonus += 2.5
    if "2025" in combined:
        bonus += 1.0
    if intent == "course_prerequisite":
        if "course-code" in category or "individual course" in category:
            bonus += 1.0
        for entity in entities:
            code = re.sub(r"\s+", "", str(entity)).lower()
            if code and code in re.sub(r"\s+", "", combined):
                bonus += 3.0
    if intent == "academic_calendar" and "calendar" in combined:
        bonus += 4.0
    if intent == "minor_requirement" and ("minor" in combined or "minor" in title):
        bonus += 4.0
    return bonus


@lru_cache(maxsize=1)
def _all_chunks():
    """Load indexed text once for lexical search; collection remains unchanged."""
    collection, _ = _resources()
    ids, docs, metas = [], [], []
    offset = 0
    batch = 1000
    while True:
        part = collection.get(
            limit=batch,
            offset=offset,
            include=["documents", "metadatas"],
        )
        p_ids = part.get("ids") or []
        if not p_ids:
            break
        ids.extend(p_ids)
        docs.extend(part.get("documents") or [])
        metas.extend(part.get("metadatas") or [])
        offset += len(p_ids)
        if len(p_ids) < batch:
            break
    return ids, docs, metas


def retrieve(question: str, plan: dict[str, Any], top_k: int = 12) -> list[dict[str, Any]]:
    collection, model = _resources()
    queries = plan.get("search_queries") or [question]
    entities = [str(x) for x in plan.get("entities", [])]
    intent = str(plan.get("intent", "other"))

    # Semantic retrieval over multiple query formulations.
    semantic_scores: dict[str, float] = {}
    semantic_payload: dict[str, dict[str, Any]] = {}
    for query in queries[:5]:
        emb = model.encode([query], normalize_embeddings=True, show_progress_bar=False).tolist()
        result = collection.query(
            query_embeddings=emb,
            n_results=45,
            include=["documents", "metadatas", "distances"],
        )
        for doc_id, doc, meta, distance in zip(
            result.get("ids", [[]])[0],
            result.get("documents", [[]])[0],
            result.get("metadatas", [[]])[0],
            result.get("distances", [[]])[0],
        ):
            meta = meta or {}
            similarity = 1.0 - float(distance)
            if doc_id not in semantic_scores or similarity > semantic_scores[doc_id]:
                semantic_scores[doc_id] = similarity
                semantic_payload[doc_id] = {"id": doc_id, "text": doc, "metadata": meta}

    # Lexical retrieval across the local indexed corpus. Exact course-code matching
    # is especially important for questions like "prerequisites for EE200".
    ids, docs, metas = _all_chunks()
    q_tokens = set(_tokens(question + " " + " ".join(queries)))
    entity_codes = {
        re.sub(r"\s+", "", e).lower()
        for e in entities + COURSE_RE.findall(question)
    }
    lexical: list[tuple[float, str, str, dict[str, Any]]] = []
    for doc_id, doc, meta in zip(ids, docs, metas):
        meta = meta or {}
        doc_text = (doc or "")
        doc_lower = doc_text.lower()
        meta_text = " ".join(str(meta.get(k, "")) for k in (
            "source_title", "source_file", "source_url", "category", "course_codes"
        )).lower()

        # Direction-sensitive safeguard: for "prerequisites FOR EE200", do not
        # retrieve EE606 merely because its document says EE200 is a prerequisite.
        # Only accept a course-specific source whose identity is EE200 itself.
        if intent == "course_prerequisite" and entity_codes:
            source_identity = " ".join(str(meta.get(k, "")) for k in (
                "source_title", "source_file", "course_codes"
            )).lower()
            compact_identity = re.sub(r"[^a-z0-9]", "", source_identity)
            if not any(code in compact_identity for code in entity_codes):
                continue
        doc_tokens = set(_tokens(doc_text[:12000] + " " + meta_text))
        overlap = len(q_tokens & doc_tokens)
        if overlap == 0:
            continue
        score = overlap * 0.55
        for code in entity_codes:
            compact_doc = re.sub(r"\s+", "", doc_lower + " " + meta_text)
            if code and code in compact_doc:
                score += 5.0
        for term in plan.get("must_have_terms", []):
            term = str(term).lower().strip()
            if term and term in doc_lower:
                score += 1.5
        score += _source_bonus(meta, intent, entities)
        score -= _source_penalty(meta)
        lexical.append((score, doc_id, doc_text, meta))

    lexical.sort(key=lambda x: x[0], reverse=True)
    combined: dict[str, dict[str, Any]] = dict(semantic_payload)
    for score, doc_id, doc, meta in lexical[:100]:
        item = combined.setdefault(doc_id, {"id": doc_id, "text": doc, "metadata": meta})
        item["lexical_score"] = score

    ranked = []
    for doc_id, item in combined.items():
        meta = item.get("metadata") or {}
        sem = semantic_scores.get(doc_id, 0.0)
        lex = float(item.get("lexical_score", 0.0))
        penalty = _source_penalty(meta)
        bonus = _source_bonus(meta, intent, entities)
        final_score = (sem * 3.0) + min(lex, 18.0) * 0.35 + bonus - penalty
        item["score"] = final_score
        ranked.append(item)

    ranked.sort(key=lambda x: x["score"], reverse=True)

    # Avoid flooding the answer with multiple copies of the same PDF. Keep
    # distinct course-code documents separate; only collapse duplicate chunks
    # from the same source file for answer context.
    selected = []
    seen_source_page = set()
    for item in ranked:
        meta = item.get("metadata") or {}
        source = str(meta.get("source_url") or meta.get("source_file") or item["id"])
        page = str(meta.get("source_pages", ""))
        key = (source, page)
        if key in seen_source_page:
            continue
        seen_source_page.add(key)
        selected.append(item)
        if len(selected) >= top_k:
            break
    return selected


def answer_iitk_question(question: str, chat_history: list[dict[str, str]], api_key: str,
                         model_name: str = "gemini-3-flash-preview") -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    plan = _plan_query(client, model_name, question)
    matches = retrieve(question, plan, top_k=12)

    if not matches:
        return (
            "I couldn't find relevant evidence in BabyBot's indexed IITK documents. "
            "I don't want to guess. The relevant official course handout or policy document may be missing."
        )

    context_parts = []
    source_parts = []
    for idx, item in enumerate(matches, 1):
        meta = item.get("metadata") or {}
        title = meta.get("source_title") or "Untitled IITK document"
        url = meta.get("source_url") or ""
        category = meta.get("category") or "Uncategorised"
        pages = meta.get("source_pages") or "Not recorded"
        text = (item.get("text") or "").strip()
        context_parts.append(
            f"[{idx}] TITLE: {title}\nCATEGORY: {category}\nPAGES: {pages}\nEXCERPT:\n{text[:1800]}"
        )
        source_parts.append(f"[{idx}] {title} | {category} | pages: {pages} | {url}")

    context = "\n\n".join(context_parts)
    source_register = "\n".join(source_parts)
    history_text = ""
    if chat_history:
        history_text = "\n\nRECENT CONVERSATION (for context only; not evidence):\n" + "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')[:700]}"
            for m in chat_history[-6:]
        )

    response = client.models.generate_content(
        model=model_name,
        contents=(
            ANSWER_PROMPT.format(context=context, source_register=source_register)
            + history_text
            + "\n\nCURRENT USER QUESTION:\n"
            + question
        ),
        config={"temperature": 0.1},
    )
    if not response.text:
        raise RuntimeError("Gemini returned an empty RAG answer.")
    return response.text.strip()


def answer_with_rag_if_relevant(question: str, chat_messages: list[dict[str, str]],
                                api_key: str, model_name: str) -> str | None:
    if not is_iitk_question(question):
        return None
    history = [m for m in chat_messages[:-1] if m.get("role") in ("user", "assistant")]
    return answer_iitk_question(question, history, api_key, model_name)
