import argparse
import sys
import traceback

import full_sync_pipeline
from sync_notifier import send_sync_notification
from sync_runtime import acquire_lock, append_history, now_iso, read_lock, release_lock, save_status


def main():
    parser = argparse.ArgumentParser(description="Scheduled sync runner for Crustacean Virus DB")
    parser.add_argument("--skip-ncbi", action="store_true", help="Run local-only sync without NCBI download")
    args = parser.parse_args()

    lock = acquire_lock()
    if not lock:
        status = {
            "status": "skipped",
            "overall_status": "skipped",
            "message": "Another scheduled sync is already running.",
            "started_at": now_iso(),
            "finished_at": now_iso(),
            "duration_seconds": 0,
            "lock": read_lock(),
        }
        save_status(status)
        append_history(status)
        return 2

    try:
        summary = full_sync_pipeline.main(skip_ncbi=args.skip_ncbi)
        if summary is None:
            summary = {
                "status": "failed",
                "overall_status": "failed",
                "message": "Sync pipeline returned no summary.",
                "started_at": now_iso(),
                "finished_at": now_iso(),
                "duration_seconds": 0,
            }
            save_status(summary)
            append_history(summary)
        send_sync_notification(summary)
        return 0 if summary.get("overall_status") == "success" else 1
    except Exception as e:
        summary = {
            "status": "failed",
            "overall_status": "failed",
            "message": f"Unhandled scheduled sync error: {e}",
            "started_at": now_iso(),
            "finished_at": now_iso(),
            "duration_seconds": 0,
            "traceback": traceback.format_exc(),
        }
        save_status(summary)
        append_history(summary)
        send_sync_notification(summary)
        return 1
    finally:
        release_lock()


if __name__ == "__main__":
    sys.exit(main())
