#!/usr/bin/env python3
"""Research-only short-history forecast for three explicitly held H9 universe names.

Never substitutes original H9, issuer action proof, pre-open seal, formal OOS, or trades.
Emits independently SHA-checked D1--D10 statistical proxy from cutoff-valid Yahoo
adjusted prices; optional D1 intraday high/low proxies use historical OHLC ratios.
No backdating, no canonical PredictionKey, no actual settlement Outcome.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, pathlib, statistics, zipfile
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Asia/Taipei')
TARGETS=('00400A','009820','3718')
METHOD='SHORT_HISTORY_EWMA_SHRUNK_LOG_RETURN_V1'
Z80=0.8416212335729143

def check(cond,reason):
    if not cond:raise ValueError(reason)
def sha(data):return hashlib.sha256(data).hexdigest()
def valid(v):return type(v) in (float,int) and math.isfinite(v) and v>0

def official_close_name(raw, code, venue, expected_day):
    """Bind current code/name/close to same-day original TWSE/TPEx bytes."""
    x=json.loads(raw)
    check(isinstance(x,dict) and str(x.get('date'))==expected_day.replace('-','')
          and str(x.get('stat','')).lower()=='ok','OFFICIAL_DAY_OR_STATUS_NOT_VERIFIED')
    sym_field,name_field,close_field=(('證券代號','證券名稱','收盤價') if venue=='TWSE'
                                      else ('代號','名稱','收盤'))
    matched=[]
    for t in x.get('tables',[]):
        fields=t.get('fields') or []
        if sym_field not in fields:continue
        check(all(fields.count(k)==1 for k in (sym_field,name_field,close_field)),
              'OFFICIAL_COLUMNS_AMBIGUOUS')
        si,ni,ci=(fields.index(k) for k in (sym_field,name_field,close_field))
        for row in t.get('data',[]):
            check(isinstance(row,list) and len(row)>max(si,ni,ci),'OFFICIAL_ROW_MALFORMED')
            if str(row[si]).strip()==code:
                v=str(row[ci]).replace(',','')
                try:price=float(v)
                except (ValueError,TypeError) as ex:raise ValueError('OFFICIAL_PRICE_NOT_NUMERIC') from ex
                check(valid(price),'OFFICIAL_PRICE_NOT_POSITIVE')
                name=str(row[ni]).strip()
                check(bool(name),'OFFICIAL_NAME_EMPTY')
                matched.append((name,price))
    check(len(matched)==1,'OFFICIAL_SYMBOL_MISSING_OR_DUPLICATE')
    return matched[0]

def adjusted_bars(raw,ticker,expected_cutoff):
    x=json.loads(raw)
    check(isinstance(x,dict) and isinstance(x.get('chart'),dict),'INVALID_YAHOO_RAW_SCHEMA')
    check(x['chart'].get('error') is None,'PROVIDER_ERROR')
    rr=x['chart'].get('result')
    check(isinstance(rr,list) and len(rr)==1 and rr[0].get('meta',{}).get('symbol')==ticker,'PROVIDER_SYMBOL_CONFLICT')
    obj=rr[0];times=obj.get('timestamp')
    check(isinstance(times,list) and len(times)>=21,'INSUFFICIENT_HISTORY_LT21')
    try:
        rawclose=obj['indicators']['quote'][0]['close'];adj=obj['indicators']['adjclose'][0]['adjclose'];high=obj['indicators']['quote'][0]['high'];low=obj['indicators']['quote'][0]['low']
    except (KeyError,IndexError,TypeError) as ex:raise ValueError('OHLC_OR_ADJUSTED_SERIES_MISSING') from ex
    check(all(isinstance(a,list) and len(a)==len(times) for a in (rawclose,adj,high,low)),'BAR_ARRAY_MISMATCH')
    dates=[dt.datetime.fromtimestamp(t,TZ).strftime('%Y-%m-%d') for t in times]
    check(dates==sorted(set(dates)),'DUPLICATE_OR_UNSORTED_TAIPEI_DATES')
    check(dates[-1]==expected_cutoff,'STALE_OR_FUTURE_LATEST_BAR')
    bars=[]
    for day,c,a,h,l in zip(dates,rawclose,adj,high,low):
        if not all(valid(k) for k in (c,a,h,l)) or not l<=c<=h:continue
        bars.append((day,float(c),float(a),float(h),float(l)))
    check(len(bars)>=21 and bars[-1][0]==expected_cutoff,'NOT_21_USABLE_BARS_AT_CUTOFF')
    return bars

def estimate(bars,official_close,horizons=10):
    check(valid(official_close) and len(bars)>=21 and horizons==10,'INVALID_ANCHOR_OR_HORIZON')
    check(abs(bars[-1][1]-official_close)<=max(.011,official_close*.00002),'OFFICIAL_YAHOO_RAW_CLOSE_CONFLICT')
    series=bars[-61:]
    returns=[math.log(b[2]/a[2]) for a,b in zip(series,series[1:])]
    check(len(returns)>=20,'INSUFFICIENT_RETURN_HISTORY')
    capped=[max(-.18,min(.18,r)) for r in returns]
    # Weighted recent log returns; shrink unstable mean toward zero, cap drift.
    n=len(capped); decay=.94
    weights=[decay**(n-1-i) for i in range(n)]
    ewmean=sum(w*r for w,r in zip(weights,capped))/sum(weights)
    prior_strength=n/(n+60)
    mu=max(-.015,min(.015,ewmean*prior_strength))
    ewvariance=sum(w*(r-ewmean)**2 for w,r in zip(weights,capped))/sum(weights)
    sigma=max(.0035,min(.18,math.sqrt(ewvariance)))
    ranges=bars[-min(20,len(bars)):]
    upside=statistics.median([max(0,math.log(h/c)) for _,c,_,h,l in ranges])
    downside=statistics.median([max(0,math.log(c/l)) for _,c,_,h,l in ranges])
    upside=max(.001,min(.15,upside));downside=max(.001,min(.15,downside))
    points=[]
    for k in range(1,horizons+1):
        p=official_close*math.exp(k*mu)
        w=Z80*sigma*math.sqrt(k)
        low=p*math.exp(-w);high=p*math.exp(w)
        row={'Horizon':f'D{k}','Point':round(p,4),'P20':round(low,4),'P50':round(p,4),'P80':round(high,4)}
        if k==1:
            row.update(D1HighProxy=round(p*math.exp(upside),4),D1LowProxy=round(p*math.exp(-downside),4),
                       HighLowQualification='EMPIRICAL_MEDIAN_OHLC_RESEARCH_NOT_FORMAL')
        check(row['P20']<=row['P50']<=row['P80'],'INVALID_INTERVAL')
        points.append(row)
    return {'Method':METHOD,'AdjustedReturnCount':n,'DailyLogMeanShrunk':mu,'DailyLogVolatility':sigma,
            'Intervals':'P20/P80_NORMAL_APPROXIMATION_NOT_CALIBRATED','HighLowSource':'MEDIAN_20_CUTOFF_BARS',
            'Forecasts':points}

def run(index,original_zip,cutoff=None):
    x=json.loads(pathlib.Path(index).read_bytes())
    entries=x.get('rows');check(isinstance(entries,list) and len(entries)==68,'UNIVERSE_NOT_68')
    codes={str(r.get('code')) for r in entries};check(len(codes)==68,'UNIVERSE_DUPLICATE')
    check(set(TARGETS).issubset(codes),'EXPECTED_SHORT_HISTORY_SET_MISSING')
    date=x.get('source_cutoff');target=x.get('authoritative_target')
    check(isinstance(date,str) and isinstance(target,str),'DATES_MISSING')
    d0=dt.date.fromisoformat(date);d1=dt.date.fromisoformat(target)
    check(d0<d1,'TARGET_MUST_FOLLOW_PRIOR_CLOSE')
    if cutoff:
        cut=dt.datetime.fromisoformat(cutoff.replace('Z','+00:00'))
        check(cut.tzinfo is not None and cut.astimezone(TZ).date()==d1,'INVALID_PREOPEN_CUTOFF')
        check(cut.astimezone(TZ).time()<dt.time(9),'NOT_PREMARKET')
        gen=x.get('data_generation_timestamp_utc')
        if gen:
            generated=dt.datetime.fromisoformat(gen.replace('Z','+00:00'))
            check(generated.tzinfo is not None and generated<=cut,'POST_CUTOFF_SOURCE_GENERATION')
    out=[]
    with zipfile.ZipFile(original_zip) as z:
        entries_zip=z.namelist();check(len(entries_zip)==len(set(entries_zip)),'DUPLICATE_ZIP_MEMBER')
        officials=x.get('official_original_shas',{})
        for venue in ('twse','tpex'):
            key=f'official_raw/{venue}.attempt1.json'
            check(sha(z.read(key))==officials.get(venue),'OFFICIAL_PARENT_SHA_MISMATCH_'+venue)
        for code in TARGETS:
            e=next(r for r in entries if str(r.get('code'))==code)
            rec={'Symbol':code,'Name':e['name'],'TargetDate':target,'SourceCutoff':date,
                 'ForecastRole':'RESEARCH_SHORT_HISTORY_PROXY','FormalEligible':False,
                 'NaturalCredit':0,'OOSCredit':0,'ExecutableShares':0,'CanonicalPredictionWritten':False,
                 'ProviderRawSHA256':e.get('provider_raw_sha256'), 'FormalH9ShortHistoryStillHold':True}
            try:
                check(e.get('source_cutoff_date')==date,'MIXED_SOURCE_DAY')
                ticker=e['ticker'];check(ticker.startswith(code+'.'),'TICKER_MISMATCH')
                raw=z.read(e['provider_raw_file']);check(sha(raw)==e['provider_raw_sha256'],'CHART_ORIGINAL_SHA_MISMATCH')
                bars=adjusted_bars(raw,ticker,date)
                venue=e.get('venue')
                check(venue in ('TWSE','TPEx'),'INVALID_OFFICIAL_VENUE')
                official_body=z.read('official_raw/'+('twse' if venue=='TWSE' else 'tpex')+'.attempt1.json')
                official_name,official_close=official_close_name(official_body,code,venue,date)
                check(official_name==str(e['name']).strip(),'OFFICIAL_NAME_INDEX_MISMATCH')
                eclose=float(e['official_close'])
                check(abs(official_close-eclose)<=max(.011,eclose*.00002),
                      'OFFICIAL_PRICE_INDEX_MISMATCH')
                forecast=estimate(bars,official_close)
                rec.update(Status='RESEARCH_PROXY_READY',PriorOfficialClose=eclose,UsableBars=len(bars),**forecast)
            except (KeyError,ValueError,TypeError,OverflowError,IndexError) as err:
                rec.update(Status='SOURCE_HOLD_NO_PREDICTION',MissingReason=str(err)[:180],Forecasts=[])
            out.append(rec)
    report={'Status':'RESEARCH_SHORT_HISTORY_3_ONLY','TargetDate':target,'SourceCutoff':date,
            'ExpectedUniverse':68,'ShortHistoryTargets':len(TARGETS),'ProxyNumericCount':sum(10 for r in out if r['Status']=='RESEARCH_PROXY_READY'),
            'Rows':out,'NoProductionWrites':True,'FormalEligible':False,'NaturalCredit':0,'OOSCredit':0,
            'Warnings':['Does not replace original 65 H9 symbols, H9 calibration or official issuer actions',
            'P20/P80 intervals are normal-approximation estimates not calibrated coverage',
            'Research only; not a trade instruction or prospective Natural forecast seal']}
    return report

def markdown(result):
    lines=[f"# {result['TargetDate']} 短歷史三檔研究預測（非正式模型）",'',
           '原始H9 65檔保持不變；以下3檔用明確替代研究方法，**不參與Natural/OOS/正式交易**。',
           '', '| 股票 | 原始日數 | 前收 | D1 Point | P20 | P50 | P80 | 估高(研究) | 估低(研究) | 狀態 |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for r in result['Rows']:
        if r['Status']!='RESEARCH_PROXY_READY':
            lines.append(f"| {r['Symbol']} {r['Name']} | — | — | — | — | — | — | — | — | {r['Status']}：{r.get('MissingReason','')} |")
        else:
            v=r['Forecasts'][0]
            lines.append(f"| {r['Symbol']} {r['Name']} | {r['UsableBars']} | {r['PriorOfficialClose']:.2f} | {v['Point']:.2f} | {v['P20']:.2f} | {v['P50']:.2f} | {v['P80']:.2f} | {v['D1HighProxy']:.2f} | {v['D1LowProxy']:.2f} | RESEARCH_ONLY |")
    lines += ['','D2–D10逐日Point/P20/P50/P80保存在同名JSON；截至前一交易日的個股來源SHA逐檔保留。',
              '缺正式發行人事件完整證據和同次盤前封存；**禁止寫入正式預測、持股或Natural/OOS**。','']
    return '\n'.join(lines)

def selftest():
    out={}
    def t(label,fn,should_fail=False):
        try:
            result=fn();out[label]='FAIL' if should_fail else ('PASS' if result else 'FAIL')
        except (ValueError,TypeError,KeyError,IndexError,OverflowError):out[label]='PASS' if should_fail else 'FAIL'
    d0=dt.datetime(2026,10,1,13,30,tzinfo=TZ).timestamp()
    # 30-day synthetic fixture; no historical market values used by CI.
    raw={'chart':{'error':None,'result':[{'meta':{'symbol':'00400A.TW'},
      'timestamp':[d0+i*86400 for i in range(30)],
      'indicators':{'quote':[{'close':[10+.01*i for i in range(30)], 'high':[10.04+.01*i for i in range(30)], 'low':[9.96+.01*i for i in range(30)]}],
                    'adjclose':[{'adjclose':[10+.01*i for i in range(30)]}]}}]}}
    import copy
    def bars(o=raw,expected='2026-10-30'):return adjusted_bars(json.dumps(o).encode(),'00400A.TW',expected)
    b=bars();m=estimate(b,10.29)
    t('success_10_horizons',lambda:len(m['Forecasts'])==10)
    t('point_inside_interval',lambda:all(z['P20']<=z['P50']<=z['P80'] for z in m['Forecasts']))
    t('positive_ohlc_proxy',lambda:m['Forecasts'][0]['D1HighProxy']>=m['Forecasts'][0]['Point']>=m['Forecasts'][0]['D1LowProxy'])
    t('official_anchor_conflict',lambda:estimate(b,11.3),True)
    t('future_day_rejected',lambda:bars(expected='2026-10-29'),True)
    t('stale_day_rejected',lambda:bars(expected='2026-10-31'),True)
    corrupt=copy.deepcopy(raw);corrupt['chart']['result'][0]['meta']['symbol']='MISMATCH.TW'
    t('symbol_drift_rejected',lambda:bars(corrupt),True)
    corrupt=copy.deepcopy(raw);corrupt['chart']['result'][0]['timestamp'][-1]=corrupt['chart']['result'][0]['timestamp'][-2]
    t('duplicate_bar_rejected',lambda:bars(corrupt),True)
    corrupt=copy.deepcopy(raw);corrupt['chart']['result'][0]['indicators']['adjclose'][0]['adjclose'].pop()
    t('no_adjusted_series_rejected',lambda:bars(corrupt),True)
    corrupt=copy.deepcopy(raw);corrupt['chart']['result'][0]['timestamp']=corrupt['chart']['result'][0]['timestamp'][:20]
    t('short_history_rejected',lambda:bars(corrupt),True)
    t('method_version_frozen',lambda:m['Method']==METHOD)
    t('interval_is_not_formal',lambda:m['Intervals'].endswith('NOT_CALIBRATED'))
    official_twse={'date':'20261030','stat':'OK','tables':[{'fields':['證券名稱','收盤價','證券代號'],
                   'data':[['主動國泰動能高息','10.29','00400A']]}]}
    t('official_columns_order_independent',lambda:official_close_name(json.dumps(official_twse).encode(),
      '00400A','TWSE','2026-10-30')==('主動國泰動能高息',10.29))
    official_tpex={'date':'20261030','stat':'ok','tables':[{'fields':['收盤','代號','名稱'],
                   'data':[['62.10','3718','中光電投控']]}]}
    t('official_tpex_quote_binding',lambda:official_close_name(json.dumps(official_tpex).encode(),
      '3718','TPEx','2026-10-30')==('中光電投控',62.10))
    bad=copy.deepcopy(official_twse);bad['date']='20261029'
    t('official_prior_date_rejected',lambda:official_close_name(json.dumps(bad).encode(),
      '00400A','TWSE','2026-10-30'),True)
    bad=copy.deepcopy(official_twse);bad['tables'][0]['data'].append(bad['tables'][0]['data'][0])
    t('official_duplicate_code_rejected',lambda:official_close_name(json.dumps(bad).encode(),
      '00400A','TWSE','2026-10-30'),True)
    ok=all(x=='PASS' for x in out.values())
    return {'status':'PASS' if ok else 'FAIL','passed':sum(x=='PASS' for x in out.values()),'total':len(out),
            'scope':'PURE_SYNTHETIC_TESTS_NO_PRIVATE_INPUT_NO_FORMAL','tests':out}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--self-test',action='store_true');parser.add_argument('--index');parser.add_argument('--source-zip');parser.add_argument('--output-dir');parser.add_argument('--cutoff')
    a=parser.parse_args()
    if a.self_test:
        result=selftest();print(json.dumps(result,ensure_ascii=False));return 0 if result['status']=='PASS' else 2
    if not all((a.index,a.source_zip,a.output_dir)):parser.error('--index --source-zip --output-dir required')
    path=pathlib.Path(a.output_dir);path.mkdir(parents=True,exist_ok=True)
    x=run(a.index,a.source_zip,a.cutoff)
    (path/'short_history_research_proxy.json').write_text(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    m=markdown(x)
    (path/'short_history_research_proxy.md').write_text(m,encoding='utf8')
    check((path/'short_history_research_proxy.md').read_text(encoding='utf8')==m,'REPORT_MD_READBACK_FAIL')
    print(json.dumps({'status':x['Status'],'numeric':x['ProxyNumericCount'],'target_date':x['TargetDate'],'formal':False},ensure_ascii=False))
    return 0
if __name__=='__main__':raise SystemExit(main())
