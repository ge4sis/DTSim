"""
발언-조치 데이터를 ChromaDB에 임베딩 저장

ChromaDB 컬렉션: trump_statements
  document  : 발언 제목 + 본문 (검색용 텍스트)
  metadata  : date, context, topics, action_count, action_summary,
              avg_delay_days, is_fulfilled
  id        : Statement.id

사용법:
  python embedder.py                         # 기본 데이터셋 사용
  python embedder.py --input <path.json>     # 파일 지정
  python embedder.py --reset                 # DB 초기화 후 재구축
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import load_statements

CHROMA_PATH  = "data/chroma_db"
COLLECTION   = "trump_statements"
DEFAULT_DATA = "data/raw/briefings_2025-01-20_enriched_linked.json"
EMBED_MODEL  = "all-MiniLM-L6-v2"


def build_document(stmt) -> str:
    """ChromaDB에 저장할 텍스트 (검색 대상)"""
    parts = [stmt.statement]  # 제목
    if stmt.notes and len(stmt.notes) > 50:
        # 본문 앞부분 (헤더 메타 정보 제거를 위해 100자 이후부터)
        body = stmt.notes[100:2500] if len(stmt.notes) > 100 else stmt.notes
        parts.append(body)
    return "\n\n".join(parts)


def build_metadata(stmt) -> dict:
    """ChromaDB metadata (필터링/표시용)"""
    actions = stmt.actions
    delays  = [a.delay_days for a in actions if a.delay_days is not None]
    action_summary = " | ".join(a.action[:120] for a in actions[:3])

    return {
        "date":          stmt.date,
        "context":       stmt.context,
        "topics":        ", ".join(stmt.topics),
        "source_url":    stmt.source_url,
        "action_count":  len(actions),
        "action_summary": action_summary[:500],
        "avg_delay_days": int(sum(delays) / len(delays)) if delays else -1,
        "is_fulfilled":  1 if stmt.is_fulfilled else 0,
        "is_threat":     1 if stmt.is_threat else 0,
    }


def run(args):
    import chromadb
    from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction

    # 데이터 로드
    input_path = args.input or DEFAULT_DATA
    print(f"데이터 로드: {input_path}")
    statements = load_statements(input_path)
    print(f"  → {len(statements)}건")

    # ChromaDB 클라이언트
    os.makedirs(CHROMA_PATH, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_PATH)

    if args.reset:
        try:
            client.delete_collection(COLLECTION)
            print(f"기존 컬렉션 삭제: {COLLECTION}")
        except Exception:
            pass

    ef = SentenceTransformerEmbeddingFunction(model_name=EMBED_MODEL)
    collection = client.get_or_create_collection(
        name=COLLECTION,
        embedding_function=ef,
        metadata={"hnsw:space": "cosine"},
    )

    existing_ids = set(collection.get()["ids"])
    print(f"기존 임베딩: {len(existing_ids)}건")

    # 신규 항목만 추가
    new_stmts = [s for s in statements if s.id not in existing_ids]
    print(f"추가 대상: {len(new_stmts)}건")

    if not new_stmts:
        print("추가할 항목 없음. 완료.")
        return

    BATCH = 64
    total = 0
    for i in range(0, len(new_stmts), BATCH):
        batch = new_stmts[i:i + BATCH]
        collection.add(
            ids       = [s.id for s in batch],
            documents = [build_document(s) for s in batch],
            metadatas = [build_metadata(s) for s in batch],
        )
        total += len(batch)
        print(f"  임베딩 진행: {total}/{len(new_stmts)}건", end="\r")

    print(f"\n완료: 총 {collection.count()}건 저장됨")
    print(f"DB 경로: {CHROMA_PATH}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    run(args)
