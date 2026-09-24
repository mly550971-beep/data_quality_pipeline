"""
ماسح ملفات CSV وExcel.

يقرأ الملفات ديناميكياً من data_input/،
ويحوّل كل Sheet في Excel إلى DataFrame مستقل،
ثم يمرر البيانات إلى anomaly_detector.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd

import config
from anomaly_detector import detect_anomalies
from rules_engine import apply_rules


def _read_csv(path: Path) -> dict[str, pd.DataFrame]:
    """قراءة CSV مع محاولة التعامل مع UTF-8 ثم cp1256."""
    try:
        return {"CSV": pd.read_csv(path)}
    except UnicodeDecodeError:
        return {"CSV": pd.read_csv(path, encoding="cp1256")}


def _read_excel(path: Path) -> dict[str, pd.DataFrame]:
    """قراءة جميع الأوراق داخل ملف Excel."""
    sheets = pd.read_excel(path, sheet_name=None)
    return {str(name): frame for name, frame in sheets.items()}


def scan_tabular_files(observability=None, run_id=None) -> list[dict]:
    """فحص كل ملفات CSV/Excel الموجودة في data_input/."""
    results = []

    for path in sorted(config.DATA_INPUT_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in config.TABULAR_EXTENSIONS:
            continue

        try:
            if path.suffix.lower() == ".csv":
                sheets = _read_csv(path)
            else:
                sheets = _read_excel(path)

            file_had_failure = False

            for sheet_name, df in sheets.items():
                source_name = f"{path.name}::{sheet_name}"

                result = detect_anomalies(
                    df=df,
                    source_name=source_name,
                    source_type="DIGITAL_FILE",
                )
                result["file_path"] = str(path)
                result["issues"].extend(apply_rules(df))
                if observability and run_id:
                    changes = observability.detect_schema_drift(run_id, source_name, df)
                    for change in changes:
                        change_type = change["change_type"]
                        column_name = change["column_name"]
                        result["issues"].append({
                            "rule": "SCHEMA_DRIFT",
                            "severity": "CRITICAL" if change_type == "TYPE_CHANGED" else "HIGH",
                            "message": f"{change_type}: {column_name}",
                            "count": 1,
                        })
                if result["issues"] and result["status"] == "PASS": result["status"] = "WARN"
                result["sheet_name"] = sheet_name
                results.append(result)

                if result["status"] == "FAIL":
                    file_had_failure = True

            # ننقل الملف ككل إلى processed/quarantine.
            target_dir = (
                config.DATA_QUARANTINE_DIR
                if file_had_failure
                else config.DATA_PROCESSED_DIR
            )

            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / path.name

            # منع الكتابة فوق ملف سابق.
            counter = 1
            while target.exists():
                target = target_dir / f"{path.stem}_{counter}{path.suffix}"
                counter += 1

            # نستخدم shutil.move بدلاً من Path.replace لأن replace/os.rename
            # يفشل بخطأ "Invalid cross-device link" إذا كانت المجلدات على
            # أقراص/Volumes مختلفة (شائع في Docker مع bind mounts منفصلة).
            shutil.move(str(path), str(target))

        except Exception as exc:
            results.append(
                {
                    "source_name": path.name,
                    "source_type": "DIGITAL_FILE",
                    "status": "FAIL",
                    "score": 0.0,
                    "row_count": 0,
                    "column_count": 0,
                    "issues": [
                        {
                            "rule": "FILE_READ_ERROR",
                            "severity": "CRITICAL",
                            "message": f"تعذر قراءة الملف: {exc}",
                            "count": 1,
                        }
                    ],
                    "column_metrics": [],
                    "anomaly_rows": [],
                    "file_path": str(path),
                    "sheet_name": "",
                }
            )

            # نقل الملف التالف/غير القابل للقراءة إلى quarantine.
            try:
                target = config.DATA_QUARANTINE_DIR / path.name
                counter = 1
                while target.exists():
                    target = (
                        config.DATA_QUARANTINE_DIR
                        / f"{path.stem}_{counter}{path.suffix}"
                    )
                    counter += 1
                shutil.move(str(path), str(target))
            except Exception:
                pass

    return results
