import os
import shutil
import subprocess
import sys
from collections import deque
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

# Windows에서 subprocess가 CMD 창을 새로 띄우지 않도록 막는 플래그
_POPEN_FLAGS: int = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _resolve_blog_root() -> Path:
    """실제 Project_Blog 디렉터리를 반환합니다. frozen EXE 환경을 고려합니다."""
    # launcher.py 또는 환경변수로 지정된 경로 우선
    env = os.environ.get("BLOGAUTO_PROJECT_ROOT", "").strip()
    if env and Path(env).exists():
        return Path(env)

    default = Path(__file__).resolve().parents[1]

    if not getattr(sys, "frozen", False):
        return default  # dev 모드: __file__ 기반 경로가 정확함

    # standalone Blog EXE: dist/Project_Blog/Project_Blog.exe → parents[2] = Project_Blog/
    exe = Path(sys.executable)
    candidate = exe.parents[2] if len(exe.parents) >= 3 else exe.parent
    if (candidate / "automation" / "app.py").exists() and (candidate / "start_blog_auto.bat").exists():
        return candidate

    return default


def _build_pipeline_cmd(script_path: Path, args: tuple[str, ...]) -> list[str]:
    """파이프라인 스크립트를 실행할 명령을 반환합니다. frozen EXE에서는 uv를 사용합니다."""
    if not getattr(sys, "frozen", False):
        return [sys.executable, "-u", str(script_path), *args]

    # frozen 모드: sys.executable이 EXE 자신이므로 uv로 대체
    uv = os.environ.get("BLOGAUTO_UV", "").strip() or shutil.which("uv") or ""
    if uv:
        return [
            uv, "run",
            "--python", "3.14",
            "--with", "requests",
            "--with", "beautifulsoup4",
            "--with", "pandas",
            "--with", "openpyxl",
            "python", "-u", str(script_path), *args,
        ]

    # uv 없음: 시스템 python 시도
    py = shutil.which("python") or shutil.which("py") or ""
    if py and "WindowsApps" not in py:
        return [py, "-u", str(script_path), *args]

    return [sys.executable, "-u", str(script_path), *args]


BASE_DIR = _resolve_blog_root()
SCRIPTS_DIR = BASE_DIR / "automation" / "scripts"
PIPELINE_SCRIPT = SCRIPTS_DIR / "run_blog_pipeline.py"
TOPIC_USED_PATH = BASE_DIR / "automation" / "data" / "topic_used.csv"
LOGS_DIR = BASE_DIR / "logs" / "pipeline"
TODAY = datetime.now().strftime("%Y-%m-%d")

from scripts.notion_config import DEFAULT_NOTION_CONFIG, build_notion_env, is_notion_configured, load_notion_config, save_notion_config
from scripts.notion_sync import _resolve_parent, _retrieve_schema, archive_notion_pages, sync_articles_to_notion
from scripts.paths import OUTPUT_DIR as ROOT_OUTPUT_DIR
from scripts.topic_registry import TOPIC_USED_COLUMNS, clear_generated_article_state, mark_as_published, normalize

OUTPUT_DIR = ROOT_OUTPUT_DIR
STATUS_LABELS = {"synced": "동기화 완료", "failed": "동기화 실패", "disabled": "연동 비활성", "": "미동기화"}
PIPELINE_STEP_CONFIG = [
    {"key": "crawl", "label": "1단계. 기존 글 불러오기", "description": "내 블로그의 기존 글을 수집합니다. 보통 2주에 1회 정도만 실행하면 충분합니다."},
    {"key": "keywords", "label": "2단계. 키워드 후보 수집", "description": "새로 쓸 수 있는 키워드 후보를 모읍니다."},
    {"key": "topics", "label": "3단계. 최종 주제 선정", "description": "수집된 후보 중 실제로 쓸 주제를 추립니다."},
    {"key": "queue", "label": "4단계. 글 생성 작업 큐 만들기", "description": "선정된 주제로 이번 회차의 글 생성 목록을 만듭니다."},
    {"key": "articles", "label": "5단계. 완성 글 생성", "description": "작업 큐를 기준으로 글을 생성하고 기록합니다."},
]

def build_article_speed_env(use_fast_mode: bool) -> dict[str, str]:
    return {} if not use_fast_mode else {"BLOGAUTO_MAX_REWRITE_ATTEMPTS": "2", "BLOGAUTO_API_MAX_ATTEMPTS": "1", "BLOGAUTO_API_TIMEOUT_SECONDS": "45", "BLOGAUTO_PARALLEL_WORKERS": "4", "BLOGAUTO_MIN_KOREAN_CHARS": "1500", "BLOGAUTO_PREVIOUS_POSTS_LIMIT": "300"}

def build_run_log_path(script_path: Path, args: tuple[str, ...]) -> Path:
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    step_name = args[0] if args else script_path.stem
    safe_step_name = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in step_name)
    return LOGS_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{safe_step_name}.log"

def run_python_script(script_path: Path, *args: str, extra_env: dict[str, str] | None = None):
    if not script_path.exists():
        return False, f"파일을 찾을 수 없습니다:\n{script_path}", None
    log_path = build_run_log_path(script_path, args)
    recent_lines = deque(maxlen=200)
    status_placeholder, log_placeholder = st.empty(), st.empty()
    command = _build_pipeline_cmd(script_path, args)
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(f"[START] {datetime.now().isoformat()}\n")
            log_file.write(f"[CWD] {BASE_DIR}\n")
            log_file.write(f"[COMMAND] {' '.join(command)}\n\n")
            log_file.flush()

            process = subprocess.Popen(
                command,
                cwd=str(BASE_DIR),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                env={
                    **os.environ,
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUNBUFFERED": "1",
                    **(extra_env or {}),
                },
                bufsize=1,
                creationflags=_POPEN_FLAGS,
            )
            status_placeholder.info(f"실행 중입니다. 로그 파일: {log_path}")
            if process.stdout is not None:
                for line in process.stdout:
                    recent_lines.append(line.rstrip())
                    log_file.write(line)
                    log_file.flush()
                    log_placeholder.code("\n".join(recent_lines) or "로그를 기다리는 중입니다.")
            return_code = process.wait()
    except Exception as exc:
        return False, str(exc), log_path
    output = "\n".join(recent_lines).strip() or "실행 로그가 없습니다."
    if return_code == 0:
        status_placeholder.success(f"실행이 완료되었습니다. 로그 파일: {log_path}")
        return True, output, log_path
    status_placeholder.error(f"실행 중 오류가 발생했습니다. 로그 파일: {log_path}")
    return False, output, log_path

def find_latest_output_run_dir(base_output_dir: Path, day_prefix: str) -> Path:
    candidates = []
    if not base_output_dir.exists():
        return base_output_dir
    for child in base_output_dir.iterdir():
        if child.is_dir() and child.name.startswith(f"{day_prefix}_"):
            suffix = child.name.split("_")[-1]
            if suffix.isdigit():
                candidates.append((int(suffix), child))
    return sorted(candidates, reverse=True)[0][1] if candidates else base_output_dir

def ensure_topic_columns(df: pd.DataFrame) -> pd.DataFrame:
    for column in TOPIC_USED_COLUMNS:
        if column not in df.columns:
            df[column] = ""
    return df if not df.empty else pd.DataFrame(columns=TOPIC_USED_COLUMNS)

def load_topic_used() -> pd.DataFrame:
    if not TOPIC_USED_PATH.exists() or TOPIC_USED_PATH.stat().st_size == 0:
        return pd.DataFrame(columns=TOPIC_USED_COLUMNS)
    try:
        return ensure_topic_columns(pd.read_csv(TOPIC_USED_PATH, encoding="utf-8-sig"))
    except Exception:
        return pd.DataFrame(columns=TOPIC_USED_COLUMNS)

def save_topic_used(df: pd.DataFrame) -> None:
    tmp = TOPIC_USED_PATH.with_suffix(".tmp")
    ensure_topic_columns(df).to_csv(tmp, index=False, encoding="utf-8-sig")
    tmp.replace(TOPIC_USED_PATH)

def load_article_text(output_path: str) -> str:
    raw = str(output_path or "").strip()
    if not raw or raw == "nan":
        return ""
    path = Path(raw)
    if not path.is_absolute():
        path = (BASE_DIR / raw).resolve()
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""

@contextmanager
def notion_env_context(config: dict[str, object]):
    env_updates = build_notion_env(config)
    previous = {key: os.environ.get(key) for key in env_updates}
    for key, value in env_updates.items():
        os.environ[key] = value
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

def test_notion_connection(config: dict[str, object]) -> tuple[bool, str]:
    if not is_notion_configured(config):
        return False, "API 키와 대상 ID를 먼저 입력해 주세요."
    try:
        with notion_env_context(config):
            parent = _resolve_parent(os.getenv("NOTION_API_KEY", ""))
            if not parent:
                return False, "노션 대상 정보를 확인하지 못했습니다."
            schema = _retrieve_schema(os.getenv("NOTION_API_KEY", ""), parent)
            return True, f"연결 성공: {parent['type']} / 속성 {', '.join(list(schema.keys())[:8]) or '없음'}"
    except Exception as exc:
        return False, str(exc)

def sync_rows_to_notion(topic_df: pd.DataFrame, row_indexes: list[int], config: dict[str, object]) -> tuple[pd.DataFrame, dict[str, int]]:
    payload = []
    key_map = {}
    for index in row_indexes:
        row = topic_df.loc[index]
        keyword = str(row.get("keyword", "")).strip()
        payload.append({"platform": str(row.get("platform", "")).strip(), "title": str(row.get("title", keyword)).strip() or keyword, "keyword": keyword, "search_intent": str(row.get("search_intent", "")).strip(), "created_at": str(row.get("created_at", "")).strip(), "output_path": str(row.get("output_path", "")).strip(), "article_text": load_article_text(row.get("output_path", "")), "notion_status": str(row.get("status", "drafted")).strip() or "drafted"})
        key_map[index] = normalize(keyword)
    with notion_env_context(config):
        results = sync_articles_to_notion(payload)
    result_map = {normalize(item.get("keyword", "")): item for item in results if item.get("keyword")}
    counts = {"synced": 0, "failed": 0, "disabled": 0}
    for index, norm_key in key_map.items():
        result = result_map.get(norm_key, {})
        status = str(result.get("status", "")).strip()
        if status in counts:
            counts[status] += 1
        topic_df.loc[index, "notion_page_id"] = str(result.get("page_id", "")).strip()
        topic_df.loc[index, "notion_page_url"] = str(result.get("page_url", "")).strip()
        topic_df.loc[index, "notion_sync_status"] = status
        topic_df.loc[index, "notion_synced_at"] = str(result.get("synced_at", "")).strip()
    save_topic_used(topic_df)
    return topic_df, counts


def reset_all_published_articles(topic_df: pd.DataFrame, config: dict[str, object], remove_notion_pages: bool) -> tuple[int, dict[str, int] | None]:
    notion_counts = None
    if remove_notion_pages:
        page_ids = []
        if "notion_page_id" in topic_df.columns:
            page_ids = [str(value).strip() for value in topic_df["notion_page_id"].fillna("").tolist() if str(value).strip()]
        with notion_env_context(config):
            notion_counts = archive_notion_pages(page_ids)
    cleared = clear_generated_article_state()
    return int(cleared.get("topic_used", 0)), notion_counts

def render_result(success: bool, message: str, log_path: Path | None):
    (st.success if success else st.error)("작업이 완료되었습니다." if success else "작업 중 오류가 발생했습니다.")
    if log_path:
        st.caption(f"실행 로그: {log_path}")
    st.code(message)


def render_pipeline_steps(article_env: dict[str, str]):
    st.subheader("글 생성 단계 실행")
    st.caption("전체 실행이 항상 필요한 것은 아닙니다. 필요한 단계만 눌러서 개별 실행할 수 있습니다.")
    for step in PIPELINE_STEP_CONFIG:
        left, right = st.columns([5, 1.2])
        with left:
            st.markdown(f"**{step['label']}**")
            st.caption(step["description"])
        result_container = st.empty()
        with right:
            if st.button("이 단계 실행", key=f"run_step_{step['key']}", use_container_width=True):
                with result_container.container():
                    success, message, log_path = run_python_script(PIPELINE_SCRIPT, step["key"], extra_env=article_env)
                    render_result(success, message, log_path)
        st.divider()

st.set_page_config(page_title="Project_Blog", page_icon="📝", layout="centered")
st.title("Project_Blog 자동 글 생성")
st.caption("글 생성과 노션 데이터베이스 관리를 함께 처리합니다.")
notion_config = load_notion_config()
notion_env = build_notion_env(notion_config)
with st.expander("노션 데이터베이스 연동 설정"):
    with st.form("notion_config_form"):
        notion_api_key = st.text_input("Notion API Key", value=str(notion_config.get("NOTION_API_KEY", "")), type="password")
        target_type = st.radio("대상 유형", options=["data_source_id", "database_id"], index=0 if str(notion_config.get("NOTION_TARGET_KIND", "data_source_id")) == "data_source_id" else 1, horizontal=True)
        target_id = st.text_input("대상 ID", value=str(notion_config.get("NOTION_TARGET_ID", "")))
        title_property = st.text_input("제목 속성", value=str(notion_config.get("NOTION_TITLE_PROPERTY", "Name")))
        status_property = st.text_input("상태 속성", value=str(notion_config.get("NOTION_STATUS_PROPERTY", "")))
        checklist_items = st.text_input("체크리스트 항목", value=str(notion_config.get("NOTION_CHECKLIST_ITEMS", DEFAULT_NOTION_CONFIG["NOTION_CHECKLIST_ITEMS"])))
        include_checklist = st.checkbox("관리 체크리스트 추가", value=bool(notion_config.get("NOTION_INCLUDE_MANAGEMENT_CHECKLIST", True)))
        if st.form_submit_button("노션 설정 저장", type="primary"):
            save_notion_config({**notion_config, "NOTION_API_KEY": notion_api_key.strip(), "NOTION_TARGET_KIND": target_type, "NOTION_TARGET_ID": target_id.strip(), "NOTION_TITLE_PROPERTY": title_property.strip() or "Name", "NOTION_STATUS_PROPERTY": status_property.strip(), "NOTION_CHECKLIST_ITEMS": checklist_items.strip(), "NOTION_INCLUDE_MANAGEMENT_CHECKLIST": include_checklist})
            notion_config = load_notion_config()
            notion_env = build_notion_env(notion_config)
            st.success("노션 설정을 저장했습니다.")
    if st.button("노션 연결 테스트"):
        ok, message = test_notion_connection(notion_config)
        (st.success if ok else st.error)(message)
    st.caption("현재 상태: 활성" if is_notion_configured(notion_config) else "현재 상태: 비활성")

fast_article_mode = st.checkbox("빠른 글 생성 모드", value=True)
article_env = {**build_article_speed_env(fast_article_mode), **notion_env}
st.info("추천 흐름: 기존 글 불러오기는 가끔만, 그 외 단계는 필요할 때만 다시 실행하면 됩니다.")
render_pipeline_steps(article_env)
col1, col2 = st.columns([1.3, 1])
with col1:
    if st.button("전체 1~5단계 한 번에 실행", type="primary", use_container_width=True):
        success, message, log_path = run_python_script(PIPELINE_SCRIPT, "all", extra_env=article_env)
        render_result(success, message, log_path)
with col2:
    if st.button("오늘 결과 폴더 열기"):
        os.startfile(str(find_latest_output_run_dir(OUTPUT_DIR, TODAY)))

topic_df = load_topic_used()
st.divider()
st.header("발행 및 노션 관리")
if topic_df.empty or "status" not in topic_df.columns:
    st.info("아직 생성된 글이 없습니다. 파이프라인을 실행해 주세요.")
else:
    drafted_df = topic_df[topic_df["status"] == "drafted"].copy()
    used_df = topic_df[topic_df["status"] == "used"].copy()
    a, b, c = st.columns(3)
    a.metric("전체 글", len(topic_df))
    b.metric("발행 대기", len(drafted_df))
    c.metric("발행 완료", len(used_df))
    view = topic_df.copy()
    view["노션 상태"] = view["notion_sync_status"].fillna("").map(STATUS_LABELS).fillna("미동기화")
    view["노션 링크"] = view["notion_page_url"].fillna("")
    st.dataframe(view[[col for col in ["platform", "title", "status", "노션 상태", "notion_synced_at", "노션 링크"] if col in view.columns]], use_container_width=True, column_config={"노션 링크": st.column_config.LinkColumn("노션 페이지")}, hide_index=True)
    selected_publish, selected_notion = [], []
    for index, row in drafted_df.iterrows():
        keyword = str(row.get("keyword", "")).strip()
        st.markdown(f"**[{row.get('platform','')}] {row.get('title', keyword)}**")
        st.caption(f"생성일: {row.get('created_at','')} | 노션 상태: {STATUS_LABELS.get(str(row.get('notion_sync_status','')).strip(), '미동기화')}")
        c1, c2 = st.columns(2)
        if c1.checkbox("발행 완료로 표시", key=f"publish_{index}"):
            selected_publish.append(keyword)
        if c2.checkbox("노션으로 동기화", key=f"notion_{index}"):
            selected_notion.append(index)
    x, y, z = st.columns(3)
    if x.button("선택한 글 발행 완료", disabled=not selected_publish):
        changed = mark_as_published(selected_publish)
        st.success(f"{changed}개 글을 발행 완료로 변경했습니다.")
        st.rerun()
    if y.button("선택한 글 노션 동기화", disabled=not selected_notion or not is_notion_configured(notion_config)):
        topic_df, counts = sync_rows_to_notion(topic_df, selected_notion, notion_config)
        st.success(f"성공 {counts.get('synced',0)}개 / 실패 {counts.get('failed',0)}개 / 비활성 {counts.get('disabled',0)}개")
        st.rerun()
    unsynced_indexes = drafted_df[drafted_df["notion_sync_status"].fillna("").isin(["", "failed", "disabled"])].index.tolist()
    if z.button("미동기화 전체 동기화", disabled=not unsynced_indexes or not is_notion_configured(notion_config)):
        topic_df, counts = sync_rows_to_notion(topic_df, unsynced_indexes, notion_config)
        st.success(f"성공 {counts.get('synced',0)}개 / 실패 {counts.get('failed',0)}개 / 비활성 {counts.get('disabled',0)}개")
        st.rerun()
    st.divider()
    with st.expander("테스트용 초기화"):
        st.caption("테스트 중이라면 현재 생성 목록을 비우고, 필요하면 노션에 만든 페이지까지 함께 정리할 수 있습니다.")
        reset_publish_confirm = st.checkbox("생성 목록 초기화를 이해했고 되돌릴 수 없다는 점을 확인했습니다.", key="reset_publish_confirm")
        reset_notion_confirm = st.checkbox("노션 페이지 보관 처리까지 함께 진행하겠습니다.", key="reset_notion_confirm")
        p1, p2 = st.columns(2)
        if p1.button("생성 목록만 초기화", disabled=not reset_publish_confirm):
            changed, _ = reset_all_published_articles(topic_df, notion_config, remove_notion_pages=False)
            if changed == 0:
                st.info("초기화할 생성 목록이 없습니다.")
            else:
                st.success(f"생성 목록 {changed}건을 비웠습니다.")
            st.rerun()
        if p2.button("생성 목록 + 노션 글 초기화", disabled=not (reset_publish_confirm and reset_notion_confirm)):
            changed, notion_counts = reset_all_published_articles(topic_df, notion_config, remove_notion_pages=True)
            archived = 0 if not notion_counts else notion_counts.get("archived", 0)
            failed = 0 if not notion_counts else notion_counts.get("failed", 0)
            disabled = 0 if not notion_counts else notion_counts.get("disabled", 0)
            if changed == 0 and archived == 0 and failed == 0 and disabled == 0:
                st.info("초기화할 생성 목록과 노션 페이지가 없습니다.")
            else:
                st.success(f"생성 목록 제거 {changed}건 / 노션 보관 처리 {archived}건 / 실패 {failed}건 / 비활성 {disabled}건")
            st.rerun()
