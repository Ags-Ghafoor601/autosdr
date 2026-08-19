"""RAG layer: PDF/text -> chunks -> embeddings in SQLite -> cited retrieval.

Falls back to TF-IDF cosine if embeddings are unavailable, so ingestion never
hard-blocks the pipeline. Retrieval returns (chunk_id, text, score) so every
downstream claim can cite its source chunk.
"""
import math
import re
from collections import Counter

import numpy as np
from pypdf import PdfReader

from . import bus, db, llm

CHUNK_CHARS = 1200
OVERLAP = 150


def _pdf_text(path: str) -> str:
    reader = PdfReader(path)
    return "\n\n".join((p.extract_text() or "") for p in reader.pages)


def _chunk(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    paras = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]
    chunks, cur = [], ""
    for p in paras:
        if len(cur) + len(p) + 2 <= CHUNK_CHARS:
            cur = f"{cur}\n\n{p}".strip()
        else:
            if cur:
                chunks.append(cur)
            while len(p) > CHUNK_CHARS:            # oversize paragraph
                chunks.append(p[:CHUNK_CHARS])
                p = p[CHUNK_CHARS - OVERLAP:]
            cur = p
    if cur:
        chunks.append(cur)
    return chunks


def ingest(source_name: str, text: str | None = None, pdf_path: str | None = None) -> int:
    if pdf_path:
        text = _pdf_text(pdf_path)
    if not text or len(text.strip()) < 80:
        raise ValueError(
            "No usable text found in the document. If this is a scanned/image PDF, "
            "run OCR first or paste the company description as text instead.")
    chunks = _chunk(text)
    bus.emit("knowledge", "tool_call", f"ingest '{source_name}': {len(text)} chars → {len(chunks)} chunks")
    with db.tx() as c:
        c.execute("DELETE FROM kb_chunks")
    embs = None
    try:
        embs = llm.embed(chunks)
        embs /= (np.linalg.norm(embs, axis=1, keepdims=True) + 1e-9)
    except Exception as e:  # noqa: BLE001
        bus.emit("knowledge", "retry", f"embeddings unavailable, TF-IDF fallback: {str(e)[:120]}")
    for i, ch in enumerate(chunks):
        db.insert("kb_chunks", {
            "id": f"c{i:03d}", "doc": source_name, "idx": i, "text": ch,
            "embedding": embs[i].tobytes() if embs is not None else None,
        })
    db.kv_set("kb_meta", {"doc": source_name, "chunks": len(chunks),
                          "mode": "embeddings" if embs is not None else "tfidf"})
    bus.emit("knowledge", "tool_result",
             f"knowledge base ready: {len(chunks)} chunks ({'embeddings' if embs is not None else 'TF-IDF'})")
    return len(chunks)


def _tokenize(t: str) -> list[str]:
    return re.findall(r"[a-z0-9]{2,}", t.lower())


def _tfidf_scores(query: str, docs: list[str]) -> np.ndarray:
    q = Counter(_tokenize(query))
    toks = [Counter(_tokenize(d)) for d in docs]
    n = len(docs)
    dfs = Counter()
    for tc in toks:
        dfs.update(tc.keys())
    scores = []
    for tc in toks:
        s = sum(
            (q[w] * tc[w]) * (math.log((n + 1) / (1 + dfs[w])) ** 2)
            for w in q if w in tc
        )
        scores.append(s / (1 + math.log(1 + sum(tc.values()))))
    return np.array(scores, dtype=np.float32)


def search(query: str, k: int = 6) -> list[dict]:
    rows = db.rows("SELECT id, idx, text, embedding FROM kb_chunks ORDER BY idx")
    if not rows:
        return []
    if rows[0]["embedding"] is not None:
        try:
            qv = llm.embed([query])[0]
            qv /= (np.linalg.norm(qv) + 1e-9)
            mat = np.stack([np.frombuffer(r["embedding"], dtype=np.float32) for r in rows])
            sims = mat @ qv
        except Exception:  # noqa: BLE001
            sims = _tfidf_scores(query, [r["text"] for r in rows])
    else:
        sims = _tfidf_scores(query, [r["text"] for r in rows])
    order = np.argsort(-sims)[:k]
    return [{"chunk_id": rows[i]["id"], "text": rows[i]["text"], "score": float(sims[i])}
            for i in order]


def context_block(query: str, k: int = 6) -> str:
    hits = search(query, k)
    return "\n\n".join(f"[{h['chunk_id']}] {h['text']}" for h in hits)
