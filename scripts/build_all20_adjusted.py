from __future__ import annotations

import csv, hashlib, io, json, re, sys, time, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path

import requests

SOURCE_REPO = 'yukishirotsubasa/tw-stock-data-release'
SOURCE_TAG = 'daily-close-csv'
START = '20180101'
CUTOFF = '20260817'
OUT = Path('output_all20')
OUT.mkdir(exist_ok=True)

TARGETS = {
 '0050':('元大台灣50','TWSE','20180102',2092),
 '00400A':('主動國泰動能高息','TWSE','20260409',90),
 '009820':('元大納斯達克精選','TWSE','20260423',80),
 '2207':('和泰車','TWSE','20180102',2097),
 '2308':('台達電','TWSE','20180102',2097),
 '2317':('鴻海','TWSE','20180102',2091),
 '2330':('台積電','TWSE','20180102',2097),
 '2368':('金像電','TWSE','20180102',2090),
 '2376':('技嘉','TWSE','20180102',2097),
 '2382':('廣達','TWSE','20180102',2097),
 '2383':('台光電','TWSE','20180102',2097),
 '2454':('聯發科','TWSE','20180102',2097),
 '2634':('漢翔','TWSE','20180102',2097),
 '2834':('臺企銀','TWSE','20180102',2097),
 '2885':('元大金','TWSE','20180102',2097),
 '3293':('鈊象','TPEX','20180102',2097),
 '3491':('昇達科','TPEX','20180102',2097),
 '3665':('貿聯-KY','TWSE','20180102',2094),
 '4916':('事欣科','TWSE','20180102',2094),
 '6770':('力積電','TWSE','20211206',1135),
}
EXPECTED_LAST3_EVENTS={'3665':9,'4916':9,'6770':3}
HEADERS={'User-Agent':'Mozilla/5.0 stock-data-helper/1.0'}
S=requests.Session(); S.headers.update(HEADERS)

def get(url, timeout=120, tries=4):
    last=None
    for i in range(tries):
        try:
            r=S.get(url,timeout=timeout); r.raise_for_status(); return r
        except Exception as e:
            last=e; time.sleep(1.5*(i+1))
    raise last

def dec(x):
    if x is None: return None
    s=str(x).strip().replace(',','').replace('−','-').replace('－','-')
    if s in ('','--','---','N/A','nan','None'): return None
    s=re.sub(r'<[^>]+>','',s).strip()
    try:return Decimal(s)
    except InvalidOperation:return None

def norm_date(x):
    s=re.sub(r'<[^>]+>','',str(x or '')).strip()
    m=re.search(r'(\d{2,4})[./-](\d{1,2})[./-](\d{1,2})',s)
    if not m:
        digits=re.sub(r'\D','',s)
        if len(digits)==8:return digits
        return None
    y,mo,d=map(int,m.groups())
    if y<1911:y+=1911
    return f'{y:04d}{mo:02d}{d:02d}'

def release_assets():
    url=f'https://api.github.com/repos/{SOURCE_REPO}/releases/tags/{SOURCE_TAG}'
    release=get(url).json()
    assets=release.get('assets',[])
    wanted=[]
    for a in assets:
        n=a['name']
        if re.fullmatch(r'yearly_20(18|19|20|21|22|23|24|25)\.zip',n): wanted.append(a)
        elif re.fullmatch(r'weekly_2026_W\d{2}\.zip',n):
            w=int(re.search(r'W(\d+)',n).group(1))
            if w<=34:wanted.append(a)
    return sorted(wanted,key=lambda a:a['name'])

def csv_rows_from_zip(blob, asset):
    z=zipfile.ZipFile(io.BytesIO(blob))
    for name in z.namelist():
        if not name.lower().endswith('.csv'):continue
        try:text=z.read(name).decode('utf-8-sig')
        except UnicodeDecodeError:text=z.read(name).decode('cp950',errors='replace')
        reader=csv.DictReader(io.StringIO(text))
        for row in reader:
            low={str(k).strip().lower():v for k,v in row.items()}
            date=low.get('date') or low.get('日期')
            code=str(low.get('code') or low.get('代號') or '').strip()
            if code not in TARGETS:continue
            date=re.sub(r'\D','',str(date or ''))[:8]
            if len(date)!=8:continue
            nm,market,start,_=TARGETS[code]
            if not(start<=date<=CUTOFF):continue
            yield {
              'date':date,'code':code,'name':str(low.get('name') or low.get('名稱') or nm).strip(),
              'market':market,'volume':str(low.get('volume') or low.get('成交股數') or '').replace(',','').strip(),
              'open':str(low.get('open') or low.get('開盤') or '').replace(',','').strip(),
              'high':str(low.get('high') or low.get('最高') or '').replace(',','').strip(),
              'low':str(low.get('low') or low.get('最低') or '').replace(',','').strip(),
              'close':str(low.get('close') or low.get('收盤') or '').replace(',','').strip(),
              'source_asset':asset,
            }

def build_raw():
    by_code=defaultdict(dict); manifest=[]
    assets=release_assets(); print('assets',len(assets))
    for i,a in enumerate(assets,1):
        n=a['name']; print(i,n)
        blob=get(a['browser_download_url']).content
        sha=hashlib.sha256(blob).hexdigest(); expected=(a.get('digest') or '').replace('sha256:','')
        added=0
        for r in csv_rows_from_zip(blob,n):
            key=r['date']; old=by_code[r['code']].get(key)
            if old and any(old[k]!=r[k] for k in ('open','high','low','close','volume')):
                raise RuntimeError(f'duplicate conflict {r["code"]} {key}')
            if not old: by_code[r['code']][key]=r; added+=1
        manifest.append([n,len(blob),sha,expected,sha==expected,added,a['browser_download_url']])
    with open(OUT/'source_manifest.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(['asset','size_bytes','sha256','expected_sha256','sha_ok','rows_added','url']); w.writerows(manifest)
    return by_code, manifest

def parse_twse_actions():
    events=[]
    for year in range(2018,2027):
        s=f'{year}0101'; e=CUTOFF if year==2026 else f'{year}1231'
        urls=[
          f'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate={s}&endDate={e}&response=json',
          f'https://www.twse.com.tw/exchangeReport/TWT49U?response=json&strDate={s}&endDate={e}'
        ]
        js=None
        for u in urls:
            try:
                j=get(u).json()
                if j.get('data'): js=j; break
            except Exception: pass
        if not js: continue
        fields=js.get('fields',[])
        def idx(cands, default):
            for i,x in enumerate(fields):
                if any(c in str(x) for c in cands): return i
            return default
        di=idx(['資料日期','除權息日期'],0); ci=idx(['股票代號','代號'],1); ni=idx(['股票名稱','名稱'],2)
        pi=idx(['除權息前收盤價'],3); ri=idx(['除權息參考價'],4)
        for row in js['data']:
            if len(row)<=max(di,ci,pi,ri):continue
            code=re.sub(r'<[^>]+>','',str(row[ci])).strip()
            if code not in TARGETS or TARGETS[code][1]!='TWSE':continue
            d=norm_date(row[di]); pre=dec(row[pi]); ref=dec(row[ri])
            if not d or not(START<=d<=CUTOFF) or pre is None or ref is None or pre<=0 or ref<=0:continue
            events.append({'event_date':d,'code':code,'name':TARGETS[code][0],'market':'TWSE','previous_close':pre,'reference_price':ref,'factor':ref/pre,'official_source':u})
    return events

def parse_tpex_actions():
    events=[]
    for year in range(2018,2027):
        ry=year-1911; end='115/08/17' if year==2026 else f'{ry}/12/31'
        start=f'{ry}/01/01'
        u=f'https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?l=zh-tw&d={start}&ed={end}'
        try:j=get(u).json()
        except Exception:continue
        rows=j.get('aaData') or j.get('data') or []
        for row in rows:
            if len(row)<5:continue
            d=norm_date(row[0]); code=re.sub(r'<[^>]+>','',str(row[1])).strip(); pre=dec(row[3]); ref=dec(row[4])
            if code not in TARGETS or TARGETS[code][1]!='TPEX':continue
            if not d or not(START<=d<=CUTOFF) or pre is None or ref is None or pre<=0 or ref<=0:continue
            events.append({'event_date':d,'code':code,'name':TARGETS[code][0],'market':'TPEX','previous_close':pre,'reference_price':ref,'factor':ref/pre,'official_source':u})
    return events

def prev_price(rows, event_date):
    for r in reversed(rows):
        if r['date']>=event_date:continue
        if all(dec(r[x]) is not None for x in ('open','high','low','close')):return r
    return None

def main():
    raw,manifest=build_raw()
    events=parse_twse_actions()+parse_tpex_actions()
    uniq={}
    for e in events: uniq[(e['code'],e['event_date'])]=e
    events=sorted(uniq.values(),key=lambda x:(x['code'],x['event_date']))
    by_event=defaultdict(list)
    for e in events:by_event[e['code']].append(e)

    qas=[]; event_out=[]; combined=[]; all_pass=True
    for code,(name,market,start,expected_source) in TARGETS.items():
        rows=sorted(raw[code].values(),key=lambda r:r['date'])
        source_rows=len(rows); no_trade=0; bad=0; price_rows=0; dup=source_rows-len({r['date'] for r in rows})
        for r in rows:
            vals=[dec(r[x]) for x in ('open','high','low','close')]; vol=dec(r['volume'])
            if all(v is None for v in vals) and (vol is None or vol==0): no_trade+=1; continue
            if any(v is None for v in vals):bad+=1; continue
            o,h,l,c=vals; price_rows+=1
            if h<max(o,c) or l>min(o,c) or h<l:bad+=1
        count_ok=source_rows==expected_source
        date_ok=bool(rows) and rows[0]['date']==start and rows[-1]['date']==CUTOFF
        evs=by_event.get(code,[])
        event_invalid=0; prev_mismatch=0
        for e in evs:
            pr=prev_price(rows,e['event_date']); actual=dec(pr['close']) if pr else None
            pm=(actual is not None and abs(actual-e['previous_close'])<=Decimal('0.05'))
            if not pm:prev_mismatch+=1
            valid=e['factor']>0
            if not valid:event_invalid+=1
            event_out.append([e['event_date'],code,name,market,str(e['previous_close']),str(e['reference_price']),f'{e["factor"]:.12f}',pr['date'] if pr else '',str(actual) if actual is not None else '',pm,'PASS' if valid else 'FAIL',e['official_source']])
        if code in EXPECTED_LAST3_EVENTS and len(evs)!=EXPECTED_LAST3_EVENTS[code]: event_invalid+=1
        stock_pass=count_ok and date_ok and dup==0 and bad==0 and event_invalid==0
        all_pass=all_pass and stock_pass
        qas.append([code,name,market,source_rows,price_rows,no_trade,expected_source,count_ok,start,rows[0]['date'] if rows else '',CUTOFF,rows[-1]['date'] if rows else '',dup,bad,len(evs),prev_mismatch,event_invalid,stock_pass])
        for r in rows:
            factor=Decimal('1')
            for e in evs:
                if e['event_date']>r['date']:factor*=e['factor']
            vals=[dec(r[x]) for x in ('open','high','low','close')]
            no_trade_flag=all(v is None for v in vals)
            adj=['','','',''] if no_trade_flag else [f'{(v*factor):.6f}' for v in vals]
            combined.append([r['date'],code,name,market,r['volume'],r['open'],r['high'],r['low'],r['close'],r['source_asset'],no_trade_flag,f'{factor:.12f}',*adj,'OK' if no_trade_flag or all(v is not None for v in vals) else 'FAIL'])

    with open(OUT/'corporate_actions_all20.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(['event_date','code','name','market','official_previous_close','official_reference_price','factor','previous_trade_date','actual_previous_close','previous_close_match','status','official_source']); w.writerows(event_out)
    with open(OUT/'all20_qa_summary.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(['code','name','market','source_rows','price_rows','no_trade_rows','expected_source_rows','source_count_match','expected_start','actual_start','expected_end','actual_end','duplicate_rows','price_or_ohlc_bad_rows','corporate_action_events','previous_close_mismatches_info','event_invalid','pass']); w.writerows(qas)
    with open(OUT/'price_history_all20_adjusted.csv','w',newline='',encoding='utf-8-sig') as f:
        w=csv.writer(f); w.writerow(['date','code','name','market','volume','open','high','low','close','source_asset','no_trade_placeholder','cumulative_factor','adj_open','adj_high','adj_low','adj_close','qa_status']); w.writerows(combined)
    report={'generated_at_utc':datetime.now(timezone.utc).isoformat(),'cutoff':CUTOFF,'source_rows_total':sum(int(x[3]) for x in qas),'price_rows_total':sum(int(x[4]) for x in qas),'no_trade_rows_total':sum(int(x[5]) for x in qas),'corporate_action_events_total':len(event_out),'all_pass':all_pass,'stocks':len(qas)}
    (OUT/'all20_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    sys.exit(0 if all_pass else 2)

if __name__=='__main__':main()
