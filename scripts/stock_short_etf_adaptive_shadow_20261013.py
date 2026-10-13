#!/usr/bin/env python3
"""Original-provider cutoff-valid SHORT-history ETF shadow with fixed method + walkforward QA.

No issuer approval, no production model, no retrospective formal or natural credit.
Only archived 2026-10-12 chart bytes; strictly no target-date 10/13 prices.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, pathlib, statistics, zipfile
from collections import Counter
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Asia/Taipei')
ASOF=dt.date(2026,10,12)
DATES=['2026-10-13','2026-10-14','2026-10-15','2026-10-16','2026-10-19','2026-10-20','2026-10-21','2026-10-22','2026-10-23','2026-10-27']
SRC='/mnt/data/stock_work_20261013/存股作戰地圖_20261013_68檔原始調整價與官方收盤交叉驗證_20261013.zip'
SYMS=['00400A','009820']
def sha(x):return hashlib.sha256(x).hexdigest()
def strict(raw):
 def hook(pairs):
  d={}
  for k,v in pairs:
   if k in d:raise ValueError('DUPLICATE_JSON_FIELD:'+k)
   d[k]=v
  return d
 return json.loads(raw.decode('utf-8-sig'),object_pairs_hook=hook,parse_constant=lambda a:(_ for _ in ()).throw(ValueError('NONFINITE')))
def q(sample,p):
 x=sorted(sample);r=(len(x)-1)*p;left=int(math.floor(r));right=int(math.ceil(r));return x[left]+(x[right]-x[left])*(r-left)
def forecast(seq,hs=10):
 if len(seq)<95 or any(p<=0 or not math.isfinite(p) for p in seq):raise ValueError('SHORT_HISTORY_NOT_READY')
 returns=[math.log(y/x) for x,y in zip(seq,seq[1:])]
 if max(abs(u) for u in returns[-20:])>.19:raise ValueError('EXTREME_UNMODELED_EVENT_NEEDS_REVIEW')
 drift=statistics.mean(returns[-20:])*20/(20+60) # fixed shrinkage=0.25; NOT trained on test outcomes
 result=[]
 for h in range(1,hs+1):
  hist=[math.log(seq[j+h]/seq[j]) for j in range(0,len(seq)-h)]
  if len(hist)<45:raise ValueError('NOT_ENOUGH_HORIZON_WINDOWS')
  anchor=seq[-1];l=q(hist,.2);u=q(hist,.8);median=q(hist,.5)
  r={'horizon':h,'point':anchor*math.exp(drift*h),'p20':anchor*math.exp(l),'p50':anchor*math.exp(median),'p80':anchor*math.exp(u),'baseline_nochange':anchor, 'historic_horizon_samples':len(hist)}
  if not(r['p20']<=r['p50']<=r['p80']):raise ValueError('BAD_INTERVAL')
  result.append(r)
 return result

def replay(seq):
 # One fixed algorithm for all original-like origins. Scoring is historical retrospective only.
 origins=range(max(95,len(seq)-36),len(seq)-10)
 errors={i:[] for i in range(1,11)};base={i:[] for i in range(1,11)};cover={i:[] for i in range(1,11)}
 for origin in origins:
  history=seq[:origin];fc=forecast(history)
  for h,r in enumerate(fc,1):
   actual=seq[origin+h-1];prev=seq[origin-1]
   errors[h].append(abs(actual-r['point'])/prev)
   base[h].append(abs(actual-prev)/prev)
   cover[h].append(r['p20']<=actual<=r['p80'])
 return {'origin_count':len(list(origins)),'d1':{'samples':len(errors[1]),'candidate_mape_pct':100*statistics.mean(errors[1]),'nochange_mape_pct':100*statistics.mean(base[1]),'coverage':statistics.mean(cover[1])},'d10':{'samples':len(errors[10]),'candidate_mape_pct':100*statistics.mean(errors[10]),'nochange_mape_pct':100*statistics.mean(base[10]),'coverage':statistics.mean(cover[10])}, 'total_horizon_pairs':sum(len(x) for x in errors.values()),'no_lookahead_in_origin':True}
def selftest():
 checks={}
 def check(name,fn):
  fn();checks[name]='PASS'
 def eq(a,b):assert a==b,(a,b)
 def throws(fn):
  try:fn()
  except ValueError:return
  raise AssertionError('expected failure')
 sample=[20*math.exp(i*.0002+math.sin(i/7)*.004) for i in range(130)]
 f=forecast(sample); r=replay(sample)
 check('ten_horizons',lambda:eq(len(f),10))
 check('d1_anchor_positive',lambda:eq(f[0]['point']>0,True))
 check('d10_sample_count',lambda:eq(f[9]['historic_horizon_samples'],120))
 check('interval_order_all',lambda:eq(all(x['p20']<=x['p50']<=x['p80'] for x in f),True))
 check('basis_all_same',lambda:eq(all(x['baseline_nochange']==sample[-1] for x in f),True))
 check('short_series_block',lambda:throws(lambda:forecast([5]*80)))
 check('nan_block',lambda:throws(lambda:forecast([5]*110+[float("nan")])))
 check('zero_block',lambda:throws(lambda:forecast([5]*100+[0]*12)))
 check('extreme_burst_block',lambda:throws(lambda:forecast([10]*115+[100]*15)))
 check('no_future_origin',lambda:eq(r['no_lookahead_in_origin'],True))
 check('walkforward_has_origins',lambda:eq(r['origin_count']>0,True))
 check('walkforward_pairs',lambda:eq(r['total_horizon_pairs'],r['origin_count']*10))
 check('coverage_bounded',lambda:eq(0<=r['d10']['coverage']<=1,True))
 check('maturity_dates_unique',lambda:eq(len(set(DATES)),10))
 check('days_holiday_skip',lambda:eq(DATES[-1],'2026-10-27'))
 print(json.dumps({"status":"PASS","passed":len(checks),"total":len(checks),"tests":checks,"scope":"SYNTHETIC_TEST_ONLY_NO_PROD"},ensure_ascii=False))

def main():
 p=argparse.ArgumentParser();p.add_argument('--source',default=SRC);p.add_argument('--output');p.add_argument('--self-test',action='store_true');args=p.parse_args()
 if args.self_test:
  selftest();return
 if not args.output:p.error('--output is required except with --self-test')
 source=pathlib.Path(args.source)
 rows=[]
 with zipfile.ZipFile(source) as z:
  manifest=strict(z.read('source_manifest_20261013.json'))
  for code in SYMS:
   d=next(x for x in manifest['rows'] if x['code']==code);b=z.read(d['provider_raw_file'])
   if sha(b)!=d['provider_raw_sha256']:raise ValueError('PROVIDER_RAW_HASH_MISMATCH:'+code)
   s=strict(b)['chart']['result'][0];ticker=code+'.TW'
   if s['meta']['symbol']!=ticker:raise ValueError('TICKER_DRIFT')
   ts=s['timestamp'];qte=s['indicators']['quote'][0]['close'];adj=s['indicators']['adjclose'][0]['adjclose']
   if len(ts)!=len(qte) or len(ts)!=len(adj):raise ValueError('MISMATCH_AXIS')
   points=[];dates=[]
   for t,c,a in zip(ts,qte,adj):
    day=dt.datetime.fromtimestamp(t,TZ).date()
    if day>ASOF:raise ValueError('TARGET_DATE_LEAKAGE')
    if c is not None and a is not None and a>0:
     dates.append(day);points.append(float(a))
   if dates[-1]!=ASOF or len(points)!=d['history_records_usable']:raise ValueError('SOURCE_STALE_OR_COUNT_DRIFT:'+code)
   if abs(qte[-1]-d['official_close'])>max(.03,d['official_close']*.0003):raise ValueError('OFFICIAL_CLOSE_BRIDGE_FAIL')
   fc=forecast(points);rep=replay(points)
   rows.append({'code':code,'name':d['name'],'count':len(points),'start':dates[0].isoformat(),'cutoff':dates[-1].isoformat(),'provider_raw_sha':sha(b),'official_prior_close':d['official_close'],'source_cutoff_proved':True,'status':'SHORT_HISTORY_EMPIRICAL_SHADOW_NO_FORMAL','prospective_at_08_10':False,'original_h9':False,'formal_eligible':False,'natural_oos_credit':0,'forecasts':[{**{'date':DATES[i]},**r} for i,r in enumerate(fc)],'walkforward_retrospective':rep})
 out={'research_id':'STOCK-ETF-SHORT-20261013-SHADOW-v1','built_after_open':True,'market_data_cutoff':ASOF.isoformat(),'source_archive_sha':sha(source.read_bytes()),'method':'Fixed 20-observation log-return drift (shrink 0.25) + historical horizon empirical quantiles', 'method_promoted_production':False,'corporate_action_issuer_verified':False,'horizon_dates':DATES,'rows':rows,'warning':'Old price source as-of prior close permits after-open research; no 08:10 same-run forecast seal, not Formal/Natural/OOS, not investment buy advice.'}
 op=pathlib.Path(args.output);op.mkdir(parents=True,exist_ok=True)
 (op/'short_etf_research_d1d10.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 fmt=lambda x:f'{x:.4f}'
 ls=['# 短歷史 ETF（00400A、009820）2026-10-13 D1～D10 影子研究','',f'資料截止：{ASOF}；原始封存 ZIP SHA256 `{out["source_archive_sha"]}`。','**這是開盤後的研究，沒有 08:10 原始封存；不得寫入正式 Prediction、Natural、OOS，也不是下單建議。**','']
 for a in rows:
  ls += [f'## {a["code"]} {a["name"]}',f'來源股價觀測{a["count"]}筆，歷史 {a["start"]}～{a["cutoff"]}，官方前收{a["official_prior_close"]:.2f}。','|期限|到期日|研究 Point|P20|P50|P80|','|---|---|---:|---:|---:|---:|']
  ls += [f'|D{r["horizon"]}|{r["date"]}|{fmt(r["point"])}|{fmt(r["p20"])}|{fmt(r["p50"])}|{fmt(r["p80"])}|' for r in a['forecasts']]
  r=a['walkforward_retrospective'];ls += [f'回顧型 walk-forward：{r["origin_count"]}個起點、共{r["total_horizon_pairs"]}個到期配對。','|指標|影子模型MAPE|不變價MAPE|P20-P80涵蓋|','|---|---:|---:|---:|']
  for horizon in ('d1','d10'):
   v=r[horizon];ls.append(f'|{horizon.upper()}|{v["candidate_mape_pct"]:.3f}%|{v["nochange_mape_pct"]:.3f}%|{v["coverage"]*100:.1f}%|')
  ls.append('')
 ls += ['## 正式缺口與處理','- 運算使用可稽核的真實當期原始價格及固定歷史分位數；不以0補價，不借用2026/10/13已發生行情。','- 00400A於2026/10/08除息0.12元，需與TWSE TWT49U原始可核查事件對證，並對其他發行人公司行動完整性做證據標記。','- 009820 Yahoo 近期沒有股息事件不代表第一方必定沒有，不會自動核准為Formal。','- 需要正式 OOS walk-forward 訓練樣本和下一交易日事前完整封存，才能受控研究升格；不可用本次回顧評分冒充。']
 (op/'short_etf_research_d1d10.md').write_text('\n'.join(ls)+'\n',encoding='utf8')
 print(json.dumps([{'code':x['code'],'count':x['count'],'d1':x['forecasts'][0]['point'],'d10':x['forecasts'][-1]['point'],'wf':x['walkforward_retrospective']} for x in rows],ensure_ascii=False))
if __name__=='__main__':main()