import pandas as pd

from notion_sync import sync_articles_to_notion
import refine_drafts_ai
from generate_practice_excel import generate_practice_excel_batch
from paths import DATA_DIR
from topic_registry import append_topic_used, normalize


QUEUE_PATH = DATA_DIR / "writing_queue.csv"
def update_queue_status(processed_keywords, status="drafted"):
    if not QUEUE_PATH.exists():
        return

    df = pd.read_csv(QUEUE_PATH, encoding="utf-8-sig")

    if df.empty or "keyword" not in df.columns:
        return

    normalized_processed = {normalize(k) for k in processed_keywords}
    mask = df["keyword"].apply(lambda k: normalize(str(k)) in normalized_processed)
    df.loc[mask, "status"] = status
    df.to_csv(QUEUE_PATH, index=False, encoding="utf-8-sig")
    print(f"writing_queue.csv status updated: {mask.sum()} -> {status}")


def main():
    print("[debug] run_refine_and_register.main started")
    print(f"[debug] queue path: {QUEUE_PATH}")
    source_df = refine_drafts_ai.generate_articles_df()
    print(f"[debug] generated rows: {len(source_df)}")

    if source_df.empty:
        print("No rows to append into topic_used.csv.")
        return

    notion_results = sync_articles_to_notion(source_df.to_dict("records"))
    notion_map = {normalize(item.get("keyword", "")): item for item in notion_results if item.get("keyword")}

    topic_rows = []
    processed_keywords = []

    for _, row in source_df.iterrows():
        keyword = str(row.get("keyword", "")).strip()
        if not keyword:
            continue
        notion_result = notion_map.get(normalize(keyword), {})

        title = str(row.get("title", "")).strip() or keyword
        topic_rows.append({
            "platform": str(row.get("platform", "")).strip(),
            "title": title,
            "keyword": keyword,
            "tag_keywords": str(row.get("tag_keywords", "")).strip(),
            "meta_description": str(row.get("meta_description", "")).strip(),
            "search_intent": str(row.get("search_intent", "")).strip(),
            "topic_type": str(row.get("topic_type", "")).strip(),
            "status": "drafted",
            "created_at": str(row.get("created_at", "")).strip(),
            "output_path": str(row.get("output_path", "")).strip(),
            "structure_slot": str(row.get("structure_slot", row.get("structure_variant", ""))).strip(),
            "lead_slot": str(row.get("lead_slot", "")).strip(),
            "rhythm_slot": str(row.get("rhythm_slot", "")).strip(),
            "style_slot": str(row.get("style_slot", "")).strip(),
            "ending_slot": str(row.get("ending_slot", "")).strip(),
            "topic_profile": str(row.get("topic_profile", "")).strip(),
            "similarity_score": row.get("similarity_score", ""),
            "structural_score": row.get("structural_score", ""),
            "total_penalty": row.get("total_penalty", ""),
            "decision": str(row.get("decision", "drafted")).strip(),
            "decision_reason": str(row.get("decision_reason", "")).strip(),
            "notion_page_id": str(notion_result.get("page_id", "")).strip(),
            "notion_page_url": str(notion_result.get("page_url", "")).strip(),
            "notion_sync_status": str(notion_result.get("status", "disabled")).strip(),
            "notion_synced_at": str(notion_result.get("synced_at", "")).strip(),
        })
        processed_keywords.append(keyword)

    saved_topic_count = append_topic_used(topic_rows, default_status="drafted")
    print(f"topic_used.csv record added: {saved_topic_count}")

    update_queue_status(processed_keywords)

    # 각 아티클에 대해 연습 Excel 생성
    output_paths = [
        str(row.get("output_path", ""))
        for _, row in source_df.iterrows()
        if str(row.get("output_path", "")).endswith(".txt")
    ]
    if output_paths:
        excel_results = generate_practice_excel_batch(output_paths)
        print(f"[practice_excel] 생성 완료: {len(excel_results)}개")

    print("[debug] run_refine_and_register.main completed")


if __name__ == "__main__":
    main()
