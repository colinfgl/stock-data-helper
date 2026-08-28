from __future__ import annotations
import csv,json,re,time,calendar
from pathlib import Path
import requests

OUT=Path('output_p1b_industry_eftri'); OUT.mkdir(exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 stock-data-helper-p1b-eftri/1.0'})
START=(2018,1); END=(2026,8)

def normdate(x):
    s=str(x or '').strip()
    m=re.search(r'(\d{2,3})/(\d{1,2})/(\d{1,2})',s)
    if not m: return ''
    y,mo,d=map(int,m.groups()); return f'{y+1911:04d}-{mo:02d}-{d:02d}'

def main():
    rows=[]; errors=[]; months=0
    y,m=START
    while (y,m)<=END:
        months+=1
        dateq=f'{y:04d}{m:02d}01'
        url='https://www.twse.com.tw/indicesReport/EFTRI_HIST'
        try:
            r=S.get(url,params={'date':dateq,'response':'json'},timeout=30); r.raise_for_status(); j=r.json(); u=r.url
            fields=j.get('fields') or []
            data=j.get('data') or []
            if not fields or not data:
                errors.append({'month':f'{y:04d}-{m:02d}','error':f"stat={j.get('stat')} no fields/data",'url':u})
            else:
                for rr in data:
                    d=normdate(rr[0] if rr else '')
                    if not d: continue
                    for i in range(1,min(len(fields),len(rr))):
                        name=str(fields[i]).strip()
                        try: val=float(str(rr[i]).replace(',',''))
                        except: continue
                        rows.append({'date':d,'index_name':name,'value':val,'source_url':u})
            print(f'{y:04d}-{m:02d}',len(data),flush=True)
        except Exception as e:
            errors.append({'month':f'{y:04d}-{m:02d}','error':repr(e),'url':url})
        m+=1
        if m==13: y+=1;m=1
        time.sleep(.08)
    with (OUT/'eftri_history.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['date','index_name','value','source_url']); w.writeheader(); w.writerows(rows)
    with (OUT/'errors.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=['month','error','url']); w.writeheader(); w.writerows(errors)
    rep={'months':months,'rows':len(rows),'index_names':sorted(set(x['index_name'] for x in rows)),'errors':len(errors),'all_pass':len(errors)==0 and len(rows)>0}
    (OUT/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False),flush=True)
    if errors: raise SystemExit(2)

if __name__=='__main__': main()
