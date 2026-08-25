"""ES 색인·검색 — io 큐 소속(자격증명 없음). 임베딩은 bge-m3 로컬(실측 채택 모델)."""
import threading

from elasticsearch import Elasticsearch
from temporalio import activity

from jobscouter.config import ES_URL, Target

EMBED_MODEL = "BAAI/bge-m3"   # 2026-07 실측 매트릭스에서 채택 — 1024d cosine
_model = None
_lock = threading.Lock()
INDICES = ("jobscout_facts", "jobscout_precedents", "jobscout_reputation")
MAPPING = {"properties": {
    "content": {"type": "text"},
    "company": {"type": "keyword"},
    "kind": {"type": "keyword"},   # fact | listed | skipped | reputation
    "embedding": {"type": "dense_vector", "dims": 1024,
                  "index": True, "similarity": "cosine"},
}}


def es() -> Elasticsearch:
    return Elasticsearch(ES_URL, request_timeout=30)


def embed(texts: list[str]) -> list[list[float]]:
    global _model
    with _lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(EMBED_MODEL)
    return [v.tolist() for v in _model.encode(texts, show_progress_bar=False)]


def hybrid(index: str, query: str, k: int = 20,
           company: str | None = None) -> list[dict]:
    """BM25·kNN 각각 → RRF(1/(60+rank)) 융합 — 클라이언트 측, 리랭커 없음."""
    client = es()
    filt = [{"term": {"company": company}}] if company else []
    bm25 = client.search(index=index, size=k, query={
        "bool": {"must": {"match": {"content": query}}, "filter": filt}})
    knn = client.search(index=index, size=k, knn={
        "field": "embedding", "query_vector": embed([query])[0],
        "k": k, "num_candidates": k * 5, "filter": filt})
    scores: dict[str, float] = {}
    docs: dict[str, dict] = {}
    for res in (bm25, knn):
        for rank, h in enumerate(res["hits"]["hits"]):
            scores[h["_id"]] = scores.get(h["_id"], 0) + 1 / (60 + rank)
            docs[h["_id"]] = {k2: v for k2, v in h["_source"].items()
                              if k2 != "embedding"}
    top = sorted(scores, key=scores.get, reverse=True)[:k]
    return [docs[i] for i in top]


def search_context_text(t: Target, requirements: str) -> str:
    """판례·평판·사실 발췌를 judge 입력용 한 블록으로. 총 ~2500자 캡."""
    q = f"{t.company} {t.title} {requirements[:200]}"
    parts = []
    prec = hybrid("jobscout_precedents", q, k=8)
    if prec:
        parts.append("[판정 판례]\n" + "\n".join(d["content"][:200] for d in prec))
    rep = hybrid("jobscout_reputation", t.company, k=3, company=None)
    rep = [d for d in rep if d["company"] and d["company"] in t.company] or rep[:1]
    if rep:
        parts.append("[기업평판 캐시]\n" + "\n".join(d["content"][:250] for d in rep))
    facts = hybrid("jobscout_facts", requirements[:300], k=6)
    if facts:
        parts.append("[사실베이스 관련 절]\n" + "\n".join(d["content"][:200] for d in facts))
    return "\n\n".join(parts)[:2500]


@activity.defn
def search_context(t: Target, requirements: str) -> str:
    return search_context_text(t, requirements)
