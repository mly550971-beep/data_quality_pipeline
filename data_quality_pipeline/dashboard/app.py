from pathlib import Path
import sqlite3, sys
import pandas as pd
import streamlit as st
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from observability import ObservabilityStore
st.set_page_config(page_title='Enterprise Data Quality',page_icon='📊',layout='wide')
st.title('📊 Enterprise Data Quality & OCR Observability')
st.caption('Run History • Data Quality • Schema Drift • OCR Observability')
store=ObservabilityStore(ROOT/'observability.db'); history=pd.DataFrame(store.history(50))
if history.empty: st.info('لا توجد Runs بعد. شغّل: python main.py'); st.stop()
latest=history.iloc[0]
c1,c2,c3,c4,c5=st.columns(5); c1.metric('Quality',f"{latest['average_score']:.1f}%"); c2.metric('Sources',int(latest['total_sources'])); c3.metric('PASS',int(latest['passed'])); c4.metric('WARN',int(latest['warnings'])); c5.metric('FAIL',int(latest['failed']))
trend=history.copy(); trend['started_at']=pd.to_datetime(trend['started_at']); trend=trend.sort_values('started_at'); st.subheader('Quality Trend'); st.line_chart(trend.set_index('started_at')['average_score'],height=300)
st.subheader('Run History'); st.dataframe(history,use_container_width=True,hide_index=True)
# ملاحظة: `with sqlite3.connect(...) as conn` لا يغلق الاتصال فعلياً (يدير
# الـ transaction بس)، لذلك نغلقه صراحة في finally لتفادي تراكم اتصالات
# مفتوحة مع كل إعادة تشغيل لسكريبت Streamlit.
conn = sqlite3.connect(str(ROOT/'observability.db'))
try:
    details=pd.read_sql_query('SELECT source_name,source_type,status,score,row_count,column_count,ocr_confidence FROM quality_results WHERE run_id=? ORDER BY score ASC',conn,params=(latest['run_id'],))
    changes=pd.read_sql_query('SELECT detected_at,source_name,change_type,column_name,previous_type,current_type FROM schema_changes WHERE run_id=? ORDER BY id DESC',conn,params=(latest['run_id'],))
finally:
    conn.close()
st.subheader('Latest Run Details'); st.dataframe(details,use_container_width=True,hide_index=True)
st.subheader('Schema Drift'); st.dataframe(changes,use_container_width=True,hide_index=True) if not changes.empty else st.success('لا توجد تغييرات Schema في آخر Run.')
st.caption(f"Latest Run ID: {latest['run_id']}")
