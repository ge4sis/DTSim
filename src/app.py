"""
DTSim — 트럼프 행동 예측 AI  (Streamlit UI)

실행:
  cd DTSim
  streamlit run src/app.py
"""

import json
import os
import sys
from collections import Counter
from datetime import datetime

import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ── 페이지 설정 ──────────────────────────────────────────────────
st.set_page_config(
    page_title="DTSim — 트럼프 행동 예측",
    page_icon="🇺🇸",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── 데이터 경로 ──────────────────────────────────────────────────
BASE      = os.path.join(os.path.dirname(__file__), "..")
DATA_STMT = os.path.join(BASE, "data/raw/briefings_2025-01-20_enriched_linked.json")
DATA_ACT  = os.path.join(BASE, "data/actions/actions_2025-01-20.json")


# ── 캐시된 데이터 로드 ────────────────────────────────────────────
@st.cache_data
def load_data():
    with open(DATA_STMT, encoding="utf-8") as f:
        statements = json.load(f)
    with open(DATA_ACT, encoding="utf-8") as f:
        actions = json.load(f)
    return statements, actions


@st.cache_resource
def get_retriever():
    from retriever import search
    return search


# ── 사이드바 ─────────────────────────────────────────────────────
with st.sidebar:
    st.title("🇺🇸 DTSim")
    st.caption("Trump Action Prediction AI")
    st.divider()

    api_key = st.text_input(
        "Anthropic API Key",
        type="password",
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        placeholder="sk-ant-...",
        help=".env 파일에 저장하거나 여기에 직접 입력하세요",
    )
    if api_key:
        os.environ["ANTHROPIC_API_KEY"] = api_key

    st.divider()
    top_k = st.slider("참조 선례 수 (Top-K)", 3, 10, 5)

    st.divider()
    statements, actions = load_data()
    linked = [s for s in statements if s["actions"]]
    st.metric("수집된 발언", f"{len(statements)}건")
    st.metric("수집된 조치", f"{len(actions)}건")
    st.metric("연결된 발언-조치 쌍", f"{len(linked)}건")
    st.caption("데이터: 2025-01-20 ~ 현재\n출처: 백악관 공식 사이트")


# ── 탭 ───────────────────────────────────────────────────────────
tab_predict, tab_search, tab_dashboard = st.tabs(["🔮 예측", "🔍 유사 사례 검색", "📊 데이터 현황"])


# ══════════════════════════════════════════════════════════════════
# Tab 1: 예측
# ══════════════════════════════════════════════════════════════════
with tab_predict:
    st.header("트럼프 발언 → 행동 예측")
    st.caption("새로운 트럼프 발언을 입력하면, 과거 패턴을 분석해 예상 행동을 예측합니다.")

    col1, col2 = st.columns([2, 1])
    with col1:
        statement_input = st.text_area(
            "발언 입력 (영문 또는 한글)",
            height=120,
            placeholder='예) "We will impose 50% tariffs on all Chinese goods"\n예) "중국산 모든 제품에 50% 관세를 부과할 것이다"',
        )

    with col2:
        st.write("")
        st.write("")
        example_stmts = [
            "We will impose 50% tariffs on all Chinese goods",
            "I'm going to close the southern border completely",
            "We will sanction any country that buys oil from Iran",
            "We are withdrawing from NATO if they don't pay",
            "I will fire anyone who doesn't follow my orders",
        ]
        selected = st.selectbox("예시 발언", ["직접 입력"] + example_stmts)
        if selected != "직접 입력":
            statement_input = selected

    predict_btn = st.button("🔮 예측 실행", type="primary", use_container_width=True)

    if predict_btn and statement_input.strip():
        search_fn = get_retriever()

        # RAG 검색 (항상 실행)
        with st.spinner("유사 사례 검색 중..."):
            hits = search_fn(statement_input.strip(), top_k=top_k)

        # Claude API 예측 (API 키가 있을 때만)
        if os.environ.get("ANTHROPIC_API_KEY"):
            with st.spinner("Claude가 예측 중..."):
                try:
                    from predictor import predict, format_precedents
                    result = predict(statement_input.strip(), top_k=top_k)
                    has_prediction = True
                except Exception as e:
                    st.error(f"예측 오류: {e}")
                    has_prediction = False
        else:
            has_prediction = False
            st.warning("⚠️ API 키가 없어 RAG 검색 결과만 표시합니다. 사이드바에 Anthropic API Key를 입력하면 AI 예측이 활성화됩니다.")

        # ── 예측 결과 카드 ──
        if has_prediction:
            prob  = result.get("fulfillment_probability", 0)
            delay = result.get("expected_delay_days", -1)
            conf  = result.get("confidence", "low")
            atype = result.get("action_type", "other")

            color = "green" if prob >= 70 else ("orange" if prob >= 40 else "red")
            conf_icon = {"high": "🟢 높음", "medium": "🟡 보통", "low": "🔴 낮음"}.get(conf, "❓")

            st.divider()
            st.subheader("예측 결과")

            m1, m2, m3, m4 = st.columns(4)
            m1.metric("이행 가능성", f"{prob}%")
            m2.metric("예상 소요일", f"{delay}일" if delay >= 0 else "불확실")
            m3.metric("신뢰도", conf_icon)
            m4.metric("조치 유형", atype)

            st.info(f"**예측 조치 (한국어):** {result.get('predicted_action_ko','')}")
            st.caption(f"*{result.get('predicted_action','')}*")

            with st.expander("📋 근거 및 상세"):
                st.write("**근거**")
                st.write(result.get("reasoning", ""))
                st.write("**주의사항**")
                st.write(result.get("caveats", ""))

            # 주요 선례 표
            precedents = result.get("key_precedents", [])
            if precedents:
                st.write("**AI가 참조한 주요 선례**")
                for p in precedents:
                    d = p.get("delay_days", -1)
                    st.markdown(
                        f"- **{p.get('date','')}** (+{d}일)  \n"
                        f"  발언: {p.get('statement','')[:80]}  \n"
                        f"  조치: {p.get('action','')[:80]}"
                    )

        # ── 유사 사례 (항상 표시) ──
        st.divider()
        st.subheader(f"📚 유사 선례 Top-{len(hits)}")

        for h in hits:
            sim = h["similarity"]
            bar = "█" * int(sim * 20) + "░" * (20 - int(sim * 20))
            has_act = h["action_count"] > 0

            with st.expander(
                f"#{h['rank']} 유사도 {sim:.2f}  {bar}  |  {h['date']}  |  {'✅ 조치 있음' if has_act else '⬜ 조치 없음'}"
            ):
                st.write(f"**발언/문서:** {h['document_preview'][:300]}")
                st.write(f"**토픽:** {h['topics']}")
                if has_act:
                    st.success(
                        f"**후속 조치** (+{h['avg_delay_days']}일):  \n{h['action_summary'][:250]}"
                    )
                st.caption(h["source_url"])

    elif predict_btn:
        st.warning("발언을 입력해주세요.")


# ══════════════════════════════════════════════════════════════════
# Tab 2: 유사 사례 검색
# ══════════════════════════════════════════════════════════════════
with tab_search:
    st.header("유사 사례 검색")
    st.caption("발언 키워드로 과거 선례를 직접 검색합니다.")

    query = st.text_input("검색어", placeholder="tariff china / border immigration / iran sanction ...")
    col_k, col_t = st.columns([1, 2])
    with col_k:
        search_k = st.slider("결과 수", 3, 15, 8, key="search_k")

    if st.button("🔍 검색", key="search_btn") and query.strip():
        search_fn = get_retriever()
        with st.spinner("검색 중..."):
            results = search_fn(query.strip(), top_k=search_k)

        st.write(f"**{len(results)}건 검색 완료**")
        for h in results:
            with st.expander(
                f"sim={h['similarity']:.3f} | {h['date']} | {h['context']} | {'✅' if h['action_count'] > 0 else '⬜'}"
            ):
                st.markdown(f"**문서 내용:**\n{h['document_preview'][:400]}")
                st.write(f"토픽: `{h['topics']}`")
                if h["action_count"] > 0:
                    delay = h["avg_delay_days"]
                    st.success(f"**후속 조치** (+{delay}일):\n{h['action_summary'][:300]}")
                st.caption(f"[원문 보기]({h['source_url']})")


# ══════════════════════════════════════════════════════════════════
# Tab 3: 데이터 현황 대시보드
# ══════════════════════════════════════════════════════════════════
with tab_dashboard:
    st.header("데이터 현황 대시보드")

    statements, actions = load_data()
    linked = [s for s in statements if s["actions"]]
    all_pairs = [a for s in linked for a in s["actions"]]
    delays = [a["delay_days"] for a in all_pairs if a.get("delay_days") is not None]

    # 상단 요약 지표
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("발언 수집", f"{len(statements)}건", "2025-01-20~")
    c2.metric("조치 수집", f"{len(actions)}건", "공식 행정명령 포함")
    c3.metric("연결된 발언", f"{len(linked)}건", f"전체의 {len(linked)*100//len(statements)}%")
    c4.metric("평균 이행 소요일", f"{sum(delays)//len(delays) if delays else 0}일")

    st.divider()
    row1_l, row1_r = st.columns(2)

    # 토픽별 연결 현황 (가로 막대)
    with row1_l:
        st.subheader("토픽별 연결 현황")
        tc = Counter(t for s in linked for t in s["topics"])
        fig = px.bar(
            x=list(tc.values()),
            y=list(tc.keys()),
            orientation="h",
            labels={"x": "건수", "y": "토픽"},
            color=list(tc.values()),
            color_continuous_scale="Blues",
        )
        fig.update_layout(showlegend=False, coloraxis_showscale=False, height=350)
        st.plotly_chart(fig, use_container_width=True)

    # 월별 조치 건수 (라인 차트)
    with row1_r:
        st.subheader("월별 조치 건수")
        mc = Counter(a["date"][:7] for a in actions if a.get("date"))
        months = sorted(mc.keys())
        fig2 = px.line(
            x=months,
            y=[mc[m] for m in months],
            labels={"x": "월", "y": "건수"},
            markers=True,
        )
        fig2.update_layout(height=350)
        st.plotly_chart(fig2, use_container_width=True)

    row2_l, row2_r = st.columns(2)

    # 이행 소요일 분포 (히스토그램)
    with row2_l:
        st.subheader("이행 소요일 분포")
        if delays:
            fig3 = px.histogram(
                x=delays,
                nbins=15,
                labels={"x": "소요일", "y": "건수"},
                color_discrete_sequence=["#1f77b4"],
            )
            fig3.update_layout(height=300)
            st.plotly_chart(fig3, use_container_width=True)

    # 조치 유형 파이 차트
    with row2_r:
        st.subheader("조치 유형 분포")
        type_counts = Counter(a.get("action_type", "other") for a in actions)
        type_ko = {
            "executive_order": "행정명령",
            "policy": "정책/포고령",
            "legislation": "법률",
            "sanction": "제재",
            "other": "기타",
        }
        labels = [type_ko.get(k, k) for k in type_counts.keys()]
        fig4 = px.pie(
            names=labels,
            values=list(type_counts.values()),
            hole=0.4,
        )
        fig4.update_layout(height=300)
        st.plotly_chart(fig4, use_container_width=True)

    # 최근 조치 목록
    st.divider()
    st.subheader("최근 공식 조치 (최신 10건)")
    recent = sorted(actions, key=lambda a: a.get("date", ""), reverse=True)[:10]
    for a in recent:
        st.markdown(
            f"- **{a['date']}** `{a.get('action_type','?')}` — "
            f"{a['action'][:80]}  \n"
            f"  [{a.get('source','')}]({a.get('source_url','')})"
        )
