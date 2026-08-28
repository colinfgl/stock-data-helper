from __future__ import annotations
import csv, json, time
from pathlib import Path
import requests

API='https://api.finmindtrade.com/api/v4/data'
START='2018-01-01'; END='2026-08-17'
OUT=Path('output_p1b_macro_finmind'); OUT.mkdir(exist_ok=True)
WANTED=['NASDAQ Composite','PHLX Semiconductor','CBOE Volatility Index']
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 stock-data-helper-p1b-macro-finmind/1.0'})

def get(params):
    r=S.get(API,params=params,timeout=60); r.raise_for_status(); j=r.json()
    if j.get('status') not in (None,200) and not j.get('data'):
        raise RuntimeError(f"status={j.get('status')} msg={j.get('msg')}")
    return j.get('data') or [], r.url

def write(path,rows):
    if not rows: path.write_text('',encoding='utf-8'); return
    fields=[]; seen=set()
    for r in rows:
        for k in r:
            if k not in seen: seen.add(k); fields.append(k)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(rows)

def main():
    info,url=get({'dataset':'USStockInfo','start_date':START,'end_date':END})
    found={}
    for r in info:
        text=' '.join(str(v) for v in r.values())
        for name in WANTED:
            if name.lower() in text.lower(): found[name]=r
    write(OUT/'USStockInfo_matches.csv',[{'wanted_name':k,**v,'_source_url':url} for k,v in found.items()])
    cov=[]; errors=[]
    for name in WANTED:
        row=found.get(name)
        if not row:
            errors.append({'name':name,'error':'not found in USStockInfo'}); continue
        sid=str(row.get('stock_id') or row.get('symbol') or row.get('ticker') or row.get('code') or '').strip()
        if not sid:
            errors.append({'name':name,'error':f'no symbol field: {row}'}); continue
        try:
            data,u=get({'dataset':'USStockPrice','data_id':sid,'start_date':START,'end_date':END})
            out=[]
            for r in data:
                x=dict(r); x['_wanted_name']=name; x['_source_url']=u; out.append(x)
            safe=name.replace(' ','_').replace('/','_')
            write(OUT/f'{safe}.csv',out)
            dates=[str(x.get('date','')) for x in data if x.get('date')]
            cov.append({'name':name,'stock_id':sid,'rows':len(data),'first_date':min(dates) if dates else '', 'last_date':max(dates) if dates else '', 'error':''})
            print(name,sid,len(data),flush=True)
        except Exception as e:
            errors.append({'name':name,'error':repr(e)})
        time.sleep(.15)
    write(OUT/'coverage.csv',cov); write(OUT/'errors.csv',errors)
    rep={'found':found,'coverage':cov,'errors':errors,'all_pass':len(errors)==0 and len(cov)==len(WANTED) and all(x['rows']>0 for x in cov)}
    (OUT/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'coverage':cov,'errors':errors,'all_pass':rep['all_pass']},ensure_ascii=False),flush=True)
    if not rep['all_pass']: raise SystemExit(2)

if __name__=='__main__': main()
