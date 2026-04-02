"""
트럼프 트위터/X 게시물 수집기
출처: Trump Twitter Archive (thetrumparchive.com)

사용법:
  # API로 특정 기간 수집
  python collector_tweets.py --start 2025-01-01 --end 2025-12-31

  # 이미 다운로드한 CSV 파싱
  python collector_tweets.py --csv data/raw/trump_tweets.csv
"""

import argparse
import json
import time
import csv
import os
import sys
from datetime import datetime, date
from typing import List, Optional

import requests
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import Statement, save_statements, TOPICS

# Trump Twitter Archive API
ARCHIVE_API = "https://thetrumparchive.com/api/tweets"

# 토픽 자동 분류 키워드 맵
TOPIC_KEYWORDS = {
    "무역/관세": ["tariff", "trade", "import", "export", "wto", "nafta", "usmca", "china trade", "duty"],
    "이민/국경": ["immigration", "border", "wall", "deportation", "illegal", "migrant", "asylum", "daca"],
    "외교/동맹": ["nato", "allies", "diplomacy", "sanctions", "un ", "united nations", "russia", "china", "korea", "japan", "europe"],
    "안보/군사": ["military", "army", "navy", "nuclear", "weapon", "defense", "war", "troops", "isis", "terror"],
    "경제/세금": ["economy", "tax", "cut", "gdp", "jobs", "unemployment", "inflation", "rate", "fed ", "budget", "deficit"],
    "에너지": ["oil", "gas", "energy", "pipeline", "coal", "solar", "green", "climate", "paris accord", "drill"],
    "규제완화": ["regulation", "deregulation", "epa", "fda", "bureaucracy", "red tape"],
    "사법/법무": ["court", "judge", "law", "crime", "fbi", "doj", "justice", "prison", "police"],
    "선거/정치": ["election", "vote", "democrat", "republican", "congress", "senate", "house", "poll", "fake news"],
    "미디어": ["media", "press", "cnn", "nyt", "fake news", "journalist", "reporter"],
    "보건": ["health", "covid", "vaccine", "obamacare", "medicare", "drug", "fentanyl"],
}


def classify_topics(text: str) -> List[str]:
    """발언 텍스트를 토픽으로 자동 분류"""
    text_lower = text.lower()
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            found.append(topic)
    return found if found else ["기타"]


def fetch_from_api(start_date: str, end_date: str, search_terms: str = "") -> List[dict]:
    """
    Trump Twitter Archive API로 트윗 수집
    API 파라미터: searchTerms, dates (JSON 배열 문자열)
    """
    params = {
        "searchTerms": search_terms,
        "dates": json.dumps([start_date, end_date]),
    }
    print(f"API 요청 중: {start_date} ~ {end_date}")
    try:
        resp = requests.get(ARCHIVE_API, params=params, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        # 응답 형식에 따라 tweets 키 또는 배열 직접 반환
        if isinstance(data, list):
            return data
        return data.get("results", data.get("tweets", []))
    except requests.RequestException as e:
        print(f"API 오류: {e}")
        print("→ CSV 파일을 직접 다운로드하세요: https://www.thetrumparchive.com/")
        return []


def parse_csv(csv_path: str) -> List[dict]:
    """다운로드한 CSV 파일 파싱 (Trump Twitter Archive CSV 포맷)"""
    tweets = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            tweets.append(row)
    print(f"CSV 로드: {len(tweets)}건")
    return tweets


def normalize_tweet(raw: dict, idx: int) -> Optional[Statement]:
    """원시 트윗 데이터를 Statement 스키마로 변환"""
    # Trump Twitter Archive의 컬럼: id, text, date, isRetweet, device
    text = raw.get("text", raw.get("Text", "")).strip()
    if not text:
        return None

    # 리트윗 제외
    is_retweet = str(raw.get("isRetweet", raw.get("IsRetweet", "f"))).lower()
    if is_retweet in ("t", "true", "1", "yes"):
        return None

    raw_date = raw.get("date", raw.get("Date", ""))
    try:
        # 다양한 날짜 형식 처리
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(raw_date[:19], fmt[:len(raw_date[:19])])
                date_str = dt.strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        else:
            date_str = raw_date[:10]
    except Exception:
        date_str = raw_date[:10] if raw_date else "unknown"

    tweet_id = raw.get("id", raw.get("Id", f"tweet_{idx}"))
    stmt_id = f"{date_str.replace('-', '')}_{str(tweet_id)[-6:]}"

    return Statement(
        id=stmt_id,
        date=date_str,
        statement=text,
        statement_ko="",  # 번역은 별도 작업
        context="tweet",
        source="Twitter/X @realDonaldTrump",
        source_url=f"https://twitter.com/realDonaldTrump/status/{tweet_id}",
        topics=classify_topics(text),
        actions=[],
        is_threat="will" in text.lower() and any(
            w in text.lower() for w in ["impose", "ban", "stop", "end", "fire", "sanction"]
        ),
    )


def run(args):
    raw_tweets = []

    if args.csv:
        raw_tweets = parse_csv(args.csv)
    else:
        raw_tweets = fetch_from_api(args.start, args.end, args.search or "")

    if not raw_tweets:
        print("수집된 트윗이 없습니다.")
        return

    statements = []
    for i, raw in enumerate(tqdm(raw_tweets, desc="변환 중")):
        stmt = normalize_tweet(raw, i)
        if stmt:
            statements.append(stmt)

    # 날짜 필터링
    if args.start or args.end:
        filtered = []
        for s in statements:
            if args.start and s.date < args.start:
                continue
            if args.end and s.date > args.end:
                continue
            filtered.append(s)
        statements = filtered

    # 토픽 필터링
    if args.topic:
        statements = [s for s in statements if args.topic in s.topics]

    print(f"\n수집 결과: {len(statements)}건")

    # 토픽 분포 출력
    topic_counts = {}
    for s in statements:
        for t in s.topics:
            topic_counts[t] = topic_counts.get(t, 0) + 1
    print("\n[토픽 분포]")
    for topic, count in sorted(topic_counts.items(), key=lambda x: -x[1]):
        print(f"  {topic}: {count}건")

    out_path = os.path.join("data", "raw", f"tweets_{args.start or 'all'}_{args.end or 'all'}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    save_statements(statements, out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="트럼프 트윗 수집기")
    parser.add_argument("--csv", help="로컬 CSV 파일 경로")
    parser.add_argument("--start", default="2025-01-01", help="시작일 (YYYY-MM-DD)")
    parser.add_argument("--end", default=date.today().isoformat(), help="종료일 (YYYY-MM-DD)")
    parser.add_argument("--search", default="", help="검색 키워드 (선택)")
    parser.add_argument("--topic", default="", help="토픽 필터 (선택)")
    args = parser.parse_args()
    run(args)
