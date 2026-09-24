"""
وحدة الـ Observability: تخزين تاريخ التشغيلات، نتائج الجودة، وكشف Schema Drift.

ملاحظة تصميم مهمة بخصوص Schema Drift:
عندما يتم فحص مصدر بيانات لأول مرة في تاريخ المشروع، لا يوجد "Snapshot" سابق
لمقارنته به. في هذه الحالة نقوم فقط بتسجيل الـ Schema الحالي كخط أساس (Baseline)
ولا نُبلغ عن أي تغييرات، لأن عدم وجود تاريخ سابق لا يعني أن كل عمود "تمت إضافته
حديثاً" - هذا سيؤدي إلى إنذارات كاذبة في كل تشغيل أول لأي مصدر جديد.
"""

from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd


class ObservabilityStore:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self):
        """
        فتح اتصال SQLite وضمان إغلاقه دائماً.

        ملاحظة: استخدام sqlite3.Connection مباشرة كـ context manager
        (`with sqlite3.connect(...) as c`) لا يغلق الاتصال فعلياً؛ فقط يدير
        الـ transaction (commit/rollback). لذلك نلف الاتصال هنا صراحةً
        ونغلقه في finally لمنع تسرب الاتصالات المفتوحة، خاصة في العمليات
        طويلة العمر مثل لوحة Streamlit التي تفتح اتصالات متكررة.
        """
        connection = sqlite3.connect(str(self.db_path))
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self):
        with self._connect() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS pipeline_runs(
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT,
                    finished_at TEXT,
                    duration_seconds REAL,
                    total_sources INTEGER,
                    passed INTEGER,
                    warnings INTEGER,
                    failed INTEGER,
                    average_score REAL
                );
                CREATE TABLE IF NOT EXISTS quality_results(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    source_name TEXT,
                    source_type TEXT,
                    status TEXT,
                    score REAL,
                    row_count INTEGER,
                    column_count INTEGER,
                    ocr_confidence REAL
                );
                CREATE TABLE IF NOT EXISTS quality_issues(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    source_name TEXT,
                    rule TEXT,
                    severity TEXT,
                    message TEXT,
                    count INTEGER
                );
                CREATE TABLE IF NOT EXISTS schema_snapshots(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_name TEXT,
                    captured_at TEXT,
                    schema_json TEXT
                );
                CREATE TABLE IF NOT EXISTS schema_changes(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    source_name TEXT,
                    change_type TEXT,
                    column_name TEXT,
                    previous_type TEXT,
                    current_type TEXT,
                    detected_at TEXT
                );
                """
            )

    def start_run(self):
        started = datetime.now()
        run_id = "DQ-" + started.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6].upper()
        with self._connect() as c:
            c.execute(
                "INSERT INTO pipeline_runs(run_id, started_at) VALUES (?, ?)",
                (run_id, started.isoformat()),
            )
        return run_id, started

    def finish_run(self, run_id, started, results):
        finished = datetime.now()
        total = len(results)
        passed = sum(r.get("status") == "PASS" for r in results)
        warnings = sum(r.get("status") == "WARN" for r in results)
        failed = sum(r.get("status") == "FAIL" for r in results)
        avg = sum(float(r.get("score", 0)) for r in results) / total if total else 0

        with self._connect() as c:
            c.execute(
                """
                UPDATE pipeline_runs
                SET finished_at = ?, duration_seconds = ?, total_sources = ?,
                    passed = ?, warnings = ?, failed = ?, average_score = ?
                WHERE run_id = ?
                """,
                (
                    finished.isoformat(),
                    (finished - started).total_seconds(),
                    total,
                    passed,
                    warnings,
                    failed,
                    avg,
                    run_id,
                ),
            )

            for r in results:
                c.execute(
                    """
                    INSERT INTO quality_results
                    (run_id, source_name, source_type, status, score, row_count, column_count, ocr_confidence)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        r.get("source_name", ""),
                        r.get("source_type", ""),
                        r.get("status", ""),
                        float(r.get("score", 0)),
                        int(r.get("row_count", 0)),
                        int(r.get("column_count", 0)),
                        r.get("ocr_confidence"),
                    ),
                )
                for i in r.get("issues", []):
                    c.execute(
                        """
                        INSERT INTO quality_issues
                        (run_id, source_name, rule, severity, message, count)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            r.get("source_name", ""),
                            i.get("rule", ""),
                            i.get("severity", ""),
                            i.get("message", ""),
                            int(i.get("count", 0)),
                        ),
                    )

    @staticmethod
    def dataframe_schema(df) -> dict:
        return {str(c): str(t) for c, t in zip(df.columns, df.dtypes)}

    def detect_schema_drift(self, run_id, source_name, df) -> list[dict]:
        """
        كشف تغييرات الـ Schema مقارنة بآخر نسخة محفوظة لنفس المصدر.

        أول مرة يتم فحص مصدر فيها (لا يوجد Snapshot سابق) نكتفي بحفظ
        الـ Schema الحالي كخط أساس ونعيد قائمة تغييرات فارغة، بدلاً من
        اعتبار كل عمود موجود "عمود مُضاف حديثاً".
        """
        current = self.dataframe_schema(df)
        now = datetime.now().isoformat()
        changes: list[dict] = []

        with self._connect() as c:
            row = c.execute(
                "SELECT schema_json FROM schema_snapshots WHERE source_name = ? ORDER BY id DESC LIMIT 1",
                (source_name,),
            ).fetchone()

            is_first_snapshot = row is None
            previous = json.loads(row[0]) if row else {}

            if not is_first_snapshot:
                for col in sorted(set(previous) - set(current)):
                    changes.append(
                        {
                            "change_type": "REMOVED_COLUMN",
                            "column_name": col,
                            "previous_type": previous[col],
                            "current_type": "",
                        }
                    )
                for col in sorted(set(current) - set(previous)):
                    changes.append(
                        {
                            "change_type": "ADDED_COLUMN",
                            "column_name": col,
                            "previous_type": "",
                            "current_type": current[col],
                        }
                    )
                for col in sorted(set(previous) & set(current)):
                    if previous[col] != current[col]:
                        changes.append(
                            {
                                "change_type": "TYPE_CHANGED",
                                "column_name": col,
                                "previous_type": previous[col],
                                "current_type": current[col],
                            }
                        )

                for ch in changes:
                    c.execute(
                        """
                        INSERT INTO schema_changes
                        (run_id, source_name, change_type, column_name, previous_type, current_type, detected_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            run_id,
                            source_name,
                            ch["change_type"],
                            ch["column_name"],
                            ch["previous_type"],
                            ch["current_type"],
                            now,
                        ),
                    )

            c.execute(
                "INSERT INTO schema_snapshots(source_name, captured_at, schema_json) VALUES (?, ?, ?)",
                (source_name, now, json.dumps(current, ensure_ascii=False)),
            )

        return changes

    def history(self, limit=30) -> list[dict]:
        with self._connect() as c:
            rows = c.execute(
                """
                SELECT run_id, started_at, finished_at, duration_seconds,
                       total_sources, passed, warnings, failed, average_score
                FROM pipeline_runs
                ORDER BY started_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        keys = [
            "run_id", "started_at", "finished_at", "duration_seconds",
            "total_sources", "passed", "warnings", "failed", "average_score",
        ]
        return [dict(zip(keys, r)) for r in rows]
