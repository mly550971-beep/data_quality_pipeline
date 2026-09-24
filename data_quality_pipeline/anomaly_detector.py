"""
محرك جودة البيانات والشذوذ الإحصائي.

الفحوصات:
- عدد الصفوف والأعمدة.
- القيم المفقودة.
- الصفوف المكررة.
- القيم الرقمية غير المنطقية.
- الشذوذ باستخدام Z-Score و IQR.
- نسبة القيم الفريدة.
- مؤشرات بسيطة لجودة النص.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

import config


def _safe_float(value: Any) -> float | None:
    """تحويل قيمة إلى float بدون كسر الفحص."""
    try:
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def detect_anomalies(
    df: pd.DataFrame,
    source_name: str,
    source_type: str,
) -> dict:
    """
    فحص DataFrame وإرجاع نتيجة موحدة تصلح للتقرير.
    """
    result = {
        "source_name": source_name,
        "source_type": source_type,
        "status": "PASS",
        "score": 100.0,
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "issues": [],
        "column_metrics": [],
        "anomaly_rows": [],
    }

    if df.empty:
        result["status"] = "FAIL"
        result["score"] = 0.0
        result["issues"].append(
            {
                "rule": "EMPTY_DATASET",
                "severity": "CRITICAL",
                "message": "مصدر البيانات فارغ ولا يحتوي على سجلات قابلة للفحص.",
                "count": 1,
            }
        )
        return result

    working = df.copy()

    # توحيد أسماء الأعمدة لتجنب مشاكل HTML/Unicode.
    working.columns = [
        str(column).strip() if str(column).strip() else f"column_{i}"
        for i, column in enumerate(working.columns)
    ]

    # نستخدم keep=False في كل مكان (بما فيها حساب الـ score) حتى يكون رقم
    # "عدد الصفوف المكررة" متطابقاً بين الـ issue وبين result["duplicate_rows"]
    # بدل ما يظهر رقمين مختلفين لنفس المشكلة في التقرير الواحد.
    duplicate_mask = working.duplicated(keep=False)
    duplicate_count = int(duplicate_mask.sum())

    if duplicate_count:
        result["issues"].append(
            {
                "rule": "DUPLICATE_ROWS",
                "severity": "WARNING",
                "message": f"تم اكتشاف {duplicate_count} صف ضمن مجموعات مكررة بالكامل.",
                "count": duplicate_count,
            }
        )
        result["score"] -= min(20.0, duplicate_count / max(len(working), 1) * 100)

    missing_cells = int(working.isna().sum().sum())
    total_cells = max(int(working.shape[0] * working.shape[1]), 1)
    missing_rate = missing_cells / total_cells

    if missing_cells:
        severity = "WARNING" if missing_rate < 0.20 else "HIGH"
        result["issues"].append(
            {
                "rule": "MISSING_VALUES",
                "severity": severity,
                "message": f"يوجد {missing_cells} خلية مفقودة بنسبة {missing_rate:.2%}.",
                "count": missing_cells,
            }
        )
        result["score"] -= min(25.0, missing_rate * 50)

    # فحص كل عمود.
    numeric_columns = []
    for column in working.columns:
        series = working[column]
        non_null = series.dropna()

        unique_count = int(non_null.nunique())
        uniqueness = (
            unique_count / len(non_null) if len(non_null) else 0.0
        )

        metric = {
            "column": column,
            "dtype": str(series.dtype),
            "missing": int(series.isna().sum()),
            "missing_rate": float(series.isna().mean()),
            "unique": unique_count,
            "uniqueness_rate": uniqueness,
            "min": "",
            "max": "",
            "mean": "",
            "outlier_count": 0,
        }

        numeric = pd.to_numeric(series, errors="coerce")
        numeric_valid = numeric.dropna()

        # إذا كانت أغلبية القيم قابلة للتحويل إلى رقم، نعامل العمود كرقمي.
        if len(numeric_valid) >= max(3, int(len(non_null) * 0.70)):
            numeric_columns.append(column)

            metric["min"] = _safe_float(numeric_valid.min())
            metric["max"] = _safe_float(numeric_valid.max())
            metric["mean"] = _safe_float(numeric_valid.mean())

            # IQR.
            q1 = numeric_valid.quantile(0.25)
            q3 = numeric_valid.quantile(0.75)
            iqr = q3 - q1

            if iqr == 0:
                iqr_mask = pd.Series(False, index=working.index)
            else:
                lower = q1 - config.IQR_MULTIPLIER * iqr
                upper = q3 + config.IQR_MULTIPLIER * iqr
                iqr_mask = (numeric < lower) | (numeric > upper)

            # Z-Score.
            std = numeric_valid.std(ddof=0)
            if std == 0 or pd.isna(std):
                z_mask = pd.Series(False, index=working.index)
            else:
                z_scores = (numeric - numeric_valid.mean()) / std
                z_mask = z_scores.abs() > config.Z_SCORE_THRESHOLD

            anomaly_mask = (iqr_mask | z_mask).fillna(False)
            outlier_count = int(anomaly_mask.sum())
            metric["outlier_count"] = outlier_count

            if outlier_count:
                result["issues"].append(
                    {
                        "rule": "STATISTICAL_OUTLIER",
                        "severity": "WARNING",
                        "message": (
                            f"العمود '{column}' يحتوي على {outlier_count} "
                            "قيمة شاذة وفق IQR/Z-Score."
                        ),
                        "count": outlier_count,
                    }
                )
                result["score"] -= min(
                    15.0,
                    outlier_count / max(len(working), 1) * 30,
                )

            # التقاط قيم سالبة في أعمدة تبدو مالية/كمية.
            name_lower = str(column).lower()
            financial_keywords = (
                "amount",
                "price",
                "cost",
                "quantity",
                "total",
                "salary",
                "المبلغ",
                "السعر",
                "الكمية",
            )

            if any(keyword in name_lower for keyword in financial_keywords):
                negative_count = int((numeric < 0).sum())
                if negative_count:
                    result["issues"].append(
                        {
                            "rule": "NEGATIVE_NUMERIC_VALUE",
                            "severity": "WARNING",
                            "message": (
                                f"العمود '{column}' يحتوي على "
                                f"{negative_count} قيمة سالبة."
                            ),
                            "count": negative_count,
                        }
                    )
                    result["score"] -= min(10.0, negative_count * 2)

        metric["missing_rate"] = round(metric["missing_rate"], 4)
        metric["uniqueness_rate"] = round(metric["uniqueness_rate"], 4)
        result["column_metrics"].append(metric)

    # التقاط الصفوف التي تحتوي على قيم شاذة في أي عمود رقمي.
    if numeric_columns:
        anomaly_index = set()

        for column in numeric_columns:
            numeric = pd.to_numeric(working[column], errors="coerce")
            valid = numeric.dropna()

            if len(valid) < 3:
                continue

            q1 = valid.quantile(0.25)
            q3 = valid.quantile(0.75)
            iqr = q3 - q1

            iqr_mask = pd.Series(False, index=working.index)
            if iqr != 0:
                iqr_mask = (numeric < q1 - config.IQR_MULTIPLIER * iqr) | (
                    numeric > q3 + config.IQR_MULTIPLIER * iqr
                )

            std = valid.std(ddof=0)
            z_mask = pd.Series(False, index=working.index)
            if std != 0 and not pd.isna(std):
                z = (numeric - valid.mean()) / std
                z_mask = z.abs() > config.Z_SCORE_THRESHOLD

            for index in working.index[(iqr_mask | z_mask).fillna(False)]:
                anomaly_index.add(index)

        for index in sorted(anomaly_index)[:100]:
            row = working.loc[index].to_dict()
            result["anomaly_rows"].append(
                {
                    "row_number": int(index) + 1,
                    "values": {
                        str(k): (
                            None
                            if pd.isna(v)
                            else str(v)
                        )
                        for k, v in row.items()
                    },
                }
            )

    # تنظيف النتيجة.
    result["score"] = max(0.0, min(100.0, round(result["score"], 2)))

    if any(
        issue["severity"] == "CRITICAL"
        for issue in result["issues"]
    ):
        result["status"] = "FAIL"
    elif any(
        issue["severity"] in {"HIGH", "WARNING"}
        for issue in result["issues"]
    ):
        result["status"] = "WARN"

    result["duplicate_rows"] = duplicate_count

    result["missing_cells"] = missing_cells
    result["missing_rate"] = round(missing_rate, 4)

    return result
