#!/usr/bin/env python3
"""Audit local Python scripts for sqlite connections without nearby FK enablement."""

from __future__ import annotations

import csv
import re
from pathlib import Path


ROOT = Path(".")
REPORTS = Path("reports")


def main() -> None:
    REPORTS.mkdir(exist_ok=True)
    rows = []
    for path in sorted(ROOT.rglob("*.py")):
        parts = set(path.parts)
        if "__pycache__" in parts or "vendor" in parts or "cdhit-4.8.1" in parts:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lines = text.splitlines()
        for i, line in enumerate(lines, 1):
            if "sqlite3.connect" not in line:
                continue
            window = "\n".join(lines[i - 1 : min(len(lines), i + 8)])
            has_fk = bool(re.search(r"PRAGMA\s+foreign_keys\s*=\s*ON", window, flags=re.I))
            rows.append(
                {
                    "path": str(path),
                    "line": i,
                    "connect_line": line.strip(),
                    "foreign_keys_enabled_nearby": int(has_fk),
                    "recommendation": "" if has_fk else "Add conn.execute('PRAGMA foreign_keys = ON') after connect if this script writes to DB.",
                }
            )
    out = REPORTS / "sqlite_connection_fk_audit.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["path", "line", "connect_line", "foreign_keys_enabled_nearby", "recommendation"],
        )
        writer.writeheader()
        writer.writerows(rows)
    missing = sum(1 for r in rows if not r["foreign_keys_enabled_nearby"])
    print(f"connections={len(rows)} missing_nearby_fk={missing} report={out}")


if __name__ == "__main__":
    main()
