from __future__ import annotations
import re
import pandas as pd
KEY_ALIASES={'customer':['customer','customer name','client','name'],'invoice_id':['invoice id','invoice','invoice number','id'],'amount':['amount','total','price','value'],'date':['date','invoice date'],'status':['status','state']}
def normalize_key(key):
    key=key.strip().lower().replace('-',' ')
    for canonical,aliases in KEY_ALIASES.items():
        if key in aliases:return canonical
    return key.replace(' ','_')
def extract_key_value_fields(text):
    out={}
    for line in text.splitlines():
        m=re.match(r'^\s*([^:=]{2,50})\s*[:=]\s*(.*?)\s*$',line)
        if not m: continue
        key=normalize_key(m.group(1)); value=m.group(2).strip()
        if key=='amount':
            n=re.search(r'[-+]?\d+(?:[.,]\d+)?',value)
            if n:
                try:value=float(n.group().replace(',',''))
                except ValueError:pass
        elif key=='invoice_id':
            n=re.search(r'\d+',value)
            if n:value=int(n.group())
        out[key]=value
    return out
def detect_ocr_table(text):
    lines=[x.strip() for x in text.splitlines() if x.strip()]; candidates=[x for x in lines if '|' in x or '\t' in x]
    if len(candidates)<2:return pd.DataFrame()
    delimiter='|' if sum('|' in x for x in candidates)>=sum('\t' in x for x in candidates) else '\t'
    rows=[[c.strip() for c in x.split(delimiter)] for x in candidates]; width=max(map(len,rows)); rows=[r+['']*(width-len(r)) for r in rows]
    return pd.DataFrame(rows[1:],columns=rows[0]) if any(rows[0]) else pd.DataFrame(rows)
