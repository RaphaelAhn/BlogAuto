import os
import subprocess
import sys
import time
from pathlib import Path

from paths import AUTOMATION_DIR, SCRIPTS_DIR


BASE_DIR = AUTOMATION_DIR

STEPS = {
    "crawl": ("기존 글 수집", SCRIPTS_DIR / "collect_previous_posts.py"),
    "keywords": ("키워드 후보 수집", SCRIPTS_DIR / "collect_keywords.py"),
    "topics": ("최종 주제 선정", SCRIPTS_DIR / "generate_topics.py"),
    "queue": ("작업 큐 생성", SCRIPTS_DIR / "build_writing_queue.py"),
    "articles": ("완성 글 생성 및 사용 기록", SCRIPTS_DIR / "run_refine_and_register.py"),
}

COMMANDS = {
    "crawl": ["crawl"],
    "keywords": ["keywords"],
    "topics": ["topics"],
    "queue": ["queue"],
    "articles": ["articles"],
    "all": ["crawl", "keywords", "topics", "queue", "articles"],
}


def run_script(script_path: Path) -> tuple[bool, str]:
    if not script_path.exists():
        return False, f"파일을 찾을 수 없습니다:\n{script_path}"

    # stdout=None → 부모 프로세스 stdout 상속 → Streamlit 로그에 실시간 출력
    result = subprocess.run(
        [sys.executable, "-u", str(script_path)],
        cwd=str(BASE_DIR),
        stdout=None,
        stderr=subprocess.STDOUT,
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"},
    )

    if result.returncode == 0:
        return True, "완료"
    return False, f"종료 코드: {result.returncode}"


def run_pipeline(command: str = "all") -> tuple[bool, str]:
    command = command.strip().lower()
    step_keys = COMMANDS.get(command)

    if not step_keys:
        commands = ", ".join(COMMANDS)
        return False, f"사용 가능한 명령: {commands}"

    logs = []
    for step_key in step_keys:
        label, script_path = STEPS[step_key]
        started = time.perf_counter()
        print(f"\n[{label}] 시작", flush=True)
        success, message = run_script(script_path)
        elapsed = time.perf_counter() - started
        status = "완료" if success else "실패"
        print(f"[{label}] {status} ({elapsed:.1f}초)", flush=True)
        logs.append(f"[{label}] {status} ({elapsed:.1f}초)")

        if not success:
            return False, "\n".join(logs)

    return True, "\n".join(logs)


def main() -> None:
    command = sys.argv[1] if len(sys.argv) > 1 else "all"
    success, message = run_pipeline(command)
    print(message, flush=True)
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
