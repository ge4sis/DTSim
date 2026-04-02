"""
linked_candidates.csv 자동 검토기

기준:
  confirmed=Y: score >= 0.6 AND days_diff <= 60
           OR: score >= 0.4 AND days_diff <= 14  (단기 직접 연관)
  fulfilled=Y: WH 공식 소스의 조치는 모두 실제 이행된 것으로 처리
  나머지: confirmed=N
"""

import csv
import os
import sys

INPUT  = "data/processed/linked_candidates.csv"
OUTPUT = "data/processed/linked_candidates_reviewed.csv"


def review(row: dict) -> dict:
    score = float(row["score"])
    days  = int(row["days_diff"])

    high_conf  = score >= 0.6 and days <= 60
    short_link = score >= 0.4 and days <= 14

    if high_conf or short_link:
        row["confirmed"] = "Y"
        row["fulfilled"]  = "Y"   # WH 공식 조치는 실제 이행
    else:
        row["confirmed"] = "N"
        row["fulfilled"]  = ""

    return row


def run():
    with open(INPUT, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    reviewed = [review(r) for r in rows]

    confirmed = [r for r in reviewed if r["confirmed"] == "Y"]
    print(f"전체 후보: {len(reviewed)}건")
    print(f"confirmed=Y: {len(confirmed)}건")
    print(f"confirmed=N: {len(reviewed) - len(confirmed)}건")

    os.makedirs(os.path.dirname(OUTPUT), exist_ok=True)
    with open(OUTPUT, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=reviewed[0].keys())
        writer.writeheader()
        writer.writerows(reviewed)

    print(f"\n저장: {OUTPUT}")

    # 확정된 매칭 샘플 출력
    print("\n=== 확정 매칭 샘플 (score 높은 순) ===")
    top = sorted(confirmed, key=lambda r: float(r["score"]), reverse=True)[:10]
    for r in top:
        print(f"  score={r['score']} +{r['days_diff']}d | {r['stmt_date']} → {r['action_date']}")
        print(f"    발언: {r['statement'][:65]}")
        print(f"    조치: {r['action'][:65]}")
        print()


if __name__ == "__main__":
    run()
