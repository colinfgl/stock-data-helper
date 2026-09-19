#!/usr/bin/env python3
"""Resume a public acquisition with bounded native-provider queries. No synthetic prices."""
import argparse, datetime as dt, hashlib, json, pathlib, re
from zoneinfo import ZoneInfo
from premarket_daily_inputs import get_json, official_quotes, validate_chart

def digest(p): return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def write(p,x): pathlib.Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2),encoding='utf-8')

def run(baseline, receipt_sha, symbol, target, out):
    base=pathlib.Path(baseline); dest=pathlib.Path(out);dest.mkdir(parents=True,exist_ok=False)
    rp=base/'acquisition_receipt.json'
    if digest(rp)!=receipt_sha: raise ValueError('BASELINE_RECEIPT_SHA')
    old=json.loads(rp.read_text()); dates=old['dates']
    if dates['target_date']!=target:raise ValueError('TARGET_MISMATCH')
    if not re.fullmatch(r'[A-Z0-9]{4,8}\.(TW|TWO)',symbol):raise ValueError('INVALID_SYMBOL')
    matches=[x for x in old['charts'] if x['symbol']==symbol]
    if len(matches)!=1 or matches[0]['status']!='FAIL':raise ValueError('ONLY_FAILED_SYMBOL_MAY_BE_RETRIED')
    market='TPEX' if symbol.endswith('.TWO') else 'TWSE'; days=[dates['previous_session'],dates['price_cutoff']];official={}
    for day in days:
        name=f'{market}_{day}.json';meta=[x for x in old['sources']if x['path']==name]
        f=base/name
        if len(meta)!=1 or digest(f)!=meta[0]['sha256'] or f.stat().st_size!=meta[0]['bytes']:raise ValueError('OFFICIAL_BASELINE_INTEGRITY')
        official[day]=official_quotes(json.loads(f.read_text()),market,day).get(symbol.split('.')[0])
    tz=ZoneInfo('Asia/Taipei');start=int(dt.datetime.strptime(days[0],'%Y%m%d').replace(tzinfo=tz).timestamp())
    end=int((dt.datetime.strptime(days[1],'%Y%m%d').replace(tzinfo=tz)+dt.timedelta(days=1)).timestamp())
    suffix='interval=1d&events=div%2Csplits&includeAdjustedClose=true'
    urls=[f'https://query1.finance.yahoo.com/v8/finance/chart/{symbol}?{suffix}&period1={start}&period2={end}',f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?{suffix}&range=5d',f'https://query2.finance.yahoo.com/v8/finance/chart/{symbol}?{suffix}&range=1mo']
    result={'started_at':dt.datetime.now(dt.timezone.utc).isoformat(),'dates':dates,'baseline_receipt_sha256':receipt_sha,'symbol':symbol,'sources':[],'chart':None,'successful_sources_refetched':0,'formal_input_qualified':False,'prediction_generated':False}
    for i,url in enumerate(urls):
        p,m=get_json(url,dest/f'chart_variant_{i}.json',attempt_limit=1);result['sources'].append(m)
        try:
            q=validate_chart(p,symbol,days,official);result['chart']={**q,'path':m['path'],'sha256':m['sha256']};break
        except Exception as e:m['validation_error']=str(e)
        finally:write(dest/'targeted_receipt.json',result)
    # Record official endpoint descriptions/raw sources; raw acquisition alone is NOT coverage certification.
    extra={
      'twse_reduction.json':f'https://www.twse.com.tw/exchangeReport/TWTAUU?response=json&startDate={days[0]}&endDate={target.replace("-","")}',
      'twse_split.json':f'https://www.twse.com.tw/exchangeReport/TWTCAU?response=json&startDate={days[0]}&endDate={target.replace("-","")}',
      'twse_swagger.json':'https://openapi.twse.com.tw/v1/swagger.json',
      'tpex_swagger.json':'https://www.tpex.org.tw/openapi/swagger.json'}
    result['action_api_candidates']=[]
    for name,url in extra.items():
        p,m=get_json(url,dest/name,attempt_limit=1);result['sources'].append(m)
        if p and isinstance(p.get('paths'),dict):
            for path,methods in p['paths'].items():
                desc=json.dumps(methods,ensure_ascii=False)
                if any(w in desc for w in ['減資','分割','面額']):
                    result['action_api_candidates'].append({'source':name,'path':path,'schema':methods})
        write(dest/'targeted_receipt.json',result)
    result['completed_at']=dt.datetime.now(dt.timezone.utc).isoformat()
    result['status']='NATIVE_PRICE_RECOVERED' if result['chart'] else 'NATIVE_PRICE_STILL_MISSING'
    write(dest/'targeted_receipt.json',result)
    print(json.dumps({k:v for k,v in result.items()if k!='action_api_candidates'},ensure_ascii=False))
    return 0 if result['chart'] else 2
if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('--baseline',required=True);a.add_argument('--receipt-sha',required=True);a.add_argument('--symbol',default='0050.TW');a.add_argument('--target',required=True);a.add_argument('--out',required=True);x=a.parse_args()
    raise SystemExit(run(x.baseline,x.receipt_sha,x.symbol,x.target,x.out))
