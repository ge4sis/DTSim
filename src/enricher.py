"""
기존 briefings JSON에 전체 본문 텍스트를 추가하는 스크립트.

- 각 브리핑 URL을 요청해 div.entry-content 내용 추출
- Statement.notes 에 전체 텍스트(최대 4000자) 저장
- Statement.statement 에는 제목 유지, 실제 본문은 notes 로 활용
- 링커에서 notes까지 포함해 매칭 → 품질 향상

사용법:
  python enricher.py --input data/raw/briefings_2025-01-20.json
"""

import argparse
import json
import os
import sys
import time

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import classify_topics

HEADERS = {"User-Agent": "Mozilla/5.0 (research; dtsim)"}
DELAY   = 0.6   # 요청 간격 (초)
MAX_TEXT = 4000  # 저장할 최대 텍스트 길이


def scrape_text(url: str) -> str:
    """백악관 브리핑 페이지에서 본문 추출"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")

        # 백악관 본문 셀렉터 (우선순위 순)
        body = soup.select_one(
            "div.entry-content, "
            "div.wp-block-post-content, "
            "div.body-content, "
            "article.wp-block-post"
        )
        if not body:
            return ""

        # 불필요한 내부 요소 제거
        for tag in body.select("figure, .wp-block-button, nav, .screen-reader-text"):
            tag.decompose()

        text = body.get_text(separator="\n", strip=True)
        # 헤더 메타 정보(날짜, 카테고리 등)는 처음에 나오므로 2줄 이후부터 사용
        lines = [l for l in text.split("\n") if len(l.strip()) > 20]
        return "\n".join(lines)[:MAX_TEXT]

    except Exception:
        return ""


def run(args):
    with open(args.input, encoding="utf-8") as f:
        data = json.load(f)

    out_path = args.input.replace(".json", "_enriched.json")

    # 이미 enriched 파일이 있으면 이어서 작업
    if os.path.exists(out_path) and not args.force:
        with open(out_path, encoding="utf-8") as f:
            enriched = json.load(f)
        done_ids = {s["id"] for s in enriched if s.get("_enriched")}
        print(f"기존 enriched 파일 로드: {len(enriched)}건 (완료: {len(done_ids)}건)")
        # 미완료 항목만 대상으로
        remaining = [s for s in enriched if not s.get("_enriched")]
    else:
        enriched = [s.copy() for s in data]
        done_ids = set()
        remaining = enriched

    print(f"스크래핑 대상: {len(remaining)}건 / 전체 {len(enriched)}건")
    print(f"예상 시간: 약 {len(remaining) * DELAY / 60:.1f}분\n")

    changed = 0
    for stmt in tqdm(remaining, desc="본문 스크래핑"):
        url = stmt.get("source_url", "")
        if not url:
            stmt["_enriched"] = True
            continue

        text = scrape_text(url)
        if text:
            stmt["notes"] = text
            # 전체 텍스트로 토픽 재분류 (제목보다 정확)
            combined = stmt.get("statement", "") + " " + text
            stmt["topics"] = classify_topics(combined)
            changed += 1
        stmt["_enriched"] = True

        time.sleep(DELAY)

    # 저장
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(enriched, f, ensure_ascii=False, indent=2)

    print(f"\n스크래핑 완료: {changed}건 업데이트")
    print(f"저장: {out_path}")

    # 토픽 재분류 결과
    topic_counts = {}
    for s in enriched:
        for t in s.get("topics", []):
            topic_counts[t] = topic_counts.get(t, 0) + 1
    print("\n[재분류 후 토픽 분포]")
    for t, c in sorted(topic_counts.items(), key=lambda x: -x[1]):
        bar = "#" * (c // 4)
        print(f"  {t:<12} {c:>3}건  {bar}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="data/raw/briefings_2025-01-20.json")
    parser.add_argument("--force", action="store_true", help="이미 완료된 항목도 재스크래핑")
    args = parser.parse_args()
    run(args)
