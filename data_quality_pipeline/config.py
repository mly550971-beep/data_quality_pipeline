"""
إعدادات المشروع المركزية.

يمكن تعديل القيم مباشرة أو وضعها في ملف .env بجوار main.py.
الهدف هو عدم وضع كلمات المرور أو بيانات SMTP الحساسة داخل الكود.
"""

from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

# تحميل متغيرات البيئة من ملف .env إن وجد.
load_dotenv()

BASE_DIR = Path(__file__).resolve().parent

# المجلدات الرئيسية للمشروع.
DATA_INPUT_DIR = BASE_DIR / "data_input"
SCANNED_PAPERS_DIR = BASE_DIR / "scanned_papers"
DATA_PROCESSED_DIR = BASE_DIR / "data_processed"
DATA_QUARANTINE_DIR = BASE_DIR / "data_quarantine"
REPORTS_DIR = BASE_DIR / "reports"

# قاعدة البيانات:
# DATABASE_TYPE = sqlite أو postgresql
DATABASE_TYPE = os.getenv("DATABASE_TYPE", "sqlite").strip().lower()

# SQLite هو الافتراضي حتى يعمل المشروع بدون خادم Database.
SQLITE_DB_PATH = Path(
    os.getenv("SQLITE_DB_PATH", str(BASE_DIR / "enterprise_quality.db"))
)

# إعدادات PostgreSQL.
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB = os.getenv("POSTGRES_DB", "data_quality")
POSTGRES_USER = os.getenv("POSTGRES_USER", "postgres")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "")

# أسماء الجداول التي سيتم فحصها عند استخدام PostgreSQL/SQLite.
# اترك DB_TABLES فارغاً ليتم اكتشاف الجداول تلقائياً.
DB_TABLES = [
    table.strip()
    for table in os.getenv("DB_TABLES", "").split(",")
    if table.strip()
]

# إعداد Tesseract OCR.
# في Windows مثال:
# TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
TESSERACT_CMD = os.getenv("TESSERACT_CMD", "").strip()

# لغة OCR الافتراضية.
# ara+eng تحتاج تثبيت ملفات اللغة العربية في Tesseract.
OCR_LANG = os.getenv("OCR_LANG", "eng")

# حد جودة OCR. إذا كان متوسط الثقة أقل منه يتم عزل الملف.
OCR_MIN_CONFIDENCE = float(os.getenv("OCR_MIN_CONFIDENCE", "45"))

# حد أدنى لطول النص المستخرج قبل اعتباره ضعيفاً.
OCR_MIN_TEXT_LENGTH = int(os.getenv("OCR_MIN_TEXT_LENGTH", "5"))

# إعدادات الشذوذ.
Z_SCORE_THRESHOLD = float(os.getenv("Z_SCORE_THRESHOLD", "3.0"))
IQR_MULTIPLIER = float(os.getenv("IQR_MULTIPLIER", "1.5"))

# SMTP.
SMTP_ENABLED = os.getenv("SMTP_ENABLED", "false").lower() == "true"
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM", SMTP_USERNAME)
EMAIL_TO = [
    x.strip()
    for x in os.getenv("EMAIL_TO", "").split(",")
    if x.strip()
]
EMAIL_SUBJECT = os.getenv(
    "EMAIL_SUBJECT",
    "Enterprise Data Quality & OCR Observability Report",
)

# الامتدادات المسموح بفحصها.
TABULAR_EXTENSIONS = {".csv", ".xlsx", ".xlsm", ".xls"}
OCR_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf"}

# مجلدات النظام.
for _directory in (
    DATA_INPUT_DIR,
    SCANNED_PAPERS_DIR,
    DATA_PROCESSED_DIR,
    DATA_QUARANTINE_DIR,
    REPORTS_DIR,
):
    _directory.mkdir(parents=True, exist_ok=True)
