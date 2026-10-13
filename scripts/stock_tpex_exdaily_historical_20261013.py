#!/usr/bin/env python3
"""Source-only TPEx historical ex-right/exdividend date-window evidence probe.

A first-party original response is eligible for Research QA only when at least one
parsed event has the requested ROC-date window, exact one-date-per-row structure,
valid stock code, and no duplicate code/date/type key. No Formals/Natural/OOS.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, pathlib, urllib.parse, urllib.request, urllib.error, re, time, sys

WINDOWS=[('2025-06-01','2025-06-30'),('2026-09-01','2026-09-30')]
BASE='https://www.tpex.org.tw'
def digest(b:bytes)->str:return hashlib.sha256(b).hexdigest()
def parse_roc_date(s:str)->str:
    s=str(s).strip().replace('年','/').replace('月','/').replace('日','').replace('-','/')
    m=re.search(r'(?<!\d)(\d{3,4})/(\d{1,2})/(\d{1,2})(?!\d)',s)
    if not m:raise ValueError('DATE_NOT_YYYY_OR_ROC:'+str(s)[:45])
    y=int(m.group(1));y += 1911 if y<1911 else 0
    return dt.date(y,int(m.group(2)),int(m.group(3))).isoformat()
def roc(s):
    d=dt.date.fromisoformat(s);return f'{d.year-1911}/{d.month:02d}/{d.day:02d}'
def source_urls(begin,end):
    old=urllib.parse.urlencode({'l':'zh-tw','d':roc(begin),'ed':roc(end)})
    new=urllib.parse.urlencode({'startDate':begin,'endDate':end})
    q=urllib.parse.urlencode({'startDate':begin,'endDate':end,'response':'json'})
    return [BASE+'/web/stock/exright/dailyquo/exDailyQ_result.php?'+old,
            BASE+'/www/zh-tw/announce/market/ex/cal?'+new,
            BASE+'/www/zh-tw/announce/market/ex/cal?'+q]
def parse_original(raw,begin,end):
    try:o=json.loads(raw.decode('utf-8-sig'))
    except Exception as e:raise ValueError('NOT_VALID_JSON:'+str(e)[:70])
    if isinstance(o,dict):
        if 'aaData' in o: rows=o['aaData']
        elif 'data' in o: rows=o['data']
        elif 'tables' in o and isinstance(o['tables'],list): rows=[r for tab in o['tables'] for r in tab.get('data',[])]
        else:raise ValueError('JSON_NO_KNOWN_ROW_SCHEMA:'+str(list(o.keys())[:8]))
    elif isinstance(o,list):rows=o
    else:raise ValueError('UNKNOWN_JSON_ROOT')
    if not isinstance(rows,list) or not rows:raise ValueError('NO_ROWS_NOT_PROOF_OF_NO_ACTIONS')
    good=[];keys=set();bad=[]
    for r in rows:
        if not isinstance(r,(list,tuple)) or len(r)<9:raise ValueError('ROW_SCHEMA_SHORT')
        date=parse_roc_date(str(r[0]));code=str(r[1]).strip();kind=str(r[8]).strip()
        if not re.fullmatch(r'[0-9A-Z]{4,6}',code):raise ValueError('STOCK_CODE_INVALID:'+code)
        if not(begin<=date<=end):bad.append(date);continue
        key=(date,code,kind)
        if key in keys:raise ValueError('DUPLICATE_DATE_CODE_EVENT')
        keys.add(key);good.append({'date':date,'symbol':code,'kind':kind,'row':list(r)})
    if bad:raise ValueError('OUT_OF_PERIOD_ROWS:'+','.join(sorted(set(bad))[:4]))
    if not good:raise ValueError('NO_MATCHING_PERIOD_ROWS')
    return {'rows':len(good),'symbols':len(set(x['symbol'] for x in good)),
            'min_date':min(x['date'] for x in good),'max_date':max(x['date'] for x in good),
            'sample':good[:3]}
def selftest():
    tests={}
    def run(name,fn,should_pass=True):
        try:fn();ok=should_pass
        except Exception:ok=not should_pass
        tests[name]=ok
    run('roc_2026',lambda:(_ for _ in ()).throw(AssertionError()) if parse_roc_date('115/09/02')!='2026-09-02' else None)
    run('parse_gregorian',lambda:(_ for _ in ()).throw(AssertionError()) if parse_roc_date('2026/09/02')!='2026-09-02' else None)
    run('invalid_date',lambda:parse_roc_date('nonsense'),False)
    rows=[['115/09/02','3105','test','100','90','0','10','10','除息']]
    def validate():
        a=parse_original(json.dumps({'aaData':rows}).encode(),'2026-09-01','2026-09-30')
        assert a['rows']==1 and a['symbols']==1
    run('valid_json_event',validate)
    run('out_of_range',lambda:parse_original(json.dumps({'aaData':rows}).encode(),'2026-08-01','2026-08-31'),False)
    run('duplicate_event',lambda:parse_original(json.dumps({'aaData':rows*2}).encode(),'2026-09-01','2026-09-30'),False)
    run('empty_data',lambda:parse_original(b'{"aaData":[]}', '2026-09-01','2026-09-30'),False)
    run('html_fallback',lambda:parse_original(b'<html></html>','2026-09-01','2026-09-30'),False)
    run('alpha_numeric_etf_symbol',lambda:parse_original(json.dumps({'aaData':[rows[0][:1]+['00950B']+rows[0][2:]]}).encode(),'2026-09-01','2026-09-30'))
    run('bad_symbol',lambda:parse_original(json.dumps({'aaData':[rows[0][:1]+['NOT_STOCK']+rows[0][2:]]}).encode(),'2026-09-01','2026-09-30'),False)
    run('urls_distinct',lambda:(_ for _ in ()).throw(AssertionError('urls')) if len(set(source_urls(*WINDOWS[1])))!=3 else None)
    assert all(tests.values()),tests
    print(json.dumps({'tests':tests,'passed':len(tests),'total':len(tests),'status':'PASS'},ensure_ascii=False))

def main():
    p=argparse.ArgumentParser();p.add_argument('--self-test',action='store_true');p.add_argument('--out');args=p.parse_args()
    if args.self_test:selftest();return 0
    if not args.out:p.error('--out required')
    out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=False)
    result={'asof_utc':dt.datetime.now(dt.timezone.utc).isoformat(),'scope':'FIRST_PARTY_TPEX_DATE_WINDOW_RESEARCH_ONLY',
      'formal_eligible':False,'natural_credit':0,'windows':[]}
    for ix,(begin,end) in enumerate(WINDOWS):
        w={'begin':begin,'end':end,'attempts':[],'status':'HOLD_SOURCE_UNVERIFIED'}
        for j,url in enumerate(source_urls(begin,end)):
            att={'url':url,'window':str(ix),'attempt':j}
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 (research source verification)','Accept':'application/json,text/plain,*/*'})
                with urllib.request.urlopen(req,timeout=12) as resp:
                    raw=resp.read(5000001);att.update(http_status=resp.status,final_url=resp.geturl(),content_type=resp.headers.get('Content-Type',''))
                if len(raw)>5000000:raise ValueError('SOURCE_TOO_LARGE')
                att.update(sha256=digest(raw),bytes=len(raw))
                file=f'tpex_exdaily_{ix}_{j}.bin';(out/file).write_bytes(raw);att['archive_file']=file
                if urllib.parse.urlparse(att['final_url']).hostname != 'www.tpex.org.tw':raise ValueError('REDIRECT_HOST_DIFF')
                parsed=parse_original(raw,begin,end)
                att['parse']=parsed;att['status']='PASS_EXACT_DATE_ORIGINAL';w.update(status=att['status'],chosen=j,parsed=parsed)
                w['attempts'].append(att);break
            except Exception as e:att.update(status='HOLD',error_type=type(e).__name__,error=str(e)[:190])
            w['attempts'].append(att)
        result['windows'].append(w)
        (out/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    result['windows_pass']=sum(w['status']=='PASS_EXACT_DATE_ORIGINAL' for w in result['windows'])
    (out/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    print(json.dumps({'windows':[(w['begin'],w['end'],w['status'],w.get('parsed',{}).get('rows',0)) for w in result['windows']], 'pass':result['windows_pass']},ensure_ascii=False))
    return 0 if result['windows_pass']==len(WINDOWS) else 1
if __name__=='__main__':raise SystemExit(main())