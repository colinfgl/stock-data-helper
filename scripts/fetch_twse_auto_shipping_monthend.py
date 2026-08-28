from __future__ import annotations
import csv,json
from pathlib import Path
import requests

DATES='20180131,20180227,20180331,20180430,20180531,20180629,20180731,20180831,20180928,20181031,20181130,20181228,20190130,20190227,20190329,20190430,20190531,20190628,20190731,20190830,20190927,20191031,20191129,20191231,20200131,20200227,20200331,20200430,20200529,20200630,20200731,20200831,20200930,20201030,20201130,20201231,20210129,20210226,20210331,20210430,20210531,20210630,20210730,20210831,20210930,20211029,20211130,20211230,20220126,20220225,20220331,20220429,20220531,20220630,20220729,20220831,20220930,20221031,20221130,20221230,20230130,20230224,20230331,20230428,20230531,20230630,20230731,20230831,20230928,20231031,20231130,20231229,20240131,20240227,20240329,20240430,20240531,20240628,20240731,20240830,20240930,20241031,20241129,20241231,20250122,20250227,20250331,20250430,20250528,20250630,20250731,20250829,20250930,20251031,20251128,20251231,20260130,20260226,20260331,20260430,20260529,20260630,20260731,20260817'.split(',')
WANTED={'汽車類指數','航運類指數'}
OUT=Path('output_industry_monthend'); OUT.mkdir(exist_ok=True)
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 stock-data-helper-industry-monthend/1.0'})

def main():
 rows=[]; errors=[]
 for ds in DATES:
  u=f'https://www.twse.com.tw/exchangeReport/MI_INDEX?date={ds}&response=json&type=ALLBUT0999'
  try:
   j=S.get(u,timeout=30).json(); found=set()
   for t in j.get('tables',[]):
    for r in t.get('data',[]):
     if len(r)>=2 and str(r[0]).strip() in WANTED:
      try:v=float(str(r[1]).replace(',',''))
      except:continue
      rows.append([ds,str(r[0]).strip(),v,u]); found.add(str(r[0]).strip())
   for x in WANTED-found: errors.append([ds,x,'missing',u])
  except Exception as e: errors.append([ds,'',repr(e),u])
 with (OUT/'industry_monthend.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f); w.writerow(['date','index_name','value','source_url']); w.writerows(rows)
 with (OUT/'errors.csv').open('w',encoding='utf-8-sig',newline='') as f:
  w=csv.writer(f); w.writerow(['date','index_name','error','source_url']); w.writerows(errors)
 counts={x:sum(1 for r in rows if r[1]==x) for x in WANTED}
 rep={'dates':len(DATES),'rows':len(rows),'counts':counts,'errors':len(errors),'all_pass':len(errors)==0 and all(v==len(DATES) for v in counts.values())}
 (OUT/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(rep,ensure_ascii=False))
 if not rep['all_pass']: raise SystemExit(2)
if __name__=='__main__':main()
