#!/usr/bin/env python3
"""Bounded, public-only source evidence. Never qualifies model inputs or forecasts.

The named queries are historical engineering targets, not a daily data feed.
HTTP error bodies are evidence, not instructions; no credentials or auto-retries.
"""
from __future__ import annotations
import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import json
import os
import pathlib
import re
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

LIMIT = 262144
TARGETS = [('0050','2026-09-17','2026-09-18'),
           ('00400A','2026-09-17','2026-09-18'),
           ('009820','2026-09-17','2026-09-18'),
           ('2330','2025-08-01','2025-08-01')]

def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def sha(data):
    return hashlib.sha256(data).hexdigest()

def validate_target(target):
    if not isinstance(target, (list, tuple)) or len(target) != 3:
        raise ValueError('TARGET_TRIPLE_REQUIRED')
    code, start, end = target
    if not isinstance(code, str) or re.fullmatch(r'[0-9A-Z]{4,6}', code) is None:
        raise ValueError('PUBLIC_SYMBOL_REQUIRED')
    if not all(isinstance(x,str) and re.fullmatch(r'\d{4}-\d{2}-\d{2}',x) for x in (start,end)):
        raise ValueError('ISO_DATE_REQUIRED')
    a,b = dt.date.fromisoformat(start),dt.date.fromisoformat(end)
    if b<a or (b-a).days>1 or b>dt.datetime.now(ZoneInfo('Asia/Taipei')).date():
        raise ValueError('BOUNDED_PAST_DATE_RANGE_REQUIRED')
    return code, start, end

def network_category(error):
    reason = error.reason if isinstance(error, urllib.error.URLError) else error
    if isinstance(reason, socket.gaierror): return 'NETWORK_DNS_ERROR'
    if isinstance(reason, (TimeoutError, socket.timeout)): return 'NETWORK_TIMEOUT'
    if isinstance(reason, ssl.SSLError): return 'NETWORK_TLS_ERROR'
    return 'NETWORK_ERROR'

def http_category(status):
    if status in (401,403): return 'HTTP_AUTHORIZATION_ERROR'
    if status == 429: return 'HTTP_RATE_LIMITED'
    if status >= 500: return 'HTTP_SERVER_ERROR'
    return 'HTTP_ERROR'

def parse_body(body, record, expected):
    try:
        payload = json.loads(body, parse_constant=lambda value: (_ for _ in ()).throw(ValueError("NONFINITE_JSON:"+value)))
    except (UnicodeError, ValueError):
        record['parse_status']='INVALID_JSON'
        return 'INVALID_JSON'
    if not isinstance(payload, dict):
        record['parse_status']='INVALID_SCHEMA'
        return 'INVALID_SCHEMA'
    record['provider_status']=payload.get('status')
    msg=payload.get('msg')
    record['provider_message']=msg[:2000] if isinstance(msg,str) else None
    record['parse_status']='JSON_PARSED'
    rows=payload.get('data')
    if payload.get('status') != 200: return 'PROVIDER_ERROR'
    if not isinstance(rows,list) or any(not isinstance(row,dict) for row in rows):
        return 'INVALID_SCHEMA'
    dates=[row.get('date') for row in rows]
    record['rows_received']=len(rows)
    record['dates_received']=dates
    if any(not isinstance(d,str) for d in dates): return 'INVALID_SCHEMA'
    if len(dates)!=len(set(dates)): return 'DUPLICATE_DATES'
    if any(row.get('stock_id')!=record['code'] for row in rows): return 'SYMBOL_MISMATCH'
    if set(dates)-expected: return 'UNEXPECTED_DATES'
    missing=sorted(expected-set(dates)); record['missing_dates']=missing
    if missing: return 'MISSING_REQUESTED_DATES'
    # Even complete rows are only candidate evidence, not approved adjusted prices.
    return 'CANDIDATE_UNVALIDATED'

def capture(target, root, opener=None):
    code,start,end=validate_target(target)
    opener = opener or urllib.request.urlopen
    root=pathlib.Path(root)
    url='https://api.finmindtrade.com/api/v4/data?'+urllib.parse.urlencode(
        {'dataset':'TaiwanStockPriceAdj','data_id':code,'start_date':start,'end_date':end})
    record={'code':code,'start_date':start,'end_date':end,'dataset':'TaiwanStockPriceAdj',
            'url':url,'requested_at':stamp(),'attempts':1,'retries':0,
            'formal_qualified':False,'root_cause':'UNDETERMINED','body_saved':False}
    req=urllib.request.Request(url,headers={'User-Agent':'B1-source-verification/2.0','Accept':'application/json'})
    response=None; is_http_error=False
    try:
        response=opener(req,timeout=15)
    except urllib.error.HTTPError as error:
        response=error; is_http_error=True
    except (urllib.error.URLError, TimeoutError, ssl.SSLError, OSError) as error:
        record.update(transport='NO_HTTP_RESPONSE',category=network_category(error),
                      error_type=type(error).__name__,error=str(error)[:1000],received_at=stamp())
        return record
    except Exception as error:
        record.update(transport='CLIENT_ERROR',category='CLIENT_ERROR',
                      error_type=type(error).__name__,error=str(error)[:1000],received_at=stamp())
        return record
    try:
        status=response.getcode()
        record['http_status']=status
        headers=getattr(response,'headers',None) or {}
        record['headers']={k:headers.get(k) for k in ('Content-Type','Retry-After') if headers.get(k) is not None}
        record['transport']='HTTP_ERROR_RESPONSE' if is_http_error or not 200<=status<300 else 'HTTP_RESPONSE'
        # Read only a bounded prefix. A truncated response is never parsed or validated.
        try:
            body=response.read(LIMIT+1)
        except Exception as error:
            record.update(category='RESPONSE_BODY_READ_ERROR',error_type=type(error).__name__,
                          error=str(error)[:1000],body_complete=False)
            return record
        complete=len(body)<=LIMIT
        body=body[:LIMIT]
        record.update(body_complete=complete,body_limit=LIMIT)
        name=f'{code}_{start}_{end}.raw'
        try:
            with (root/name).open('xb') as output: output.write(body)
        except OSError as error:
            record.update(category='LOCAL_EVIDENCE_SAVE_ERROR',error_type=type(error).__name__,
                          error=str(error)[:1000])
            return record
        record.update(body_saved=True,path=name,sha256=sha(body),bytes=len(body))
        payload_category=parse_body(body,record,{start,end}) if complete else 'BODY_LIMIT_EXCEEDED'
        record['payload_category']=payload_category
        record['category']=http_category(status) if is_http_error or not 200<=status<300 else payload_category
        record['candidate_received']=record['category']=='CANDIDATE_UNVALIDATED'
        record['retry_performed']=False
        return record
    finally:
        record['received_at']=stamp()
        if response is not None:
            try: response.close()
            except Exception: record['response_close_failed']=True

def run(out, targets=None, opener=None):
    targets=TARGETS if targets is None else targets
    validated=[validate_target(t) for t in targets]
    if not validated or len(validated)>4 or len(validated)!=len(set(validated)):
        raise ValueError('ONE_TO_FOUR_UNIQUE_TARGETS_REQUIRED')
    root=pathlib.Path(out); root.mkdir(parents=True,exist_ok=False)
    started=stamp()
    with cf.ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda t:capture(t,root,opener),validated))
    candidate_count=sum(r.get('candidate_received') is True for r in results)
    receipt={'started_at':started,'completed_at':stamp(),
             'operation':'HISTORICAL_SOURCE_DIAGNOSTIC_NOT_DAILY_FORECAST',
             'sources':results,'requests':len(results),'retries':0,'model_runs':0,
             'script_sha256':sha(pathlib.Path(__file__).read_bytes()),
             'checkout_sha':os.environ.get('GITHUB_SHA'),
             'private_portfolio_included':False,'formal_input_qualified':False,
             'candidate_count':candidate_count,'all_candidates_received':candidate_count==len(results),
             'limitation':'Complete candidate rows still require original financial, history and action checks. HTTP/body evidence is not model qualification.'}
    with (root/'receipt.json').open('x',encoding='utf8') as f:
        json.dump(receipt,f,ensure_ascii=False,indent=2,allow_nan=False)
    return receipt

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--out',required=True)
    parser.add_argument('--diagnostic-one',action='store_true')
    args=parser.parse_args()
    result=run(args.out,TARGETS[:1] if args.diagnostic_one else None)
    print(json.dumps({'requests':result['requests'],'candidate_count':result['candidate_count'],
                      'categories':[r['category'] for r in result['sources']],
                      'formal_input_qualified':False},ensure_ascii=False))
    return 0 if result['all_candidates_received'] else 2

if __name__=='__main__':
    raise SystemExit(main())
