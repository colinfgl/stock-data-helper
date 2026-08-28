from __future__ import annotations
import csv, json, time
from datetime import date,timedelta
from pathlib import Path
import requests

START=date(2018,1,1); END=date(2026,8,17)
OUT=Path('output_industry_extra'); OUT.mkdir(exist_ok=True)
WANTED={'汽車類指數','航運類指數'}
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 stock-data-helper-industry-extra/1.0'})

def get_day(d):
    u=f'https://www.twse.com.tw/exchangeReport/MI_INDEX?date={d:%Y%m%d}&response=json&type=ALLBUT0999'
    r=S.get(u,timeout=30); r.raise_for_status(); j=r.json(); return j,u

def main():
    rows=[]; errors=[]; d=START; requests_n=0
    while d<=END:
        if d.weekday()<5:
            try:
                j,u=get_day(d); requests_n+=1
                found=0
                for t in j.get('tables',[]):
                    for r in t.get('data',[]):
                        if len(r)>=2 and str(r[0]).strip() in WANTED:
                            try:v=float(str(r[1]).replace(',',''))
                            except:continue
                            rows.append([d.isoformat(),str(r[0]).strip(),v,u]); found+=1
                if not found and j.get('stat') not in ('OK','很抱歉，沒有符合條件的資料!'):
                    errors.append([d.isoformat(),j.get('stat',''),u])
            except Exception as e: errors.append([d.isoformat(),repr(e),''])
            time.sleep(.025)
        d+=timedelta(days=1)
    with (OUT/'industry_extra.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f); w.writerow(['date','index_name','value','source_url']); w.writerows(rows)
    with (OUT/'errors.csv').open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f); w.writerow(['date','error','source_url']); w.writerows(errors)
    counts={x:sum(1 for r in rows if r[1]==x) for x in sorted(WANTED)}
    rep={'rows':len(rows),'counts':counts,'requests':requests_n,'errors':len(errors),'all_pass':all(v>1800 for v in counts.values())}
    (OUT/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False))
    if not rep['all_pass']: raise SystemExit(2)
if __name__=='__main__': main()
