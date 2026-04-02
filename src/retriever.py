"""
ChromaDB에서 유사 발언-조치 사례 검색

사용법:
  python retriever.py "We will impose tariffs on all imports from China"
  python retriever.py "Border security is a disaster" --top-k 5
"""

import argparse
import json
import os
import sys

CHROMA_PATH = "data/chroma_db"
COLLECTION  = "trump_statements"
EMBED_MODEL = "all-MiniLM-L6-v2"


def get_collection():
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    return client.get_collection(name=COLLECTION, embedding_function=ef)


def search(query: str, top_k: int = 5, topic_filter: str = "") -> list[dict]:
    """
    query와 유사한 과거 발언-조치 사례 반환

    반환값 각 항목:
      id, score, date, statement(제목), context, topics,
      action_count, action_summary, avg_delay_days
    """
    collection = get_collection()

    where = {}
    if topic_filter:
        where = {"topics": {"$contains": topic_filter}}

    results = collection.query(
        query_texts=[query],
        n_results=min(top_k, collection.count()),
        where=where if where else None,
        include=["documents", "metadatas", "distances"],
    )

    hits = []
    for i, (doc_id, doc, meta, dist) in enumerate(zip(
        results["ids"][0],
        results["documents"][0],
        results["metadatas"][0],
        results["distances"][0],
    )):
        similarity = round(1 - dist, 4)  # cosine distance → similarity
        hits.append({
            "rank":          i + 1,
            "id":            doc_id,
            "similarity":    similarity,
            "date":          meta.get("date", ""),
            "context":       meta.get("context", ""),
            "topics":        meta.get("topics", ""),
            "action_count":  meta.get("action_count", 0),
            "action_summary": meta.get("action_summary", ""),
            "avg_delay_days": meta.get("avg_delay_days", -1),
            "is_fulfilled":  meta.get("is_fulfilled", 0),
            "source_url":    meta.get("source_url", ""),
            "document_preview": doc[:300],
        })
    return hits


def _safe(text: str, limit: int = 120) -> str:
    return text[:limit].encode("utf-8", errors="replace").decode("utf-8")


def print_results(query: str, hits: list[dict]):
    print(f"\n[검색 쿼리] {query}")
    print(f"[유사 사례 {len(hits)}건]\n")
    for h in hits:
        fulfilled = "이행됨" if h["is_fulfilled"] else "미확인"
        delay = f"+{h['avg_delay_days']}일" if h["avg_delay_days"] >= 0 else "미연결"
        print(f"  #{h['rank']} 유사도={h['similarity']:.3f} | {h['date']} | {h['context']}")
        print(f"  토픽: {_safe(h['topics'])}")
        print(f"  발언: {_safe(h['document_preview'])}")
        if h["action_count"] > 0:
            print(f"  조치: {_safe(h['action_summary'])}")
            print(f"  이행: {fulfilled} ({delay})")
        else:
            print(f"  조치: (연결 없음)")
        print(f"  URL: {h['source_url'][:70]}")
        print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("query", help="검색할 발언 텍스트")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--topic", default="", help="토픽 필터 (예: 무역/관세)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")
    args = parser.parse_args()

    hits = search(args.query, top_k=args.top_k, topic_filter=args.topic)

    if args.json:
        print(json.dumps(hits, ensure_ascii=False, indent=2))
    else:
        print_results(args.query, hits)
