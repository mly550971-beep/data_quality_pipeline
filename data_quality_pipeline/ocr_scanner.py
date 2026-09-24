"""
وحدة OCR Observability.

المسار:
Image/PDF -> Pillow/PyMuPDF -> Tesseract -> نص -> DataFrame
                                           -> confidence/quality metrics

يدعم PNG/JPG/JPEG/TIFF/PDF.
- Pillow تستخدم لمعالجة الصور.
- pytesseract هو محرك الربط مع Tesseract OCR.
- PyMuPDF يستخدم فقط لتحويل صفحات PDF إلى صور، لأن Pillow وحدها
  ليست أداة موثوقة لتحويل PDF متعدد الصفحات إلى صور OCR.

النتيجة النهائية DataFrame موحد يمكن تمريره إلى anomaly_detector.
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Iterable

import pandas as pd
import pytesseract
from PIL import Image, ImageOps, ImageFilter
from pytesseract import Output

import config
from ocr_extractor import extract_key_value_fields, detect_ocr_table

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None


if config.TESSERACT_CMD:
    pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD


def preprocess_image(image: Image.Image) -> Image.Image:
    """تحسين الصورة قبل OCR."""
    image = image.convert("L")
    image = ImageOps.autocontrast(image)
    image = image.filter(ImageFilter.SHARPEN)

    # تكبير بسيط يساعد Tesseract في الأوراق منخفضة الدقة.
    width, height = image.size
    if width < 1600:
        scale = 1600 / max(width, 1)
        image = image.resize(
            (int(width * scale), int(height * scale))
        )

    return image


def _ocr_image(image: Image.Image) -> tuple[str, float, pd.DataFrame]:
    """تنفيذ OCR وإرجاع النص ومتوسط الثقة وبيانات الكلمات."""
    processed = preprocess_image(image)

    text = pytesseract.image_to_string(
        processed,
        lang=config.OCR_LANG,
        config="--psm 6",
    )

    data = pytesseract.image_to_data(
        processed,
        lang=config.OCR_LANG,
        config="--psm 6",
        output_type=Output.DATAFRAME,
    )

    if data is None or data.empty:
        confidence = 0.0
        data = pd.DataFrame()
    else:
        data["conf"] = pd.to_numeric(data["conf"], errors="coerce")
        valid_conf = data.loc[data["conf"] >= 0, "conf"]
        confidence = float(valid_conf.mean()) if not valid_conf.empty else 0.0

    return text.strip(), confidence, data


def _extract_numeric_values(text: str) -> list[float]:
    """استخراج الأرقام الظاهرة في النص."""
    values = []
    pattern = r"[-+]?\d+(?:[.,]\d+)?"

    for match in re.findall(pattern, text):
        try:
            values.append(float(match.replace(",", "")))
        except ValueError:
            continue

    return values


def _text_to_dataframe(
    text: str,
    source_name: str,
    page_number: int,
    confidence: float,
) -> pd.DataFrame:
    """
    تحويل النص إلى DataFrame.

    كل سطر OCR يصبح سجلاً، مع استخراج الأرقام الموجودة داخله.
    هذا التصميم يجعل نتائج OCR قابلة للفحص بنفس محرك الجودة.
    """
    rows = []

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()

        if not line:
            continue

        numbers = _extract_numeric_values(line)

        rows.append(
            {
                "source_file": source_name,
                "page": page_number,
                "line_number": line_number,
                "ocr_text": line,
                "numeric_value_count": len(numbers),
                "numeric_values": ", ".join(str(x) for x in numbers),
                "ocr_confidence": round(confidence, 2),
                "text_length": len(line),
            }
        )

    # حتى الملف الذي لم ينتج أسطراً سيصل إلى detector كسجل واحد.
    if not rows:
        rows.append(
            {
                "source_file": source_name,
                "page": page_number,
                "line_number": 0,
                "ocr_text": "",
                "numeric_value_count": 0,
                "numeric_values": "",
                "ocr_confidence": round(confidence, 2),
                "text_length": 0,
            }
        )

    return pd.DataFrame(rows)


def _pdf_pages(path: Path) -> Iterable[tuple[int, Image.Image]]:
    """تحويل صفحات PDF إلى صور Pillow."""
    if fitz is None:
        raise RuntimeError(
            "ملفات PDF تحتاج PyMuPDF. ثبّت الحزمة: pip install pymupdf"
        )

    document = fitz.open(path)

    try:
        for page_index in range(len(document)):
            page = document.load_page(page_index)

            # دقة تقريبية 180 DPI.
            matrix = fitz.Matrix(180 / 72, 180 / 72)
            pixmap = page.get_pixmap(
                matrix=matrix,
                alpha=False,
            )

            image = Image.frombytes(
                "RGB",
                [pixmap.width, pixmap.height],
                pixmap.samples,
            )

            yield page_index + 1, image
    finally:
        document.close()


def scan_single_ocr_file(path: Path) -> tuple[pd.DataFrame, dict]:
    """فحص ملف OCR واحد."""
    frames = []
    page_metrics = []

    if path.suffix.lower() == ".pdf":
        pages = _pdf_pages(path)
    else:
        image = Image.open(path)
        pages = [(1, image)]

    for page_number, image in pages:
        text, confidence, _ = _ocr_image(image)

        page_metrics.append(
            {
                "page": page_number,
                "confidence": round(confidence, 2),
                "text_length": len(text),
            }
        )

        frames.append(
            _text_to_dataframe(
                text=text,
                source_name=path.name,
                page_number=page_number,
                confidence=confidence,
            )
        )

    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()

    full_text_length = int(df["text_length"].sum()) if not df.empty else 0
    average_confidence = (
        float(sum(x["confidence"] for x in page_metrics) / len(page_metrics))
        if page_metrics
        else 0.0
    )

    # ملاحظات جودة OCR مستقلة عن anomaly_detector.
    issues = []

    if full_text_length < config.OCR_MIN_TEXT_LENGTH:
        issues.append(
            {
                "rule": "OCR_EMPTY_OR_TOO_SHORT",
                "severity": "CRITICAL",
                "message": "النص المستخرج فارغ أو قصير جداً.",
                "count": 1,
            }
        )

    if average_confidence < config.OCR_MIN_CONFIDENCE:
        issues.append(
            {
                "rule": "LOW_OCR_CONFIDENCE",
                "severity": "HIGH",
                "message": (
                    f"متوسط ثقة OCR هو {average_confidence:.2f}% "
                    f"وهو أقل من الحد {config.OCR_MIN_CONFIDENCE:.2f}%."
                ),
                "count": 1,
            }
        )

    full_text = "\n".join(df["ocr_text"].astype(str).tolist()) if not df.empty and "ocr_text" in df.columns else ""
    table = detect_ocr_table(full_text)
    return df, {
        "average_confidence": round(average_confidence, 2),
        "page_metrics": page_metrics,
        "ocr_issues": issues,
        "structured_fields": extract_key_value_fields(full_text),
        "extracted_table_rows": int(len(table)),
        "extracted_table_columns": int(len(table.columns)),
    }


def scan_scanned_papers(observability=None, run_id=None) -> list[dict]:
    """
    فحص جميع الصور وPDFs الموجودة في scanned_papers/.

    observability/run_id اختياريان: عند تمريرهما، تتم مراقبة "Schema" الحقول
    المستخرجة من كل مستند (customer, invoice_id, amount, date, status...)
    بنفس آلية Schema Drift المستخدمة مع ملفات CSV/Excel وجداول قاعدة البيانات،
    بدلاً من ترك مصادر OCR بدون أي مراقبة Schema على الإطلاق.
    """
    results = []

    for path in sorted(config.SCANNED_PAPERS_DIR.iterdir()):
        if not path.is_file() or path.suffix.lower() not in config.OCR_EXTENSIONS:
            continue

        try:
            df, ocr_meta = scan_single_ocr_file(path)

            result = {
                "source_name": path.name,
                "source_type": "OCR_DOCUMENT",
                "file_path": str(path),
                "sheet_name": "",
                "ocr_confidence": ocr_meta["average_confidence"],
                "ocr_pages": ocr_meta["page_metrics"],
            }

            from anomaly_detector import detect_anomalies

            quality_result = detect_anomalies(
                df=df,
                source_name=path.name,
                source_type="OCR_DOCUMENT",
            )

            # دمج ملاحظات OCR مع ملاحظات جودة البيانات.
            quality_result["issues"].extend(ocr_meta["ocr_issues"])
            quality_result["ocr_confidence"] = ocr_meta["average_confidence"]
            quality_result["ocr_pages"] = ocr_meta["page_metrics"]
            quality_result["structured_fields"] = ocr_meta["structured_fields"]
            quality_result["extracted_table_rows"] = ocr_meta["extracted_table_rows"]
            quality_result["extracted_table_columns"] = ocr_meta["extracted_table_columns"]

            # مراقبة Schema Drift على الحقول المستخرجة من المستند (مثل
            # customer/invoice_id/amount/date/status)، بنفس الآلية المستخدمة
            # لملفات CSV/Excel وجداول قاعدة البيانات.
            if observability and run_id and ocr_meta["structured_fields"]:
                fields_df = pd.DataFrame([ocr_meta["structured_fields"]])
                changes = observability.detect_schema_drift(run_id, path.name, fields_df)
                for change in changes:
                    change_type = change["change_type"]
                    column_name = change["column_name"]
                    quality_result["issues"].append({
                        "rule": "SCHEMA_DRIFT",
                        "severity": "CRITICAL" if change_type == "TYPE_CHANGED" else "HIGH",
                        "message": f"{change_type}: {column_name}",
                        "count": 1,
                    })

            if any(
                issue["severity"] == "CRITICAL"
                for issue in quality_result["issues"]
            ):
                quality_result["status"] = "FAIL"
            elif quality_result["issues"]:
                quality_result["status"] = "WARN"

            # خصم إضافي بناءً على جودة OCR.
            if ocr_meta["average_confidence"] < config.OCR_MIN_CONFIDENCE:
                quality_result["score"] = max(
                    0.0,
                    quality_result["score"] - 20.0,
                )

            result.update(quality_result)
            results.append(result)

            target_dir = (
                config.DATA_QUARANTINE_DIR
                if result["status"] == "FAIL"
                else config.DATA_PROCESSED_DIR
            )
            target_dir.mkdir(parents=True, exist_ok=True)

            target = target_dir / path.name
            counter = 1
            while target.exists():
                target = target_dir / f"{path.stem}_{counter}{path.suffix}"
                counter += 1

            # shutil.move بدلاً من Path.replace لتفادي فشل النقل بين
            # أقراص/Volumes مختلفة (Invalid cross-device link).
            shutil.move(str(path), str(target))

        except Exception as exc:
            results.append(
                {
                    "source_name": path.name,
                    "source_type": "OCR_DOCUMENT",
                    "status": "FAIL",
                    "score": 0.0,
                    "row_count": 0,
                    "column_count": 0,
                    "issues": [
                        {
                            "rule": "OCR_PROCESSING_ERROR",
                            "severity": "CRITICAL",
                            "message": f"تعذر تنفيذ OCR: {exc}",
                            "count": 1,
                        }
                    ],
                    "column_metrics": [],
                    "anomaly_rows": [],
                    "file_path": str(path),
                    "sheet_name": "",
                    "ocr_confidence": 0.0,
                    "ocr_pages": [],
                }
            )

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
