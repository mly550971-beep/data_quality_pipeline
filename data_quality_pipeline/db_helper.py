"""
وحدة التعامل مع قواعد البيانات.

تدعم:
1) SQLite باستخدام المكتبة القياسية sqlite3.
2) PostgreSQL باستخدام psycopg2-binary.

الوظيفة الأساسية هي اكتشاف الجداول وسحبها إلى Pandas DataFrame.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Generator, Iterable

import pandas as pd

import config

try:
    import psycopg2
    from psycopg2 import sql
except ImportError:  # PostgreSQL اختياري وقت التشغيل.
    psycopg2 = None
    sql = None


@contextmanager
def get_connection():
    """إنشاء اتصال بقاعدة البيانات وإغلاقه بأمان."""
    connection = None

    try:
        if config.DATABASE_TYPE == "sqlite":
            connection = sqlite3.connect(str(config.SQLITE_DB_PATH))
        elif config.DATABASE_TYPE == "postgresql":
            if psycopg2 is None:
                raise RuntimeError(
                    "لم يتم تثبيت psycopg2-binary، لذلك لا يمكن الاتصال بـ PostgreSQL."
                )

            connection = psycopg2.connect(
                host=config.POSTGRES_HOST,
                port=config.POSTGRES_PORT,
                dbname=config.POSTGRES_DB,
                user=config.POSTGRES_USER,
                password=config.POSTGRES_PASSWORD,
            )
        else:
            raise ValueError(
                "DATABASE_TYPE يجب أن يكون sqlite أو postgresql."
            )

        yield connection
    finally:
        if connection is not None:
            connection.close()


def _quote_identifier(identifier: str) -> str:
    """حماية اسم الجدول من حقن SQL عند استخدام أسماء مكتشفة من قاعدة البيانات."""
    if not identifier or not identifier.replace("_", "").isalnum():
        raise ValueError(f"اسم جدول غير صالح: {identifier}")

    if config.DATABASE_TYPE == "postgresql":
        # نستخدم psycopg2.sql.Identifier في الاستعلام النهائي.
        return identifier

    return identifier


def list_tables() -> list[str]:
    """اكتشاف أسماء الجداول الموجودة في قاعدة البيانات."""
    with get_connection() as conn:
        if config.DATABASE_TYPE == "sqlite":
            query = """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """
            result = pd.read_sql_query(query, conn)
            return result["name"].tolist()

        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        result = pd.read_sql_query(query, conn)
        return result["table_name"].tolist()


def read_table(table_name: str) -> pd.DataFrame:
    """قراءة جدول كامل إلى DataFrame."""
    table_name = _quote_identifier(table_name)

    with get_connection() as conn:
        if config.DATABASE_TYPE == "sqlite":
            # بعد التحقق من اسم الجدول يمكن إدخاله في الاستعلام.
            query = f'SELECT * FROM "{table_name}"'
            return pd.read_sql_query(query, conn)

        query = sql.SQL("SELECT * FROM {}").format(
            sql.Identifier(table_name)
        )
        return pd.read_sql_query(query.as_string(conn), conn)


def get_target_tables() -> list[str]:
    """إرجاع الجداول المحددة يدوياً أو اكتشافها تلقائياً."""
    if config.DB_TABLES:
        return config.DB_TABLES
    return list_tables()


def initialize_demo_database() -> None:
    """
    إنشاء جدول تجريبي في SQLite.
    هذه الدالة مخصصة لـ create_dummy_data.py ولا تستخدم في الإنتاج.
    """
    if config.DATABASE_TYPE != "sqlite":
        raise RuntimeError(
            "قاعدة البيانات التجريبية يتم إنشاؤها تلقائياً على SQLite فقط."
        )

    with get_connection() as conn:
        conn.execute("DROP TABLE IF EXISTS customer_orders")
        conn.execute(
            """
            CREATE TABLE customer_orders (
                order_id INTEGER,
                customer_name TEXT,
                email TEXT,
                amount REAL,
                order_date TEXT,
                status TEXT
            )
            """
        )

        rows = [
            (1001, "Ahmed Ali", "ahmed@example.com", 1200.50, "2026-09-01", "PAID"),
            (1002, "Mona Hassan", "mona@example.com", 450.00, "2026-09-02", "PAID"),
            (1002, "Mona Hassan", "mona@example.com", 450.00, "2026-09-02", "PAID"),
            (None, "Unknown", "not-an-email", 999999.0, "wrong-date", "UNKNOWN"),
            (1005, None, "youssef@example.com", -50.0, "2026-09-05", "REFUND"),
        ]

        conn.executemany(
            """
            INSERT INTO customer_orders
            (order_id, customer_name, email, amount, order_date, status)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        conn.commit()
