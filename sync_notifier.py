import json
import smtplib
import urllib.error
import urllib.request
from email.mime.text import MIMEText

from sync_runtime import (
    NOTIFICATION_CONFIG_EXAMPLE_FILE,
    NOTIFICATION_CONFIG_FILE,
    append_notification_log,
    now_iso,
    read_json,
    write_json,
)


DEFAULT_CONFIG = {
    "webhook": {
        "enabled": False,
        "url": "",
        "headers": {},
    },
    "email": {
        "enabled": False,
        "smtp_host": "",
        "smtp_port": 587,
        "use_tls": True,
        "username": "",
        "password": "",
        "from_addr": "",
        "to_addrs": [],
    },
    "notify_on": ["success", "partial", "failed"],
}


def ensure_example_config():
    if not NOTIFICATION_CONFIG_EXAMPLE_FILE.exists():
        write_json(NOTIFICATION_CONFIG_EXAMPLE_FILE, DEFAULT_CONFIG)


def load_config():
    ensure_example_config()
    cfg = read_json(NOTIFICATION_CONFIG_FILE, DEFAULT_CONFIG)
    merged = json.loads(json.dumps(DEFAULT_CONFIG))
    for key, value in cfg.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key].update(value)
        else:
            merged[key] = value
    return merged


def format_summary(summary):
    failed_steps = [
        name for name, ok in summary.get("step_results", {}).items() if not ok
    ]
    lines = [
        f"Status: {summary.get('overall_status', 'unknown')}",
        f"Started: {summary.get('started_at', '')}",
        f"Finished: {summary.get('finished_at', '')}",
        f"Duration: {summary.get('duration_seconds', 0):.1f} s",
        f"New records: {summary.get('new_count', 0)}",
        f"Backup: {summary.get('backup', 'N/A')}",
    ]
    if failed_steps:
        lines.append("Failed steps: " + ", ".join(failed_steps))
    else:
        lines.append("Failed steps: none")
    return "\n".join(lines)


def send_webhook(config, title, body, summary):
    webhook = config["webhook"]
    if not webhook.get("enabled") or not webhook.get("url"):
        return {"channel": "webhook", "skipped": True}

    payload = {
        "title": title,
        "message": body,
        "status": summary.get("overall_status"),
        "summary": summary,
    }
    req = urllib.request.Request(
        webhook["url"],
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", **webhook.get("headers", {})},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return {"channel": "webhook", "status_code": resp.status}


def send_email(config, title, body):
    email_cfg = config["email"]
    if not email_cfg.get("enabled"):
        return {"channel": "email", "skipped": True}

    required = ["smtp_host", "smtp_port", "username", "password", "from_addr"]
    if any(not email_cfg.get(k) for k in required) or not email_cfg.get("to_addrs"):
        return {"channel": "email", "skipped": True, "reason": "incomplete_config"}

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = title
    msg["From"] = email_cfg["from_addr"]
    msg["To"] = ", ".join(email_cfg["to_addrs"])

    server = smtplib.SMTP(email_cfg["smtp_host"], int(email_cfg["smtp_port"]), timeout=20)
    try:
        if email_cfg.get("use_tls", True):
            server.starttls()
        server.login(email_cfg["username"], email_cfg["password"])
        server.sendmail(email_cfg["from_addr"], email_cfg["to_addrs"], msg.as_string())
    finally:
        server.quit()
    return {"channel": "email", "sent_to": email_cfg["to_addrs"]}


def send_sync_notification(summary):
    config = load_config()
    status = summary.get("overall_status", "unknown")
    if status not in set(config.get("notify_on", [])):
        result = {"status": status, "skipped": True, "reason": "status_filtered"}
        append_notification_log({"time": now_iso(), "result": result, "summary": summary})
        return result

    title = f"[CrustaVirus DB] Sync {status.upper()}"
    body = format_summary(summary)
    results = []
    errors = []

    for sender in (send_webhook, send_email):
        try:
            if sender is send_email:
                results.append(sender(config, title, body))
            else:
                results.append(sender(config, title, body, summary))
        except (urllib.error.URLError, smtplib.SMTPException, TimeoutError, OSError) as e:
            errors.append({"channel": sender.__name__, "error": str(e)})

    event = {
        "time": now_iso(),
        "title": title,
        "status": status,
        "results": results,
        "errors": errors,
    }
    append_notification_log(event)
    return event
