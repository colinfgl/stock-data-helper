from __future__ import annotations
import csv,json,re,time,calendar
from collections import defaultdict
from datetime import date,timedelta
from pathlib import Path
import requests

OUT=Path('output_p1b_industry'); OUT.mkdir(exist_ok=True)
START='2018-01-01'; END='2026-08-17'
TARGETS=['0050','00400A','009820','2207','2308','2317','2330','2368','2376','2382','2383','2454','2634','2834','2885','3293','3491','3665','4916','6770']
FAPI='https://api.finmindtrade.com/api/v4/data'
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0 stock-data-helper-p1b-industry/1.0'})

def getj(url,params=None,tries=4):
    last=None
    for i in range(tries):
        try:
            r=S.get(url,params=params,timeout=60); r.raise_for_status(); return r.json(),r.url
        except Exception as e:
            last=e; time.sleep(1.0*(i+1))
    raise last

def norm(x):
    return re.sub(r'[\s　]','',str(x or '')).replace('工業','').replace('業','').replace('類','')

def extract_rows(obj):
    out=[]
    if isinstance(obj,dict):
        if isinstance(obj.get('data'),list):
            for r in obj['data']:
                if isinstance(r,list) and len(r)>=2 and isinstance(r[0],str): out.append(r)
        for v in obj.values(): out.extend(extract_rows(v))
    elif isinstance(obj,list):
        for v in obj: out.extend(extract_rows(v))
    return out

def main():
    info,_=getj(FAPI,{'dataset':'TaiwanStockInfo'})
    imap={}
    for r in info.get('data',[]):
        c=str(r.get('stock_id',''))
        if c in TARGETS:
            imap[c]={'stock_name':r.get('stock_name',''),'industry_category':r.get('industry_category',''),'type':r.get('type','')}

    td,_=getj(FAPI,{'dataset':'TaiwanStockTradingDate'})
    trading=sorted(date.fromisoformat(r['date']) for r in td.get('data',[]) if START<=r.get('date','')<=END)
    bym=defaultdict(list)
    for d in trading: bym[(d.year,d.month)].append(d)
    anchors=[max(v) for k,v in sorted(bym.items())]

    idx_rows=[]; errors=[]; available_names=set()
    for n,d in enumerate(anchors,1):
        ds=d.strftime('%Y%m%d')
        url='https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX'
        try:
            j,u=getj(url,{'date':ds,'response':'json','type':'IND'})
            found=0
            seen=set()
            for r in extract_rows(j):
                name=re.sub(r'<[^>]+>','',str(r[0])).strip()
                val=str(r[1]).replace(',','').strip() if len(r)>1 else ''
                if '指數' not in name or name in seen: continue
                try: fv=float(val)
                except: continue
                seen.add(name); found+=1; available_names.add(name)
                idx_rows.append({'date':d.isoformat(),'index_name':name,'value':fv,'source_url':u})
            if found==0: errors.append({'date':d.isoformat(),'error':'no index rows parsed','url':u})
            print(n,ds,'rows',found,flush=True)
        except Exception as e:
            errors.append({'date':d.isoformat(),'error':repr(e),'url':url})
        time.sleep(.12)

    # Map current broad exchange industry category to official historical index name.
    # This mapping is explicit and auditable; it can still have current-classification bias.
    def choose(cat):
        n=norm(cat)
        candidates=[]
        for nm in available_names:
            nn=norm(nm.replace('報酬指數','').replace('指數',''))
            if n and (n==nn or n in nn or nn in n): candidates.append(nm)
        # prefer price index over total return when both exist
        candidates=sorted(set(candidates),key=lambda x:(('報酬' in x),len(x)))
        return candidates[0] if candidates else ''

    maps=[]
    for c in TARGETS:
        x=imap.get(c,{})
        cat=x.get('industry_category','')
        chosen=choose(cat)
        proxy='official-TWSE-sector-index' if chosen else 'neutral-no-sector-index'
        # ETFs are deliberately neutral in company-industry cross-sectional score.
        if c in ('0050','00400A','009820'):
            chosen=''; proxy='neutral-ETF'
        maps.append({'code':c,'stock_name':x.get('stock_name',''),'market':x.get('type',''),'industry_category':cat,'index_name':chosen,'proxy_type':proxy})

    def write(path,rows,fields=None):
        if not rows:
            path.write_text('',encoding='utf-8'); return
        if fields is None:
            fields=list(rows[0])
        with path.open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore'); w.writeheader(); w.writerows(rows)
    write(OUT/'twse_industry_monthly.csv',idx_rows)
    write(OUT/'stock_industry_map.csv',maps)
    write(OUT/'errors.csv',errors, ['date','error','url'])
    report={'anchors':len(anchors),'index_rows':len(idx_rows),'errors':len(errors),'mapped':sum(bool(x['index_name']) for x in maps),'neutral':sum(not bool(x['index_name']) for x in maps),'all_months_pass':len(errors)==0}
    (OUT/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    if errors: raise SystemExit(2)

if __name__=='__main__': main()
