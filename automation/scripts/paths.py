import os
from pathlib import Path

# BLOGAUTO_PROJECT_ROOT: frozen EXE 또는 Hub 실행 시 실제 Project_Blog 경로를 가리킵니다.
_env_root = os.environ.get("BLOGAUTO_PROJECT_ROOT", "").strip()
if _env_root and Path(_env_root).exists():
    AUTOMATION_DIR = Path(_env_root) / "automation"
else:
    AUTOMATION_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = AUTOMATION_DIR.parent

DATA_DIR = AUTOMATION_DIR / "data"
SCRIPTS_DIR = AUTOMATION_DIR / "scripts"
CONTENT_DIR = AUTOMATION_DIR / "content"
OUTPUT_DIR = AUTOMATION_DIR / "output"
LOGS_DIR = PROJECT_ROOT / "logs"
CONTENT_QUALITY_LOG_PATH = DATA_DIR / "content_quality_log.csv"

PLATFORM_CONTENT_DIRS = {
    "naver": CONTENT_DIR / "naver",
    "tistory": CONTENT_DIR / "tistory",
    "blogspot_kr": CONTENT_DIR / "blogspot_kr",
    "blogspot_en": CONTENT_DIR / "blogspot_en",
}

PLATFORM_DRAFT_DIRS = {
    platform: base_dir / "drafts"
    for platform, base_dir in PLATFORM_CONTENT_DIRS.items()
}

PLATFORM_FINAL_DIRS = {
    platform: base_dir / "final"
    for platform, base_dir in PLATFORM_CONTENT_DIRS.items()
}


def build_output_run_dir(now=None) -> Path:
    if now is None:
        from datetime import datetime

        now = datetime.now()

    day_prefix = now.strftime("%Y-%m-%d")
    run_index = 1

    while True:
        candidate = OUTPUT_DIR / f"{day_prefix}_{run_index}"
        if not candidate.exists():
            return candidate
        run_index += 1
