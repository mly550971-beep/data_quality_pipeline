"""
المحرك الرئيسي للـ Enterprise Multi-Source Data Quality & OCR Observability Pipeline.

الترتيب:
1. فحص ملفات CSV/Excel.
2. فحص Scanned Images/PDFs عبر OCR.
3. فحص جداول قاعدة البيانات.
4. تجميع النتائج.
5. إنشاء تقرير HTML.
6. إرسال التقرير بالبريد عند تفعيل SMTP.
"""

from __future__ import annotations

import mimetypes
import smtplib
import logging
from email.message import EmailMessage
from datetime import datetime
from pathlib import Path

import pandas as pd

import config
from anomaly_detector import detect_anomalies
from db_helper import get_target_tables, read_table
from file_scanner import scan_tabular_files
from ocr_scanner import scan_scanned_papers
from report_generator import generate_html_report
from observability import ObservabilityStore
from rules_engine import apply_rules


def scan_database(observability=None, run_id=None) -> list[dict]:
    """فحص جميع جداول قاعدة البيانات المستهدفة."""
    results = []

    try:
        tables = get_target_tables()
    except Exception as exc:
        return [
            {
                "source_name": "DATABASE",
                "source_type": "DATABASE",
                "status": "FAIL",
                "score": 0.0,
                "row_count": 0,
                "column_count": 0,
                "issues": [
                    {
                        "rule": "DATABASE_CONNECTION_ERROR",
                        "severity": "CRITICAL",
                        "message": str(exc),
                        "count": 1,
                    }
                ],
                "column_metrics": [],
                "anomaly_rows": [],
            }
        ]

    for table in tables:
        try:
            df = read_table(table)

            result = detect_anomalies(
                df=df,
                source_name=table,
                source_type="DATABASE",
            )

            # تطبيق قواعد الجودة المخصصة (YAML) على جداول قاعدة البيانات.
            # ملاحظة: كانت هذه القواعد تُطبَّق سابقاً على ملفات CSV/Excel فقط
            # رغم أن أعمدة jadwal customer_orders (order_id, amount, order_date...)
            # مطابقة تماماً لأسماء الأعمدة المعرّفة في rules/quality_rules.yaml.
            result["issues"].extend(apply_rules(df))

            if observability and run_id:
                changes = observability.detect_schema_drift(run_id, table, df)
                for change in changes:
                    change_type = change["change_type"]
                    column_name = change["column_name"]
                    result["issues"].append({
                        "rule": "SCHEMA_DRIFT",
                        "severity": "CRITICAL" if change_type == "TYPE_CHANGED" else "HIGH",
                        "message": f"{change_type}: {column_name}",
                        "count": 1,
                    })
                if changes:
                    result["status"] = "FAIL" if any(i["severity"] == "CRITICAL" for i in result["issues"]) else "WARN"

            if result["issues"] and result["status"] == "PASS":
                result["status"] = "WARN"

            result["table_name"] = table
            results.append(result)

            # يتم حفظ نسخة من الصفوف الشاذة فقط للمراجعة، بدلاً من تعديل قاعدة البيانات.
            if result.get("anomaly_rows"):
                quarantine_file = (
                    config.DATA_QUARANTINE_DIR
                    / f"db_{table}_anomalies.csv"
                )

                anomaly_rows = [
                    {
                        "row_number": item["row_number"],
                        **item["values"],
                    }
                    for item in result["anomaly_rows"]
                ]

                pd.DataFrame(anomaly_rows).to_csv(
                    quarantine_file,
                    index=False,
                    encoding="utf-8-sig",
                )

        except Exception as exc:
            results.append(
                {
                    "source_name": table,
                    "source_type": "DATABASE",
                    "status": "FAIL",
                    "score": 0.0,
                    "row_count": 0,
                    "column_count": 0,
                    "issues": [
                        {
                            "rule": "TABLE_READ_ERROR",
                            "severity": "CRITICAL",
                            "message": f"تعذر قراءة الجدول: {exc}",
                            "count": 1,
                        }
                    ],
                    "column_metrics": [],
                    "anomaly_rows": [],
                }
            )

    return results


def send_email(report_path: Path) -> bool:
    """إرسال التقرير عبر SMTP عند تفعيل SMTP."""
    if not config.SMTP_ENABLED:
        return False

    if not config.SMTP_USERNAME or not config.SMTP_PASSWORD:
        raise RuntimeError(
            "SMTP_ENABLED=true لكن SMTP_USERNAME/SMTP_PASSWORD غير موجودين."
        )

    if not config.EMAIL_TO:
        raise RuntimeError(
            "SMTP_ENABLED=true لكن EMAIL_TO فارغ."
        )

    message = EmailMessage()
    message["Subject"] = config.EMAIL_SUBJECT
    message["From"] = config.EMAIL_FROM
    message["To"] = ", ".join(config.EMAIL_TO)
    message.set_content(
        "تم إنشاء تقرير Enterprise Multi-Source Data Quality & OCR Observability. "
        "التقرير مرفق بصيغة HTML."
    )

    report_bytes = report_path.read_bytes()
    message.add_attachment(
        report_bytes,
        maintype="text",
        subtype="html",
        filename=report_path.name,
    )

    with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as server:
        server.starttls()
        server.login(config.SMTP_USERNAME, config.SMTP_PASSWORD)
        server.send_message(message)

    return True


def run_pipeline() -> Path:
    """تشغيل الـ pipeline بالكامل مع Audit/Observability."""
    print("=" * 80)
    print("Enterprise Multi-Source Data Quality & OCR Observability Pipeline")
    print("=" * 80)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
        handlers=[
            logging.FileHandler(config.REPORTS_DIR / "pipeline.log", encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )
    observability = ObservabilityStore(config.BASE_DIR / "observability.db")
    run_id, started = observability.start_run()
    logging.info("Started pipeline run %s", run_id)
    all_results = []

    print(f"\nRUN ID: {run_id}")
    print("\n[1/3] فحص CSV/Excel...")
    file_results = scan_tabular_files(observability=observability, run_id=run_id)
    all_results.extend(file_results)
    print(f"      تم فحص {len(file_results)} نتيجة مصدر رقمي.")

    print("\n[2/3] فحص الصور وPDF عبر OCR...")
    ocr_results = scan_scanned_papers(observability=observability, run_id=run_id)
    all_results.extend(ocr_results)
    print(f"      تم فحص {len(ocr_results)} مستند OCR.")

    print("\n[3/3] فحص قاعدة البيانات...")
    db_results = scan_database(observability=observability, run_id=run_id)
    all_results.extend(db_results)
    print(f"      تم فحص {len(db_results)} جدول/نتيجة Database.")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = config.REPORTS_DIR / f"quality_report_{timestamp}.html"

    generate_html_report(
        results=all_results,
        output_path=report_path,
    )

    observability.finish_run(run_id, started, all_results)
    print(f"\n[REPORT] {report_path}")

    if config.SMTP_ENABLED:
        try:
            send_email(report_path)
            print("[EMAIL] تم إرسال التقرير بنجاح.")
        except Exception as exc:
            print(f"[EMAIL ERROR] {exc}")

    logging.info("Completed pipeline run %s", run_id)
    print(f"\nاكتمل التشغيل. Run ID: {run_id}")
    return report_path


if __name__ == "__main__":
    run_pipeline()
