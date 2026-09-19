#!/usr/bin/env python3
"""Date-aware public input collector. Does not generate predictions or synthetic prices."""
from __future__ import annotations
import argparse, concurrent.futures as cf, datetime as dt, hashlib, json, math
import pathlib, re, time, urllib.request, urllib.error
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Asia/Taipei')
class InputError(ValueError): pass
def stamp(): return dt.datetime.now(dt.timezone.utc).isoformat()
def sha(b): return hashlib.sha256(b).hexdigest()
def dump(path,obj):
    path=pathlib.Path(path); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(obj,ensure_ascii=False,indent=2),encoding='utf-8')
def date_of(s):
    s=str(s).strip()
    if re.fullmatch(r'\d{8}',s): return dt.datetime.strptime(s,'%Y%m%d').date()
    if '/' in s:
        y,m,d=map(int,s.split('/')); return dt.date(y+1911 if y<1911 else y,m,d)
    return dt.date.fromisoformat(s)
def calendar_days(payloads):
    closed=set(); years=set()
    for p in payloads:
        if str(p.get('stat','')).lower()!='ok' or not p.get('data'): raise InputError('CALENDAR_PAYLOAD_INVALID')
        year=int(p.get('queryYear',str(p.get('date',''))[:4])); year=year+1911 if year<1911 else year
        if any(date_of(r[0]).year!=year for r in p['data']): raise InputError('CALENDAR_YEAR_MISMATCH')
        years.add(year)
        for r in p['data']:
            if not any(x in str(r[1]) for x in ('開始交易','最後交易')): closed.add(date_of(r[0]))
    return closed,years

def resolve_calendar(payloads,target):
    target=date_of(target); closed,years=calendar_days(payloads)
    def isopen(d):
        if d.year not in years: raise InputError('CALENDAR_YEAR_UNCOVERED:'+str(d.year))
        return d.weekday()<5 and d not in closed
    if not isopen(target): raise InputError('NOT_SCHEDULED_TRADING_DAY:'+str(target))
    d=target-dt.timedelta(days=1)
    while not isopen(d): d-=dt.timedelta(days=1)
    cutoff=d; p=d-dt.timedelta(days=1)
    while not isopen(p): p-=dt.timedelta(days=1)
    fut=[];d=target
    while len(fut)<10:
        if isopen(d):fut.append(d.strftime('%Y%m%d'))
        d+=dt.timedelta(days=1)
    return {'target_date':target.isoformat(),'price_cutoff':cutoff.strftime('%Y%m%d'),'previous_session':p.strftime('%Y%m%d'),'future_dates':fut,'calendar_basis':'official annual calendar; exceptional closures require date-matched official market payloads'}

def official_quotes(p,market,day):
    if str(p.get('stat','')).lower()!='ok' or str(p.get('date','')).replace('/','')!=day: raise InputError('OFFICIAL_DATE_OR_STATUS:'+market)
    rows={}
    for t in p.get('tables',[]):
        f=t.get('fields',[])
        if market=='TWSE' and '證券代號' in f:c=f.index('證券代號');k=f.index('收盤價')
        elif market=='TPEX' and '代號' in f:c=f.index('代號');k=f.index('收盤')
        else:continue
        for r in t.get('data',[]):
            try: price=float(str(r[k]).replace(',',''))
            except (ValueError,TypeError):continue
            if price>0 and math.isfinite(price):rows[str(r[c])]=price
    if not rows:raise InputError('OFFICIAL_EMPTY:'+market)
    return rows

def validate_chart(payload,symbol,days,official):
    if 'provenance' in payload:raise InputError('SYNTHETIC_OR_REPACKAGED_CHART_REJECTED')
    try:
        if payload['chart'].get('error'):raise InputError('PROVIDER_ERROR')
        r=payload['chart']['result'][0]
        if r['meta']['symbol']!=symbol:raise InputError('SYMBOL_MISMATCH')
        quotes=r['indicators']['quote'][0]['close'];adjusted=r['indicators']['adjclose'][0]['adjclose'];ts=r['timestamp']
        if len(set(ts))!=len(ts) or len(ts)!=len(quotes) or len(ts)!=len(adjusted):raise InputError('CHART_AXIS_MISMATCH')
    except (KeyError,TypeError,IndexError):raise InputError('ADJUSTED_SERIES_REQUIRED_NO_RAW_FALLBACK')
    rows={}
    for t,c,a in zip(ts,quotes,adjusted):
        day=dt.datetime.fromtimestamp(t,TZ).strftime('%Y%m%d')
        if day in rows:raise InputError('DUPLICATE_SESSION')
        rows[day]={'close':c,'adjusted':a}
    checked={}
    for d in days:
        r=rows.get(d)
        if r is None or any(not isinstance(r[k],(int,float)) or isinstance(r[k],bool) or not math.isfinite(r[k]) or r[k]<=0 for k in ('close','adjusted')):raise InputError('MISSING_OR_INVALID_ADJUSTED:'+d)
        ref=official.get(d)
        if ref is None:raise InputError('OFFICIAL_REFERENCE_REQUIRED:'+d)
        if abs(r['close']-ref)>max(.011,abs(ref)*.00002):raise InputError('RAW_OFFICIAL_MISMATCH:'+d)
        checked[d]=r
    return {'status':'NATIVE_ADJUSTED_CROSSCHECK_PASS','symbol':symbol,'sessions':checked,'corporate_action_exhaustiveness':'NOT_ESTABLISHED_BY_CHART_ALONE','formal_input_qualified':False,'limitation':'Native adjusted series alone does not prove complete reduction/split coverage or pre-target corporate actions.'}

def get_json(url,path,attempt_limit=2):
    """Preserve bounded failure evidence without changing financial validation."""
    import socket, ssl
    if type(attempt_limit) is not int or not 1 <= attempt_limit <= 2:
        raise InputError('ATTEMPT_LIMIT_MUST_BE_ONE_OR_TWO')
    errors=[];diagnostics=[];path=pathlib.Path(path)
    def reject_constant(value): raise ValueError('NONFINITE_JSON:'+value)
    for n in range(attempt_limit):
        response=None;body=None;retryable=False
        info={'attempt':n+1,'requested_at':stamp(),'root_cause':'UNDETERMINED'}
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 premarket-data/1.0','Accept':'application/json'})
            response=urllib.request.urlopen(req,timeout=20)
            info['http_status']=response.getcode()
            body=response.read(33554433)
            if len(body)>33554432:raise InputError('RESPONSE_SIZE_LIMIT')
            p=json.loads(body,parse_constant=reject_constant)
            if not isinstance(p,dict):raise InputError('JSON_OBJECT_REQUIRED')
            path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
            return p,{'url':url,'path':str(path.name),'sha256':sha(body),'bytes':len(body),'retrieved_at':stamp(),
                      'attempts':n+1,'errors':errors,'diagnostics':diagnostics,'status':'FETCHED'}
        except urllib.error.HTTPError as e:
            response=e;info.update(http_status=e.code,category='HTTP_ERROR',error_type=type(e).__name__)
            if e.code in (401,403):info['category']='HTTP_AUTHORIZATION_ERROR'
            elif e.code==429:info['category']='HTTP_RATE_LIMITED'
            elif e.code>=500:info['category']='HTTP_SERVER_ERROR'
            retryable=e.code==429 or 500<=e.code<600
            headers=e.headers or {}
            info['headers']={k:headers.get(k) for k in ('Content-Type','Retry-After') if headers.get(k) is not None}
            try:body=e.read(262145)
            except Exception as read_error:info['body_read_error']=type(read_error).__name__+': '+str(read_error)
            errors.append(type(e).__name__+': '+str(e))
        except (urllib.error.URLError,TimeoutError,ssl.SSLError) as e:
            reason=e.reason if isinstance(e,urllib.error.URLError) else e
            category='NETWORK_DNS_ERROR' if isinstance(reason,socket.gaierror) else 'NETWORK_TIMEOUT' if isinstance(reason,TimeoutError) else 'NETWORK_TLS_ERROR' if isinstance(reason,ssl.SSLError) else 'NETWORK_ERROR'
            info.update(category=category,error_type=type(e).__name__)
            retryable=category!='NETWORK_TLS_ERROR'
            errors.append(type(e).__name__+': '+str(e))
        except Exception as e:
            info.update(category='LOCAL_SAVE_ERROR' if isinstance(e,OSError) else 'CONTENT_ERROR',error_type=type(e).__name__)
            errors.append(type(e).__name__+': '+str(e))
        finally:
            if response is not None:
                try:response.close()
                except Exception:info['response_close_failed']=True
        info['received_at']=stamp()
        if body is not None:
            full=len(body)<=262144;raw=body[:262144]
            evidence=path.with_name(path.name+f'.attempt-{n+1}.response.raw')
            try:
                evidence.parent.mkdir(parents=True,exist_ok=True)
                with evidence.open('xb') as f:f.write(raw)
                info.update(body_path=evidence.name,body_sha256=sha(raw),body_bytes=len(raw),body_complete=full)
            except OSError as save_error:
                info['evidence_save_error']=type(save_error).__name__+': '+str(save_error)
        diagnostics.append(info)
        if not retryable:break
        if n+1<attempt_limit:time.sleep(1)
    return None,{'url':url,'path':str(path.name),'sha256':None,'retrieved_at':stamp(),'attempts':len(errors),
                 'errors':errors,'diagnostics':diagnostics,'status':'FETCH_FAILED'}

def collect(out,target='auto',symbols=()):
    out=pathlib.Path(out);out.mkdir(parents=True,exist_ok=True);started=stamp();records=[];validation=[]
    now=dt.datetime.now(TZ);requested=now.date() if target=='auto' else date_of(target)
    c,m=get_json(f'https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear={requested.year-1911}',out/'calendar.json');records.append(m)
    if c is None:raise InputError('CALENDAR_FETCH_FAILED')
    if target=='auto':
        closed,years=calendar_days([c])
        while requested.weekday()>4 or requested in closed:requested+=dt.timedelta(days=1)
    calendar=[c]
    if requested.month in (1,12):
        year=requested.year+1 if requested.month==12 else requested.year-1
        extra,em=get_json(f'https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear={year-1911}',out/f'calendar_{year}.json');records.append(em)
        if extra:calendar.append(extra)
    dates=resolve_calendar(calendar,requested);cut=dates['price_cutoff'];prev=dates['previous_session'];end=dates['target_date'].replace('-','')
    jobs=[]
    for d in [prev,cut]:
        jobs += [(f'TWSE_{d}.json',f'https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date={d}&type=ALLBUT0999&response=json'),(f'TPEX_{d}.json',f'https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQuotes?date={d[:4]}%2F{d[4:6]}%2F{d[6:]}&id=&response=json')]
    jobs += [('index_raw.json',f'https://www.twse.com.tw/rwd/zh/afterTrading/FMTQIK?date={cut}&response=json'),('ohlc_raw.json',f'https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?date={cut}&response=json'),('actions_exdiv.json',f'https://www.twse.com.tw/exchangeReport/TWT49U?response=json&startDate={prev}&endDate={end}'),('tpex_exdiv.json',f'https://www.tpex.org.tw/www/zh-tw/bulletin/exDailyQ?startDate={prev[:4]}%2F{prev[4:6]}%2F{prev[6:]}&endDate={end[:4]}%2F{end[4:6]}%2F{end[6:]}&response=json')]
    def fetchjob(j):return j[0],get_json(j[1],out/j[0])
    payload={}
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        for name,(p,m) in pool.map(fetchjob,jobs):payload[name]=p;records.append(m)
    quotes={}
    for market in ('TWSE','TPEX'):
        for d in (prev,cut):
            try:quotes[market,d]=official_quotes(payload[f'{market}_{d}.json'],market,d);validation.append({'source':f'{market}_{d}.json','status':'PASS'})
            except Exception as e:validation.append({'source':f'{market}_{d}.json','status':'FAIL','error':str(e)})
    for name in ('index_raw.json','ohlc_raw.json'):
        try:
            p=payload[name]
            if str(p.get('stat','')).lower()!='ok':raise InputError('INDEX_STATUS')
            rows=[r for r in p.get('data',[]) if date_of(r[0])<=date_of(cut)]
            if not rows or max(date_of(r[0]) for r in rows)!=date_of(cut):raise InputError('EXPECTED_CLOSE_MISSING')
            view=dict(p);view['data']=rows;view['total']=len(rows);dump(out/name.replace('_raw','_cutoff'),view)
            validation.append({'source':name,'status':'PASS','cutoff_view':name.replace('_raw','_cutoff'),'derived_from_raw_sha256':sha((out/name).read_bytes())})
        except Exception as e:validation.append({'source':name,'status':'FAIL','error':str(e)})
    for name in ('actions_exdiv.json','tpex_exdiv.json'):
        try:
            p=payload[name];ok=p and str(p.get('stat','')).lower()=='ok'
            if name.startswith('tpex'):ok=ok and p.get('date')==prev+'~'+end
            else:ok=ok and p.get('strDate')==prev and p.get('endDate')==end
            if not ok:raise InputError('ACTION_RANGE_NOT_CONFIRMED')
            validation.append({'source':name,'status':'PASS','scope':'EX_RIGHT_DIVIDEND_ONLY_NOT_ALL_CORPORATE_ACTIONS'})
        except Exception as e:validation.append({'source':name,'status':'FAIL','error':str(e)})
    for symbol in symbols:
        if not re.fullmatch(r'[A-Z0-9]{4,8}\.(TW|TWO)',symbol):raise InputError('INVALID_SYMBOL:'+symbol)
    jobs=[(f'chart_{s}.json',f'https://query1.finance.yahoo.com/v8/finance/chart/{s}?interval=1d&range=3mo&events=div%2Csplits&includeAdjustedClose=true') for s in symbols]
    charts=[]
    with cf.ThreadPoolExecutor(max_workers=3) as pool:
        for name,(p,m) in pool.map(fetchjob,jobs):
            records.append(m);s=name[6:-5];market='TPEX' if s.endswith('.TWO') else'TWSE';code=s.split('.')[0]
            try:charts.append(validate_chart(p,s,[prev,cut],{d:quotes.get((market,d),{}).get(code) for d in (prev,cut)}))
            except Exception as e:charts.append({'symbol':s,'status':'FAIL','error':str(e),'formal_input_qualified':False})
    result={'started_at':started,'completed_at':stamp(),'dates':dates,'sources':records,'official_validation':validation,'charts':charts,'transport_complete':all(r['status']=='FETCHED' for r in records),'official_validation_pass':all(v['status']=='PASS' for v in validation),'formal_input_qualified':False,'prediction_generated':False,'portfolio_data_collected':False,'remaining_requirements':['Complete qualified corporate-action coverage, including reductions/splits and target-day effects','Original gate and exact model-input continuity check','Same-run report, two-provider save/readback and actual scheduled delivery']}
    dump(out/'acquisition_receipt.json',result);return result

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--out',required=True);ap.add_argument('--target-date',default='auto');ap.add_argument('--symbols',default='2330.TW,0050.TW,5274.TWO');a=ap.parse_args()
    try:
        r=collect(a.out,a.target_date,[s for s in a.symbols.split(',') if s]);print(json.dumps(r,ensure_ascii=False));return 0 if r['official_validation_pass'] and r['transport_complete'] and all(c['status']!='FAIL' for c in r['charts']) else 2
    except Exception as e:
        r={'completed_at':stamp(),'status':'INPUT_ACQUISITION_FAILED','error':str(e),'formal_input_qualified':False,'prediction_generated':False};dump(pathlib.Path(a.out)/'acquisition_receipt.json',r);print(json.dumps(r,ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
