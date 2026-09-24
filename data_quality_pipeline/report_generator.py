"""
مولد تقرير HTML تفاعلي.

لا يعتمد على خدمة خارجية أو API.
يتم تضمين JavaScript بسيط للبحث والتصفية داخل التقرير.
"""

from __future__ import annotations

import html
import json
from datetime import datetime
from pathlib import Path


def _escape(value) -> str:
    """حماية النص عند وضعه داخل HTML."""
    return html.escape(str(value))


def _issue_rows(results: list[dict]) -> str:
    rows = []

    for result in results:
        for issue in result.get("issues", []):
            rows.append(
                f"""
                <tr>
                    <td>{_escape(result.get("source_name", ""))}</td>
                    <td>{_escape(result.get("source_type", ""))}</td>
                    <td>{_escape(issue.get("rule", ""))}</td>
                    <td class="severity-{_escape(issue.get("severity", ""))}">
                        {_escape(issue.get("severity", ""))}
                    </td>
                    <td>{_escape(issue.get("message", ""))}</td>
                    <td>{_escape(issue.get("count", ""))}</td>
                </tr>
                """
            )

    return "\n".join(rows) or """
        <tr><td colspan="6">لا توجد مشاكل مسجلة.</td></tr>
    """


def _source_rows(results: list[dict]) -> str:
    rows = []

    for result in results:
        rows.append(
            f"""
            <tr>
                <td>{_escape(result.get("source_name", ""))}</td>
                <td>{_escape(result.get("source_type", ""))}</td>
                <td>{_escape(result.get("status", ""))}</td>
                <td>{float(result.get("score", 0)):.2f}</td>
                <td>{_escape(result.get("row_count", 0))}</td>
                <td>{_escape(result.get("column_count", 0))}</td>
                <td>{_escape(result.get("ocr_confidence", "-"))}</td>
            </tr>
            """
        )

    return "\n".join(rows)


def generate_html_report(
    results: list[dict],
    output_path: Path,
) -> Path:
    """إنشاء التقرير النهائي."""
    total = len(results)
    passed = sum(1 for x in results if x.get("status") == "PASS")
    warnings = sum(1 for x in results if x.get("status") == "WARN")
    failed = sum(1 for x in results if x.get("status") == "FAIL")

    average_score = (
        sum(float(x.get("score", 0)) for x in results) / total
        if total
        else 0
    )

    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    payload = {
        "generated_at": generated_at,
        "total_sources": total,
        "passed": passed,
        "warnings": warnings,
        "failed": failed,
        "average_score": round(average_score, 2),
    }

    report = f"""<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Enterprise Data Quality & OCR Observability</title>
<style>
    body {{
        margin: 0;
        background: #f4f7fb;
        color: #172033;
        font-family: "Segoe UI", Tahoma, Arial, sans-serif;
    }}
    header {{
        background: #101828;
        color: white;
        padding: 28px 5%;
    }}
    header h1 {{ margin: 0 0 8px; font-size: 27px; }}
    header p {{ margin: 0; opacity: .85; }}
    .container {{ width: 90%; max-width: 1400px; margin: 25px auto; }}
    .cards {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
        gap: 16px;
        margin-bottom: 24px;
    }}
    .card {{
        background: white;
        border-radius: 14px;
        padding: 20px;
        box-shadow: 0 6px 22px rgba(16,24,40,.07);
    }}
    .card .value {{ font-size: 30px; font-weight: 700; margin-top: 8px; }}
    .section {{
        background: white;
        border-radius: 14px;
        padding: 20px;
        margin-bottom: 22px;
        box-shadow: 0 6px 22px rgba(16,24,40,.07);
    }}
    input {{
        width: 100%;
        box-sizing: border-box;
        padding: 12px;
        border: 1px solid #d0d5dd;
        border-radius: 9px;
        margin-bottom: 14px;
        font-size: 15px;
    }}
    table {{
        width: 100%;
        border-collapse: collapse;
        overflow: hidden;
    }}
    th, td {{
        padding: 11px;
        border-bottom: 1px solid #eaecf0;
        text-align: right;
        vertical-align: top;
    }}
    th {{
        background: #f9fafb;
        position: sticky;
        top: 0;
    }}
    .severity-CRITICAL, .severity-HIGH {{ color: #b42318; font-weight: 700; }}
    .severity-WARNING {{ color: #b54708; font-weight: 700; }}
    .badge {{
        padding: 5px 9px;
        border-radius: 99px;
        font-size: 12px;
        font-weight: 700;
    }}
    .PASS {{ background: #ecfdf3; color: #027a48; }}
    .WARN {{ background: #fffaeb; color: #b54708; }}
    .FAIL {{ background: #fef3f2; color: #b42318; }}
    .muted {{ color: #667085; }}
</style>
</head>
<body>
<header>
    <h1>Enterprise Multi-Source Data Quality & OCR Observability Pipeline</h1>
    <p>تقرير جودة البيانات — تم الإنشاء في {_escape(generated_at)}</p>
</header>

<div class="container">
    <div class="cards">
        <div class="card">
            <div class="muted">إجمالي المصادر</div>
            <div class="value">{total}</div>
        </div>
        <div class="card">
            <div class="muted">PASS</div>
            <div class="value">{passed}</div>
        </div>
        <div class="card">
            <div class="muted">WARN</div>
            <div class="value">{warnings}</div>
        </div>
        <div class="card">
            <div class="muted">FAIL</div>
            <div class="value">{failed}</div>
        </div>
        <div class="card">
            <div class="muted">متوسط الجودة</div>
            <div class="value">{average_score:.2f}%</div>
        </div>
    </div>

    <div class="section">
        <h2>ملخص التشغيل</h2>
        <pre>{_escape(json.dumps(payload, ensure_ascii=False, indent=2))}</pre>
    </div>

    <div class="section">
        <h2>نتائج المصادر</h2>
        <input id="sourceSearch" placeholder="ابحث باسم الملف أو نوع المصدر أو الحالة...">
        <table id="sourceTable">
            <thead>
                <tr>
                    <th>المصدر</th>
                    <th>النوع</th>
                    <th>الحالة</th>
                    <th>الدرجة</th>
                    <th>الصفوف</th>
                    <th>الأعمدة</th>
                    <th>OCR Confidence</th>
                </tr>
            </thead>
            <tbody>
                {_source_rows(results)}
            </tbody>
        </table>
    </div>

    <div class="section">
        <h2>تفاصيل المشاكل</h2>
        <input id="issueSearch" placeholder="ابحث في قواعد الجودة ورسائل الأخطاء...">
        <table id="issueTable">
            <thead>
                <tr>
                    <th>المصدر</th>
                    <th>النوع</th>
                    <th>Rule</th>
                    <th>Severity</th>
                    <th>التفاصيل</th>
                    <th>Count</th>
                </tr>
            </thead>
            <tbody>
                {_issue_rows(results)}
            </tbody>
        </table>
    </div>
</div>

<script>
function filterTable(inputId, tableId) {{
    const input = document.getElementById(inputId);
    const table = document.getElementById(tableId);

    input.addEventListener("input", function() {{
        const query = input.value.toLowerCase();
        const rows = table.querySelectorAll("tbody tr");

        rows.forEach(function(row) {{
            row.style.display = row.innerText.toLowerCase().includes(query)
                ? ""
                : "none";
        }});
    }});
}}

filterTable("sourceSearch", "sourceTable");
filterTable("issueSearch", "issueTable");
</script>
</body>
</html>
"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    return output_path
