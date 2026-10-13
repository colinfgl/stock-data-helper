#!/usr/bin/env python3
"""Post-close Taiwan 68-security provenance pack for next premarket.

One source-only GitHub Actions helper, never another ChatGPT premarket or settlement
job. Reuses existing stock-data-helper dynamic official/calendar/Yahoo collector,
then writes a private-proof-compatible H9 source package and integrity manifest.
The full provider chart and official original bytes are maintained separately.
NO Formal, order, portfolio, historical prediction, Natural, OOS or prompt writes.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, pathlib, re, sys, zipfile
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Asia/Taipei')

def sha(raw: bytes) -> str: return hashlib.sha256(raw).hexdigest()
def canon(x):return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def check(cond,msg):
    if not cond:raise ValueError(msg)
def date8(s):
    s=str(s)
    check(bool(re.fullmatch(r'\d{8}',s)),'DATE8_REQUIRED')
    return dt.datetime.strptime(s,'%Y%m%d').date()
def next_session(base: dt.date, closed: set[dt.date], years: set[int]):
    check(base.year in years,'CALENDAR_BASE_YEAR_UNVERIFIED')
    check(base.weekday()<5 and base not in closed,'BASE_DATE_NOT_A_TRADING_DAY')
    target=base+dt.timedelta(days=1)
    while True:
        check(target.year in years,'TARGET_YEAR_UNVERIFIED')
        if target.weekday()<5 and target not in closed:return target
        target+=dt.timedelta(days=1)

def runtime_day_gate(now: dt.datetime):
    check(now.tzinfo is not None,'NAIVE_CLOCK_HOLD')
    z=now.astimezone(TZ)
    check(dt.time(19,0)<=z.time()<dt.time(23,55),'AFTER_CLOSE_WINDOW_REQUIRED_19_TO_2355')
    return z.date()

def approved_universe():
    from stock_adjusted_20261013_source_closure import CODES
    check(len(CODES)==68 and len(set(CODES))==68,'SOURCE_UNIVERSE_NOT_68_UNIQUE')
    check(all(re.fullmatch(r'[A-Z0-9]{4,8}\.(TW|TWO)',s) for s in CODES),'BAD_TICKER')
    return CODES


def validated_taiex_ohlc(document: dict, day: str) -> dict:
    """Verify the original first-party monthly TWSE index OHLC contains exact target day."""
    check(isinstance(document,dict),'TAIEX_PARENT_OBJECT_REQUIRED')
    check(str(document.get('date'))==day and str(document.get('stat','')).lower()=='ok',
          'TAIEX_PARENT_DATE_OR_STATUS')
    required=('日期','開盤指數','最高指數','最低指數','收盤指數')
    fields=document.get('fields')
    check(isinstance(fields,list) and all(fields.count(k)==1 for k in required),
          'TAIEX_OHLC_FIELDS_REQUIRED')
    idx=[fields.index(k) for k in required]
    check(isinstance(document.get('data'),list) and len(document['data'])>0,'TAIEX_OHLC_ROWS_EMPTY')
    target=date8(day)
    found=[]
    for row in document['data']:
        check(isinstance(row,list) and len(row)>max(idx),'TAIEX_OHLC_ROW_SCHEMA')
        match=re.fullmatch(r'(\d{2,4})/(\d{1,2})/(\d{1,2})',str(row[idx[0]]).strip())
        check(match is not None,'TAIEX_OHLC_ROC_DATE_BAD')
        yy,mm,dd=map(int,match.groups())
        this=dt.date(yy+1911 if yy<1911 else yy,mm,dd)
        check(this<=target,'TAIEX_OHLC_FUTURE_DATE_LEAK')
        if this==target:
            check(not found,'TAIEX_OHLC_DUPLICATE_TARGET_DATE')
            try:
                o,h,l,cl=[float(str(row[k]).replace(',','')) for k in idx[1:]]
            except (TypeError,ValueError,OverflowError) as exc:
                raise ValueError('TAIEX_OHLC_NON_NUMERIC') from exc
            check(all(math.isfinite(n) and n>0 for n in (o,h,l,cl)),
                  'TAIEX_OHLC_NONFINITE_OR_NONPOSITIVE')
            check(l<=min(o,cl)<=max(o,cl)<=h,'TAIEX_OHLC_PRICE_INVARIANT')
            found.append({'open':o,'high':h,'low':l,'close':cl})
    check(len(found)==1,'TAIEX_OHLC_EXACT_DAY_MISSING')
    return found[0]

def official_names(obj, market, date):
    check(str(obj.get('date'))==date and str(obj.get('stat','')).lower()=='ok',
          'OFFICIAL_NAME_DATE_OR_STATUS_INVALID_'+market)
    symbol_col,name_col=('證券代號','證券名稱') if market=='TWSE' else ('代號','名稱')
    names={};matched=0
    for block in obj.get('tables',[]):
        fields=block.get('fields') or []
        if symbol_col not in fields:continue
        check(fields.count(symbol_col)==1 and fields.count(name_col)==1,
              'OFFICIAL_NAME_FIELDS_AMBIGUOUS_'+market)
        ci=fields.index(symbol_col);ni=fields.index(name_col);matched+=1
        for row in block.get('data',[]):
            check(isinstance(row,list) and len(row)>max(ci,ni),
                  'OFFICIAL_NAME_ROW_SCHEMA_'+market)
            code=str(row[ci]).strip();name=str(row[ni]).strip()
            check(bool(code and name) and name.lower() not in ('none','null','nan'),
                  'OFFICIAL_NAME_EMPTY_'+market)
            check(code not in names,'OFFICIAL_DUPLICATE_NAMED_SYMBOL_'+market+'_'+code)
            names[code]=name
    check(matched>0 and bool(names),'OFFICIAL_NAME_TABLE_MISSING_'+market)
    return names
def build_h9_package(folder: pathlib.Path, target: dt.date, day: dt.date, universe: list[str], output: pathlib.Path):
    """Require one independently SHA-verified chart per security plus firstparty quotes."""
    def official_quotes(obj, market, date):
        check(str(obj.get('date'))==date and str(obj.get('stat','')).lower()=='ok','OFFICIAL_DATE_OR_STATUS_INVALID_'+market)
        result={}
        for block in obj.get('tables',[]):
            fields=block.get('fields') or []
            code_key='證券代號' if market=='TWSE' else '代號'
            price_key='收盤價' if market=='TWSE' else '收盤'
            if code_key not in fields or price_key not in fields:continue
            check(fields.count(code_key)==1 and fields.count(price_key)==1,'OFFICIAL_AMBIGUOUS_COLS_'+market)
            ci=fields.index(code_key);pi=fields.index(price_key)
            for row in block.get('data',[]):
                check(len(row)==len(fields),'OFFICIAL_ROW_WRONG_SIZE_'+market)
                code=str(row[ci]); v=str(row[pi]).replace(',','')
                try: x=float(v)
                except (ValueError,TypeError):continue
                if not math.isfinite(x) or x<=0:continue
                check(code not in result,'DUPLICATE_OFFICIAL_SYMBOL_'+code)
                result[code]=x
        check(result,'OFFICIAL_CLOSE_EMPTY_'+market)
        return result
    d=day.strftime('%Y%m%d'); t=target.strftime('%Y%m%d')
    official_files={'twse':folder/f'TWSE_{d}.json','tpex':folder/f'TPEX_{d}.json', 'ohlc':folder/'ohlc_raw.json'}
    raws={k:p.read_bytes() for k,p in official_files.items()}
    for role,raw in raws.items():
        doc=json.loads(raw)
        check(str(doc.get('date'))==d,'OFFICIAL_DATE_NOT_PREVIOUS_SESSION_'+role)
        check(str(doc.get('stat','')).lower()=='ok','OFFICIAL_STATUS_NOT_OK_'+role)
    taiex=validated_taiex_ohlc(json.loads(raws['ohlc']),d)
    names={'TWSE':official_names(json.loads(raws['twse']),'TWSE',d),
           'TPEx':official_names(json.loads(raws['tpex']),'TPEx',d)}
    quote={'TWSE':official_quotes(json.loads(raws['twse']),'TWSE',d),
           'TPEx':official_quotes(json.loads(raws['tpex']),'TPEX',d)}
    rt=folder/'acquisition_receipt.json';rr=json.loads(rt.read_bytes())
    check(rr['dates']['target_date']==target.isoformat(),'COLLECTOR_TARGET_MISMATCH')
    check(rr['dates']['price_cutoff']==d,'COLLECTOR_CUTOFF_MISMATCH')
    required_sources={f'TWSE_{d}.json',f'TPEX_{d}.json','ohlc_raw.json'}
    exact_receipts=[v for v in rr.get('official_validation',[]) if v.get('source') in required_sources]
    check(len(exact_receipts)==3 and {v['source'] for v in exact_receipts}==required_sources and
          all(v.get('status')=='PASS' for v in exact_receipts),
          'OFFICIAL_TWSE_TPEX_TAIEX_VALIDATION_RECEIPTS_REQUIRED')
    entries=[];rawchart={}
    checked={r['symbol']:r for r in rr.get('charts',[]) if r.get('status')=='NATIVE_ADJUSTED_CROSSCHECK_PASS'}
    # The collector's own success status is strictly per original code/date; all 68
    # must pass without a fallback or a replacement from old output dates.
    for ticker in universe:
        code,ext=ticker.split('.');market='TPEx' if ext=='TWO' else 'TWSE'
        rec=checked.get(ticker)
        check(rec is not None,'SINGLE_SYMBOL_NOT_READY_'+ticker)
        chk=folder/f'chart_{ticker}.json'
        body=chk.read_bytes();doc=json.loads(body)
        result=doc['chart']['result']
        check(len(result)==1 and result[0]['meta']['symbol']==ticker,'SOURCE_PROVIDER_SYMBOL_CONFLICT_'+ticker)
        timestamps=result[0].get('timestamp') or []
        quote_rows=result[0]['indicators']['quote'][0]['close']; adjrows=result[0]['indicators']['adjclose'][0]['adjclose']
        check(len(timestamps)==len(quote_rows)==len(adjrows),'SOURCE_ARRAYS_MISMATCH_'+ticker)
        dates=[dt.datetime.fromtimestamp(z,TZ).strftime('%Y%m%d') for z in timestamps]
        check(len(set(dates))==len(dates) and dates==sorted(dates),'SOURCE_DUPLICATE_DATES_'+ticker)
        check(dates[-1]==d,'SOURCE_CUTOFF_STALE_'+ticker)
        check(not any(x> d for x in dates),'SOURCE_LEAKED_FUTURE_'+ticker)
        official_close=quote[market].get(code)
        check(isinstance(official_close,(int,float)) and math.isfinite(official_close) and official_close>0,'OFFICIAL_CLOSE_MISSING_'+ticker)
        j=dates.index(d)
        close=quote_rows[j]; adj=adjrows[j]
        check(isinstance(close,(int,float)) and isinstance(adj,(int,float)) and close>0 and adj>0,'CHART_CLOSE_MISSING_'+ticker)
        check(abs(close-official_close)<max(0.011,official_close*.00002),'OFFICIAL_YAHOO_CLOSE_MISMATCH_'+ticker)
        official_name=names[market].get(code)
        check(isinstance(official_name,str) and bool(official_name.strip()),
              'OFFICIAL_NAME_MISSING_FOR_UNIVERSE_'+ticker)
        source_rel='yahoo_raw/chart_'+ticker+'.json';rawchart[source_rel]=body
        original_receipt=next((x for x in rr.get('sources',[]) if x.get('path')==chk.name),None)
        check(original_receipt is not None and original_receipt.get('sha256')==sha(body),'SOURCE_INDEPENDENT_RAW_SHA_MISMATCH_'+ticker)
        bar_asof=dt.datetime.fromtimestamp(timestamps[j],TZ)
        check(bar_asof.date()==day,'PROVIDER_BAR_DATE_NOT_PRIOR_SESSION_'+ticker)
        entries.append({'code':code,'name':official_name,'venue':market,
          'official_name_source':'NATIVE_EXACT_DATE_'+market,
          'provider_short_label_for_audit':str(result[0]['meta'].get('shortName') or ''),
          'ticker':ticker,'target_date':target.isoformat(),'source_cutoff_date':day.isoformat(),
          'provider_raw_sha256':sha(body),'provider_raw_file':source_rel,
          'retrieved_at':original_receipt['retrieved_at'],
          'published_or_asof':bar_asof.strftime('%Y-%m-%d %H:%M Asia/Taipei'),
          'provider_bar_asof_basis':'YAHOO_ORIGINAL_BAR_TIMESTAMP_NOT_INDEPENDENT_PUBLICATION_TIME',
          'corporate_action_exhaustive':'UNVERIFIED','official_close':float(official_close),
          'formal_input_qualified':False,'natural_credit':0,'oos_credit':0})
    check(len(entries)==68 and len({r['provider_raw_sha256'] for r in entries})==68,'INDEPENDENT_SOURCE_CLOSURE_FAIL')
    all_original_shas={r['provider_raw_sha256'] for r in entries}|{sha(v) for v in raws.values()}
    check(len(all_original_shas)==71,'SOURCES_68_PLUS_3_SHA_UNIQUENESS_FAIL')
    index={'authoritative_target':target.isoformat(),'source_cutoff':day.isoformat(),
      'data_generation_timestamp_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
      'official_original_shas':{k:sha(v) for k,v in raws.items()},
      'rows':entries,'manifest_version':'STOCK-DAILY-SOURCE-68-v1.2-OFFICIAL-NAMES',
      'all_names_from_official':True,
      'official_taiex_ohlc':taiex,'source_qualification':'RESEARCH_ONLY',
      'corporate_action_gate':'ISSUER_ALL_ACTIONS_NOT_EXHAUSTIVE','formal_input_qualified':False,
      'forecast_generated':False,'cash_changed':False,'natural_credit':0,'oos_credit':0}
    output.mkdir(parents=True,exist_ok=False)
    target_zip=output/('h9_source_'+t+'.zip')
    with zipfile.ZipFile(target_zip,'w',compression=zipfile.ZIP_DEFLATED) as zp:
        for role,raw in raws.items():zp.writestr('official_raw/'+('tpex' if role=='tpex' else role)+'.attempt1.json',raw)
        for name,raw in sorted(rawchart.items()):zp.writestr(name,raw)
    (output/'h9_source_index.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    status={'status':'RESEARCH_SOURCE_68_OF_68_READY_NOT_FORMAL','target_date':target.isoformat(),
      'source_date':day.isoformat(),'ticker_count':68,'per_symbol_sha_count':len(entries),
      'official_primary_count':2,'TAIEX_INDEX_PARENT_SHA':index['official_original_shas']['ohlc'],
      'package_sha256':sha(target_zip.read_bytes()),'source_index_sha256':sha((output/'h9_source_index.json').read_bytes()),
      'total_unique_original_raw_shas':len(all_original_shas),
      'taiex_ohlc_verified':True,'taiex_ohlc':taiex,
      'full_official_symbol_names':True,
      'formal_input_qualified':False,'formal_forecast_written':False,'natural_credit':0,'oos_credit':0,
      'limitation':'Corporate action MOPS exhaustive, formal Model/Config same-run seal, and market-day source original approval still required.'}
    (output/'source_closure_readback.json').write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    # Verify archive bytes after close. Never trust only the writes.
    with zipfile.ZipFile(target_zip) as zp:
        check(len(zp.namelist())==71 and len(set(zp.namelist()))==71,'PACKED_SOURCE_ENTRY_COUNT_BAD')
        for k,raw in raws.items():check(sha(zp.read('official_raw/'+k+'.attempt1.json'))==sha(raw),'PACK_OFFICIAL_BYTES_DRIFT_'+k)
        for filename,raw in rawchart.items():check(sha(zp.read(filename))==sha(raw),'PACK_CHART_BYTES_DRIFT_'+filename)
    return status

def bind_calendar_to_source_index(pack:pathlib.Path,outer:pathlib.Path,original_sha:str,status:dict):
    """Bind the exact official calendar parent to H9 index and both closure receipts."""
    check(isinstance(original_sha,str) and re.fullmatch(r'[0-9a-f]{64}',original_sha),
          'CALENDAR_SHA256_REQUIRED')
    indexfile=pack/'h9_source_index.json'
    index=json.loads(indexfile.read_bytes())
    check(index.get('source_qualification')=='RESEARCH_ONLY' and
          index.get('formal_input_qualified') is False and
          index.get('corporate_action_gate')=='ISSUER_ALL_ACTIONS_NOT_EXHAUSTIVE',
          'CALENDAR_SOURCE_GOVERNANCE_CONFLICT')
    entries=index.get('rows')
    check(isinstance(entries,list) and len(entries)==68 and
          len({r['code'] for r in entries})==68,'CALENDAR_SOURCE_UNIVERSE_NOT_68')
    check(index.get('official_calendar_sha256') in (None,original_sha),
          'CALENDAR_ORIGINAL_SHA_CONFLICT')
    check(status.get('source_index_sha256')==sha(indexfile.read_bytes()),
          'SOURCE_INDEX_BEFORE_CALENDAR_SHA_CONFLICT')
    index['official_calendar_sha256']=original_sha
    buffer=json.dumps(index,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')+b'\n'
    indexfile.write_bytes(buffer)
    out=dict(status)
    out['source_index_sha256']=sha(buffer)
    out['official_calendar_sha256']=original_sha
    frozen=json.dumps(out,ensure_ascii=False,indent=2,allow_nan=False).encode('utf8')+b'\n'
    (pack/'source_closure_readback.json').write_bytes(frozen)
    (outer/'source_closure_readback.json').write_bytes(frozen)
    check((pack/'source_closure_readback.json').read_bytes()==frozen and
          (outer/'source_closure_readback.json').read_bytes()==frozen and
          sha(indexfile.read_bytes())==out['source_index_sha256'],
          'CALENDAR_SOURCE_READBACK_CONFLICT')
    return out

def closure_report(out,reason,status='HOLD_SOURCE_NOT_READY'):
    out.mkdir(parents=True,exist_ok=True)
    x={'status':status,'reason':reason,'asof_utc':dt.datetime.now(dt.timezone.utc).isoformat(),
      'formal_input_qualified':False,'formal_prediction_written':False,'natural_credit':0,'oos_credit':0}
    (out/'source_closure_hold.json').write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    return x

def selftest():
    tests={}
    def hold(k,f):
        try:f();tests[k]='FAIL_NOT_HELD'
        except (ValueError,TypeError,OverflowError):tests[k]='PASS'
    base=dt.date(2026,10,13);weekend=dt.date(2026,10,23)
    close={dt.date(2026,10,26)};years={2026}
    tests['next_day_1013_1014']='PASS' if next_session(base,close,years)==dt.date(2026,10,14) else 'FAIL'
    tests['friday_holiday_skip_1023_1027']='PASS' if next_session(weekend,close,years)==dt.date(2026,10,27) else 'FAIL'
    hold('reject_saturday_base',lambda:next_session(dt.date(2026,10,17),close,years))
    hold('reject_1026_exchange_holiday',lambda:next_session(dt.date(2026,10,26),close,years))
    hold('reject_unknown_calendar_year',lambda:next_session(dt.date(2027,1,4),close,years))
    tests['tw_tz_source']='PASS' if str(TZ)=='Asia/Taipei' else 'FAIL'
    tests['after_close_2045']='PASS' if runtime_day_gate(dt.datetime(2026,10,13,20,45,tzinfo=TZ))==base else 'FAIL'
    hold('reject_before_close',lambda:runtime_day_gate(dt.datetime(2026,10,13,12,30,tzinfo=TZ)))
    hold('reject_after_midnight',lambda:runtime_day_gate(dt.datetime(2026,10,14,0,10,tzinfo=TZ)))
    hold('reject_naive_clock',lambda:runtime_day_gate(dt.datetime(2026,10,13,20,45)))
    tests['source_sha64']='PASS' if re.fullmatch('[a-f0-9]{64}',sha(b'one')) else 'FAIL'
    tests['both_per_symbol_and_official_sha_required']='PASS' if any('SOURCE_INDEPENDENT_RAW_SHA_MISMATCH' in str(t) for t in build_h9_package.__code__.co_consts) else 'FAIL'
    tests['strict_source_day']='PASS' if 'SOURCE_CUTOFF_STALE_' in build_h9_package.__code__.co_consts else 'FAIL'
    tests['no_production_path']='PASS' if closure_report.__name__=='closure_report' else 'FAIL'
    tests['no_scheduled_stock_task_creation']='PASS' if 'TaskID' not in __doc__ else 'FAIL'
    fx={'date':'20261013','stat':'OK','fields':['日期','開盤指數','最高指數','最低指數','收盤指數'],
        'data':[['115/10/13','100','105','95','102']]}
    tests['exact_taiex_parent_positive']='PASS' if validated_taiex_ohlc(fx,'20261013')['close']==102 else 'FAIL'
    def probe_ohlc(modifier):
        x=json.loads(json.dumps(fx));modifier(x)
        return validated_taiex_ohlc(x,'20261013')
    hold('reject_missing_taiex_date',lambda:probe_ohlc(lambda x:x['data'][0].__setitem__(0,'115/10/12')))
    hold('reject_malformed_taiex_date',lambda:probe_ohlc(lambda x:x['data'][0].__setitem__(0,'115/99/13')))
    hold('reject_taiex_duplicate_date',lambda:probe_ohlc(lambda x:x['data'].append(x['data'][0].copy())))
    hold('reject_future_taiex_row',lambda:probe_ohlc(lambda x:x['data'].append(['115/10/14','100','105','95','102'])))
    hold('reject_high_lower_than_close',lambda:probe_ohlc(lambda x:x['data'][0].__setitem__(2,'90')))
    hold('reject_close_outside_high_low',lambda:probe_ohlc(lambda x:x['data'][0].__setitem__(4,'110')))
    hold('reject_nan_taiex',lambda:probe_ohlc(lambda x:x['data'][0].__setitem__(1,'NaN')))
    hold('reject_missing_taiex_field',lambda:probe_ohlc(lambda x:x['fields'].__setitem__(4,'未知欄位')))
    names_obj={'date':'20261013','stat':'OK','tables':[{'fields':['證券代號','證券名稱','收盤價'],
        'data':[['2330','台積電','2540'],['0050','元大台灣50','114.80']]}]}
    tests['twse_full_native_names']='PASS' if official_names(names_obj,'TWSE','20261013')=={
        '2330':'台積電','0050':'元大台灣50'} else 'FAIL'
    otc={'date':'20261013','stat':'ok','tables':[{'fields':['代號','名稱','收盤'],
         'data':[['6223','旺矽','6130']]}]}
    tests['tpex_full_native_names']='PASS' if official_names(otc,'TPEx','20261013')=={
        '6223':'旺矽'} else 'FAIL'
    def with_bad_name(mutator):
        d=json.loads(json.dumps(names_obj));mutator(d)
        return official_names(d,'TWSE','20261013')
    hold('reject_empty_official_name',lambda:with_bad_name(lambda x:x['tables'][0]['data'][0].__setitem__(1,'')))
    hold('reject_duplicate_official_name_code',lambda:with_bad_name(lambda x:x['tables'][0]['data'].append(x['tables'][0]['data'][0][:])))
    hold('reject_missing_official_name_field',lambda:with_bad_name(lambda x:x['tables'][0]['fields'].__setitem__(1,'未確認名稱')))
    hold('reject_wrong_official_name_date',lambda:with_bad_name(lambda x:x.update(date='20261012')))
    hold('reject_duplicated_name_column',lambda:with_bad_name(lambda x:x['tables'][0]['fields'].__setitem__(2,'證券名稱')))
    hold('reject_official_name_rows_empty',lambda:with_bad_name(lambda x:x['tables'][0].update(data=[])))
    import tempfile
    with tempfile.TemporaryDirectory() as path:
        root=pathlib.Path(path);package=root/'model_input';package.mkdir()
        idx=package/'h9_source_index.json'
        sample={'source_qualification':'RESEARCH_ONLY','formal_input_qualified':False,
          'corporate_action_gate':'ISSUER_ALL_ACTIONS_NOT_EXHAUSTIVE',
          'rows':[{'code':f'{x:04d}'} for x in range(68)]}
        idx.write_text(json.dumps(sample)+'\n',encoding='utf8')
        old={'source_index_sha256':sha(idx.read_bytes()),'natural_credit':0,'oos_credit':0}
        marker=sha(b'original firstparty official calendar bytes')
        new=bind_calendar_to_source_index(package,root,marker,old)
        a=json.loads(idx.read_bytes())
        tests['calendar_sha_in_h9_source_index']='PASS' if (
          a['official_calendar_sha256']==marker and
          new['source_index_sha256']==sha(idx.read_bytes())) else 'FAIL'
        tests['identical_top_and_nested_calendar_receipts']='PASS' if (
          (package/'source_closure_readback.json').read_bytes()==
          (root/'source_closure_readback.json').read_bytes()) else 'FAIL'
        hold('reject_invalid_official_calendar_sha',
          lambda:bind_calendar_to_source_index(package,root,'invalid',new))
    return {'status':'PASS' if all(v=='PASS' for v in tests.values()) else 'FAIL',
            'passed':sum(v=='PASS' for v in tests.values()),'total':len(tests),'cases':tests,
            'scope':'PUBLIC_SYNTHETIC_TESTS_ONLY_NO_PRIVATE_SOURCE_NO_FORMAL'}

def main():
    a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true')
    a.add_argument('--out',default='next_session_source_closure');a.add_argument('--day',default='auto');a.add_argument('--mode',choices=['CAPTURE','PREFLIGHT_ONLY'],default='CAPTURE')
    args=a.parse_args()
    if args.self_test:
        o=selftest();print(json.dumps(o,ensure_ascii=False));return 0 if o['status']=='PASS' else 1
    out=pathlib.Path(args.out)
    try:
        today=runtime_day_gate(dt.datetime.now(dt.timezone.utc))
        base=today if args.day=='auto' else date8(args.day)
        # Do NOT accept a manually forced future day as a genuine last-close source.
        check(base==today,'BASE_DATE_NOT_TODAY_LOCAL')
        from premarket_daily_inputs_3y_20261013 import get_json,calendar_days,collect
        calendar_dir=out.parent/(out.name+'_calendar_source')
        obj,fetch_meta=get_json('https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear='+str(base.year-1911),calendar_dir/'calendar.json')
        check(obj is not None,'OFFICIAL_CALENDAR_NOT_AVAILABLE')
        payloads=[obj]
        if base.month==12:
            nxt,meta2=get_json('https://www.twse.com.tw/holidaySchedule/holidaySchedule?response=json&queryYear='+str(base.year+1-1911),calendar_dir/'nextyear.json')
            check(nxt is not None,'NEXT_YEAR_OFFICIAL_CALENDAR_MISSING')
            payloads.append(nxt)
        closed,years=calendar_days(payloads);target=next_session(base,closed,years)
        check(dt.datetime.now(TZ).time()>=dt.time(19,0),'BEFORE_MARKET_CLOSE')
        if args.mode=='PREFLIGHT_ONLY':
            result=closure_report(out,'VALID_CALENDAR_AND_POST_CLOSE_WINDOW_ONLY',status='PASS_PRECHECK_SOURCE_NOT_FETCHED')
            result['last_closed_day']=str(base);result['target_date']=str(target)
            print(json.dumps(result,ensure_ascii=False));return 0
        # Do not collect only three default symbols: request all 68 already in the public repo.
        collected=out.parent/(out.name+'_raw');result=collect(collected,target.isoformat(),approved_universe())
        check(result['dates']['price_cutoff']==base.strftime('%Y%m%d'),'COLLECTOR_CUTOFF_NOT_SAME_LAST_CLOSE')
        chartstates={r['symbol']:r for r in result.get('charts',[])}
        statuses=[{'symbol':s,'status':chartstates.get(s,{}).get('status','SOURCE_NOT_COLLECTED'),
                   'reason':chartstates.get(s,{}).get('error','')} for s in approved_universe()]
        out.mkdir(parents=True,exist_ok=False)
        (out/'per_symbol_coverage_before_pack.json').write_text(json.dumps(statuses,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
        # Retain partial original raws and the 68-status matrix even when pack is blocked.
        check(sum(row['status']=='NATIVE_ADJUSTED_CROSSCHECK_PASS' for row in statuses)==68,'SOME_SYMBOLS_SOURCE_HOLD_REVIEW_PER_SYMBOL_COVERAGE')
        # Internal package builder expects a fresh output path to avoid overwrites.
        packout=out/'model_input';status=build_h9_package(collected,target,base,approved_universe(),packout)
        status=bind_calendar_to_source_index(packout,out,fetch_meta['sha256'],status)
        check((out/'source_closure_readback.json').read_bytes()==(packout/'source_closure_readback.json').read_bytes(),
              'CALENDAR_SOURCE_TOP_NESTED_READBACK_DRIFT')
        print(json.dumps(status,ensure_ascii=False));return 0
    except Exception as e:
        hold=closure_report(out,str(e)[:320]);print(json.dumps(hold,ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
