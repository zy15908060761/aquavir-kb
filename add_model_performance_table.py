#!/usr/bin/env python3
"""Create model_performance_metrics table for recording ML model evaluations.

Addresses CRITICAL gap C-R7: the database has no record of how accurate
the virulence/temperature prediction models are. Reviewers will ask for
accuracy, recall, F1, and cross-validation results — this table provides
the schema to store them.

The table is created empty; actual metric values must be populated by
re-running model training/evaluation scripts. Placeholder entries are
inserted to document that the table exists and is ready for population.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path

from db_utils import backup_database as wal_safe_backup, get_db

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "crustacean_virus_core.db"
BACKUP_DIR = BASE_DIR / "backups"


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS model_performance_metrics (
    metric_id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_name TEXT NOT NULL,
    target_column TEXT NOT NULL,
    metric_name TEXT NOT NULL CHECK (
        metric_name IN (
            'accuracy', 'precision', 'recall', 'f1', 'auc_roc',
            'mcc', 'r2', 'mae', 'rmse', 'cross_val_mean', 'cross_val_std',
            'balanced_accuracy', 'sensitivity', 'specificity'
        )
    ),
    metric_value REAL NOT NULL,
    cv_folds INTEGER,
    test_set_size INTEGER,
    train_set_size INTEGER,
    feature_count INTEGER,
    hyperparameters TEXT,
    evaluation_timestamp TEXT,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


def main() -> None:
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    backup_path = wal_safe_backup(DB_PATH, BACKUP_DIR, label="add_model_metrics")
    print(f"Backup: {backup_path}")

    conn = get_db()
    try:
        conn.execute(CREATE_TABLE_SQL)

        # Check if table already has data
        existing = conn.execute(
            "SELECT COUNT(*) FROM model_performance_metrics"
        ).fetchone()[0]

        if existing > 0:
            print(f"model_performance_metrics already exists with {existing} rows. No action needed.")
        else:
            print("model_performance_metrics table created (empty).")
            print("Populate with real metric values after re-running model training.")
            print("Example INSERT:")
            print("  INSERT INTO model_performance_metrics (model_name, target_column, metric_name,")
            print("      metric_value, cv_folds, test_set_size, train_set_size)")
            print("  VALUES ('virulence_model', 'virulence_level', 'f1', 0.85, 5, 200, 800);")

        # Add provenance entry documenting table existence
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        conn.execute(
            """
            INSERT OR IGNORE INTO data_provenance (
                table_name, record_id, data_source, confidence_level,
                verification_method, curator_notes
            )
            VALUES ('model_performance_metrics', 0, 'ml_model_evaluation',
                    'unverified', 'model_retraining_required',
                    'Table created {timestamp}; metric values must be populated by re-running model training/evaluation scripts before publication.')
            """

        conn.commit()
        print("Provenance entries added for model_performance_metrics.")

    finally:
        conn.close()

    print("\nDone. Run model training scripts and UPDATE model_performance_metrics with real values.")


if __name__ == "__main__":
    main()
