import pandas as pd
from rules_engine import apply_rules
from observability import ObservabilityStore

def test_rules_engine_range():
    issues=apply_rules(pd.DataFrame({'amount':[10,-5]})); assert any(x['rule']=='RANGE' for x in issues)

def test_schema_drift_first_run_has_no_false_positives(tmp_path):
    # Regression test: قبل الإصلاح كان أول فحص لأي مصدر (لا يوجد Snapshot
    # سابق) يُبلّغ عن كل الأعمدة كـ ADDED_COLUMN، مما يُنتج WARN وهمي على
    # كل مصدر جديد من أول تشغيل للنظام.
    s=ObservabilityStore(tmp_path/'obs.db')
    run,_=s.start_run()
    changes=s.detect_schema_drift(run,'orders',pd.DataFrame({'id':[1],'amount':[10]}))
    assert changes == []

def test_schema_drift_detects_real_change(tmp_path):
    s=ObservabilityStore(tmp_path/'obs.db'); run,_=s.start_run(); s.detect_schema_drift(run,'orders',pd.DataFrame({'id':[1]})); run2,_=s.start_run(); changes=s.detect_schema_drift(run2,'orders',pd.DataFrame({'id':[1],'phone':['x']})); assert any(x['change_type']=='ADDED_COLUMN' for x in changes)

def test_rules_engine_applies_to_database_style_columns():
    # Regression test: apply_rules كانت مربوطة بملفات CSV/Excel فقط رغم أن
    # rules/quality_rules.yaml يعرّف قواعد لأعمدة order_id/order_date/amount
    # المطابقة تماماً لجدول customer_orders في قاعدة البيانات.
    df = pd.DataFrame({
        'order_id': [1, 1],
        'amount': [50, 50],
        'order_date': ['2026-09-01', 'not-a-date'],
    })
    issues = apply_rules(df)
    rules = {x['rule'] for x in issues}
    assert 'UNIQUE' in rules
    assert 'DATE_VALIDATION' in rules
