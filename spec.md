# DTSim — 트럼프 예측 AI 개발 사양서

> 작성일: 2026-04-02  
> 목적: 트럼프 대통령의 역대 발언과 실제 조치를 데이터화하여, 새로운 발언이 주어졌을 때 향후 행동을 예측하는 AI 시스템 구축  
> 사업화 제외, 빠른 프로토타입 우선

---

## 1. 시스템 개요

### 핵심 가설
트럼프의 발언에는 패턴이 있으며, 과거 발언-조치 쌍 데이터로 미래 행동을 예측할 수 있다.

### 예측 흐름
```
새로운 발언 입력
      ↓
유사 과거 발언 검색 (벡터 DB)
      ↓
관련 실제 조치 조회
      ↓
Claude API로 예측 생성
      ↓
예상 조치 / 이행 가능성 / 예상 시기 출력
```

### 출력 예시
```
[예측 결과]
- 예상 조치: 관세 행정명령 서명
- 이행 가능성: 높음 (78%)
- 예상 시기: 발언 후 7~30일
- 유사 선례:
  ① 2025-10-26 말레이시아 무역합의 공동성명 → 관세 조정 행정명령 (9일 후)
  ② 2025-01-20 캐나다 관세 발언 → 행정명령 서명 (12일 후)
- 주의사항: 협상용 발언일 가능성도 있음
```

---

## 2. 아키텍처

```
[데이터 수집]          [벡터 DB]           [예측 엔진]         [UI]
 WH Briefings RSS  →              →   RAG + Claude API  →  Streamlit
 WH Actions RSS    →  ChromaDB    →
 Federal Register  →  (로컬)      →
```

### 기술 스택

| 구성 요소 | 기술 |
|-----------|------|
| 언어 | Python 3.11+ |
| 데이터 수집 | requests, feedparser, BeautifulSoup4 |
| 벡터 DB | ChromaDB (로컬) |
| 임베딩 | sentence-transformers (all-MiniLM-L6-v2) |
| LLM | Claude API (claude-sonnet-4-6) |
| UI | Streamlit |
| 데이터 포맷 | JSON + CSV |

---

## 3. 데이터 모델

### Statement (발언)
```python
@dataclass
class Statement:
    id: str              # 고유 ID (날짜_순번)
    date: str            # 발언일 (YYYY-MM-DD)
    statement: str       # 발언 제목/원문
    statement_ko: str    # 한국어 번역 (선택)
    context: str         # tweet / speech / press_conference / statement 등
    source: str          # 출처
    source_url: str      # 원문 URL
    topics: List[str]    # 토픽 태그
    actions: List[Action]# 이후 실제 조치들
    is_threat: bool      # 협박/경고성 발언 여부
    is_fulfilled: bool   # 이행 여부
    notes: str
```

### Action (조치)
```python
@dataclass
class Action:
    date: str            # 조치 실행일
    action: str          # 조치 내용
    action_type: str     # executive_order / legislation / policy / other
    source: str          # 출처
    source_url: str      # URL
    fulfilled: bool      # 실제 이행 여부
    delay_days: int      # 발언 후 조치까지 걸린 일수
    notes: str
```

### 토픽 분류
무역/관세 | 이민/국경 | 외교/동맹 | 안보/군사 | 경제/세금 | 에너지 | 규제완화 | 사법/법무 | 선거/정치 | 미디어 | 보건 | 기타

---

## 4. 개발 단계 (Phase)

### Phase 1 — 데이터 수집 ✅ 완료 (2026-04-02)

**수집 결과**
| 데이터 | 건수 | 기간 |
|--------|------|------|
| 발언 (WH Briefings) | 333건 | 2025-01-20 ~ 2026-03-30 |
| 본문 스크래핑 완료 | 331건 (99%) | — |
| 조치 (WH Actions) | 505건 | 2025-01-20 ~ 2026-03-31 |
| 자동 매칭 후보 | 1,355쌍 | — |
| 확정 발언-조치 쌍 | 257쌍 (score ≥ 0.6) | — |
| 조치 연결된 발언 | 150건 | — |
| 평균 이행 소요일 | 22일 (범위: 0~60일) | — |

**토픽별 연결 현황**
기타:118 | 외교/동맹:104 | 이민/국경:82 | 안보/군사:73 | 경제/세금:68 | 규제완화:66

**이행 소요일 분포**
0~7일: 79건 | 8~30일: 91건 | 31~60일: 87건

**데이터 소스**
- 백악관 Briefings RSS: `whitehouse.gov/briefings-statements/feed/` (페이지네이션)
- 백악관 Actions RSS: `whitehouse.gov/presidential-actions/feed/` (페이지네이션)
- Federal Register API: 행정명령/포고령/각서

**수집 스크립트**
```bash
python src/collector_wh.py --since 2025-01-20      # 전체 수집
python src/linker.py --statements ... --actions ... # 자동 매칭
python src/linker.py --import-confirmed ...         # 검토 결과 병합
```

**자동 검토 기준**
- score ≥ 0.6 AND days_diff ≤ 60일 → confirmed=Y (고신뢰)
- score ≥ 0.4 AND days_diff ≤ 14일 → confirmed=Y (단기 직접 연관)
- 나머지 → confirmed=N

---

### Phase 2 — RAG 시스템 구축 ✅ 완료 (2026-04-02)

**목표**: 벡터 DB에 발언-조치 쌍을 저장하고, 새 발언이 들어오면 유사 사례를 검색

**구현 내용**
1. `src/embedder.py` — Statement를 ChromaDB에 임베딩 저장 (all-MiniLM-L6-v2)
2. `src/retriever.py` — 입력 발언과 유사한 Statement 검색 (Top-K, cosine similarity)

**ChromaDB 컬렉션 구조**
```
collection : trump_statements
  document : 발언 제목 + 본문 (최대 2500자)
  metadata : date, context, topics, action_count, action_summary,
             avg_delay_days, is_fulfilled, is_threat, source_url
  id       : Statement.id
DB 경로   : data/chroma_db/
저장 건수  : 333건
```

**검색 성능 확인 (2026-04-02)**
| 쿼리 | #1 유사도 | 결과 |
|------|-----------|------|
| "impose heavy tariffs on China" | 0.586 | U.S.-China 무역회의 → 관세 EO (+12일) ✓ |
| "close the southern border" | 0.504 | America First Priorities 문서 ✓ |
| "sanction countries trading with Iran" | 0.507 | 이란 제재 성명 ✓ |
| "NASA space exploration" | 0.524 | 허블망원경 35주년 메시지 ✓ |

**실행**
```bash
python src/embedder.py --reset   # DB 초기화 및 재구축
python src/retriever.py "tariffs on China" --top-k 5   # 검색 테스트
```

---

### Phase 3 — 예측 엔진 ✅ 완료 (2026-04-02)

**목표**: 새 발언 → RAG 검색 → Claude API → 예측 결과

**구현 내용**
1. `src/predictor.py` — RAG + Claude API 예측 로직
2. `--dry-run` 모드: API 키 없이 RAG 검색 결과와 프롬프트 확인 가능

**예측 출력 항목 (JSON)**
```json
{
  "predicted_action": "행동 예측 (영문)",
  "predicted_action_ko": "행동 예측 (한국어)",
  "action_type": "executive_order | policy | sanction | ...",
  "fulfillment_probability": 75,
  "expected_delay_days": 12,
  "confidence": "high | medium | low",
  "reasoning": "선례 기반 근거",
  "key_precedents": [...],
  "caveats": "주의사항"
}
```

**dry-run 검증 결과 (2026-04-02)**
- 쿼리: "impose 50% tariffs on all Chinese goods"
- Top-1 유사도: 0.577 (U.S.-China Stockholm 무역회의)
- 선례 조치: 관세 조정 행정명령 (+12일)
- 프롬프트 총 길이: 4,668자

**실행**
```bash
# API 키 없이 파이프라인 검증
python src/predictor.py "tariffs on China" --dry-run

# 실제 예측 (API 키 필요)
set ANTHROPIC_API_KEY=sk-ant-...
python src/predictor.py "We will close the border"
python src/predictor.py "tariffs on China" --json
```

---

### Phase 4 — Streamlit UI ✅ 완료 (2026-04-02)

**목표**: 발언 입력 → 예측 결과 시각화

**화면 구성 (3개 탭)**

| 탭 | 내용 |
|----|------|
| 🔮 예측 | 발언 입력 → RAG 검색 → Claude 예측 결과 카드 + 유사 선례 |
| 🔍 유사 사례 검색 | 키워드 검색으로 과거 선례 직접 탐색 |
| 📊 데이터 현황 | 토픽별/월별/소요일/유형 차트 대시보드 |

**주요 기능**
- API 키 미입력 시 RAG 검색 결과만 표시 (graceful degradation)
- 사이드바에서 API 키 직접 입력 가능
- 예시 발언 selectbox (5개 제공)
- 유사도 시각화 (█ 블록 바)

**실행**
```bash
streamlit run src/app.py
# → http://localhost:8501
```

---

## 5. 디렉토리 구조

```
DTSim/
├── spec.md                          # 이 문서
├── requirements.txt
├── .env.example                     # API 키 템플릿
├── data/
│   ├── raw/
│   │   └── briefings_2025-01-20.json        # 발언 원본
│   ├── actions/
│   │   └── actions_2025-01-20.json          # 조치 원본
│   └── processed/
│       ├── linked_candidates.csv            # 자동 매칭 후보
│       └── briefings_2025-01-20_linked.json # 확정 발언-조치 쌍
└── src/
    ├── schema.py            # 데이터 모델 (Statement, Action)
    ├── collector_wh.py      # 백악관 RSS 수집기
    ├── collector_tweets.py  # 트위터 아카이브 수집기 (CSV 지원)
    ├── collector_actions.py # 뉴스 RSS 수집기
    ├── linker.py            # 발언-조치 연결기
    ├── embedder.py          # ChromaDB 임베딩 (Phase 2)
    ├── predictor.py         # 예측 엔진 (Phase 3)
    └── app.py               # Streamlit UI (Phase 4)
```

---

## 6. 알려진 이슈 및 제약

| 이슈 | 상태 | 비고 |
|------|------|------|
| Trump Twitter Archive API 폐지 | 확인됨 | WH Briefings RSS로 대체 |
| WH RSS 1회 10건 페이지네이션 | 해결됨 | 전체 51페이지 자동 수집 |
| 발언-조치 자동 매칭 정확도 낮음 | 진행중 | score ≥ 0.6 기준으로 필터링 |
| WH Briefings는 Trump 발언이 아닌 공식 문서도 포함 | 제약 | press_conference/speech 컨텍스트 우선 활용 |
| Federal Register API fields 파라미터 오류 | 미해결 | WH Actions RSS가 대체 |

---

## 7. 주요 도전과제

| 도전 | 해결책 |
|------|--------|
| 발언과 조치 매핑의 어려움 | 키워드 유사도 자동매칭 + 임계값 필터링 |
| 협박용 발언 vs 실제 의지 구분 | is_threat 플래그 + 이행률 통계로 불확실성 표현 |
| 트위터 아카이브 접근 불가 | 백악관 공식 채널로 대체 (더 신뢰성 높음) |
| 데이터 지속 업데이트 | collector_wh.py --since 로 증분 수집 |
