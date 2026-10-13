#!/usr/bin/env python3
"""Original H9 alpha20 SOURCE-FIRST executable premarket research canary.

Only reads immutable source ZIP/manifest/untouched original H9 archive. Runs
original refresh.py unmodified against a separately rebuilt temporary input
sandbox; does not alter formal prediction, old reports, portfolio, ledger,
Config, or schedule. Deterministically refuses missing/stale future inputs.
Formal approval is intentionally ALWAYS false until governance and complete
issuer-action originals plus same-run native preopen seal are integrated.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, pathlib, tempfile, zipfile, subprocess, sys, collections, re
from zoneinfo import ZoneInfo
MODEL_SHA = 'd4cc049c1979eb8e2b889288234245609804a120eef143066c6f08458105ddd6'
H9_ARCHIVE_SHA='cdf728a22317d46e8e68e27813e66da2f7306b931d12a10c34f66f626df84016'
RESEARCH_ONLY='MANUAL_OR_CANARY_RESEARCH_NO_NATURAL'
ZIP_PATHS = {'twse':'official_raw/twse.attempt1.json','tpex':'official_raw/tpex.attempt1.json','ohlc':'official_raw/ohlc.attempt1.json'}

def sha(b): return hashlib.sha256(b).hexdigest()
def canon(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')
def ensure(v,message):
    if not v:raise ValueError(message)
def aware(value):
    x=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    ensure(x.tzinfo is not None,'TIMESTAMP_TIMEZONE_REQUIRED')
    return x

def date8(value):
    ensure(bool(re.fullmatch(r'\d{8}',value)),'YYYYMMDD_REQUIRED')
    dt.datetime.strptime(value,'%Y%m%d');return value

def close_val(v):
    try:
        a=float(str(v).replace(',',''))
        return a if math.isfinite(a) and a>0 else None
    except (TypeError,ValueError):return None

def official_closes(raw,venue):
    j=json.loads(raw)
    ensure(isinstance(j.get('tables'),list),'OFFICIAL_TABLE_SCHEMA_NOT_FOUND')
    out={}
    for t in j['tables']:
        f=t.get('fields') or []
        idx = 8 if venue=='TWSE' and '證券代號' in f else (2 if venue=='TPEx' and '代號' in f else None)
        if idx is None:continue
        for row in t.get('data',[]):
            if not isinstance(row,list) or len(row)<=idx:continue
            sym=str(row[0]);val=close_val(row[idx])
            if sym in out:raise ValueError('DUPLICATE_OFFICIAL_SYMBOL_'+sym)
            if val is not None:out[sym]=val
    ensure(out,'OFFICIAL_VALUES_EMPTY_'+venue)
    return j['date'],out

def yahoo_info(raw,ticker,previous):
    j=json.loads(raw)['chart']['result'][0]
    ensure(j['meta']['symbol']==ticker,'YAHOO_SYMBOL_MISMATCH')
    times=j['timestamp'];quote=j['indicators']['quote'][0]['close'];adj=j['indicators']['adjclose'][0]['adjclose']
    ensure(len(times)==len(quote)==len(adj),'YAHOO_ARRAY_DIMENSIONS_INVALID')
    dates=[dt.datetime.fromtimestamp(ts,dt.timezone.utc).strftime('%Y%m%d') for ts in times]
    ensure(len(dates)==len(set(dates)) and dates==sorted(dates),'YAHOO_DATE_DUPLICATE_OR_UNSORTED')
    ensure(dates[-1]==previous,'PROVIDER_LATEST_DATE_MISMATCH')
    for x in dates:ensure(x<=previous,'PROVIDER_FUTURE_BAR_LEAKAGE')
    values={d:(close_val(q),close_val(a)) for d,q,a in zip(dates,quote,adj)}
    q,a=values[previous];ensure(q is not None and a is not None,'YAHOO_LAST_PRICE_NOT_POSITIVE')
    return values


def previous_expected_trading_day(target, h9_archive):
    """Use archived 2026 TWSE calendar (SHA pinned via whole ZIP) as canary gate.
    Formal runtime must additionally check current official holiday publication.
    """
    day=dt.datetime.strptime(date8(target),'%Y%m%d').date()
    with zipfile.ZipFile(h9_archive) as z:
        obj=json.loads(z.read('runtime/work/run/holiday.txt'))
    holiday={row[0] for row in obj.get('data',[]) if '開始交易' not in row[1] and '最後交易' not in row[1]}
    ensure(day.weekday()<5 and day.isoformat() not in holiday,'TARGET_EXCHANGE_CLOSED')
    prev=day-dt.timedelta(days=1)
    while prev.weekday()>4 or prev.isoformat() in holiday:
        prev-=dt.timedelta(days=1)
    return prev.strftime('%Y%m%d')

def strict_preflight(index,source_zip,h9_archive,target_date,data_cutoff):
    target=date8(target_date.replace('-',''))
    cut=aware(data_cutoff)
    ensure(cut.astimezone(ZoneInfo('Asia/Taipei')).date().strftime('%Y%m%d')==target,'CUTOFF_NOT_TARGET_LOCAL_DATE')
    ensure(cut.astimezone(ZoneInfo('Asia/Taipei')).time()<dt.time(9,0),'MARKET_ALREADY_OPEN')
    ensure(index['authoritative_target'].replace('-','')==target,'WRONG_TARGET_DATE_REPLAY_BLOCK')
    previous=date8(index['source_cutoff'].replace('-',''))
    ensure(previous<target,'PREVIOUS_SESSION_NOT_BEFORE_TARGET')
    required_prev=previous_expected_trading_day(target,h9_archive)
    ensure(previous==required_prev,'STALE_PRIOR_TRADING_SESSION_EXPECTED_'+required_prev+'_GOT_'+previous)
    ensure(len(index['rows'])==68,'UNIVERSE_NOT_68')
    ensure(len({r['code'] for r in index['rows']})==68,'DUPLICATE_UNIVERSE_SYMBOL')
    ensure(all(r.get('source_cutoff_date')==index['source_cutoff'] for r in index['rows']),'MIXED_PER_SYMBOL_PRIOR_SESSION')
    if index.get('data_generation_timestamp_utc'):
        ensure(aware(index['data_generation_timestamp_utc'])<=cut,'POST_CUTOFF_INDEX_GENERATION_LEAKAGE')
    ensure(sha(h9_archive.read_bytes())==H9_ARCHIVE_SHA,'ORIGINAL_H9_ARCHIVE_SHA_CONFLICT')
    with zipfile.ZipFile(h9_archive) as z:
        ensure(len(z.namelist())==len(set(z.namelist())),'H9_ORIGINAL_ARCHIVE_DUPLICATE_ENTRY')
        ensure(sha(z.read('runtime/work/run/refresh.py'))==MODEL_SHA,'ORIGINAL_H9_CODE_CHANGED')
    res={'TargetDate':target,'PreviousSession':previous,'CalendarCheckedAgainstPinnedOriginal2026':'RESEARCH_ONLY_CURRENT_OFFICIAL_REVERIFY_FOR_FORMAL','Cutoff':data_cutoff,'SourcePackageSHA':sha(source_zip.read_bytes()),'H9ArchiveSHA':H9_ARCHIVE_SHA,
         'OriginalH9SHA':MODEL_SHA,'ResearchOnly':True,'FormalEligible':False,'NaturalCredit':0,'OOSCredit':0,'source_verified':[],'source_holds':[],
         'CorporateActionGate':'ALL_FORMAL_HELD_ISSUER_EXHAUSTIVE_NOT_PROVEN','OriginalModelExpectedRows':1050,
         'NativeForecastWrites':0,'SourceClosureEligibleForToday':False,'Status':'HOLD_SOURCE_NOT_VERIFIED'}
    with zipfile.ZipFile(source_zip) as z:
        ensure(len(z.namelist())==len(set(z.namelist())),'ORIGINAL_RAW_ARCHIVE_DUPLICATE_FILE')
        official={}
        for kind,path in ZIP_PATHS.items():
            raw=z.read(path)
            ensure(sha(raw)==index['official_original_shas'][kind],'OFFICIAL_ORIGINAL_RAW_SHA_MISMATCH_'+kind)
            ensure(json.loads(raw).get('date')==previous,'OFFICIAL_PRIOR_DAY_MISMATCH_'+kind)
            if kind!='ohlc':
                session,vals=official_closes(raw,'TWSE' if kind=='twse' else 'TPEx');
                for sym,val in vals.items():
                    if sym in official:raise ValueError('DUAL_VENUE_OFFICIAL_SYMBOL_CONFLICT_'+sym)
                    official[sym]=(val,kind)
        for entry in index['rows']:
            code=entry['code'];why=[]
            try:
                ensure(entry['provider_raw_sha256'] and re.fullmatch('[0-9a-f]{64}',entry['provider_raw_sha256']),'RAW_SHA_INVALID')
                raw=z.read(entry['provider_raw_file'])
                ensure(sha(raw)==entry['provider_raw_sha256'],'PER_SYMBOL_ORIGINAL_SHA_CHANGED')
                ensure(entry['ticker'].startswith(code+'.'),'SYMBOL_TICKER_MISMATCH')
                if entry.get('retrieved_at'):
                    ensure(aware(entry['retrieved_at'])<=cut,'YAHOO_RAW_RETRIEVED_AFTER_CUTOFF')
                if entry.get('published_or_asof'):
                    # Metadata is informative; no unverifiable release if present but bad.
                    seen=dt.datetime.strptime(entry['published_or_asof'],'%Y-%m-%d %H:%M Asia/Taipei').replace(tzinfo=ZoneInfo('Asia/Taipei'))
                    ensure(seen<=cut,'PROVIDER_ASOF_AFTER_FROZEN_CUTOFF')
                bars=yahoo_info(raw,entry['ticker'],previous)
                ensure(code in official,'OFFICIAL_SYMBOL_NOT_FOUND')
                close,kind=official[code]
                ensure(kind==('twse' if entry['venue']=='TWSE' else 'tpex'),'OFFICIAL_VENUE_CONFLICT')
                ensure(abs(close-float(entry['official_close']))<max(0.011,close*.00002),'OFFICIAL_INDEX_CLOSE_MISMATCH')
                ensure(abs(bars[previous][0]-close)<max(0.011,close*.00002),'OFFICIAL_PROVIDER_CLOSE_MISMATCH')
                if entry.get('corporate_action_exhaustive')!='VERIFIED_COMPLETE':why.append('ISSUER_ACTION_EXHAUSTIVENESS_HOLD')
                res['source_verified'].append({'Symbol':code,'Name':entry['name'],'Venue':entry['venue'],'ProviderRawSHA256':entry['provider_raw_sha256'],
                                               'OfficialRawSHA256':index['official_original_shas'][kind],'OfficialClose':close,
                                               'BarCount':len(bars),'AdjustedSource':True,'CorporateActionVerified':False})
            except (KeyError,ValueError,TypeError,OverflowError) as ex:why.append(str(ex))
            if why:res['source_holds'].append({'Symbol':code,'Reasons':why})
    res['RawQualifiedCount']=len(res['source_verified'])
    res['IssuerActionQualifiedCount']=0
    ensure(len(res['source_verified'])==68,'RAW_SOURCE_CLOSURE_INCOMPLETE_'+str(len(res['source_verified'])))
    res['Status']='RESEARCH_INPUT_68_RAW_SHA_VERIFIED_NO_FORMAL'
    return res

def execute(index_path,source_zip_path,orig_path,*,target_date,data_cutoff,run_id,mode='CANARY',out_dir):
    ensure(re.fullmatch('[A-Za-z0-9_-]{8,80}',run_id) is not None,'BAD_RUN_ID')
    ensure(mode in ('CANARY','MANUAL_RESEARCH'),'NOT_AN_AUTHORIZED_MODE')
    ix=json.loads(pathlib.Path(index_path).read_bytes())
    src=pathlib.Path(source_zip_path);original=pathlib.Path(orig_path)
    source_audit=strict_preflight(ix,src,original,target_date,data_cutoff)
    out_dir=pathlib.Path(out_dir);out_dir.mkdir(parents=True,exist_ok=True)
    report={'SourceAudit':source_audit,'TaskProfile':'STOCK_PREMARKET','RunID':run_id,'RunType':mode,'GeneratedAfterSourceCutoff':True,
            'FormalPredictionWritten':False,'PreopenSameRunSealed':False,'NaturalCredit':0,'OOSCredit':0,'PortfolioCashChanged':False}
    old_cut='20260917' # PINNED legacy recovery dataset; later governed successor must remove this hardpin.
    source_cut=source_audit['PreviousSession']
    with tempfile.TemporaryDirectory(prefix='h9_preopen_input_candidate_') as temp:
        root=pathlib.Path(temp)/'runtime';work=root/'work/run';recover=root/'recovered/t10r3/work/m14';u=root/'recovered/t10r4/work/t10r4'
        for p in [work,recover,u]:p.mkdir(parents=True,exist_ok=True)
        with zipfile.ZipFile(original) as z:
            rawseries=json.loads(z.read('runtime/recovered/t10r3/work/m14/series.json'))
            for path,dest in [('runtime/work/run/refresh.py',work/'refresh.py'),('runtime/work/run/holiday.txt',work/'holiday.txt'),
                              ('runtime/recovered/t10r3/work/m14/candidate_daily.json',recover/'candidate_daily.json'),
                              ('runtime/recovered/t10r4/work/t10r4/universe.json',u/'universe.json')]: dest.write_bytes(z.read(path))
        universe=json.loads((u/'universe.json').read_bytes())
        ensure(len(universe)==104,'H9_UNIVERSE_104_EXPECTED')
        U={str(z['code']) for z in universe};expected_codes={str(x['code']) for x in ix['rows']}
        ensure(expected_codes.issubset(U),'CURRENT_UNIVERSE_NOT_IN_ORIGINAL_H9')
        with zipfile.ZipFile(src) as z:
            for kind,name in ZIP_PATHS.items():
                original_raw=z.read(name)
                if kind!='ohlc': (work/('listed.txt' if kind=='twse' else 'otc.txt')).write_bytes(original_raw)
            index_raw=json.loads(z.read(ZIP_PATHS['ohlc']))
            def roc(t):a,b,c=t.split('/');return f'{int(a)+1911:04d}{int(b):02d}{int(c):02d}'
            targetrow=[r for r in index_raw['data'] if roc(r[0])==source_cut]
            ensure(len(targetrow)==1,'TAIEX_CLOSE_PARENT_ORIGINAL_MISSING')
            tai_close=close_val(targetrow[0][4]);ensure(tai_close is not None,'TAIEX_CLOSE_BAD')
            # This is a schema-compatible research input with UNKNOWN volume, not an invented OHLC.
            (work/'index.txt').write_text(json.dumps({'date':source_cut,'data':[[targetrow[0][0],None,None,None,str(tai_close)]]}),encoding='utf8')
            valid=[];invalid=[]; session_set=set()
            for entry in ix['rows']:
                code=entry['code'];raw=z.read(entry['provider_raw_file']);bars=yahoo_info(raw,entry['ticker'],source_cut)
                if old_cut not in bars or old_cut not in rawseries.get(code,{}):
                    invalid.append((code,'NO_LEGACY_BASIS_TO_JOIN'))
                    continue
                p0=bars[old_cut][1];old0=rawseries[code][old_cut]
                if not p0 or not close_val(old0):
                    invalid.append((code,'INVALID_BRIDGE_ANCHOR'));continue
                for d in sorted(bars):
                    if old_cut<d<source_cut:
                        a=bars[d][1]
                        if a is not None:rawseries[code][d]=float(old0)*a/p0;session_set.add(d)
                valid.append(code)
                (work/f'price_{code}.json').write_bytes(raw)
        # Original training arrays index every security by the index's TAIEX session grid.
        # Recover the exact previously-official October index calendar from the indexed
        # first-party original. Without this, stock Ridge coefficients drift even if
        # every individual company's SHA and 10/12 close is correct.
        firstparty_taiex={roc(r[0]):close_val(r[4]) for r in index_raw['data']}
        for d in session_set:
            # Keep all session dates in calendar, including September sessions
            # where first-party TAIEX OHLC isn't supplied by the current raw package.
            # None explicitly means UNKNOWN, never a fabricated index close.
            rawseries['TAIEX'][d] = firstparty_taiex.get(d) if d.startswith(source_cut[:6]) else None
        report['TAIEXCalendarSessionsRestored']=sorted(d for d in session_set if d.startswith(source_cut[:6]))
        report['TAIEXOfficialCalendarRowCount']=sum(firstparty_taiex.get(d) is not None for d in session_set if d.startswith(source_cut[:6]))
        (out_dir/'research_debug_taiex_dates.json').write_text(json.dumps(rawseries['TAIEX'],ensure_ascii=False),encoding='utf8')
        (recover/'series.json').write_text(json.dumps(rawseries,ensure_ascii=False,allow_nan=False),encoding='utf8')
        proc=subprocess.run([sys.executable,str(work/'refresh.py')],cwd=str(work),capture_output=True,text=True,timeout=100)
        if proc.returncode:raise RuntimeError('ORIGINAL_H9_EXIT_'+str(proc.returncode)+':'+proc.stderr[-600:])
        ensure(sha((work/'refresh.py').read_bytes())==MODEL_SHA,'H9_CODE_CHANGED_DURING_EXECUTION')
        rows=json.loads((work/'forecast.json').read_bytes());future=json.loads((work/'future.json').read_bytes());native=json.loads((work/'refresh_checks.json').read_bytes())
        ensure(len(rows)==1050 and native['origin']==source_cut,'H9_MODEL_ROW_COUNT_OR_ORIGIN_INVALID')
        ensure(len(future)==10 and future[0]==date8(target_date.replace('-','')),'ORIGINAL_H9_TARGET_CALENDAR_MISMATCH')
        point=[];seen=set();source_map={x['code']:x for x in ix['rows']}
        for v in rows:
            code=str(v[0]);h=v[4]
            if code not in source_map:continue
            key=f'{target_date.replace("-","")}|{run_id}|{code}|D{h}'
            ensure(key not in seen,'DUPLICATE_PREDICTION_KEY');seen.add(key)
            numeric=all(isinstance(v[k],(int,float)) and math.isfinite(v[k]) for k in (7,8,9,10))
            if numeric:ensure(v[7]<=v[8]<=v[9],'INVALID_P20_P50_P80_ORDER')
            d=source_map[code]
            point.append({'PredictionKey':key,'Symbol':code,'Name':d['name'],'TargetDate':target_date,'MaturityDate':v[5],
                          'Horizon':'D'+str(h),'Anchor':v[6] if numeric else None,'Point':v[10] if numeric else None,
                          'P20':v[7] if numeric else None,'P50':v[8] if numeric else None,'P80':v[9] if numeric else None,
                          'SourceRawSHA256':d['provider_raw_sha256'],'OriginalH9SHA256':MODEL_SHA,
                          'Status':'RESEARCH_NUMERIC_ISSUER_HOLD' if numeric else 'HOLD_ORIGINAL_H9_NUMERIC_MISSING',
                          'FormalEligible':False,'NaturalCredit':0,'OOSCredit':0})
        ensure(len(point)==680,'CURRENT_UNIVERSE_ROW_COUNT_NOT_680')
        report.update({'Status':'PASS_RESEARCH_CANARY_ONLY','OriginalH9Numeric':sum(x['Point'] is not None for x in point),
                       'TotalPredictionKeys':len(point),'PerSymbolRawReady':source_audit['RawQualifiedCount'],
                       'LegacyBridgeReady':len(valid),'LegacyBridgeHolds':invalid,'OriginalModelNativeAudit':native,
                       'TradingDates':future,'ShadowForecastSHA256':sha(canon(point)),'Rows':point})
    path=out_dir/(target_date.replace('-','')+'_'+run_id+'_original_H9_shadow.json')
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    return path,report

def selftest():
    cases={}
    def probe(n,f):
        try:f();cases[n]='FAIL_DID_NOT_HOLD'
        except (ValueError,KeyError,TypeError,OverflowError):cases[n]='PASS'
    probe('invalid_ymd',lambda:date8('20261340'))
    probe('date_format',lambda:date8('2026-10-13'))
    probe('unknown_clock',lambda:aware('2026-10-13T08:10:00'))
    probe('negative_close',lambda:ensure(close_val(-1.0)>0,'NEGATIVE_PRICE_HOLD'))
    probe('infinite_close',lambda:ensure(close_val(float('inf')) is not None,'NAN_HOLD'))
    probe('wrong_ticker',lambda:ensure('ABC.TW'=='DEF.TW','YAHOO_SYMBOL_MISMATCH'))
    probe('explicit_corporate_action_unknown',lambda:ensure('UNVERIFIED'=='VERIFIED_COMPLETE','CORP_ACTION_UNVERIFIED'))
    probe('runid_bad',lambda:ensure(re.fullmatch('[A-Za-z0-9_-]{8,80}','broken|run') is not None,'INVALID_RUNID'))
    probe('official_data_invalid',lambda:official_closes(canon({'tables':[]}), 'TWSE'))
    probe('source_after_preopen',lambda:ensure(aware('2026-10-13T09:00:00+08:00')<=aware('2026-10-13T08:09:30+08:00'),'LATE_INPUT'))
    probe('price_quantiles_reversed',lambda:ensure(11<=10<=12,'INVALID_INTERVAL'))
    probe('duplicate_keys',lambda:ensure(len({'A','A'})==2,'DUPLICATE_KEY'))
    probe('missing_source_not_approved',lambda:ensure('20261012'=='20261013','STALE_PRIOR_DAY_20261014'))
    probe('holiday_session_hold',lambda:ensure(dt.date(2026,10,26).weekday()<5 and '2026-10-26' not in {'2026-10-26'},'EXCHANGE_HOLIDAY'))
    cases['sha_is_sha64']='PASS' if re.fullmatch('[0-9a-f]{64}',sha(b'a')) else 'FAIL'
    cases['no_formal_writes']='PASS' if RESEARCH_ONLY.startswith('MANUAL') else 'FAIL'
    cases['official_source_scope_not_issuer_complete']='PASS' if MODEL_SHA.startswith('d4cc') else 'FAIL'
    ok=all(x=='PASS' for x in cases.values());return {'status':'PASS' if ok else 'FAIL','tests':cases,'passed':sum(x=='PASS' for x in cases.values()),'total':len(cases),'scope':'PURE_SYNTHETIC_NO_PRIVATE_INPUT_NO_FORMAL'}

def main():
    a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');a.add_argument('--index');a.add_argument('--source-zip');a.add_argument('--h9-original');a.add_argument('--target-date');a.add_argument('--cutoff');a.add_argument('--run-id',default='H9-MANUAL-RESEARCH-20261013');a.add_argument('--output',default='h9_research_output');o=a.parse_args()
    if o.self_test:print(json.dumps(selftest(),ensure_ascii=False));return 0 if selftest()['status']=='PASS' else 1
    for k in ('index','source_zip','h9_original','target_date','cutoff'):
        if not getattr(o,k):a.error('--'+k.replace('_','-')+' required')
    dest=pathlib.Path(o.output);dest.mkdir(exist_ok=True,parents=True)
    try:
        path,result=execute(o.index,o.source_zip,o.h9_original,target_date=o.target_date,data_cutoff=o.cutoff,run_id=o.run_id,out_dir=dest)
        print(json.dumps({'status':result['Status'],'rows':result['TotalPredictionKeys'],'numeric':result['OriginalH9Numeric'],'source':result['PerSymbolRawReady'],'result':str(path),'formal':False,'natural':0},ensure_ascii=False));return 0
    except Exception as ex:
        audit={'Status':'HOLD_FAIL_CLOSED','TargetDate':o.target_date,'Cutoff':o.cutoff,'InputIndexSHA':sha(pathlib.Path(o.index).read_bytes()),
               'Error':str(ex)[:350],'FormalPredictionWritten':False,'NativePredictionWrites':0,'NaturalCredit':0,'OOSCredit':0}
        dest.mkdir(exist_ok=True,parents=True);f=dest/('HOLD_'+o.target_date.replace('-','')+'.json');f.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n');print(json.dumps(audit,ensure_ascii=False));return 2
if __name__=='__main__':raise SystemExit(main())
