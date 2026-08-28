from __future__ import annotations

import csv, json, time
from collections import defaultdict
from pathlib import Path

import requests

API = 'https://api.finmindtrade.com/api/v4/data'
START = '2018-01-01'
END = '2026-08-17'
OUT = Path('output_p1b_phase1')
OUT.mkdir(exist_ok=True)

TARGETS = [
    '0050','00400A','009820','2207','2308','2317','2330','2368','2376','2382',
    '2383','2454','2634','2834','2885','3293','3491','3665','4916','6770'
]
DATASETS = [
    'TaiwanStockMonthRevenue',
    'TaiwanStockFinancialStatements',
    'TaiwanStockInstitutionalInvestorsBuySell',
    'TaiwanStockMarginPurchaseShortSale',
    'TaiwanStockPER',
]
MACRO = [
    ('TaiwanExchangeRate','USD'),
    ('GovernmentBondsYield','United States 2-Year'),
    ('GovernmentBondsYield','United States 10-Year'),
]

S = requests.Session()
S.headers.update({'User-Agent':'Mozilla/5.0 stock-data-helper-p1b/1.0'})

def fetch(dataset, data_id):
    params={'dataset':dataset,'data_id':data_id,'start_date':START,'end_date':END}
    last=None
    for attempt in range(4):
        try:
            r=S.get(API,params=params,timeout=60)
            r.raise_for_status()
            j=r.json()
            if j.get('status') not in (None,200) and not j.get('data'):
                raise RuntimeError(f"FinMind status={j.get('status')} msg={j.get('msg')}")
            return j.get('data') or [], r.url, None
        except Exception as e:
            last=e
            time.sleep(1.2*(attempt+1))
    return [], '', repr(last)

def write_union(path, rows):
    if not rows:
        path.write_text('',encoding='utf-8')
        return []
    fields=[]
    seen=set()
    for r in rows:
        for k in r:
            if k not in seen:
                seen.add(k); fields.append(k)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore')
        w.writeheader(); w.writerows(rows)
    return fields

def main():
    coverage=[]
    errors=[]
    totals={}
    for ds in DATASETS:
        all_rows=[]
        for i,code in enumerate(TARGETS,1):
            rows,url,err=fetch(ds,code)
            print(ds,code,len(rows),err or 'OK',flush=True)
            if err:
                errors.append({'dataset':ds,'data_id':code,'error':err})
            for r in rows:
                r=dict(r); r['_query_dataset']=ds; r['_query_id']=code; r['_source_url']=url
                all_rows.append(r)
            dates=[str(r.get('date','')) for r in rows if r.get('date')]
            coverage.append({
                'dataset':ds,'data_id':code,'rows':len(rows),
                'first_date':min(dates) if dates else '',
                'last_date':max(dates) if dates else '',
                'error':err or ''
            })
            time.sleep(0.08)
        write_union(OUT/f'{ds}.csv',all_rows)
        totals[ds]=len(all_rows)

    for ds,did in MACRO:
        rows,url,err=fetch(ds,did)
        key=f'{ds}__{did}'.replace(' ','_').replace('/','_')
        print(ds,did,len(rows),err or 'OK',flush=True)
        if err: errors.append({'dataset':ds,'data_id':did,'error':err})
        out=[]
        for r in rows:
            r=dict(r); r['_query_dataset']=ds; r['_query_id']=did; r['_source_url']=url; out.append(r)
        write_union(OUT/f'{key}.csv',out)
        dates=[str(r.get('date','')) for r in rows if r.get('date')]
        coverage.append({'dataset':ds,'data_id':did,'rows':len(rows),'first_date':min(dates) if dates else '', 'last_date':max(dates) if dates else '', 'error':err or ''})
        totals[key]=len(rows)
        time.sleep(0.08)

    write_union(OUT/'coverage.csv',coverage)
    write_union(OUT/'errors.csv',errors)
    report={
        'start':START,'end':END,'targets':len(TARGETS),
        'requests_expected':len(TARGETS)*len(DATASETS)+len(MACRO),
        'errors':len(errors),'totals':totals,
        'core_datasets_with_rows':sum(1 for ds in DATASETS if totals.get(ds,0)>0),
        'all_requests_error_free':len(errors)==0,
    }
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2),flush=True)
    if len(errors)>0:
        raise SystemExit(2)

if __name__=='__main__':
    main()
