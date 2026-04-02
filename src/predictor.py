"""
트럼프 행동 예측 엔진 (RAG + Claude API)

새로운 발언 → 유사 과거 사례 검색 → Claude API로 예측 생성

사용법:
  python predictor.py "We will impose 50% tariffs on all Chinese goods"
  python predictor.py "I'm going to close the border completely" --top-k 7
  python predictor.py "문장" --json   # JSON 구조화 출력
"""

import argparse
import io
import json
import os
import sys
from datetime import datetime

from dotenv import load_dotenv

# Windows 콘솔 UTF-8 출력 강제
if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from retriever import search

load_dotenv()

MODEL    = "claude-sonnet-4-6"
TOP_K    = 5       # 기본 유사 사례 수
MAX_DAYS = 180     # 이 범위 내 조치만 선례로 활용

SYSTEM_PROMPT = """You are an expert policy analyst specializing in predicting Trump administration actions.
You have access to a historical database of Trump's official statements and the actual policy actions that followed.

Your task: given a new Trump statement, analyze similar historical patterns and predict what concrete actions will likely follow.

Guidelines:
- Base predictions strictly on the historical precedents provided
- Distinguish between rhetorical statements (often unfulfilled) and policy-specific statements (usually followed by action)
- Consider the delay pattern: how many days it typically took from statement to action
- Be calibrated in your probability estimates — not everything Trump says becomes policy
- Output must follow the exact JSON structure requested"""

PREDICT_PROMPT = """## New Trump Statement
"{statement}"

## Historical Precedents (retrieved by semantic similarity)
{precedents}

## Prediction Task
Based on the historical patterns above, predict what concrete actions the Trump administration will likely take in response to or following this statement.

Respond with ONLY a valid JSON object in this exact structure:
{{
  "predicted_action": "Specific description of the most likely action (1-2 sentences in English)",
  "predicted_action_ko": "위 예측의 한국어 번역",
  "action_type": "executive_order | legislation | policy | sanction | speech | other",
  "fulfillment_probability": <integer 0-100>,
  "expected_delay_days": <integer, estimated days from statement to action, -1 if uncertain>,
  "confidence": "high | medium | low",
  "reasoning": "Brief explanation of why (2-3 sentences, referencing specific precedents)",
  "key_precedents": [
    {{"date": "YYYY-MM-DD", "statement": "...", "action": "...", "delay_days": <int>}}
  ],
  "caveats": "Important caveats or alternative scenarios (1-2 sentences)",
  "topics": ["topic1", "topic2"]
}}"""


def format_precedents(hits: list[dict]) -> str:
    """검색된 유사 사례를 프롬프트용 텍스트로 변환"""
    lines = []
    for i, h in enumerate(hits, 1):
        has_action = h["action_count"] > 0
        delay = h["avg_delay_days"]
        delay_str = f"{delay} days after statement" if delay >= 0 else "no linked action"
        fulfilled = "Action was taken" if h["is_fulfilled"] else "Action status unknown"

        lines.append(f"### Precedent #{i} (similarity: {h['similarity']:.2f})")
        lines.append(f"Date: {h['date']} | Context: {h['context']}")
        lines.append(f"Topics: {h['topics']}")
        # 본문 미리보기 (인코딩 안전하게)
        preview = h["document_preview"][:400]
        lines.append(f"Statement/Document: {preview}")
        if has_action:
            lines.append(f"Subsequent Action: {h['action_summary'][:300]}")
            lines.append(f"Outcome: {fulfilled} ({delay_str})")
        else:
            lines.append("Subsequent Action: No linked action in database")
        lines.append("")

    return "\n".join(lines)


def predict(statement: str, top_k: int = TOP_K) -> dict:
    """
    메인 예측 함수

    Returns:
        dict with keys: predicted_action, fulfillment_probability,
                        expected_delay_days, reasoning, key_precedents, ...
    """
    import anthropic

    # Step 1: 유사 사례 검색
    hits = search(statement, top_k=top_k)

    # Step 2: 프롬프트 구성
    precedents_text = format_precedents(hits)
    user_prompt = PREDICT_PROMPT.format(
        statement=statement,
        precedents=precedents_text,
    )

    # Step 3: Claude API 호출
    client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))
    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt}],
    )

    raw = response.content[0].text.strip()

    # Step 4: JSON 파싱
    # 마크다운 코드블록 제거
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    result = json.loads(raw)

    # 메타 정보 추가
    result["input_statement"] = statement
    result["retrieved_precedents_count"] = len(hits)
    result["top_similarity"] = hits[0]["similarity"] if hits else 0.0
    result["generated_at"] = datetime.now().isoformat()

    return result


def print_prediction(result: dict):
    """예측 결과를 사람이 읽기 좋게 출력"""

    def safe(s, n=200):
        if not isinstance(s, str):
            return str(s)
        return s[:n].encode("utf-8", errors="replace").decode("utf-8")

    prob  = result.get("fulfillment_probability", "?")
    delay = result.get("expected_delay_days", -1)
    conf  = result.get("confidence", "?")

    delay_str = f"약 {delay}일 후" if isinstance(delay, int) and delay >= 0 else "시기 불확실"
    conf_icon = {"high": "●●●", "medium": "●●○", "low": "●○○"}.get(conf, "?")

    print("\n" + "="*60)
    print("  트럼프 행동 예측 결과")
    print("="*60)
    print(f"\n[입력 발언]\n  {safe(result.get('input_statement',''), 200)}\n")

    print(f"[예측 조치]")
    print(f"  {safe(result.get('predicted_action_ko', result.get('predicted_action','')), 200)}")
    print(f"  ({safe(result.get('predicted_action',''), 200)})\n")

    print(f"[핵심 지표]")
    print(f"  이행 가능성  : {prob}%")
    print(f"  예상 시기    : {delay_str}")
    print(f"  조치 유형    : {result.get('action_type','?')}")
    print(f"  신뢰도       : {conf_icon} ({conf})\n")

    print(f"[근거]")
    print(f"  {safe(result.get('reasoning',''), 400)}\n")

    precedents = result.get("key_precedents", [])
    if precedents:
        print(f"[주요 선례]")
        for p in precedents[:3]:
            d  = p.get("delay_days", "?")
            dd = f"+{d}일" if isinstance(d, int) and d >= 0 else ""
            print(f"  • {p.get('date','')} {dd}")
            print(f"    발언: {safe(p.get('statement',''), 80)}")
            print(f"    조치: {safe(p.get('action',''), 80)}")

    print(f"\n[주의사항]")
    print(f"  {safe(result.get('caveats',''), 300)}")
    print(f"\n  (유사도 Top-1: {result.get('top_similarity',0):.3f} | "
          f"참조 선례: {result.get('retrieved_precedents_count',0)}건)")
    print("="*60)


def dry_run(statement: str, top_k: int = TOP_K):
    """API 호출 없이 RAG 검색 결과와 생성될 프롬프트만 출력"""
    hits = search(statement, top_k=top_k)
    precedents_text = format_precedents(hits)

    def safe(s, n=120):
        return s[:n].encode("utf-8", errors="replace").decode("utf-8") if s else ""

    print(f"\n[Dry-run] 발언: {safe(statement, 100)}")
    print(f"\n--- 검색된 유사 선례 {len(hits)}건 ---")
    for h in hits:
        print(f"  #{h['rank']} sim={h['similarity']:.3f} | {h['date']} | actions={h['action_count']}")
        print(f"       {safe(h['document_preview'])}")
        if h["action_count"] > 0:
            print(f"       → {safe(h['action_summary'])} (+{h['avg_delay_days']}일)")
    print(f"\n--- Claude에게 보낼 프롬프트 ({len(PREDICT_PROMPT.format(statement=statement, precedents=precedents_text))}자) ---")
    print(PREDICT_PROMPT.format(statement=statement, precedents=precedents_text)[:800].encode("utf-8","replace").decode("utf-8"))
    print("...(이하 생략)")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="트럼프 행동 예측기")
    parser.add_argument("statement", help="예측할 트럼프 발언 (영문 또는 한글)")
    parser.add_argument("--top-k", type=int, default=TOP_K, help="참조 선례 수")
    parser.add_argument("--json", action="store_true", help="JSON으로 출력")
    parser.add_argument("--dry-run", action="store_true", help="API 호출 없이 RAG 결과만 확인")
    args = parser.parse_args()

    if args.dry_run:
        dry_run(args.statement, top_k=args.top_k)
        sys.exit(0)

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("오류: ANTHROPIC_API_KEY 환경변수가 설정되지 않았습니다.")
        print("  방법 1) .env 파일에 ANTHROPIC_API_KEY=sk-ant-... 추가")
        print("  방법 2) 터미널에서: set ANTHROPIC_API_KEY=sk-ant-...")
        print("\n  API 키 없이 RAG 결과만 보려면: python predictor.py \"...\" --dry-run")
        sys.exit(1)

    result = predict(args.statement, top_k=args.top_k)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_prediction(result)
