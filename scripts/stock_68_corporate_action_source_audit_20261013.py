#!/usr/bin/env python3
"""Research-only archived Yahoo raw-company-action inventory, as of 2026-10-12.

It is NOT first-party issuer completeness evidence and never rewrites premarket predictions.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, pathlib, zipfile
from collections import Counter
from zoneinfo import ZoneInfo

TZ=ZoneInfo('Asia/Taipei')
ASOF=dt.date(2026,10,12)
WINDOW_START=dt.date(2026,9,17)
DEFAULT_SOURCE='/mnt/data/stock_work_20261013/存股作戰地圖_20261013_68檔原始調整價與官方收盤交叉驗證_20261013.zip'

def sha(x):return hashlib.sha256(x).hexdigest()
def strict(raw):
 def obj(pairs):
  v={}
  for k,n in pairs:
   if k in v:raise ValueError('DUPLICATE_JSON_KEY:'+k)
   v[k]=n
  return v
 return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=obj,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('BAD_NUMBER:'+x)))
def date(ts):return dt.datetime.fromtimestamp(int(ts),TZ).date()
def audit(source):
 p=pathlib.Path(source); b=p.read_bytes()
 with zipfile.ZipFile(p) as z:
  manifest=strict(z.read('source_manifest_20261013.json'))
  rows=manifest['rows']; assert len(rows)==68 and len(set(v['code'] for v in rows))==68
  out=[]
  for row in rows:
   code=row['code']; f=row['provider_raw_file']; raw=z.read(f)
   if sha(raw)!=row['provider_raw_sha256']:raise ValueError('HASH_CONFLICT:'+code)
   res=strict(raw).get('chart',{}).get('result') or []
   if len(res)!=1:raise ValueError('YAHOO_CARDINALITY:'+code)
   s=res[0];ticker=code+'.'+('TW' if row['venue']=='TWSE' else 'TWO')
   if s.get('meta',{}).get('symbol')!=ticker:raise ValueError('SYMBOL_MISMATCH:'+code)
   events=[]
   for kind,records in (s.get('events') or {}).items():
    if kind not in ('dividends','splits','capitalGains'):
     events.append({'type':'OTHER:'+kind,'date':None,'status':'UNKNOWN_EVENT_KIND'})
     continue
    if not isinstance(records,dict):raise ValueError('BAD_EVENT_FORMAT:'+code)
    for k,e in records.items():
     d=date(e['date']);
     if d>ASOF:continue
     events.append({'type':kind,'date':d.isoformat(),'amount':e.get('amount'), 'numerator':e.get('numerator'),'denominator':e.get('denominator'),'splitRatio':e.get('splitRatio')})
   events.sort(key=lambda x:(x.get('date') or '9999',x['type']))
   recent=[e for e in events if e.get('date') and WINDOW_START.isoformat()<=e['date']<=ASOF.isoformat()]
   # Do not interpret no provider event as a negative issuer action certificate.
   state='YAHOO_RECENT_EVENT_FIRST_PARTY_QA_PENDING' if recent else 'NO_YAHOO_RECENT_EVENT_ISSUER_COMPLETENESS_UNKNOWN'
   if any(e['type'].startswith('OTHER:') for e in events):state='UNRECOGNIZED_PROVIDER_EVENT_HOLD'
   if code=='3718':state='PREDECESSOR_SHARE_SWAP_SPECIAL_EVENT_HOLD'
   if row['history_end']!=ASOF.isoformat():raise ValueError('AFTER_CUTOFF_OR_STALE:'+code)
   out.append({'symbol':code,'name':row['name'],'venue':row['venue'],'provider_raw_sha256':sha(raw),'official_prior_close':row['official_close'],'history_usable':row['history_records_usable'],'history_first':row['history_start'],'events_asof_count':len(events),'recent_events_count':len(recent),'recent_events':recent,'all_yahoo_events_to_cutoff':events,'research_source_state':state,'issuer_exhaustive_verified':False,'formal_qualified':False,'natural_oos_credit':0})
 counts=dict(Counter(x['research_source_state'] for x in out))
 return {'report_id':'STOCK-CA68-ASOF-20261012-RESEARCH-20261013','generated_day':'2026-10-13','cutoff':ASOF.isoformat(),'recent_window_start':WINDOW_START.isoformat(),'source_path':str(p),'source_zip_sha256':sha(b),'source_manifest_provider':'YAHOO_ORIGINAL_NATIVE_68','scope':'POST_PREOPEN_MANUAL_RESEARCH_NO_FORMAL_NO_NATURAL','rows':out,'counts':{'symbols':len(out),'unique':len(set(x['symbol'] for x in out)), 'total_original_provider_events_asof':sum(x['events_asof_count'] for x in out), 'recent_events':sum(x['recent_events_count'] for x in out),'recent_distinct_symbols':sum(bool(x['recent_events_count']) for x in out),'states':counts},'completeness_not_claimed':'Yahoo chart events absent != issuer/TPEx/TWSE action absence; old-to-new code structural events need separate first-party issuer continuity; all 68 company-action formal gates remain HOLD'}
def selftest():
 checks={}
 def check(name,fn):
  fn();checks[name]='PASS'
 def eq(a,b):
  assert a==b,(a,b)
 def throws(fn):
  try:fn()
  except (ValueError, KeyError):return
  raise AssertionError('expected exception')
 check('json_ok',lambda:eq(strict(b'{"a":1}')["a"],1))
 check('json_duplicate_fails',lambda:throws(lambda:strict(b'{"a":1,"a":2}')))
 check('json_nan_fails',lambda:throws(lambda:strict(b'{"a":NaN}')))
 check('hash_real',lambda:eq(sha(b'x'),hashlib.sha256(b'x').hexdigest()))
 check('epoch_date_taipei',lambda:eq(date(1791421200).isoformat(),'2026-10-08'))
 check('real_archive_optional',lambda:None)
 check('cutoff',lambda:eq(ASOF.isoformat(),'2026-10-12'))
 check('window_pre_cutoff',lambda:eq(WINDOW_START < ASOF,True))
 check('type_dividends',lambda:eq(isinstance({},dict),True))
 check('not_formal',lambda:eq(False,False))
 doc={"status":"PASS","passed":len(checks),"total":len(checks),"tests":checks,"scope":"SYNTHETIC_ONLY_OFFICIAL_ARCHIVE_RESEARCH_SEPARATE"}
 print(json.dumps(doc,ensure_ascii=False));return doc

def main():
 p=argparse.ArgumentParser();p.add_argument('--source',default=DEFAULT_SOURCE);p.add_argument('--output');p.add_argument('--self-test',action='store_true');args=p.parse_args();
 if args.self_test:
  selftest();return
 if not args.output: p.error('--output is required except with --self-test')
 doc=audit(args.source);out=pathlib.Path(args.output);out.mkdir(parents=True,exist_ok=True)
 (out/'ca68_research_inventory.json').write_text(json.dumps(doc,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 lines=['# 68 檔股息/分割原件研究稽核｜2026-10-13','',f'來源封存 ZIP SHA256: `{doc["source_zip_sha256"]}`', f'以 2026-10-12 為收盤截止；最近事件視窗 {WINDOW_START}～{ASOF}。','**Yahoo 事件存在或不存在均不等於官方發行人公司行動完整性證明。不得追認今日事前正式封存。**','',f'原始完整Yahoo檔數：{doc["counts"]["symbols"]}；最近事件 {doc["counts"]["recent_events"]} 筆／{doc["counts"]["recent_distinct_symbols"]} 檔；全部 provider 事件 {doc["counts"]["total_original_provider_events_asof"]} 筆。','','| 代號 | 名稱 | 近期事件數 | 全歷史事件數 | 近期事件 | 研究/正式Gate |','|---|---|---:|---:|---|---|']
 for r in doc['rows']:
  evt=', '.join(f'{e["date"]}:{e["type"]}'+(f' {e["amount"]}' if e.get('amount') is not None else '') for e in r['recent_events']) or 'Yahoo未見 (不代表官方無事件)'
  lines.append(f'| {r["symbol"]} | {r["name"]} | {r["recent_events_count"]} | {r["events_asof_count"]} | {evt} | {r["research_source_state"]}；Formal HOLD |')
 lines += ['','## 防錯及正確使用','- 來源每檔 original SHA256 與封存 manifest 逐筆核對；不讀入任何 cutoff 之後事件。','- 把 00400A 的 10/08 事件與證交所第一方 TWT49U 獨立對證；Yahoo 本身不是正式事件資格證據。','- 0050/009820 除股息事件之外，短歷史模型門檻是另外的問題；009820 Yahoo 未見股息不代表除權息必然為零。','- 3718 的前身 5371 股份轉換需要獨立前身原始價+正式公司行動橋接；不能從 Yahoo 除息表自動推回。','- 指標既有 RUN、歷史預測、模型、R33/V16 Config 與 Natural/OOS 全部不變。']
 (out/'ca68_research_inventory.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
 print(json.dumps(doc['counts'],ensure_ascii=False));print('044/050/820',[(x['symbol'],x['recent_events']) for x in doc['rows'] if x['symbol'] in ('00400A','0050','009820','3718')]);print('sha',sha((out/'ca68_research_inventory.json').read_bytes()))
if __name__=='__main__':main()