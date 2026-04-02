"""
트럼프 실제 조치 수집기
출처: 백악관 공식 사이트, Federal Register, Reuters/AP RSS 피드

수집 대상:
  1. 행정명령 (Executive Orders) - Federal Register
  2. 백악관 공식 성명/보도자료
  3. 주요 언론 뉴스 (Reuters, AP, Politico RSS)

사용법:
  python collector_actions.py --start 2025-01-20
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, date
from typing import List, Dict, Optional
from urllib.parse import urljoin

import requests
import feedparser
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import Action

HEADERS = {
    "User-Agent": "Mozilla/5.0 (research bot; contact: research@example.com)"
}

# RSS 피드 목록 (트럼프 관련 주요 소스)
RSS_FEEDS = {
    "Reuters Politics": "https://feeds.reuters.com/Reuters/PoliticsNews",
    "Reuters US": "https://feeds.reuters.com/reuters/USNewsHeadlines",
    "AP Politics": "https://rsshub.app/apnews/politics",
    "Politico": "https://www.politico.com/rss/politics08.xml",
    "The Hill": "https://thehill.com/news/administration/feed/",
    "Federal Register EO": "https://www.federalregister.gov/api/v1/documents.rss?conditions%5Btype%5D%5B%5D=PRESDOCU&conditions%5Bpresidential_document_type%5D%5B%5D=executive_order",
}

# 백악관 공식 사이트
WHITEHOUSE_ACTIONS_URL = "https://www.whitehouse.gov/presidential-actions/"
WHITEHOUSE_BRIEFINGS_URL = "https://www.whitehouse.gov/briefings-statements/"

# Federal Register Executive Orders API
FEDERAL_REGISTER_API = "https://www.federalregister.gov/api/v1/documents.json"

# 행동 분류 키워드
ACTION_TYPE_KEYWORDS = {
    "executive_order": ["executive order", "signed", "e.o.", "presidential memorandum", "proclamation"],
    "legislation": ["signed into law", "bill signed", "congress passed", "legislation"],
    "speech": ["speech", "address", "remarks", "statement"],
    "policy": ["policy", "announced", "administration", "regulation", "rule"],
    "sanction": ["sanction", "tariff imposed", "ban", "restricted"],
}

# 트럼프 관련 필터 키워드
TRUMP_KEYWORDS = [
    "trump", "white house", "president", "administration",
    "executive order", "tariff", "immigration", "border"
]


def classify_action_type(text: str) -> str:
    text_lower = text.lower()
    for action_type, keywords in ACTION_TYPE_KEYWORDS.items():
        if any(kw in text_lower for kw in keywords):
            return action_type
    return "other"


def is_trump_related(title: str, summary: str) -> bool:
    combined = (title + " " + summary).lower()
    return any(kw in combined for kw in TRUMP_KEYWORDS)


def fetch_rss_actions(start_date: str) -> List[dict]:
    """RSS 피드에서 트럼프 관련 뉴스/조치 수집"""
    actions = []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")

    for source_name, feed_url in RSS_FEEDS.items():
        print(f"  RSS 수집: {source_name}")
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries:
                # 날짜 파싱
                published = entry.get("published_parsed") or entry.get("updated_parsed")
                if published:
                    pub_dt = datetime(*published[:6])
                    if pub_dt < start_dt:
                        continue
                    date_str = pub_dt.strftime("%Y-%m-%d")
                else:
                    date_str = date.today().isoformat()

                title = entry.get("title", "")
                summary = entry.get("summary", entry.get("description", ""))
                link = entry.get("link", "")

                if not is_trump_related(title, summary):
                    continue

                actions.append({
                    "date": date_str,
                    "action": title,
                    "summary": BeautifulSoup(summary, "lxml").get_text()[:500],
                    "action_type": classify_action_type(title + " " + summary),
                    "source": source_name,
                    "source_url": link,
                    "fulfilled": True,  # 뉴스에 보도된 것은 실제 조치로 간주
                })
            time.sleep(0.5)
        except Exception as e:
            print(f"    오류 ({source_name}): {e}")

    return actions


def fetch_executive_orders(start_date: str) -> List[dict]:
    """Federal Register에서 행정명령 수집"""
    print("  Federal Register 행정명령 수집 중...")
    actions = []
    params = {
        "conditions[type][]": "PRESDOCU",
        "conditions[presidential_document_type][]": "executive_order",
        "conditions[publication_date][gte]": start_date,
        "per_page": 100,
        "order": "newest",
        "fields[]": ["document_number", "title", "publication_date", "html_url", "abstract"],
    }
    try:
        resp = requests.get(FEDERAL_REGISTER_API, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        for doc in data.get("results", []):
            actions.append({
                "date": doc.get("publication_date", "")[:10],
                "action": f"[행정명령] {doc.get('title', '')}",
                "summary": doc.get("abstract", ""),
                "action_type": "executive_order",
                "source": "Federal Register",
                "source_url": doc.get("html_url", ""),
                "fulfilled": True,
                "document_number": doc.get("document_number", ""),
            })
    except Exception as e:
        print(f"    Federal Register 오류: {e}")
    return actions


def fetch_whitehouse_actions(start_date: str) -> List[dict]:
    """백악관 공식 사이트에서 Presidential Actions 수집"""
    print("  백악관 공식 사이트 수집 중...")
    actions = []
    start_dt = datetime.strptime(start_date, "%Y-%m-%d")

    try:
        resp = requests.get(WHITEHOUSE_ACTIONS_URL, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")

        # 백악관 사이트 구조에 맞춰 파싱 (카드/리스트 형태)
        articles = soup.select("article, .briefings-statements__item, li.briefing-statement")
        for article in articles[:50]:
            title_tag = article.select_one("h2, h3, .news-item__title")
            date_tag = article.select_one("time, .date")
            link_tag = article.select_one("a")

            if not title_tag:
                continue

            title = title_tag.get_text(strip=True)
            raw_date = date_tag.get("datetime", date_tag.get_text(strip=True)) if date_tag else ""
            link = urljoin(WHITEHOUSE_ACTIONS_URL, link_tag.get("href", "")) if link_tag else ""

            try:
                pub_dt = datetime.fromisoformat(raw_date[:10])
                if pub_dt < start_dt:
                    continue
                date_str = pub_dt.strftime("%Y-%m-%d")
            except Exception:
                date_str = date.today().isoformat()

            actions.append({
                "date": date_str,
                "action": f"[백악관] {title}",
                "summary": "",
                "action_type": classify_action_type(title),
                "source": "White House",
                "source_url": link,
                "fulfilled": True,
            })
        time.sleep(1)
    except Exception as e:
        print(f"    백악관 사이트 오류: {e}")

    return actions


def deduplicate(actions: List[dict]) -> List[dict]:
    """URL 기준 중복 제거"""
    seen_urls = set()
    unique = []
    for a in actions:
        url = a.get("source_url", "")
        if url and url in seen_urls:
            continue
        seen_urls.add(url)
        unique.append(a)
    return unique


def run(args):
    print(f"\n=== 트럼프 조치 수집 시작: {args.start} ~ ===\n")
    all_actions = []

    if not args.skip_rss:
        print("[1/3] RSS 뉴스 피드 수집")
        all_actions.extend(fetch_rss_actions(args.start))
        print(f"  → {len(all_actions)}건 수집")

    if not args.skip_eo:
        print("\n[2/3] 행정명령 (Federal Register)")
        eo_actions = fetch_executive_orders(args.start)
        all_actions.extend(eo_actions)
        print(f"  → {len(eo_actions)}건 수집")

    if not args.skip_wh:
        print("\n[3/3] 백악관 공식 사이트")
        wh_actions = fetch_whitehouse_actions(args.start)
        all_actions.extend(wh_actions)
        print(f"  → {len(wh_actions)}건 수집")

    all_actions = deduplicate(all_actions)
    all_actions.sort(key=lambda x: x["date"], reverse=True)

    print(f"\n총 수집 (중복 제거 후): {len(all_actions)}건")

    # 액션 타입 분포
    type_counts = {}
    for a in all_actions:
        t = a.get("action_type", "other")
        type_counts[t] = type_counts.get(t, 0) + 1
    print("\n[조치 유형 분포]")
    for t, c in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {t}: {c}건")

    out_path = os.path.join("data", "actions", f"actions_{args.start}.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(all_actions, f, ensure_ascii=False, indent=2)
    print(f"\n저장 완료: {out_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="트럼프 실제 조치 수집기")
    parser.add_argument("--start", default="2025-01-20", help="수집 시작일 (트럼프 2기 취임일)")
    parser.add_argument("--skip-rss", action="store_true", help="RSS 수집 건너뜀")
    parser.add_argument("--skip-eo", action="store_true", help="행정명령 수집 건너뜀")
    parser.add_argument("--skip-wh", action="store_true", help="백악관 수집 건너뜀")
    args = parser.parse_args()
    run(args)
