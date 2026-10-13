#!/usr/bin/env python3
"""Research-only, exact-day TWSE/TPEx actual OHLC. Never writes any Prediction/Outcome."""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, pathlib, re, time, urllib.request, urllib.error
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Asia/Taipei')
DAY='20261013'
def sha(raw): return hashlib.sha256(raw).hexdigest()
def need(ok,code):
    if not ok: raise ValueError(code)
def date8(x):
    s=str(x).strip()
    if re.fullmatch(r'\d{8}',s): return s
    m=re.fullmatch(r'(\d{2,4})/(\d{1,2})/(\d{1,2})',s)
    need(m is not None,'BAD_OFFICIAL_DATE')
    y,mo,d=map(int,m.groups())
    return dt.date(y+1911 if y<1911 else y,mo,d).strftime('%Y%m%d')
def price(v):
    try:
        n=float(str(v).replace(',',''))
        return n if math.isfinite(n) and n>0 else None
    except (ValueError,TypeError): return None
def parse_quotes(doc,venue,day):
    need(isinstance(doc,dict) and str(doc.get('stat','')).lower()=='ok','OFFICIAL_NOT_OK_'+venue)
    need(date8(doc.get('date'))==day,'OFFICIAL_WRONG_DATE_'+venue)
    fields=('證券代號','證券名稱','開盤價','最高價','最低價','收盤價') if venue=='TWSE' else ('代號','名稱','開盤','最高','最低','收盤')
    out={};found=0
    for t in doc.get('tables',[]):
        f=t.get('fields') or []
        if fields[0] not in f: continue
        need(all(f.count(k)==1 for k in fields),'OFFICIAL_MISSING_FIELDS_'+venue)
        ci=[f.index(k) for k in fields];found+=1
        for row in t.get('data',[]):
            need(isinstance(row,list) and len(row)>max(ci),'OFFICIAL_WRONG_ROW_SIZE')
            code=str(row[ci[0]]).strip();name=str(row[ci[1]]).strip()
            need(bool(code and name),'OFFICIAL_BLANK_NAME')
            need(code not in out,'OFFICIAL_DUPLICATE_CODE_'+code)
            o,h,l,c=[price(row[j]) for j in ci[2:]]
            if any(z is None for z in (o,h,l,c)):
                out[code]={'Name':name,'Status':'HOLD_MISSING_OHLC','Open':None,'High':None,'Low':None,'Close':None}
            elif not (l<=min(o,c)<=max(o,c)<=h):
                # Corrupt per-symbol quote must never erase valid siblings.
                # Retain security identity; do not publish logically invalid prices.
                out[code]={'Name':name,'Status':'HOLD_INVALID_OFFICIAL_OHLC_INVARIANT',
                           'Open':None,'High':None,'Low':None,'Close':None}
            else:
                out[code]={'Name':name,'Status':'PASS_OFFICIAL_OHLC','Open':o,'High':h,'Low':l,'Close':c}
    need(found>0 and bool(out),'OFFICIAL_EMPTY_'+venue)
    return out
def parse_index(doc,day):
    need(isinstance(doc,dict) and str(doc.get('stat','')).lower()=='ok','TAIEX_NOT_OK')
    need(date8(doc.get('date'))==day,'TAIEX_WRONG_DATE')
    fields=doc.get('fields');keys=('日期','開盤指數','最高指數','最低指數','收盤指數')
    need(isinstance(fields,list) and all(fields.count(k)==1 for k in keys),'TAIEX_FIELDS_INVALID')
    idx=[fields.index(k) for k in keys];found=[]
    for row in doc.get('data',[]):
        need(isinstance(row,list) and len(row)>max(idx),'TAIEX_BAD_ROW')
        date=date8(row[idx[0]])
        need(date<=day,'TAIEX_FUTURE_LEAK')
        if date!=day:continue
        need(not found,'TAIEX_DUPLICATE_TARGET')
        o,h,l,c=[price(row[k]) for k in idx[1:]]
        need(all(z is not None for z in (o,h,l,c)),'TAIEX_NONNUMERIC')
        need(l<=min(o,c)<=max(o,c)<=h,'TAIEX_OHLC_INCONSISTENT')
        found.append({'Open':o,'High':h,'Low':l,'Close':c})
    need(len(found)==1,'TAIEX_DAY_MISSING')
    return found[0]
def fetch(url,dst):
    errors=[]
    for attempt in range(2):
        try:
            request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 StockResearch/1.0','Accept':'application/json','Cache-Control':'no-cache'})
            with urllib.request.urlopen(request,timeout=22) as r:
                need(r.status==200,'HTTP_NOT_OK')
                content=r.read(30_000_001)
                need(len(content)<=30_000_000,'TOO_LARGE')
            raw=json.loads(content)
            need(isinstance(raw,dict),'JSON_OBJECT_EXPECTED')
            dst.write_bytes(content)
            return raw,{'Status':'PASS','URL':url,'OriginalSHA256':sha(content),'Bytes':len(content),'RetrievedAtUTC':dt.datetime.now(dt.timezone.utc).isoformat()}
        except Exception as e:
            errors.append(f'{type(e).__name__}:{str(e)[:130]}')
            if isinstance(e,urllib.error.HTTPError) and e.code not in (429,500,502,503,504):break
            if attempt==0:time.sleep(.4)
    return None,{'Status':'FETCH_FAILED','URL':url,'OriginalSHA256':None,'Errors':errors}
def markdown(rows,index):
    line=['# 2026/10/13 68檔官方收盤（研究回填來源）','',
      '完整官方來源驗證：此表只有盤後實際 OHLC，不包含任何事前預測或投資指令。','']
    line.append('TAIEX: '+(', '.join(f'{k} {v:,.2f}' for k,v in index.items()) if index else 'MISSING_TAIEX'))
    line+=['','| 股票代號 | 官方中文名稱 | 場別 | 開盤 | 最高 | 最低 | 收盤 | 證據狀態 |','|---|---|---|---:|---:|---:|---:|---|']
    for x in rows:
        def num(k):return f'{x[k]:,.2f}' if isinstance(x.get(k),(int,float)) else 'MISSING'
        line.append('| '+' | '.join([x['Symbol'],x.get('Name') or 'MISSING',x['Venue'],num('Open'),num('High'),num('Low'),num('Close'),x['Status']])+' |')
    line.append('\n研究資料不等於正式事前預測。未驗原始Preopen封存、Issuer或Cash7者，Formal/Natural/OOS保持0。')
    return '\n'.join(line)+'\n'
def selftest():
    day=DAY;result={}
    tw={'stat':'OK','date':day,'tables':[{'fields':['收盤價','證券名稱','證券代號','最高價','開盤價','最低價'],'data':[['102','台積電','2330','103','100','98']]}]}
    tp={'stat':'OK','date':day,'tables':[{'fields':['代號','名稱','開盤','最高','最低','收盤'],'data':[['6223','旺矽','9','12','8','11']]}]}
    index={'stat':'OK','date':day,'fields':['日期','開盤指數','最高指數','最低指數','收盤指數'],'data':[['115/10/13','100','110','95','105']]}
    def test(name,call,reject=False):
        try:
            x=call();result[name]='FAIL_EXPECTED_HOLD' if reject else ('PASS' if x else 'FAIL_ASSERT')
        except (ValueError,TypeError,IndexError,KeyError):result[name]='PASS' if reject else 'FAIL'
    def mutate(x,fn):
        y=json.loads(json.dumps(x));fn(y);return y
    test('twse_field_order',lambda:parse_quotes(tw,'TWSE',day)['2330']['Close']==102)
    test('tpex_quote_positive',lambda:parse_quotes(tp,'TPEx',day)['6223']['Close']==11)
    test('index_valid',lambda:parse_index(index,day)['Close']==105)
    test('wrong_day_rejected',lambda:parse_quotes(mutate(tw,lambda z:z.update(date='20261012')),'TWSE',day),True)
    test('wrong_venue_rejected',lambda:parse_quotes(tw,'TPEx',day),True)
    test('duplicate_symbol_rejected',lambda:parse_quotes(mutate(tw,lambda z:z['tables'][0]['data'].append(z['tables'][0]['data'][0][:])),'TWSE',day),True)
    test('missing_close_hold_only',lambda:parse_quotes(mutate(tw,lambda z:z['tables'][0]['data'][0].__setitem__(0,'--')),'TWSE',day)['2330']['Status']=='HOLD_MISSING_OHLC')
    test('bad_price_bounds_hold_only',lambda:parse_quotes(mutate(tw,lambda z:z['tables'][0]['data'][0].__setitem__(3,'99')),'TWSE',day)['2330']['Status']=='HOLD_INVALID_OFFICIAL_OHLC_INVARIANT')
    def two_rows():
        return mutate(tw,lambda z:z['tables'][0]['data'].append(['25','廣達','2382','26','24','23']))
    test('one_inconsistent_one_good',lambda:(
        lambda y:y['2330']['Status']=='HOLD_INVALID_OFFICIAL_OHLC_INVARIANT' and
                 y['2382']['Status']=='PASS_OFFICIAL_OHLC' and y['2382']['Close']==25
        )(parse_quotes(mutate(two_rows(),lambda z:z['tables'][0]['data'][0].__setitem__(3,'99')),'TWSE',day)))
    test('one_non_numeric_one_good',lambda:(
        lambda y:y['2330']['Status']=='HOLD_MISSING_OHLC' and
                 y['2382']['Status']=='PASS_OFFICIAL_OHLC' and y['2382']['Close']==25
        )(parse_quotes(mutate(two_rows(),lambda z:z['tables'][0]['data'][0].__setitem__(0,'--')),'TWSE',day)))
    test('missing_col_rejected',lambda:parse_quotes(mutate(tw,lambda z:z['tables'][0]['fields'].__setitem__(0,'unknown')),'TWSE',day),True)
    test('index_duplicate_date_rejected',lambda:parse_index(mutate(index,lambda z:z['data'].append(z['data'][0][:])),day),True)
    test('index_wrong_day_rejected',lambda:parse_index(mutate(index,lambda z:z.update(date='20261012')),day),True)
    test('index_future_rejected',lambda:parse_index(mutate(index,lambda z:z['data'].append(['115/10/14','100','110','95','105'])),day),True)
    ok=all(v=='PASS' for v in result.values())
    return {'Status':'PASS' if ok else 'FAIL','Passed':sum(x=='PASS' for x in result.values()),'Total':len(result),'Tests':result,'Scope':'SYNTHETIC_NO_REAL_DATA'}
def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--target',default=DAY);p.add_argument('--out',default='stock_1013_official_actual')
    a=p.parse_args()
    if a.self_test:
        r=selftest();print(json.dumps(r,ensure_ascii=False));return 0 if r['Status']=='PASS' else 2
    need(a.target==DAY,'ONLY_EXACT_20261013_TARGET')
    now=dt.datetime.now(TZ)
    need(now.date()>dt.date(2026,10,13) or (now.date()==dt.date(2026,10,13) and now.time()>=dt.time(13,45)),'TARGET_NOT_YET_CLOSED')
    from stock_adjusted_20261013_source_closure import CODES
    codes=list(CODES);need(len(codes)==len(set(codes))==68,'UNIVERSE_NOT_UNIQUE68')
    out=pathlib.Path(a.out);out.mkdir(exist_ok=True,parents=True)
    endpoints={'TWSE':f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={DAY}&type=ALLBUT0999&response=json',
     'TPEx':'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date=2026%2F10%2F13&id=&response=json',
     'TAIEX':f'https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?date={DAY}&response=json'}
    sources={};meta={};problems=[]
    for venue,url in endpoints.items():
        d,m=fetch(url,out/(venue.lower()+'_raw.json'));meta[venue]=m
        if d is None:problems.append('FETCH_'+venue)
        else:
            try:sources[venue]=parse_index(d,DAY) if venue=='TAIEX' else parse_quotes(d,venue,DAY)
            except Exception as exc:problems.append(venue+'_PARSE_'+str(exc))
    rows=[]
    for ticker in codes:
        sym,ext=ticker.split('.');venue='TPEx' if ext=='TWO' else 'TWSE'
        obj=sources.get(venue,{}).get(sym)
        r={'Symbol':sym,'Venue':venue,**(obj or {'Name':None,'Open':None,'High':None,'Low':None,'Close':None,'Status':'HOLD_OFFICIAL_MISSING'})}
        r.update(OfficialSourceSHA256=meta.get(venue,{}).get('OriginalSHA256'),OfficialAsOf=DAY)
        rows.append(r)
    count=sum(x['Status']=='PASS_OFFICIAL_OHLC' for x in rows)
    result={'Date':DAY,'Status':'OFFICIAL_68_READY' if count==68 and sources.get('TAIEX') else 'OFFICIAL_PARTIAL_HOLD',
      'CountVerified':count,'CountHold':68-count,'TAIEX':sources.get('TAIEX'),'Records':rows,
      'RawSources':meta,'Problems':problems,'FormalPredictionWritten':False,'NaturalCredit':0,'OOSCredit':0}
    (out/'official_actual_68.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    (out/'official_actual_68.md').write_text(markdown(rows,result['TAIEX']),encoding='utf8')
    check=json.loads((out/'official_actual_68.json').read_bytes())
    need(check['CountVerified']==count and len(check['Records'])==68,'FILE_READBACK_MISMATCH')
    print(json.dumps({'status':result['Status'],'count':count,'taiex':result['TAIEX'],'errors':problems,'source_sha':{k:v.get('OriginalSHA256') for k,v in meta.items()}},ensure_ascii=False))
    print('OFFICIAL_68_JSON='+json.dumps({'Date':DAY,'TAIEX':result['TAIEX'],'Records':rows,'SHA':{k:v.get('OriginalSHA256') for k,v in meta.items()}},ensure_ascii=False,separators=(',',':')))
    return 0 if result['Status']=='OFFICIAL_68_READY' else 2
if __name__=='__main__':raise SystemExit(main())
