# DTSim — 트럼프 행동 예측 AI

> **Donald Trump Simulation** — 트럼프 대통령의 발언 패턴을 분석하여 향후 정책 행동을 예측하는 RAG 기반 AI 시스템

[![Python](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.56-red.svg)](https://streamlit.io/)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-1.5-green.svg)](https://www.trychroma.com/)
[![Claude](https://img.shields.io/badge/Claude-Sonnet_4.6-orange.svg)](https://www.anthropic.com/)
[![License](https://img.shields.io/badge/License-MIT-lightgrey.svg)](LICENSE)

---

## 개요

트럼프 대통령은 발언 이후 일정한 패턴으로 정책 행동을 취해왔습니다.  
DTSim은 백악관 공식 발언 데이터와 실제 행정 조치를 연결하여, **새로운 발언이 주어졌을 때 어떤 행동이 뒤따를지**를 예측합니다.

파인튜닝 없이 **RAG(Retrieval-Augmented Generation)** 방식으로 빠르게 구현하였으며,  
과거 발언-조치 쌍을 벡터 DB에 저장하고 Claude API로 예측을 생성합니다.

```
새로운 발언 입력
      ↓
ChromaDB에서 유사 과거 사례 검색 (코사인 유사도)
      ↓
상위 K개 선례를 컨텍스트로 Claude API에 주입
      ↓
예상 조치 · 이행 가능성(%) · 예상 시기(일) · 근거 출력
```

---

## 주요 기능

| 기능 | 설명 |
|------|------|
| 🔮 **행동 예측** | 발언 입력 → 예상 조치 유형, 이행 가능성(%), 소요 기간 예측 |
| 🔍 **유사 사례 검색** | 키워드로 과거 발언-조치 선례 의미 검색 |
| 📊 **데이터 대시보드** | 토픽별/월별/소요일 분포, 최근 조치 현황 시각화 |
| 🌐 **데이터 자동 수집** | 백악관 공식 RSS, Federal Register API 연동 |

---

## 데이터 현황

수집 기간: **2025년 1월 20일 (트럼프 2기 취임) ~ 현재**

| 항목 | 수량 |
|------|------|
| 수집된 발언 (WH Briefings) | 333건 |
| 수집된 공식 조치 (WH Actions) | 505건 |
| 본문 스크래핑 완료 | 331건 (99%) |
| 확정 발언-조치 연결 쌍 | 257쌍 |
| 평균 이행 소요일 | 22일 |

**주요 토픽:** 기타 · 외교/동맹 · 이민/국경 · 안보/군사 · 경제/세금 · 규제완화

**데이터 출처:**
- 백악관 공식 사이트 (whitehouse.gov) — 브리핑, 성명, 행정명령
- Federal Register API — 행정명령/포고령/대통령각서

---

## 시작하기

### 요구 사항

- Python 3.11+
- [Anthropic API Key](https://console.anthropic.com/) (예측 기능에 필요, 검색은 키 없이 동작)

### 설치

```bash
git clone https://github.com/ge4sis/DTSim.git
cd DTSim
pip install -r requirements.txt
```

### API 키 설정

```bash
cp .env.example .env
# .env 파일을 열어 ANTHROPIC_API_KEY=sk-ant-... 입력
```

### 벡터 DB 구축

```bash
python src/embedder.py --reset
```

> 처음 실행 시 임베딩 모델(`all-MiniLM-L6-v2`)이 자동으로 다운로드됩니다 (~90MB).

### 앱 실행

```bash
streamlit run src/app.py
```

브라우저에서 **http://localhost:8501** 로 접속하세요.

---

## 프로젝트 구조

```
DTSim/
├── spec.md                    # 전체 개발 사양서
├── requirements.txt
├── .env.example               # API 키 템플릿
│
├── data/
│   ├── raw/
│   │   └── briefings_*.json   # 발언 원본 데이터
│   ├── actions/
│   │   └── actions_*.json     # 공식 조치 데이터
│   ├── processed/
│   │   └── linked_candidates_enriched_reviewed.csv  # 확정 발언-조치 쌍
│   └── chroma_db/             # 벡터 DB (embedder.py로 생성)
│
└── src/
    ├── schema.py              # 데이터 모델 (Statement, Action)
    ├── collector_wh.py        # 백악관 RSS 수집기
    ├── enricher.py            # 브리핑 본문 스크래핑
    ├── linker.py              # 발언-조치 자동 매칭
    ├── auto_review.py         # 매칭 자동 검토
    ├── embedder.py            # ChromaDB 임베딩 구축
    ├── retriever.py           # 유사 사례 검색
    ├── predictor.py           # Claude API 예측 엔진
    └── app.py                 # Streamlit UI
```

---

## 스크립트 사용법

### 데이터 최신화 (증분 수집)

```bash
# 새로운 발언 및 조치 수집
python src/collector_wh.py --since 2026-01-01

# 본문 스크래핑 보강
python src/enricher.py --input data/raw/briefings_2026-01-01.json

# 발언-조치 자동 매칭
python src/linker.py \
  --statements data/raw/briefings_2026-01-01_enriched.json \
  --actions data/actions/actions_2026-01-01.json \
  --output data/processed/candidates.csv

# 벡터 DB 재구축
python src/embedder.py --reset
```

### CLI로 예측 실행

```bash
# 발언 예측
python src/predictor.py "We will impose 50% tariffs on all Chinese goods"

# 유사 사례 검색
python src/retriever.py "border security immigration" --top-k 5

# API 없이 RAG 결과만 확인
python src/predictor.py "We will close the border" --dry-run
```

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│                      Streamlit UI                        │
│          (예측 탭 / 검색 탭 / 대시보드 탭)               │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────▼─────────────┐
         │       predictor.py        │
         │   RAG + Claude Sonnet     │
         └──────┬──────────┬─────────┘
                │          │
    ┌───────────▼──┐  ┌────▼────────────┐
    │  retriever   │  │  Claude API     │
    │  ChromaDB    │  │  (Anthropic)    │
    │  (코사인유사도)│  └─────────────────┘
    └───────────┬──┘
                │
    ┌───────────▼──────────────────────┐
    │          embedder.py             │
    │   all-MiniLM-L6-v2 임베딩        │
    │   333건 발언 문서 저장            │
    └───────────┬──────────────────────┘
                │
    ┌───────────▼──────────────────────┐
    │        데이터 파이프라인           │
    │  collector_wh → enricher         │
    │  → linker → auto_review          │
    │  (백악관 RSS / Federal Register)  │
    └──────────────────────────────────┘
```

---

## 기술 스택

| 구성 요소 | 기술 |
|-----------|------|
| 언어 | Python 3.11+ |
| 벡터 DB | ChromaDB 1.5 |
| 임베딩 | sentence-transformers (all-MiniLM-L6-v2) |
| LLM | Claude Sonnet 4.6 (Anthropic API) |
| UI | Streamlit + Plotly |
| 데이터 수집 | requests, feedparser, BeautifulSoup4 |

---

## 한계 및 주의사항

- 본 프로젝트는 **연구 및 학습 목적**으로 제작되었습니다.
- 예측 결과는 과거 패턴에 기반하며, 실제 정치적 판단의 대안이 될 수 없습니다.
- 데이터는 백악관 공식 발표 기준이며, 트위터/X 발언은 현재 포함되지 않습니다.
- 발언-조치 연결은 키워드 유사도 기반 자동 매칭으로, 일부 부정확한 연결이 있을 수 있습니다.

---

## 기여

이슈 및 PR은 언제든지 환영합니다.  
데이터 품질 개선(발언-조치 수동 검토), 새로운 데이터 소스 추가, 예측 모델 개선 등 다양한 방면에서 기여 가능합니다.

---

## 라이선스

MIT License — 자유롭게 사용, 수정, 배포하실 수 있습니다.
