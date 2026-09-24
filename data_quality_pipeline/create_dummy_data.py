"""
إنشاء بيانات تجريبية كاملة للمشروع.

ينشئ:
- CSV يحتوي على قيم ناقصة وتكرار وشذوذ.
- Excel يحتوي على Sheet إضافي.
- SQLite database وجدول تجريبي.
- صورة PNG تحتوي على نص وأرقام لاختبار OCR.
- PDF اختياري إذا كانت PyMuPDF مثبتة.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

import config
from db_helper import initialize_demo_database


def create_csv() -> None:
    """إنشاء ملف CSV تجريبي."""
    df = pd.DataFrame(
        [
            [1, "Ahmed", "ahmed@example.com", 120.50, "PAID"],
            [2, "Mona", "mona@example.com", 450.00, "PAID"],
            [2, "Mona", "mona@example.com", 450.00, "PAID"],
            [3, None, "invalid-email", 999999.00, "UNKNOWN"],
            [4, "Omar", None, -100.00, "REFUND"],
            [5, "Sara", "sara@example.com", 80.00, "PAID"],
        ],
        columns=["id", "customer", "email", "amount", "status"],
    )

    df.to_csv(
        config.DATA_INPUT_DIR / "sample_orders.csv",
        index=False,
        encoding="utf-8-sig",
    )


def create_excel() -> None:
    """إنشاء ملف Excel تجريبي بورقتين."""
    customers = pd.DataFrame(
        [
            [101, "Ali", "Cairo"],
            [102, "Nour", "Giza"],
            [103, None, "Alexandria"],
            [103, None, "Alexandria"],
        ],
        columns=["customer_id", "name", "city"],
    )

    payments = pd.DataFrame(
        [
            [1, 250.0, "2026-09-01"],
            [2, 300.0, "2026-09-02"],
            [3, 999999.0, "bad-date"],
            [4, None, "2026-09-04"],
        ],
        columns=["payment_id", "amount", "payment_date"],
    )

    with pd.ExcelWriter(
        config.DATA_INPUT_DIR / "sample_workbook.xlsx",
        engine="openpyxl",
    ) as writer:
        customers.to_excel(writer, sheet_name="Customers", index=False)
        payments.to_excel(writer, sheet_name="Payments", index=False)


def create_ocr_image() -> None:
    """إنشاء صورة مستند بسيطة تحتوي على بيانات قابلة للقراءة بواسطة OCR."""
    image = Image.new("RGB", (1800, 1000), "white")
    draw = ImageDraw.Draw(image)

    # قائمة مسارات خطوط شائعة على Windows/Linux/macOS بترتيب الأولوية.
    # "arial.ttf" لوحده يعمل على Windows فقط؛ على Linux/macOS/Docker كان
    # يفشل بصمت ويرجع لخط PIL الافتراضي (bitmap صغير جداً وغير قابل للتكبير)،
    # مما ينتج صوراً OCR ضعيفة الجودة بشكل عشوائي حسب بيئة التشغيل.
    FONT_CANDIDATES = [
        "arial.ttf",  # Windows
        "Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux (Debian/Ubuntu)
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/Library/Fonts/Arial.ttf",  # macOS
        "/System/Library/Fonts/Supplemental/Arial.ttf",
    ]

    def _load_font(size: int) -> ImageFont.ImageFont:
        for candidate in FONT_CANDIDATES:
            try:
                return ImageFont.truetype(candidate, size)
            except OSError:
                continue
        # لم يتم إيجاد أي خط TrueType حقيقي على النظام.
        print(
            "تحذير: لم يتم العثور على خط TrueType مناسب؛ "
            "سيتم استخدام خط PIL الافتراضي وقد تقل جودة اختبار OCR."
        )
        return ImageFont.load_default()

    font = _load_font(52)
    small_font = _load_font(38)

    draw.text(
        (100, 80),
        "QUALITY CHECK DOCUMENT",
        fill="black",
        font=font,
    )

    lines = [
        "Customer: Ahmed Ali",
        "Order ID: 5001",
        "Amount: 1250.50",
        "Status: PAID",
        "Date: 2026-09-20",
        "Quality test: 999999",
    ]

    y = 190
    for line in lines:
        draw.text((120, y), line, fill="black", font=small_font)
        y += 110

    image.save(
        config.SCANNED_PAPERS_DIR / "sample_scanned_document.png"
    )


def create_pdf_copy() -> None:
    """
    إنشاء PDF تجريبي باستخدام PyMuPDF إن كان متاحاً.
    لا نعتبر عدم وجوده خطأ لأن صورة PNG كافية لاختبار OCR الأساسي.
    """
    try:
        import fitz
    except ImportError:
        return

    pdf_path = config.SCANNED_PAPERS_DIR / "sample_scanned_document.pdf"

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)

    text = (
        "QUALITY CHECK DOCUMENT\n\n"
        "Customer: Ahmed Ali\n"
        "Order ID: 5001\n"
        "Amount: 1250.50\n"
        "Status: PAID\n"
        "Date: 2026-09-20\n"
        "Quality test: 999999"
    )

    page.insert_text(
        (60, 80),
        text,
        fontsize=18,
    )

    doc.save(pdf_path)
    doc.close()


def main() -> None:
    # تنظيف ملفات الإدخال القديمة فقط.
    for directory in (
        config.DATA_INPUT_DIR,
        config.SCANNED_PAPERS_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        for item in directory.iterdir():
            if item.is_file():
                item.unlink()

    create_csv()
    create_excel()
    create_ocr_image()
    create_pdf_copy()

    if config.DATABASE_TYPE == "sqlite":
        initialize_demo_database()
    else:
        print(
            "DATABASE_TYPE ليس sqlite؛ تم تخطي إنشاء قاعدة البيانات التجريبية."
        )

    print("تم إنشاء البيانات التجريبية بنجاح.")
    print(f"CSV/Excel: {config.DATA_INPUT_DIR}")
    print(f"OCR files: {config.SCANNED_PAPERS_DIR}")
    print(f"SQLite DB: {config.SQLITE_DB_PATH}")


if __name__ == "__main__":
    main()
