"""RAG Engine for TradeZen Chatbot.

Provides:
- Ingestion of markdown knowledge files into DB with chunking & embeddings
- Cosine similarity retrieval with cached numpy matrix
- Plain Python BM25-style keyword search fallback
- User notes storage and isolated retrieval
"""
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import logging
import math
import re
import threading
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import numpy as np
from sqlalchemy.orm import Session

from .config import cfg
from .models import ChatKbChunk, ChatNote, get_db_session, init_db
from .llm import llm_client

logger = logging.getLogger(__name__)

STOP_WORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and", "any", "are", "aren't",
    "as", "at", "be", "because", "been", "before", "being", "below", "between", "both", "but", "by", "can",
    "can't", "cannot", "could", "couldn't", "did", "didn't", "do", "does", "doesn't", "doing", "don't",
    "down", "during", "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't", "have",
    "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here", "here's", "hers", "herself", "him",
    "himself", "his", "how", "how's", "i", "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't",
    "it", "it's", "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself", "no", "nor",
    "not", "of", "off", "on", "once", "only", "or", "other", "ought", "our", "ours", "ourselves", "out",
    "over", "own", "same", "shan't", "she", "she'd", "she'll", "she's", "should", "shouldn't", "so", "some",
    "such", "than", "that", "that's", "the", "their", "theirs", "them", "themselves", "then", "there",
    "there's", "these", "they", "they'd", "they'll", "they're", "they've", "this", "those", "through", "to",
    "too", "under", "until", "up", "very", "was", "wasn't", "we", "we'd", "we'll", "we're", "we've", "were",
    "weren't", "what", "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's",
    "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd", "you'll", "you're",
    "you've", "your", "yours", "yourself", "yourselves"
}


@dataclass
class SearchHit:
    id: str
    title: str
    heading: str
    content: str
    source_title: Optional[str]
    source_url: Optional[str]
    evidence: Optional[str]
    score: float
    method: str  # 'vector' or 'keyword'


def slugify(text: str) -> str:
    """Converts a heading title to a clean slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"[-\s]+", "_", text)


def tokenize(text: str) -> List[str]:
    """Unicode-safe lowercase tokenization without stop words."""
    words = re.findall(r"\b\w+\b", text.lower(), flags=re.UNICODE)
    return [w for w in words if w not in STOP_WORDS and len(w) > 1]


def compute_bm25_score(query_tokens: List[str], doc_tokens: List[str], avg_doc_len: float, num_docs: int, df_map: Dict[str, int]) -> float:
    """Computes BM25 score for a document."""
    k1 = 1.5
    b = 0.75
    doc_len = len(doc_tokens)
    if doc_len == 0:
        return 0.0

    score = 0.0
    doc_counts = {}
    for t in doc_tokens:
        doc_counts[t] = doc_counts.get(t, 0) + 1

    for q in query_tokens:
        if q not in doc_counts:
            continue
        tf = doc_counts[q]
        df = df_map.get(q, 1)
        idf = math.log((num_docs - df + 0.5) / (df + 0.5) + 1.0)
        numerator = tf * (k1 + 1)
        denominator = tf + k1 * (1 - b + b * (doc_len / (avg_doc_len or 1.0)))
        score += idf * (numerator / denominator)

    return score


def parse_frontmatter(text: str) -> Tuple[Dict[str, str], str]:
    """Hand-written parser for frontmatter between --- and --- without external dependencies."""
    meta: Dict[str, str] = {}
    body = text
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            fm_text = parts[1]
            body = parts[2]
            for line in fm_text.splitlines():
                line = line.strip()
                if ":" in line:
                    key, val = line.split(":", 1)
                    meta[key.strip()] = val.strip()
    return meta, body.strip()


def chunk_markdown(file_id: str, title: str, body: str) -> List[Dict[str, str]]:
    """Splits markdown at '## ' headings into chunks (80-300 words)."""
    raw_sections = body.split("\n## ")
    chunks: List[Dict[str, str]] = []

    # First section might be intro before any ## heading
    sections_to_process = []
    if raw_sections:
        first = raw_sections[0]
        if first.startswith("## "):
            first = first[3:]
            lines = first.split("\n", 1)
            heading = lines[0].strip()
            content = lines[1].strip() if len(lines) > 1 else ""
            sections_to_process.append((heading, content))
        elif first.strip():
            sections_to_process.append(("Overview", first.strip()))

        for sec in raw_sections[1:]:
            lines = sec.split("\n", 1)
            heading = lines[0].strip()
            content = lines[1].strip() if len(lines) > 1 else ""
            sections_to_process.append((heading, content))

    # Merge sections under 40 words into next, split over 300 words at paragraphs
    merged_sections: List[Tuple[str, str]] = []
    carry_heading = ""
    carry_content = ""

    for h, c in sections_to_process:
        full_text = (carry_content + "\n\n" + c).strip() if carry_content else c.strip()
        current_heading = carry_heading if carry_heading else h
        word_count = len(full_text.split())

        if word_count < 40:
            carry_heading = current_heading
            carry_content = full_text
            continue

        merged_sections.append((current_heading, full_text))
        carry_heading = ""
        carry_content = ""

    if carry_content:
        if merged_sections:
            # append to last
            last_h, last_c = merged_sections[-1]
            merged_sections[-1] = (last_h, (last_c + "\n\n" + carry_content).strip())
        else:
            merged_sections.append((carry_heading or "Overview", carry_content))

    for h, c in merged_sections:
        # Check if over 300 words: split by paragraphs
        words = c.split()
        if len(words) > 300:
            paragraphs = c.split("\n\n")
            current_p = []
            curr_words = 0
            part = 1
            for p in paragraphs:
                p_len = len(p.split())
                if curr_words + p_len > 300 and current_p:
                    chunk_text = "\n\n".join(current_p).strip()
                    sub_h = f"{h} Part {part}"
                    chunks.append({"heading": sub_h, "content": chunk_text})
                    current_p = [p]
                    curr_words = p_len
                    part += 1
                else:
                    current_p.append(p)
                    curr_words += p_len
            if current_p:
                sub_h = f"{h} Part {part}" if part > 1 else h
                chunks.append({"heading": sub_h, "content": "\n\n".join(current_p).strip()})
        else:
            chunks.append({"heading": h, "content": c})

    return chunks


class RAGEngine:
    """Thread-safe RAG engine."""

    def __init__(self, config=cfg):
        self.config = config
        self._cache_lock = threading.Lock()
        self._chunk_ids: List[str] = []
        self._chunk_vectors: Optional[np.ndarray] = None
        self._chunk_metadata: Dict[str, Dict[str, Any]] = {}
        self._is_initialized = False

    def refresh_cache(self, session: Optional[Session] = None):
        """Refreshes cached numpy matrix of chunk vectors."""
        db = session or get_db_session()
        try:
            chunks = db.query(ChatKbChunk).all()
            ids = []
            vectors = []
            meta = {}
            for c in chunks:
                ids.append(c.id)
                meta[c.id] = {
                    "id": c.id,
                    "file_id": c.file_id,
                    "type": c.type,
                    "title": c.title,
                    "heading": c.heading,
                    "content": c.content,
                    "source_title": c.source_title,
                    "source_url": c.source_url,
                    "evidence": c.evidence,
                }
                if c.embedding:
                    vectors.append(c.embedding)
                else:
                    vectors.append([0.0] * self.config.EMBED_DIMENSIONS)

            with self._cache_lock:
                self._chunk_ids = ids
                self._chunk_metadata = meta
                if vectors and len(ids) > 0:
                    self._chunk_vectors = np.array(vectors, dtype=np.float32)
                else:
                    self._chunk_vectors = None
                self._is_initialized = True
        finally:
            if not session:
                db.close()

    def ingest(self, force: bool = False, session: Optional[Session] = None) -> Dict[str, int]:
        """Walks knowledge folder, chunks markdown, updates DB and embeds chunks."""
        init_db()
        db = session or get_db_session()
        created = 0
        updated = 0
        deleted = 0
        unchanged = 0

        try:
            knowledge_path = self.config.knowledge_dir
            if not knowledge_path.exists():
                logger.warning("Knowledge folder does not exist: %s", knowledge_path)
                return {"created": 0, "updated": 0, "deleted": 0, "unchanged": 0}

            md_files = sorted(knowledge_path.rglob("*.md"))
            seen_chunk_ids = set()
            chunks_to_upsert: List[Dict[str, Any]] = []

            for path in md_files:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content_str = f.read()
                except Exception as exc:
                    logger.warning("Failed to read %s: %s", path, exc)
                    continue

                meta, body = parse_frontmatter(content_str)
                file_id = meta.get("id") or path.stem
                kb_type = meta.get("type", "platform")
                title = meta.get("title", file_id)
                source_title = meta.get("source_title", "")
                source_url = meta.get("source_url", "")
                evidence = meta.get("evidence", "platform")

                file_chunks = chunk_markdown(file_id, title, body)
                for c in file_chunks:
                    heading = c["heading"]
                    content = c["content"]
                    chunk_id = f"{file_id}:{slugify(heading)}"
                    seen_chunk_ids.add(chunk_id)

                    # sha256 of title, heading, and content
                    h_input = f"{title}\n{heading}\n{content}".encode("utf-8")
                    content_hash = hashlib.sha256(h_input).hexdigest()

                    chunks_to_upsert.append({
                        "id": chunk_id,
                        "file_id": file_id,
                        "type": kb_type,
                        "title": title,
                        "heading": heading,
                        "content": content,
                        "content_hash": content_hash,
                        "source_title": source_title,
                        "source_url": source_url,
                        "evidence": evidence,
                    })

            # Check existing chunks in DB
            existing_chunks = {c.id: c for c in db.query(ChatKbChunk).all()}

            # Delete chunks whose section disappeared
            for old_id, old_chunk in existing_chunks.items():
                if old_id not in seen_chunk_ids:
                    db.delete(old_chunk)
                    deleted += 1

            # Prepare items needing embed
            items_to_embed = []
            for item in chunks_to_upsert:
                cid = item["id"]
                existing = existing_chunks.get(cid)
                needs_embed = False

                if existing is None:
                    created += 1
                    needs_embed = True
                else:
                    content_changed = existing.content_hash != item["content_hash"]
                    # Only consider model changed if existing actually had an embedding
                    model_changed = (
                        existing.embedding is not None
                        and existing.embedding_model != self.config.GEMINI_EMBED_MODEL
                    )
                    missing_embed = (existing.embedding is None and self.config.has_gemini_key)

                    if force or content_changed or model_changed or missing_embed:
                        updated += 1
                        needs_embed = True
                    else:
                        unchanged += 1

                if needs_embed:
                    items_to_embed.append(item)

            # Embed if needed and possible
            embeddings_map = {}
            if items_to_embed and self.config.has_gemini_key:
                texts = [f"{it['title']} - {it['heading']}: {it['content']}" for it in items_to_embed]
                res = llm_client.embed(texts, kind="document")
                if res.ok and res.vectors and len(res.vectors) == len(items_to_embed):
                    for it, vec in zip(items_to_embed, res.vectors):
                        embeddings_map[it["id"]] = vec

            # Persist upserts
            for item in items_to_embed:
                cid = item["id"]
                vec = embeddings_map.get(cid)
                existing = existing_chunks.get(cid)

                if existing:
                    existing.type = item["type"]
                    existing.title = item["title"]
                    existing.heading = item["heading"]
                    existing.content = item["content"]
                    existing.content_hash = item["content_hash"]
                    existing.source_title = item["source_title"]
                    existing.source_url = item["source_url"]
                    existing.evidence = item["evidence"]
                    if vec:
                        existing.embedding = vec
                        existing.embedding_model = self.config.GEMINI_EMBED_MODEL
                    existing.updated_at = datetime.now(timezone.utc)
                else:
                    new_chunk = ChatKbChunk(
                        id=cid,
                        file_id=item["file_id"],
                        type=item["type"],
                        title=item["title"],
                        heading=item["heading"],
                        content=item["content"],
                        content_hash=item["content_hash"],
                        source_title=item["source_title"],
                        source_url=item["source_url"],
                        evidence=item["evidence"],
                        embedding=vec,
                        embedding_model=self.config.GEMINI_EMBED_MODEL if vec else None,
                        updated_at=datetime.now(timezone.utc)
                    )
                    db.add(new_chunk)

            db.commit()
            self.refresh_cache(session=db)
            return {"created": created, "updated": updated, "deleted": deleted, "unchanged": unchanged}
        except Exception as exc:
            db.rollback()
            logger.error("Ingestion failed: %s", exc)
            return {"created": 0, "updated": 0, "deleted": 0, "unchanged": 0}
        finally:
            if not session:
                db.close()

    def get_chunk_by_file_id(self, file_id: str) -> Optional[SearchHit]:
        """Exact lookup by file_id."""
        with self._cache_lock:
            if not self._is_initialized:
                self.refresh_cache()
            for cid, meta in self._chunk_metadata.items():
                if meta["file_id"] == file_id:
                    return SearchHit(
                        id=meta["id"],
                        title=meta["title"],
                        heading=meta["heading"],
                        content=meta["content"],
                        source_title=meta["source_title"],
                        source_url=meta["source_url"],
                        evidence=meta["evidence"],
                        score=1.0,
                        method="exact"
                    )
        return None

    def retrieve(self, query: str, k: Optional[int] = None, types: Optional[List[str]] = None) -> List[SearchHit]:
        """Retrieves top k chunks using cosine similarity or keyword search fallback."""
        top_k = k or self.config.RAG_TOP_K
        if not self._is_initialized:
            self.refresh_cache()

        with self._cache_lock:
            chunk_ids = list(self._chunk_ids)
            chunk_vectors = self._chunk_vectors
            chunk_metadata = dict(self._chunk_metadata)

        if not chunk_ids:
            return []

        # Attempt vector search if key is present
        has_vectors = (chunk_vectors is not None and np.any(chunk_vectors != 0))
        if self.config.has_gemini_key and has_vectors:
            embed_res = llm_client.embed([query], kind="query")
            if embed_res.ok and embed_res.vectors and len(embed_res.vectors) > 0:
                query_vec = np.array(embed_res.vectors[0], dtype=np.float32)
                scores = np.dot(chunk_vectors, query_vec)
                ranked_indices = np.argsort(scores)[::-1]
                hits = []
                for idx in ranked_indices:
                    score = float(scores[idx])
                    if score < self.config.RAG_MIN_SIMILARITY:
                        break
                    cid = chunk_ids[idx]
                    meta = chunk_metadata[cid]
                    if types and meta["type"] not in types:
                        continue
                    hits.append(SearchHit(
                        id=meta["id"],
                        title=meta["title"],
                        heading=meta["heading"],
                        content=meta["content"],
                        source_title=meta["source_title"],
                        source_url=meta["source_url"],
                        evidence=meta["evidence"],
                        score=round(score, 4),
                        method="vector"
                    ))
                    if len(hits) >= top_k:
                        break
                if hits:
                    return hits

        # Fallback to BM25 keyword search
        return self._keyword_search(query, top_k, types)

    def _keyword_search(self, query: str, k: int, types: Optional[List[str]] = None) -> List[SearchHit]:
        """BM25-style keyword search in pure Python."""
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        docs = []
        with self._cache_lock:
            all_meta = list(self._chunk_metadata.values())

        for meta in all_meta:
            if types and meta["type"] not in types:
                continue
            text = f"{meta['title']} {meta['heading']} {meta['content']}"
            doc_toks = tokenize(text)
            docs.append((meta, doc_toks))

        if not docs:
            return []

        num_docs = len(docs)
        avg_doc_len = sum(len(d[1]) for d in docs) / num_docs if num_docs > 0 else 1.0

        # Calculate document frequency (df) for each query term
        df_map = {}
        for q in query_tokens:
            df_map[q] = sum(1 for _, toks in docs if q in set(toks))

        scored_docs = []
        for meta, toks in docs:
            score = compute_bm25_score(query_tokens, toks, avg_doc_len, num_docs, df_map)
            # Minimum BM25 cutoff to avoid irrelevant hits
            if score >= 0.5:
                scored_docs.append((score, meta))

        scored_docs.sort(key=lambda x: x[0], reverse=True)
        hits = []
        for score, meta in scored_docs[:k]:
            hits.append(SearchHit(
                id=meta["id"],
                title=meta["title"],
                heading=meta["heading"],
                content=meta["content"],
                source_title=meta["source_title"],
                source_url=meta["source_url"],
                evidence=meta["evidence"],
                score=round(score, 4),
                method="keyword"
            ))
        return hits

    def add_note(self, user_id: int, text: str) -> bool:
        """Stores a reflection note with its embedding if available."""
        init_db()
        db = get_db_session()
        try:
            vec = None
            if self.config.has_gemini_key:
                res = llm_client.embed([text], kind="document")
                if res.ok and res.vectors:
                    vec = res.vectors[0]

            note = ChatNote(
                user_id=user_id,
                text=text.strip(),
                embedding=vec,
                embedding_model=self.config.GEMINI_EMBED_MODEL if vec else None,
                created_at=datetime.now(timezone.utc)
            )
            db.add(note)
            db.commit()
            return True
        except Exception as exc:
            db.rollback()
            logger.error("Failed to add note for user %s: %s", user_id, exc)
            return False
        finally:
            db.close()

    def search_notes(self, user_id: int, query: str, k: int = 3) -> List[Dict[str, Any]]:
        """Searches ONLY the matching user's latest 300 notes."""
        init_db()
        db = get_db_session()
        try:
            notes = (
                db.query(ChatNote)
                .filter(ChatNote.user_id == user_id)
                .order_by(ChatNote.created_at.desc())
                .limit(300)
                .all()
            )

            if not notes:
                return []

            # Lazy backfill missing embeddings up to 20 per call
            if self.config.has_gemini_key:
                unembedded = [n for n in notes if n.embedding is None][:20]
                if unembedded:
                    emb_res = llm_client.embed([n.text for n in unembedded], kind="document")
                    if emb_res.ok and emb_res.vectors and len(emb_res.vectors) == len(unembedded):
                        for note_obj, vec in zip(unembedded, emb_res.vectors):
                            note_obj.embedding = vec
                            note_obj.embedding_model = self.config.GEMINI_EMBED_MODEL
                        db.commit()

            # Attempt vector search
            valid_vector_notes = [n for n in notes if n.embedding is not None]
            if self.config.has_gemini_key and valid_vector_notes:
                q_res = llm_client.embed([query], kind="query")
                if q_res.ok and q_res.vectors:
                    q_vec = np.array(q_res.vectors[0], dtype=np.float32)
                    matrix = np.array([n.embedding for n in valid_vector_notes], dtype=np.float32)
                    scores = np.dot(matrix, q_vec)
                    ranked = np.argsort(scores)[::-1]
                    hits = []
                    for idx in ranked[:k]:
                        score = float(scores[idx])
                        if score >= self.config.RAG_MIN_SIMILARITY:
                            target_note = valid_vector_notes[idx]
                            hits.append({
                                "text": target_note.text,
                                "created_at": target_note.created_at.isoformat() if target_note.created_at else "",
                                "score": round(score, 4),
                                "method": "vector"
                            })
                    if hits:
                        return hits

            # Fallback to BM25 keyword search
            query_tokens = tokenize(query)
            if not query_tokens:
                return []

            docs = [(n, tokenize(n.text)) for n in notes]
            num_docs = len(docs)
            avg_doc_len = sum(len(d[1]) for d in docs) / num_docs if num_docs > 0 else 1.0
            df_map = {q: sum(1 for _, toks in docs if q in set(toks)) for q in query_tokens}

            scored = []
            for n_obj, toks in docs:
                score = compute_bm25_score(query_tokens, toks, avg_doc_len, num_docs, df_map)
                if score >= 0.3:
                    scored.append((score, n_obj))

            # If no keyword matches and user asked generic 'what did I note last time', return the most recent note
            if not scored and any(w in query.lower() for w in ["last time", "last note", "recent note", "what did i note"]):
                scored.append((1.0, notes[0]))

            scored.sort(key=lambda x: x[0], reverse=True)
            results = []
            for score, n_obj in scored[:k]:
                results.append({
                    "text": n_obj.text,
                    "created_at": n_obj.created_at.isoformat() if n_obj.created_at else "",
                    "score": round(score, 4),
                    "method": "keyword"
                })
            return results
        finally:
            db.close()


rag_engine = RAGEngine()
