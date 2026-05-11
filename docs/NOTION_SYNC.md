# Notion Sync

Completed articles can be pushed into Notion immediately after generation.

## Required env vars

- `NOTION_API_KEY`
- `NOTION_DATA_SOURCE_ID`
  - Recommended for current Notion API versions.
- or `NOTION_DATABASE_ID`

## Optional env vars

- `NOTION_TITLE_PROPERTY`
  - Default: `Name`
- `NOTION_STATUS_PROPERTY`
- `NOTION_STATUS_VALUE`
  - Example: `Draft` or `검수전`
- `NOTION_PLATFORM_PROPERTY`
- `NOTION_KEYWORD_PROPERTY`
- `NOTION_OUTPUT_PATH_PROPERTY`
- `NOTION_CREATED_AT_PROPERTY`
- `NOTION_SEARCH_INTENT_PROPERTY`
- `NOTION_READY_PROPERTY`
  - Default: `Ready`
- `NOTION_REVIEWED_PROPERTY`
  - Default: `Reviewed`
- `NOTION_UPLOADED_PROPERTY`
  - Default: `Uploaded`
- `NOTION_INCLUDE_MANAGEMENT_CHECKLIST`
  - Default: `true`
- `NOTION_CHECKLIST_ITEMS`
  - Example: `검수 필요|대표 이미지 추가|블로그 업로드|발행 완료`

## Recommended Notion schema

- `Name`: title
- `Status`: status or select
- `Platform`: select or text
- `Keyword`: text
- `Created At`: date or text
- `Output Path`: text or url
- `Ready`: checkbox
- `Reviewed`: checkbox
- `Uploaded`: checkbox

## Behavior

- A new Notion page is created for each generated article.
- The article body is converted into Notion blocks.
- A management checklist is inserted at the top of the page by default.
- Sync results are stored in `automation/data/topic_used.csv` using:
  - `notion_page_id`
  - `notion_page_url`
  - `notion_sync_status`
  - `notion_synced_at`
