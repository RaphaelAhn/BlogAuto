import pandas as pd
from pathlib import Path
from datetime import datetime

# =========================
# 경로 설정
# =========================
BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"

DATA_DIR.mkdir(parents=True, exist_ok=True)

HISTORY_TOP10_PATH = DATA_DIR / "topic_top10_history.csv"

TOP10_COUNT = 12

# =========================
# 유틸 함수
# =========================

def generate_topic_title(keyword):
    return f"{keyword} 완벽 가이드"


def remove_past_top10(df, history_df):
    if history_df is None or history_df.empty:
        return df

    if "keyword" not in history_df.columns:
        return df

    past_keywords = set(history_df["keyword"].dropna().tolist())

    return df[~df["keyword"].isin(past_keywords)].copy()


# =========================
# 메인 함수
# =========================

def main():

    print("TOPIC 생성 시작")

    # -------------------------
    # 입력 데이터 로드
    # -------------------------
    usable_path = DATA_DIR / "usable_keywords.csv"

    if not usable_path.exists():
        print("usable_keywords.csv 없음")
        return

    usable_df = pd.read_csv(usable_path, encoding="utf-8-sig")

    # -------------------------
    # history 로드
    # -------------------------
    if HISTORY_TOP10_PATH.exists():
        history_df = pd.read_csv(HISTORY_TOP10_PATH, encoding="utf-8-sig")
    else:
        history_df = pd.DataFrame()

    # -------------------------
    # 그룹 분류 (예시 기준)
    # -------------------------
    approved_df = usable_df[usable_df["final_score"] >= 120].copy()
    hold_df = usable_df[
        (usable_df["final_score"] >= 90) &
        (usable_df["final_score"] < 120)
    ].copy()
    rejected_df = usable_df[usable_df["final_score"] < 90].copy()

    # =========================
    # 🔥 TOP10 생성 (핵심)
    # =========================

    top10_pool_df = usable_df.copy()

    # 과거 TOP10 제거
    top10_pool_df = remove_past_top10(top10_pool_df, history_df)

    # 점수 기준 정렬 → 상위 12개
    top10_df = top10_pool_df.sort_values(
        by=["final_score"],
        ascending=False
    ).head(TOP10_COUNT).copy()

    # -------------------------
    # 공통 컬럼 생성
    # -------------------------
    for df in [approved_df, hold_df, top10_df, rejected_df]:
        if not df.empty:
            df["title"] = df["keyword"].apply(generate_topic_title)
            df["created_at"] = datetime.now().strftime("%Y-%m-%d")

    # -------------------------
    # 파일 저장
    # -------------------------
    approved_df.to_csv(DATA_DIR / "topics_approved.csv", index=False, encoding="utf-8-sig")
    hold_df.to_csv(DATA_DIR / "topics_hold.csv", index=False, encoding="utf-8-sig")
    top10_df.to_csv(DATA_DIR / "topic_top10.csv", index=False, encoding="utf-8-sig")
    rejected_df.to_csv(DATA_DIR / "topics_rejected.csv", index=False, encoding="utf-8-sig")

    # -------------------------
    # TOP10 히스토리 저장
    # -------------------------
    if not top10_df.empty:

        top10_history_df = top10_df.copy()
        top10_history_df["selected_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        if HISTORY_TOP10_PATH.exists():
            old_history_df = pd.read_csv(HISTORY_TOP10_PATH, encoding="utf-8-sig")

            top10_history_df = pd.concat(
                [old_history_df, top10_history_df],
                ignore_index=True
            )

        top10_history_df.to_csv(
            HISTORY_TOP10_PATH,
            index=False,
            encoding="utf-8-sig"
        )

    # -------------------------
    # 로그 출력
    # -------------------------
    print("완료")
    print(f"전체 후보: {len(usable_df)}")
    print(f"승인: {len(approved_df)}")
    print(f"보류: {len(hold_df)}")
    print(f"TOP10: {len(top10_df)}")
    print(f"제외: {len(rejected_df)}")


# =========================
# 실행
# =========================

if __name__ == "__main__":
    main()
