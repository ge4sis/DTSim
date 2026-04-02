"""
백악관 공식 데이터 수집기 (White House RSS 기반)

발언 출처: whitehouse.gov/briefings-statements  (기자회견, 연설, 성명)
조치 출처: whitehouse.gov/presidential-actions  (행정명령, 포고령, 각서)
           federalregister.gov API              (행정명령 상세)

사용법:
  python collector_wh.py                  # 전체 수집
  python collector_wh.py --type actions   # 조치만
  python collector_wh.py --type briefings # 발언만
  python collector_wh.py --since 2025-03-01  # 특정일 이후
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import List, Optional

import feedparser
import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from schema import Statement, Action, save_statements, classify_topics

HEADERS = {"User-Agent": "Mozilla/5.0 (research; dtsim)"}
TRUMP_INAUGURATION = "2025-01-20"

WH_ACTIONS_RSS  = "https://www.whitehouse.gov/presidential-actions/feed/?paged={page}"
WH_BRIEFINGS_RSS = "https://www.whitehouse.gov/briefings-statements/feed/?paged={page}"
FEDERAL_REGISTER_API = "https://www.federalregister.gov/api/v1/documents.json"


# ── 날짜 파싱 ────────────────────────────────────────────────────
def parse_rss_date(raw: str) -> str:
    """RFC 2822 → YYYY-MM-DD"""
    try:
        return parsedate_to_datetime(raw).strftime("%Y-%m-%d")
    except Exception:
        return raw[:10] if raw else ""


# ── RSS 전체 페이지 수집 ──────────────────────────────────────────
def fetch_rss_all_pages(url_template: str, since: str, label: str) -> List[dict]:
    """페이지네이션을 따라가며 since 날짜 이후 항목만 수집"""
    entries = []
    page = 1
    since_dt = datetime.strptime(since, "%Y-%m-%d")

    with tqdm(desc=f"{label} 수집") as pbar:
        while True:
            feed = feedparser.parse(url_template.format(page=page))
            if not feed.entries:
                break

            stop = False
            for e in feed.entries:
                date_str = parse_rss_date(e.get("published", ""))
                if not date_str:
                    continue
                try:
                    entry_dt = datetime.strptime(date_str[:10], "%Y-%m-%d")
                except ValueError:
                    continue

                if entry_dt < since_dt:
                    stop = True
                    break

                entries.append({
                    "date": date_str[:10],
                    "title": e.get("title", ""),
                    "summary": BeautifulSoup(
                        e.get("summary", e.get("description", "")), "lxml"
                    ).get_text()[:800],
                    "link": e.get("link", ""),
                    "categories": [t.get("term", "") for t in e.get("tags", [])],
                })
                pbar.update(1)

            if stop:
                break
            page += 1
            time.sleep(0.4)

    return entries


# ── 브리핑 페이지 본문 스크래핑 ──────────────────────────────────
def scrape_briefing_text(url: str) -> str:
    """백악관 브리핑 페이지에서 본문 텍스트 추출"""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        # 백악관 본문 셀렉터
        body = soup.select_one(
            ".body-content, .entry-content, article .wp-block-post-content, "
            ".page-content, main article"
        )
        if body:
            return body.get_text(separator="\n", strip=True)[:3000]
    except Exception:
        pass
    return ""


# ── Federal Register 행정명령 ─────────────────────────────────────
def fetch_federal_register(since: str) -> List[dict]:
    """Federal Register API로 행정명령/포고령/대통령각서 수집"""
    params = {
        "conditions[type][]": "PRESDOCU",
        "conditions[publication_date][gte]": since,
        "per_page": 100,
        "order": "newest",
        "fields[]": [
            "document_number", "title", "publication_date",
            "html_url", "abstract", "presidential_document_type"
        ],
    }
    results = []
    try:
        resp = requests.get(FEDERAL_REGISTER_API, params=params, headers=HEADERS, timeout=20)
        resp.raise_for_status()
        data = resp.json()
        for doc in data.get("results", []):
            results.append({
                "date": (doc.get("publication_date") or "")[:10],
                "title": doc.get("title", ""),
                "doc_type": doc.get("presidential_document_type", ""),
                "doc_number": doc.get("document_number", ""),
                "abstract": doc.get("abstract") or "",
                "link": doc.get("html_url", ""),
            })
    except Exception as e:
        print(f"  Federal Register 오류: {e}")
    return results


# ── 브리핑 → Statement 변환 ──────────────────────────────────────
def briefing_to_statement(entry: dict, idx: int, scrape: bool = False) -> Statement:
    text = entry["title"]
    if scrape and entry["link"]:
        full_text = scrape_briefing_text(entry["link"])
        if full_text:
            # 실제 발언 내용이 있으면 사용 (요약은 메모로)
            text = entry["title"]  # 제목을 발언 레이블로
            entry["summary"] = full_text[:800]

    date_str = entry["date"]
    stmt_id = f"{date_str.replace('-', '')}_br{idx:04d}"

    # 브리핑 유형 분류
    title_lower = entry["title"].lower()
    if "press briefing" in title_lower or "press conference" in title_lower:
        context = "press_conference"
    elif "speech" in title_lower or "address" in title_lower or "remarks" in title_lower:
        context = "speech"
    elif "interview" in title_lower:
        context = "interview"
    elif "proclamation" in title_lower:
        context = "statement"
    else:
        context = "statement"

    combined = entry["title"] + " " + entry["summary"]
    topics = classify_topics(combined)

    return Statement(
        id=stmt_id,
        date=date_str,
        statement=entry["title"],
        statement_ko="",
        context=context,
        source="White House Briefings",
        source_url=entry["link"],
        topics=topics,
        actions=[],
        notes=entry["summary"][:300],
    )


# ── 행정명령 → Action 변환 ──────────────────────────────────────
def fr_to_action(doc: dict) -> Action:
    doc_type_map = {
        "executive_order": "executive_order",
        "presidential_memorandum": "executive_order",
        "proclamation": "policy",
    }
    action_type = doc_type_map.get(doc.get("doc_type", "").lower(), "policy")
    label = {
        "executive_order": "[행정명령]",
        "presidential_memorandum": "[대통령각서]",
        "proclamation": "[포고령]",
    }.get(doc.get("doc_type", "").lower(), "[조치]")

    return Action(
        date=doc["date"],
        action=f"{label} {doc['title']}",
        action_type=action_type,
        source=f"Federal Register ({doc.get('doc_number','')})",
        source_url=doc["link"],
        fulfilled=True,
        notes=doc.get("abstract", "")[:200],
    )


# ── WH Actions → Action 변환 ────────────────────────────────────
def wh_action_to_action(entry: dict) -> Action:
    title_lower = entry["title"].lower()
    if "executive order" in title_lower:
        action_type = "executive_order"
        label = "[행정명령]"
    elif "proclamation" in title_lower:
        action_type = "policy"
        label = "[포고령]"
    elif "memorandum" in title_lower:
        action_type = "executive_order"
        label = "[각서]"
    else:
        action_type = "policy"
        label = "[조치]"

    return Action(
        date=entry["date"],
        action=f"{label} {entry['title']}",
        action_type=action_type,
        source="White House Presidential Actions",
        source_url=entry["link"],
        fulfilled=True,
        notes=entry["summary"][:200],
    )


# ── 메인 ─────────────────────────────────────────────────────────
def run(args):
    os.makedirs("data/raw", exist_ok=True)
    os.makedirs("data/actions", exist_ok=True)

    since = args.since

    # ── 발언 수집 ──
    if args.type in ("all", "briefings"):
        print(f"\n[1] 백악관 브리핑/발언 수집 ({since} 이후)")
        briefing_entries = fetch_rss_all_pages(WH_BRIEFINGS_RSS, since, "Briefings")
        print(f"  → RSS: {len(briefing_entries)}건")

        statements = []
        for i, entry in enumerate(tqdm(briefing_entries, desc="Statement 변환")):
            stmt = briefing_to_statement(entry, i, scrape=args.scrape)
            statements.append(stmt)
            if args.scrape:
                time.sleep(0.5)  # 스크래핑 시 서버 부하 방지

        out = f"data/raw/briefings_{since}.json"
        save_statements(statements, out)

        # 토픽 분포
        topic_counts = {}
        for s in statements:
            for t in s.topics:
                topic_counts[t] = topic_counts.get(t, 0) + 1
        print("  [토픽 분포]", " | ".join(f"{t}:{c}" for t, c in
              sorted(topic_counts.items(), key=lambda x: -x[1])[:8]))

    # ── 조치 수집 ──
    if args.type in ("all", "actions"):
        print(f"\n[2] 백악관 공식 조치 수집 ({since} 이후)")

        # WH Actions RSS
        wh_entries = fetch_rss_all_pages(WH_ACTIONS_RSS, since, "WH Actions")
        print(f"  → WH RSS: {len(wh_entries)}건")

        # Federal Register
        print("  → Federal Register 수집 중...")
        fr_docs = fetch_federal_register(since)
        print(f"  → Federal Register: {len(fr_docs)}건")

        # WH Actions → Action 객체
        wh_actions = [wh_action_to_action(e) for e in wh_entries]
        # FR → Action 객체
        fr_actions = [fr_to_action(d) for d in fr_docs]

        # 중복 제거 (URL 기준)
        all_actions = []
        seen = set()
        for a in wh_actions + fr_actions:
            if a.source_url not in seen:
                seen.add(a.source_url)
                all_actions.append(a)

        all_actions.sort(key=lambda a: a.date, reverse=True)

        # JSON 저장
        from dataclasses import asdict
        out = f"data/actions/actions_{since}.json"
        with open(out, "w", encoding="utf-8") as f:
            json.dump([asdict(a) for a in all_actions], f, ensure_ascii=False, indent=2)
        print(f"  저장: {out} ({len(all_actions)}건)")

        # 유형 분포
        type_counts = {}
        for a in all_actions:
            type_counts[a.action_type] = type_counts.get(a.action_type, 0) + 1
        print("  [유형 분포]", " | ".join(f"{t}:{c}" for t, c in
              sorted(type_counts.items(), key=lambda x: -x[1])))

    print("\n수집 완료.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default=TRUMP_INAUGURATION)
    parser.add_argument("--type", choices=["all", "briefings", "actions"], default="all")
    parser.add_argument("--scrape", action="store_true",
                        help="브리핑 페이지 본문 스크래핑 (느리지만 풍부한 데이터)")
    args = parser.parse_args()
    run(args)
