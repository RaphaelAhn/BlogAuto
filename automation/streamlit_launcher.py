import os
import runpy
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        exe_path = Path(sys.executable).resolve()
        for candidate in (exe_path.parent, *exe_path.parents):
            if (candidate / "automation" / "app.py").exists():
                return candidate
            if (candidate / "_internal" / "automation" / "app.py").exists():
                return candidate / "_internal"
        return exe_path.parent
    return Path(__file__).resolve().parents[1]


def resolve_script_invocation() -> tuple[Path, list[str]] | None:
    args = sys.argv[1:]
    # skip Python flags like -u, -v passed by app.py subprocess command
    while args and args[0].startswith("-"):
        args = args[1:]
    if not args:
        return None

    candidate = Path(args[0])
    if not candidate.suffix.lower() == ".py":
        return None
    if not candidate.exists():
        return None

    return candidate.resolve(), args[1:]


def run_script_mode(script_path: Path, script_args: list[str]) -> None:
    previous_argv = sys.argv[:]
    previous_cwd = Path.cwd()
    previous_sys_path = sys.path[:]

    try:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        if hasattr(sys.stderr, "reconfigure"):
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        sys.argv = [str(script_path), *script_args]
        os.chdir(script_path.parent.parent)
        sys.path.insert(0, str(script_path.parent))
        runpy.run_path(str(script_path), run_name="__main__")
    finally:
        sys.argv = previous_argv
        os.chdir(previous_cwd)
        sys.path[:] = previous_sys_path


def main() -> None:
    script_invocation = resolve_script_invocation()
    if script_invocation is not None:
        script_path, script_args = script_invocation
        run_script_mode(script_path, script_args)
        return

    root = project_root()
    logs_dir = root / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / "BlogAuto.log"
    log_file = log_path.open("a", encoding="utf-8")
    sys.stdout = log_file
    sys.stderr = log_file
    print("\n--- BlogAuto launch ---", flush=True)

    from streamlit.web import bootstrap

    app_path = root / "automation" / "app.py"
    if not app_path.exists():
        raise FileNotFoundError(f"Streamlit app not found: {app_path}")

    os.chdir(root)
    port = os.environ.get("BLOGAUTO_PORT", "8501")
    url = f"http://localhost:{port}"

    os.environ["STREAMLIT_GLOBAL_DEVELOPMENT_MODE"] = "false"
    os.environ["STREAMLIT_SERVER_HEADLESS"] = "true"
    os.environ["STREAMLIT_BROWSER_GATHER_USAGE_STATS"] = "false"

    def open_browser() -> None:
        import urllib.request

        for _ in range(20):
            try:
                urllib.request.urlopen(url, timeout=1)
                webbrowser.open(url)
                return
            except Exception:
                time.sleep(1)

        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()

    flag_options = {
        "global_developmentMode": False,
        "server_port": int(port),
        "server_headless": True,
        "browser_gatherUsageStats": False,
    }

    bootstrap.load_config_options(flag_options)
    print(f"Starting Streamlit on {url}", flush=True)
    bootstrap.run(str(app_path), False, [], flag_options)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
        raise
