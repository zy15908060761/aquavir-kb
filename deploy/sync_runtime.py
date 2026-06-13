import json
import os
import socket
import ctypes
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = APP_DIR / "sync_runtime"
RUNTIME_DIR.mkdir(exist_ok=True)

STATUS_FILE = RUNTIME_DIR / "sync_status.json"
HISTORY_FILE = RUNTIME_DIR / "sync_history.jsonl"
NOTIFICATION_LOG_FILE = RUNTIME_DIR / "notification_log.jsonl"
LOCK_FILE = RUNTIME_DIR / "sync.lock"
SCHEDULED_LOG_FILE = RUNTIME_DIR / "scheduled_sync.log"

NOTIFICATION_CONFIG_FILE = APP_DIR / "notification_config.json"
NOTIFICATION_CONFIG_EXAMPLE_FILE = APP_DIR / "notification_config.example.json"


def now_iso():
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def ensure_runtime_dir():
    RUNTIME_DIR.mkdir(exist_ok=True)


def read_json(path, default=None):
    if default is None:
        default = {}
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError:
        return default


def write_json(path, data):
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path, data):
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(data, ensure_ascii=False) + "\n")


def default_status():
    return {
        "status": "idle",
        "message": "No sync has been run yet.",
        "updated_at": now_iso(),
        "host": socket.gethostname(),
    }


def load_status():
    status = read_json(STATUS_FILE, default_status())
    if status.get("status") == "running" and status.get("host") == socket.gethostname():
        lock = read_lock()
        pid = status.get("pid") or lock.get("pid")
        if not pid_exists(pid):
            status = dict(status)
            status["status"] = "stale"
            status["overall_status"] = "stale"
            status["message"] = "Previous sync process is no longer running; stale lock/status detected."
    return status


def save_status(status):
    merged = default_status()
    merged.update(status)
    merged["updated_at"] = now_iso()
    write_json(STATUS_FILE, merged)
    return merged


def append_history(entry):
    append_jsonl(HISTORY_FILE, entry)


def append_notification_log(entry):
    append_jsonl(NOTIFICATION_LOG_FILE, entry)


def pid_exists(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False

    if os.name == "nt":
        kernel32 = ctypes.windll.kernel32
        handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == 259  # STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def remove_stale_lock():
    lock = read_lock()
    if lock.get("host") == socket.gethostname() and not pid_exists(lock.get("pid")):
        try:
            LOCK_FILE.unlink()
            return True
        except FileNotFoundError:
            return True
    return False


def acquire_lock():
    ensure_runtime_dir()
    for attempt in range(2):
        try:
            fd = os.open(str(LOCK_FILE), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            if attempt == 0 and remove_stale_lock():
                continue
            return None

    payload = {
        "pid": os.getpid(),
        "host": socket.gethostname(),
        "started_at": now_iso(),
    }
    os.write(fd, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    os.close(fd)
    return payload


def release_lock():
    try:
        LOCK_FILE.unlink()
    except FileNotFoundError:
        pass


def read_lock():
    return read_json(LOCK_FILE, {})
