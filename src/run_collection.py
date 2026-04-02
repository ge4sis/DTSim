"""
데이터 수집 전체 파이프라인 실행기

사용법:
  # 전체 파이프라인 실행 (트윗 API + 조치 수집 + 자동 매칭)
  python run_collection.py

  # CSV 파일 사용 시 (Trump Twitter Archive에서 직접 다운로드한 경우)
  python run_collection.py --tweets-csv data/raw/trump_tweets.csv

  # 특정 기간만
  python run_collection.py --start 2025-01-20 --end 2025-06-01
"""

import argparse
import os
import subprocess
import sys
from datetime import date


def run_step(label: str, cmd: list):
    print(f"\n{'='*50}")
    print(f"[STEP] {label}")
    print(f"{'='*50}")
    result = subprocess.run([sys.executable] + cmd, cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if result.returncode != 0:
        print(f"\n오류 발생 (exit code {result.returncode}) — 계속 진행합니다.")


def main():
    parser = argparse.ArgumentParser(description="DTSim 데이터 수집 파이프라인")
    parser.add_argument("--start", default="2025-01-20", help="수집 시작일")
    parser.add_argument("--end", default=date.today().isoformat(), help="수집 종료일")
    parser.add_argument("--tweets-csv", default="", help="로컬 트윗 CSV 경로 (없으면 API 사용)")
    parser.add_argument("--min-score", default="0.2", help="발언-조치 매칭 최소 점수")
    args = parser.parse_args()

    src = os.path.join(os.path.dirname(os.path.abspath(__file__)))
    tweets_out = f"data/raw/tweets_{args.start}_{args.end}.json"
    actions_out = f"data/actions/actions_{args.start}.json"
    linked_out = "data/processed/linked_candidates.csv"

    # Step 1: 트윗 수집
    tweet_cmd = [
        os.path.join(src, "collector_tweets.py"),
        "--start", args.start,
        "--end", args.end,
    ]
    if args.tweets_csv:
        tweet_cmd += ["--csv", args.tweets_csv]
    run_step("트럼프 트윗/발언 수집", tweet_cmd)

    # Step 2: 조치 수집
    action_cmd = [
        os.path.join(src, "collector_actions.py"),
        "--start", args.start,
    ]
    run_step("실제 조치 수집 (RSS + EO + 백악관)", action_cmd)

    # Step 3: 자동 매칭
    if os.path.exists(tweets_out) and os.path.exists(actions_out):
        link_cmd = [
            os.path.join(src, "linker.py"),
            "--statements", tweets_out,
            "--actions", actions_out,
            "--output", linked_out,
            "--min-score", args.min_score,
        ]
        run_step("발언-조치 자동 매칭", link_cmd)
    else:
        print("\n[SKIP] 발언 또는 조치 파일이 없어 매칭 건너뜀")

    print(f"""
{'='*50}
수집 완료!

[결과 파일]
  발언 데이터  : {tweets_out}
  조치 데이터  : {actions_out}
  매칭 후보    : {linked_out}

[다음 단계]
  1. {linked_out} 를 Excel/Sheets로 열기
  2. confirmed 열: Y(연결 확정) / N(무관)
  3. fulfilled 열: Y(이행) / N(미이행) / P(부분이행)
  4. 저장 후 실행:
     python src/linker.py \\
       --statements {tweets_out} \\
       --import-confirmed {linked_out}
{'='*50}
""")


if __name__ == "__main__":
    main()
