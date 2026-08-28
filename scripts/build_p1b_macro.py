from __future__ import annotations

import csv, io, json
from pathlib import Path
import requests

OUT=Path('output_p1b_macro'); OUT.mkdir(exist_ok=True)
START='2018-01-01'; END='2026-08-17'
SERIES=['VIXCLS','NASDAQCOM','NASDAQSOX']
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 stock-data-helper-p1b-macro/1.0'})

def main():
    cov=[]; errors=[]
    for sid in SERIES:
        url=f'https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}&coed={END}'
        try:
            r=S.get(url,timeout=60); r.raise_for_status()
            text=r.text
            rows=list(csv.DictReader(io.StringIO(text)))
            good=[]
            for x in rows:
                d=x.get('DATE') or x.get('observation_date') or x.get('date') or ''
                v=x.get(sid,'')
                if v not in ('','.','NA','NaN'):
                    good.append({'date':d,'value':v,'series_id':sid,'source_url':url})
            with (OUT/f'{sid}.csv').open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.DictWriter(f,fieldnames=['date','value','series_id','source_url']); w.writeheader(); w.writerows(good)
            dates=[x['date'] for x in good]
            cov.append({'series_id':sid,'rows':len(good),'first_date':min(dates) if dates else '', 'last_date':max(dates) if dates else '', 'error':''})
            print(sid,len(good),flush=True)
        except Exception as e:
            errors.append({'series_id':sid,'error':repr(e),'url':url})
            cov.append({'series_id':sid,'rows':0,'first_date':'','last_date':'','error':repr(e)})
    with (OUT/'coverage.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['series_id','rows','first_date','last_date','error']); w.writeheader(); w.writerows(cov)
    with (OUT/'errors.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['series_id','error','url']); w.writeheader(); w.writerows(errors)
    report={'start':START,'end':END,'series':SERIES,'errors':len(errors),'all_pass':len(errors)==0 and all(x['rows']>0 for x in cov)}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if not report['all_pass']: raise SystemExit(2)

if __name__=='__main__': main()
