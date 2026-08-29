from __future__ import annotations
import csv, json, time
from pathlib import Path
import requests

API='https://api.finmindtrade.com/api/v4/data'
OUT=Path('output_current_snapshot_20260828'); OUT.mkdir(exist_ok=True)
TARGETS=['0050','00400A','009820','2207','2308','2317','2330','2368','2376','2382','2383','2454','2634','2834','2885','3293','3491','3665','4916','6770']
QUERIES=[
 ('TaiwanStockPriceAdj','2026-01-01','2026-08-28'),
 ('TaiwanStockPrice','2026-01-01','2026-08-28'),
 ('TaiwanStockMonthRevenue','2025-01-01','2026-08-28'),
 ('TaiwanStockFinancialStatements','2024-01-01','2026-08-28'),
 ('TaiwanStockInstitutionalInvestorsBuySellWide','2026-06-01','2026-08-28'),
 ('TaiwanStockMarginPurchaseShortSale','2026-06-01','2026-08-28'),
 ('TaiwanStockPER','2026-06-01','2026-08-28'),
]
# Diagnostic-only endpoint. R54/R55 do not depend on it: adjusted history is
# carried forward from verified R45 data and corporate actions are applied
# separately. Optional-source failure must never fail the required snapshot.
OPTIONAL_DATASETS={'TaiwanStockPriceAdj'}
MACRO=[
 ('TaiwanExchangeRate','USD','2025-08-01','2026-08-28'),
 ('GovernmentBondsYield','United States 2-Year','2025-08-01','2026-08-28'),
 ('GovernmentBondsYield','United States 10-Year','2025-08-01','2026-08-28'),
 ('USStockPrice','^IXIC','2025-08-01','2026-08-28'),
 ('USStockPrice','^SOX','2025-08-01','2026-08-28'),
 ('USStockPrice','^VIX','2025-08-01','2026-08-28'),
]
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 stock-data-helper-current-snapshot/1.2'})

def get(params):
    last=None
    for attempt in range(4):
        try:
            r=S.get(API,params=params,timeout=60); r.raise_for_status(); j=r.json()
            if j.get('status') not in (None,200) and not j.get('data'):
                raise RuntimeError(f"status={j.get('status')} msg={j.get('msg')}")
            return j.get('data') or [], r.url, None
        except Exception as e:
            last=e; time.sleep(1.0*(attempt+1))
    return [],'',repr(last)

def write_union(path,rows):
    if not rows:
        path.write_text('',encoding='utf-8'); return
    fields=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); fields.append(k)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)

def main():
    coverage=[]; required_errors=[]; optional_errors=[]
    for ds,start,end in QUERIES:
        allrows=[]
        is_optional=ds in OPTIONAL_DATASETS
        optional_unavailable=False
        for code in TARGETS:
            if is_optional and optional_unavailable:
                coverage.append({'dataset':ds,'data_id':code,'required':False,'rows':0,'first_date':'','last_date':'','error':'SKIPPED_AFTER_OPTIONAL_SOURCE_UNAVAILABLE'})
                continue
            rows,url,err=get({'dataset':ds,'data_id':code,'start_date':start,'end_date':end})
            if err:
                rec={'dataset':ds,'data_id':code,'severity':'optional' if is_optional else 'required','error':err}
                (optional_errors if is_optional else required_errors).append(rec)
                if is_optional:
                    optional_unavailable=True
            for x in rows:
                y=dict(x); y['_query_id']=code; y['_source_url']=url; allrows.append(y)
            dates=[str(x.get('date','')) for x in rows if x.get('date')]
            coverage.append({'dataset':ds,'data_id':code,'required':not is_optional,'rows':len(rows),'first_date':min(dates) if dates else '','last_date':max(dates) if dates else '','error':err or ''})
            print(ds,code,len(rows),max(dates) if dates else '',err or 'OK',flush=True)
            time.sleep(.06)
        write_union(OUT/f'{ds}.csv',allrows)

    for ds,did,start,end in MACRO:
        rows,url,err=get({'dataset':ds,'data_id':did,'start_date':start,'end_date':end})
        if err: required_errors.append({'dataset':ds,'data_id':did,'severity':'required','error':err})
        out=[]
        for x in rows:
            y=dict(x); y['_query_id']=did; y['_source_url']=url; out.append(y)
        safe=(ds+'__'+did).replace(' ','_').replace('/','_').replace('^','')
        write_union(OUT/f'{safe}.csv',out)
        dates=[str(x.get('date','')) for x in rows if x.get('date')]
        coverage.append({'dataset':ds,'data_id':did,'required':True,'rows':len(rows),'first_date':min(dates) if dates else '','last_date':max(dates) if dates else '','error':err or ''})
        print(ds,did,len(rows),max(dates) if dates else '',err or 'OK',flush=True)

    u='https://www.twse.com.tw/exchangeReport/MI_INDEX?response=json&date=20260828&type=ALLBUT0999'
    try:
        rr=S.get(u,timeout=60); rr.raise_for_status(); j=rr.json(); rows=[]
        for t in j.get('tables',[]):
            for row in t.get('data',[]):
                if len(row)>=2 and '類指數' in str(row[0]):
                    try: val=float(str(row[1]).replace(',',''))
                    except Exception: continue
                    rows.append({'date':'2026-08-28','index_name':str(row[0]).strip(),'value':val,'_source_url':u})
        write_union(OUT/'TWSE_industry_20260828.csv',rows)
        coverage.append({'dataset':'TWSE_MI_INDEX','data_id':'industry','required':True,'rows':len(rows),'first_date':'2026-08-28','last_date':'2026-08-28','error':''})
        print('TWSE_MI_INDEX',len(rows),'OK',flush=True)
    except Exception as e:
        required_errors.append({'dataset':'TWSE_MI_INDEX','data_id':'industry','severity':'required','error':repr(e)})

    all_errors=required_errors+optional_errors
    write_union(OUT/'coverage.csv',coverage); write_union(OUT/'errors.csv',all_errors)
    report={
        'targets':len(TARGETS),
        'required_errors':len(required_errors),
        'optional_errors':len(optional_errors),
        'errors':len(all_errors),
        'coverage_rows':len(coverage),
        'all_pass':len(required_errors)==0,
        'gate_rule':'optional source failures do not fail the required snapshot gate',
    }
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if required_errors: raise SystemExit(2)
if __name__=='__main__': main()
