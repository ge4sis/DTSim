"""
데이터 스키마 정의
발언(Statement)과 실제 조치(Action) 쌍을 저장하는 구조
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional
import json


TOPICS = [
    "무역/관세", "이민/국경", "외교/동맹", "안보/군사",
    "경제/세금", "에너지", "규제완화", "사법/법무",
    "선거/정치", "미디어", "보건", "기타"
]

CONTEXTS = [
    "tweet",           # 트위터/X 게시물
    "speech",          # 공식 연설
    "press_conference",# 기자회견
    "interview",       # 인터뷰
    "debate",          # 토론
    "rally",           # 유세 집회
    "statement",       # 공식 성명
]


@dataclass
class Action:
    date: str                        # 조치 실행일 (YYYY-MM-DD)
    action: str                      # 조치 내용 요약
    action_type: str                 # executive_order / legislation / speech / policy / other
    source: str                      # 출처 언론사/기관
    source_url: str                  # 원문 URL
    fulfilled: bool                  # 발언 이행 여부
    delay_days: Optional[int] = None # 발언 후 조치까지 걸린 일수
    notes: str = ""                  # 추가 메모 (예: "협상 후 철회", "부분 이행")


@dataclass
class Statement:
    id: str                          # 고유 ID (날짜_순번, 예: 20250120_001)
    date: str                        # 발언일 (YYYY-MM-DD)
    statement: str                   # 발언 원문 (영어)
    statement_ko: str                # 발언 번역 (한국어, 선택)
    context: str                     # 발언 유형 (CONTEXTS 중 하나)
    source: str                      # 출처
    source_url: str                  # 원문 URL
    topics: List[str] = field(default_factory=list)   # 토픽 태그 (TOPICS 중 복수 선택)
    actions: List[Action] = field(default_factory=list)  # 이후 실제 조치들
    is_threat: bool = False          # 협박/경고성 발언 여부
    is_fulfilled: Optional[bool] = None  # 전체 이행 여부 (None=미확인)
    notes: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Statement":
        d = {k: v for k, v in d.items() if not k.startswith("_")}  # 내부 메타 필드 제거
        actions = [Action(**a) for a in d.pop("actions", [])]
        return cls(**d, actions=actions)


TOPIC_KEYWORDS = {
    "무역/관세": ["tariff", "trade", "import", "export", "wto", "nafta", "usmca", "duty", "customs"],
    "이민/국경": ["immigration", "border", "wall", "deportation", "illegal", "migrant", "asylum", "daca", "visa"],
    "외교/동맹": ["nato", "allies", "diplomacy", "sanctions", "united nations", "russia", "china", "korea", "japan", "europe", "israel", "ukraine"],
    "안보/군사": ["military", "army", "navy", "nuclear", "weapon", "defense", "war", "troops", "isis", "terror", "pentagon"],
    "경제/세금": ["economy", "tax", "cut", "gdp", "jobs", "unemployment", "inflation", "rate", "fed ", "budget", "deficit", "spending"],
    "에너지": ["oil", "gas", "energy", "pipeline", "coal", "solar", "green", "climate", "paris accord", "drill", "lng"],
    "규제완화": ["regulation", "deregulation", "epa", "fda", "bureaucracy", "red tape", "permitting"],
    "사법/법무": ["court", "judge", "law", "crime", "fbi", "doj", "justice", "prison", "police", "prosecution"],
    "선거/정치": ["election", "vote", "democrat", "republican", "congress", "senate", "house", "poll", "campaign"],
    "미디어": ["media", "press", "cnn", "nyt", "fake news", "journalist", "reporter", "censorship"],
    "보건": ["health", "covid", "vaccine", "obamacare", "medicare", "drug", "fentanyl", "nih", "cdc"],
}


def classify_topics(text: str) -> List[str]:
    """텍스트에서 토픽 자동 분류"""
    text_lower = text.lower()
    found = [topic for topic, keywords in TOPIC_KEYWORDS.items()
             if any(kw in text_lower for kw in keywords)]
    return found if found else ["기타"]


def save_statements(statements: List[Statement], path: str):
    data = [s.to_dict() for s in statements]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"저장 완료: {path} ({len(statements)}건)")


def load_statements(path: str) -> List[Statement]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Statement.from_dict(d) for d in data]
