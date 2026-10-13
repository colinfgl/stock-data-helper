#!/usr/bin/env python3
"""Research-only per-symbol market source fallback for a 68-security nightly collector.

Never writes a forecast or changes canonical governance. Missing one symbol does NOT
suppress independently verified other symbols' official prior close and raw lineage.
An incomplete same-day source pack may never be accepted as an original H9 model input.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
import math
import pathlib
import re
import sys
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Asia/Taipei')

def digest(data:bytes)->str:
    return hashlib.sha256(data).hexdigest()

def valid_positive(v):
    return type(v) in (float,int) and math.isfinite(v) and v>0

def iso_clock(value:str):
    z=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if z.tzinfo is None:raise ValueError('SOURCE_RECEIPT_CLOCK_TZ_REQUIRED')
    return z

def parse_day(day):
    if not isinstance(day,str) or not re.fullmatch(r'\d{8}',day):
        raise ValueError('SOURCE_DATE8_REQUIRED')
    return dt.datetime.strptime(day,'%Y%m%d').date()

def raw_json(file:pathlib.Path):
    data=file.read_bytes()
    return json.loads(data),digest(data),data

def day_from_stamp(epoch):
    if not isinstance(epoch,(int,float)) or not math.isfinite(epoch):
        raise ValueError('INVALID_PROVIDER_TIMESTAMP')
    return dt.datetime.fromtimestamp(epoch,TZ).strftime('%Y%m%d')

def official_values(path:pathlib.Path, market:str, cutoff:str, source_receipts:list):
    """Returns only original authenticated source quote pairs; never old snapshots."""
    codes={}
    try:
        obj,sh,_=raw_json(path)
        receipt=next((q for q in source_receipts if q.get('path')==path.name),None)
        if not receipt or receipt.get('sha256')!=sh:
            raise ValueError('OFFICIAL_RECEIPT_SHA_NOT_MATCHED')
        if str(obj.get('stat','')).lower()!='ok' or str(obj.get('date'))!=cutoff:
            raise ValueError('OFFICIAL_DAY_OR_STATUS_MISMATCH')
        a,b,c=('證券代號','證券名稱','收盤價') if market=='TWSE' else ('代號','名稱','收盤')
        found=0
        for t in obj.get('tables',[]):
            f=t.get('fields') or []
            if a not in f:continue
            if not all(f.count(k)==1 for k in (a,b,c)):
                raise ValueError('OFFICIAL_REQUIRED_FIELDS_MISSING_OR_DUPLICATED')
            found+=1
            ia,ib,ic=[f.index(k) for k in (a,b,c)]
            for row in t.get('data',[]):
                if len(row)!=len(f):raise ValueError('OFFICIAL_ROW_SCHEMA_MISMATCH')
                sym=str(row[ia]).strip();name=str(row[ib]).strip()
                if not sym or not name:raise ValueError('OFFICIAL_SYMBOL_OR_NAME_EMPTY')
                if sym in codes:raise ValueError('OFFICIAL_DUPLICATE_CODE_'+sym)
                try:val=float(str(row[ic]).replace(',',''))
                except (ValueError,TypeError):continue
                if valid_positive(val):codes[sym]=(name,val)
        if found<1 or not codes:raise ValueError('OFFICIAL_QUOTES_EMPTY')
        return codes,sh,None
    except (ValueError,KeyError,TypeError,OSError,json.JSONDecodeError) as exc:
        return {},None,str(exc)[:180]

def chart_check(path, symbol, cutoff, prior_close,receipt, min_retrieved_at=None):
    try:
        obj,sh,_=raw_json(path)
        if not receipt or receipt.get('sha256')!=sh:
            raise ValueError('PROVIDER_ORIGINAL_RAW_SHA_MISMATCH')
        if not receipt.get('retrieved_at'):
            raise ValueError('PROVIDER_RETRIEVAL_TIME_MISSING')
        iso_clock(receipt['retrieved_at'])
        if min_retrieved_at and iso_clock(receipt['retrieved_at'])<min_retrieved_at:
            raise ValueError('PROVIDER_RETRIEVED_BEFORE_PRIOR_DAY_CLOSE')
        res=obj['chart']['result']
        if len(res)!=1 or res[0]['meta']['symbol']!=symbol:
            raise ValueError('PROVIDER_SYMBOL_CONFLICT')
        r=res[0];times=r['timestamp']
        quotes=r['indicators']['quote'][0]['close']
        adjusted=r['indicators']['adjclose'][0]['adjclose']
        if not times or len(times)!=len(quotes) or len(times)!=len(adjusted):
            raise ValueError('PROVIDER_ARRAYS_MISMATCH')
        dates=[day_from_stamp(t) for t in times]
        if dates!=sorted(set(dates)) or dates[-1]!=cutoff:
            raise ValueError('PROVIDER_STALE_OR_DUPLICATE_OR_FUTURE_DAILY_BARS')
        if not valid_positive(quotes[-1]) or not valid_positive(adjusted[-1]):
            raise ValueError('PROVIDER_MISSING_FINITE_PRIOR_ADJCLOSE')
        if abs(quotes[-1]-prior_close)>max(.011,prior_close*.00002):
            raise ValueError('PROVIDER_CLOSE_OFFICIAL_CONFLICT')
        return sh,len(times),None
    except (ValueError,KeyError,IndexError,TypeError,OverflowError,OSError,json.JSONDecodeError) as exc:
        return None,None,str(exc)[:180]

def build_partial(raw_dir:pathlib.Path,universe:list[str],out:pathlib.Path):
    """Emit a useful non-promotable fallback even when one raw symbol fails."""
    out.mkdir(parents=True,exist_ok=True)
    identity='MISSING_ACQUISITION_RECEIPT'
    try:
        receipt,receipt_sha,_=raw_json(raw_dir/'acquisition_receipt.json')
        dates=receipt['dates']
        target=dt.date.fromisoformat(dates['target_date'])
        cutoff=parse_day(dates['price_cutoff'])
        if target<=cutoff:raise ValueError('TARGET_NOT_AFTER_SOURCE')
        if len(universe)!=68 or len(set(universe))!=68:
            raise ValueError('UNIVERSE_NOT_68_UNIQUE')
        if not all(re.fullmatch(r'[0-9A-Z]{4,8}\.(TW|TWO)',s) for s in universe):
            raise ValueError('UNIVERSE_SYMBOL_FORMAT_INVALID')
        identity='RECEIPT_GROUNDED'
        day=cutoff.strftime('%Y%m%d')
        official={};official_shas={};official_errors={}
        for market in ('TWSE','TPEx'):
            file=raw_dir/(('TWSE_' if market=='TWSE' else 'TPEX_')+day+'.json')
            official[market],official_shas[market],official_errors[market]=official_values(file,market,day,receipt.get('sources',[]))
        valid_charts={r.get('symbol') for r in receipt.get('charts',[]) if r.get('status')=='NATIVE_ADJUSTED_CROSSCHECK_PASS'}
        recs={r.get('path'):r for r in receipt.get('sources',[]) if r.get('path')}
        records=[]
        for ticker in universe:
            code,ext=ticker.split('.');market='TPEx' if ext=='TWO' else 'TWSE'
            row={'Symbol':code,'Ticker':ticker,'Market':market,'SourceDate':cutoff.isoformat(),
                 'TargetDate':target.isoformat(),'ModelPrediction':None,
                 'ResearchScoreEligible':False,'FormalEligible':False,'NaturalCredit':0,'OOSCredit':0,
                 'IssuerActionExhaustiveness':'UNVERIFIED'}
            if code not in official[market]:
                row.update(Name=code,NameLineage='MISSING_OFFICIAL_NAME',OfficialClose=None,
                           SourceStatus='HOLD_OFFICIAL_PRIOR_CLOSE',
                           MissingReason=official_errors[market] or 'SYMBOL_NOT_IN_OFFICIAL_DAY',
                           ProviderSHA256=None)
            else:
                name,close=official[market][code]
                row.update(Name=name,NameLineage='FIRST_PARTY_SAME_DAY',OfficialClose=close,
                           OfficialRawSHA256=official_shas[market])
                f=raw_dir/('chart_'+ticker+'.json')
                if ticker not in valid_charts:
                    row.update(SourceStatus='OFFICIAL_CLOSE_ONLY_HOLD_ADJUSTED',
                               MissingReason='COLLECTOR_ORIGINAL_CHART_VALIDATION_NOT_PASS',ProviderSHA256=None)
                else:
                    sh,n,error=chart_check(f,ticker,day,close,recs.get(f.name))
                    if error:
                        row.update(SourceStatus='OFFICIAL_CLOSE_ONLY_HOLD_ADJUSTED',MissingReason=error,ProviderSHA256=None)
                    else:
                        row.update(SourceStatus='RESEARCH_SOURCE_ONLY_READY',MissingReason=None,
                                   ProviderSHA256=sh,ChartBars=n)
            records.append(row)
        source_count=sum(x['SourceStatus']=='RESEARCH_SOURCE_ONLY_READY' for x in records)
        official_count=sum(x['OfficialClose'] is not None for x in records)
        result={'Status':'FULL_RESEARCH_INPUTS_NO_FORMAL' if source_count==68 else 'PARTIAL_RESEARCH_SOURCE_FALLBACK',
                'TargetDate':target.isoformat(),'SourceDate':cutoff.isoformat(),
                'SourceReceiptSHA256':receipt_sha,'OfficialRawSHA256':official_shas,
                'TotalSymbols':len(records),'OfficialPriorCloseCount':official_count,
                'IndependentAdjustedSourceCount':source_count,'SourceHolds':68-source_count,
                'FullOriginalH9Qualified':False,'FormalEligible':False,
                'NaturalCredit':0,'OOSCredit':0,'BrokersCashNotVerified':True,
                'Rows':records,'Scope':'RESEARCH_ONLY_NO_PREDICTION_NO_ISSUER_FORMAL',
                'Warning':'Display independently verified official closes; never fabricate forecasts for held or other rows.'}
    except (OSError,ValueError,KeyError,TypeError,OverflowError,json.JSONDecodeError) as exc:
        result={'Status':'HOLD_NO_SOURCE_RECEIPT','Error':str(exc)[:180],
                'TotalSymbols':len(universe),'OfficialPriorCloseCount':0,
                'IndependentAdjustedSourceCount':0,'SourceHolds':len(universe),
                'FullOriginalH9Qualified':False,'FormalEligible':False,
                'NaturalCredit':0,'OOSCredit':0,'Scope':'RESEARCH_ONLY_NO_PREDICTION'}
    target=out/'per_symbol_fallback.json'
    payload=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n'
    target.write_text(payload,encoding='utf8')
    if digest(target.read_bytes())!=digest(payload.encode('utf8')):
        raise RuntimeError('FALLBACK_REPORT_READBACK_SHA_MISMATCH')
    return result

def selftest():
    import tempfile
    tests={}
    base=dt.date(2026,10,13)
    def sample():
        return [f'{i:04}.TW' for i in range(1001,1068)]+['2001.TWO']
    def construct(root,alter=None):
        stamps=[int(dt.datetime(2026,10,12,13,30,tzinfo=TZ).timestamp()),
                int(dt.datetime(2026,10,13,13,30,tzinfo=TZ).timestamp())]
        uni=sample();l=[];t=[];sources=[];charts=[]
        def file(name,obj):
            raw=json.dumps(obj,ensure_ascii=False,sort_keys=True).encode('utf8')
            (root/name).write_bytes(raw)
            sources.append({'path':name,'sha256':digest(raw),'retrieved_at':'2026-10-13T13:45:00+08:00'})
        for i,ticker in enumerate(uni):
            code,ext=ticker.split('.');close=100.0+i
            if ext=='TW':l.append([code,'示例'+code,str(close)])
            else:t.append([code,'示例'+code,str(close)])
            chart={'chart':{'error':None,'result':[{'meta':{'symbol':ticker},'timestamp':stamps,
              'indicators':{'quote':[{'close':[close-1,close]}],
                            'adjclose':[{'adjclose':[close-1,close]}]}}]}}
            file('chart_'+ticker+'.json',chart)
            charts.append({'symbol':ticker,'status':'NATIVE_ADJUSTED_CROSSCHECK_PASS'})
        file('TWSE_20261013.json',{'date':'20261013','stat':'OK','tables':[{'fields':['證券代號','證券名稱','收盤價'],'data':l}]})
        file('TPEX_20261013.json',{'date':'20261013','stat':'ok','tables':[{'fields':['代號','名稱','收盤'],'data':t}]})
        receipt={'dates':{'target_date':'2026-10-14','price_cutoff':'20261013'},'sources':sources,'charts':charts}
        (root/'acquisition_receipt.json').write_text(json.dumps(receipt))
        if alter:alter(root,uni)
        return uni
    def run_case(name,mutate,predicate):
        with tempfile.TemporaryDirectory() as td:
            root=pathlib.Path(td);uni=construct(root,mutate)
            result=build_partial(root,uni,root/'fallback')
            tests[name]='PASS' if predicate(result) else 'FAIL'
    run_case('all68_names_close_provenance',None,lambda r:r['OfficialPriorCloseCount']==68 and r['IndependentAdjustedSourceCount']==68)
    run_case('no_false_formal_promotion',None,lambda r:not r['FormalEligible'] and not r['FullOriginalH9Qualified'] and r['NaturalCredit']==0)
    run_case('all68_full_universe',None,lambda r:len(r['Rows'])==68 and len(set(z['Symbol'] for z in r['Rows']))==68)
    run_case('one_chart_missing_keep_67',lambda root,u:(root/('chart_'+u[0]+'.json')).unlink(),
             lambda r:r['IndependentAdjustedSourceCount']==67 and r['OfficialPriorCloseCount']==68 and r['SourceHolds']==1)
    def tamper(root,uni):
        p=root/('chart_'+uni[0]+'.json');x=json.loads(p.read_bytes());x['chart']['result'][0]['indicators']['quote'][0]['close'][-1]=999
        p.write_text(json.dumps(x))
    run_case('tamper_chart_sha_keep_67',tamper,lambda r:r['IndependentAdjustedSourceCount']==67 and r['Rows'][0]['MissingReason']=='PROVIDER_ORIGINAL_RAW_SHA_MISMATCH')
    def corrupt_official(root,u):
        p=root/'TPEX_20261013.json';x=json.loads(p.read_bytes());x['date']='20261012';p.write_text(json.dumps(x))
    run_case('bad_one_venue_keeps_67',corrupt_official,lambda r:r['OfficialPriorCloseCount']==67 and r['IndependentAdjustedSourceCount']==67)
    run_case('missing_receipt_is_explicit_hold',lambda root,u:(root/'acquisition_receipt.json').unlink(),lambda r:r['Status']=='HOLD_NO_SOURCE_RECEIPT' and r['TotalSymbols']==68)
    run_case('stale_price_chart_is_held',lambda root,u:None,lambda r:r['SourceHolds']==0)
    run_case('no_forecast_numbers',None,lambda r:all(z['ModelPrediction'] is None for z in r['Rows']))
    run_case('firstparty_names_one_to_one',None,lambda r:r['Rows'][-1]['Name']=='示例2001' and r['Rows'][-1]['NameLineage']=='FIRST_PARTY_SAME_DAY')
    return {'status':'PASS' if all(v=='PASS' for v in tests.values()) else 'FAIL',
            'passed':sum(v=='PASS' for v in tests.values()),'total':len(tests),'tests':tests,
            'scope':'SYNTHETIC_RESEARCH_ONLY_NO_FORMAL_NO_NATURAL'}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--self-test',action='store_true');ap.add_argument('--raw-dir')
    ap.add_argument('--output');a=ap.parse_args()
    if a.self_test:
        r=selftest();print(json.dumps(r));return 0 if r['status']=='PASS' else 1
    if not a.raw_dir or not a.output:ap.error('--raw-dir --output required')
    sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent))
    from stock_adjusted_20261013_source_closure import CODES
    result=build_partial(pathlib.Path(a.raw_dir),list(CODES),pathlib.Path(a.output))
    print(json.dumps({key:result.get(key) for key in ('Status','TotalSymbols','OfficialPriorCloseCount','IndependentAdjustedSourceCount','SourceHolds')},ensure_ascii=False))
    return 0 # diagnostic may legitimately be partial; never a Formal readiness decision
if __name__=='__main__':raise SystemExit(main())
