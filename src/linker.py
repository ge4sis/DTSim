"""
발언-조치 연결기 (Semi-automated Linker)
수집된 발언(Statement)과 조치(Action)를 키워드 유사도로 자동 매칭 후
사람이 검토/확정할 수 있는 CSV를 출력합니다.

사용법:
  python linker.py \
    --statements data/raw/tweets_2025-01-01_2025-12-31.json \
    --actions data/actions/actions_2025-01-20.json \
    --output data/processed/linked_candidates.csv
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime, timedelta
from typing import List, Tuple

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import Statement, Action, load_statements, save_statements

# 매칭 키워드 (발언 토픽 → 조치 텍스트 검색어)
TOPIC_MATCH_KEYWORDS = {
    "무역/관세": ["tariff", "trade", "duty", "import", "export", "관세"],
    "이민/국경": ["immigration", "border", "deportation", "migrant", "이민", "국경"],
    "외교/동맹": ["sanction", "diplomatic", "nato", "alliance", "외교"],
    "안보/군사": ["military", "defense", "troops", "armed", "군사"],
    "경제/세금": ["tax", "economy", "budget", "gdp", "세금", "경제"],
    "에너지": ["energy", "oil", "gas", "pipeline", "drill", "에너지"],
    "규제완화": ["regulation", "deregulation", "rule", "규제"],
    "사법/법무": ["court", "judge", "law", "crime", "fbi", "사법"],
    "선거/정치": ["election", "vote", "congress", "선거"],
    "보건": ["health", "vaccine", "drug", "의료"],
}

# 발언 후 최대 탐색 일수 (이 범위 내 조치만 후보로)
MAX_DAYS_AFTER = 180


def load_actions(path: str) -> List[dict]:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def text_similarity_score(stmt_text: str, action_text: str, topics: List[str]) -> float:
    """
    단순 키워드 기반 유사도 점수 (0.0 ~ 1.0)
    토픽 키워드가 조치 텍스트에 얼마나 등장하는지 계산
    """
    stmt_lower = stmt_text.lower()
    action_lower = action_text.lower()
    score = 0.0

    # 토픽별 키워드 매칭
    for topic in topics:
        keywords = TOPIC_MATCH_KEYWORDS.get(topic, [])
        hits = sum(1 for kw in keywords if kw in action_lower)
        score += hits * 0.3

    # 발언의 핵심 단어가 조치에 등장하는지
    stmt_words = set(w for w in stmt_lower.split() if len(w) > 4)
    action_words = set(action_lower.split())
    common = stmt_words & action_words
    score += len(common) * 0.1

    return min(score, 1.0)


def find_action_candidates(
    stmt: Statement,
    actions: List[dict],
    min_score: float = 0.2,
    max_candidates: int = 5,
) -> List[Tuple[float, dict]]:
    """발언에 매칭될 수 있는 조치 후보 목록 반환"""
    stmt_dt = datetime.strptime(stmt.date, "%Y-%m-%d")
    candidates = []

    for action in actions:
        action_date = action.get("date", "")
        if not action_date:
            continue
        try:
            action_dt = datetime.strptime(action_date[:10], "%Y-%m-%d")
        except ValueError:
            continue

        # 발언 이후 MAX_DAYS_AFTER 이내 조치만 후보
        days_diff = (action_dt - stmt_dt).days
        if not (0 <= days_diff <= MAX_DAYS_AFTER):
            continue

        action_text = action.get("action", "") + " " + action.get("summary", "")
        # 발언 제목 + 본문(notes) 모두 활용
        stmt_text = stmt.statement + " " + stmt.notes
        score = text_similarity_score(stmt_text, action_text, stmt.topics)
        if score >= min_score:
            candidates.append((score, action, days_diff))

    candidates.sort(key=lambda x: -x[0])
    return candidates[:max_candidates]


def run(args):
    print(f"발언 로드: {args.statements}")
    statements = load_statements(args.statements)
    print(f"  → {len(statements)}건")

    print(f"조치 로드: {args.actions}")
    actions = load_actions(args.actions)
    print(f"  → {len(actions)}건")

    # 이미 조치가 연결된 발언은 건너뜀
    unlinked = [s for s in statements if not s.actions]
    print(f"\n미연결 발언: {len(unlinked)}건 → 후보 매칭 중...")

    rows = []
    for stmt in unlinked:
        candidates = find_action_candidates(stmt, actions, min_score=args.min_score)
        if not candidates:
            continue
        for score, action, days_diff in candidates:
            rows.append({
                "stmt_id": stmt.id,
                "stmt_date": stmt.date,
                "statement": stmt.statement[:200],
                "topics": ", ".join(stmt.topics),
                "action_date": action.get("date", ""),
                "action": action.get("action", "")[:200],
                "action_type": action.get("action_type", ""),
                "source": action.get("source", ""),
                "source_url": action.get("source_url", ""),
                "days_diff": days_diff,
                "score": round(score, 3),
                # 검토자가 채울 열
                "confirmed": "",      # Y/N
                "fulfilled": "",      # Y/N/P (P=부분이행)
                "notes": "",
            })

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys() if rows else [])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\n매칭 후보: {len(rows)}건")
    print(f"CSV 저장: {args.output}")
    print("\n[다음 단계]")
    print("  1. CSV 파일을 Excel/Sheets로 열기")
    print("  2. 'confirmed' 열에 Y/N 입력")
    print("  3. 'fulfilled' 열에 Y/N/P(부분이행) 입력")
    print("  4. python linker.py --import-confirmed 으로 최종 데이터셋 생성")


def import_confirmed(args):
    """검토 완료된 CSV를 Statement 데이터셋에 병합"""
    statements = load_statements(args.statements)
    stmt_map = {s.id: s for s in statements}

    with open(args.import_confirmed, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    merged = 0
    for row in rows:
        if row.get("confirmed", "").strip().upper() != "Y":
            continue
        stmt_id = row.get("stmt_id", "")
        stmt = stmt_map.get(stmt_id)
        if not stmt:
            continue

        fulfilled_raw = row.get("fulfilled", "").strip().upper()
        fulfilled = fulfilled_raw == "Y"

        try:
            days = int(row.get("days_diff", 0))
        except ValueError:
            days = None

        action = Action(
            date=row.get("action_date", ""),
            action=row.get("action", ""),
            action_type=row.get("action_type", "other"),
            source=row.get("source", ""),
            source_url=row.get("source_url", ""),
            fulfilled=fulfilled,
            delay_days=days,
            notes=row.get("notes", ""),
        )
        stmt.actions.append(action)
        stmt.is_fulfilled = fulfilled if fulfilled_raw in ("Y", "N") else None
        merged += 1

    out_path = args.statements.replace(".json", "_linked.json")
    save_statements(statements, out_path)
    print(f"병합 완료: {merged}건 연결 → {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="발언-조치 연결기")
    parser.add_argument("--statements", required=True, help="발언 JSON 파일")
    parser.add_argument("--actions", help="조치 JSON 파일")
    parser.add_argument("--output", default="data/processed/linked_candidates.csv")
    parser.add_argument("--min-score", type=float, default=0.2, help="최소 매칭 점수")
    parser.add_argument("--import-confirmed", help="검토 완료된 CSV 파일 경로 (병합 모드)")
    args = parser.parse_args()

    if args.import_confirmed:
        import_confirmed(args)
    else:
        run(args)
