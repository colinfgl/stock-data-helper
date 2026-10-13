#!/usr/bin/env python3
"""Research-only immutable two-source OHLC/history bridge after Yahoo vendor retroactive NULL.

For 10/14 research as-of 10/13 post close only. NEVER qualifies one-raw H9 source,
complete corporate actions, formal ForecastSHA, Natural, OOS, cash or orders.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, pathlib, re
from zoneinfo import ZoneInfo
TZ=ZoneInfo('Asia/Taipei')
PRIOR_DATE='20261012'
CURRENT_DATE='20261013'
TARGET_DATE='20261014'
CUTOFF=dt.datetime(2026,10,14,8,9,30,tzinfo=TZ)

def guard(ok,message):
    if not ok: raise ValueError(message)
def h(b): return hashlib.sha256(b).hexdigest()
def acceptable(a,b):return abs(a-b)<=max(.011,abs(b)*.00002)
def good(x):return type(x) in (int,float) and math.isfinite(x) and x>0
def read_stamped_receipt(folder):
    p=pathlib.Path(folder)/'acquisition_receipt.json'
    r=json.loads(p.read_bytes())
    guard(isinstance(r,dict) and isinstance(r.get('sources'),list),'RECEIPT_SCHEMA')
    table={}
    for x in r['sources']:
        name=x.get('path')
        if name:
            guard(name not in table,'DUPLICATE_SOURCE_RECEIPT')
            table[name]=x
    return r,table

def srcfile(folder,name,entries):
    guard(bool(re.fullmatch(r'[A-Za-z0-9_.-]+',name)),'UNSAFE_SOURCE_NAME')
    p=pathlib.Path(folder)/name
    raw=p.read_bytes()
    record=entries.get(name)
    guard(record and record['status']=='FETCHED','ORIGINAL_SOURCE_RECEIPT_ABSENT_'+name)
    guard(record['sha256']==h(raw),'SOURCE_RAW_SHA_CONFLICT_'+name)
    date=dt.datetime.fromisoformat(record['retrieved_at'])
    guard(date.tzinfo is not None,'SOURCE_ORIGINAL_NO_TIMEZONE')
    guard(date.astimezone(TZ)<=CUTOFF,'SOURCE_EXCEEDS_NEXT_PREOPEN_CUTOFF')
    return raw,record

def chart(raw:bytes,symbol:str):
    z=json.loads(raw,parse_constant=lambda c:(_ for _ in ()).throw(ValueError('NONFINITE_JSON_'+c)))
    guard('provenance' not in z,'UNTRUSTED_REPACKAGED_VENDOR_CHART')
    c=z.get('chart');guard(isinstance(c,dict) and c.get('error') is None,'CHART_PROVIDER_ERROR')
    a=c.get('result');guard(isinstance(a,list) and len(a)==1,'MULTIPLE_OR_EMPTY_CHART')
    v=a[0];guard(v.get('meta',{}).get('symbol')==symbol,'CHART_SYMBOL_IDENTITY_CONFLICT')
    ts=v.get('timestamp');guard(isinstance(ts,list) and len(ts)>=10,'TOO_SHORT_CHART')
    try:
        q=v['indicators']['quote'][0]['close'];adj=v['indicators']['adjclose'][0]['adjclose']
    except (KeyError,TypeError,IndexError) as e:raise ValueError('NO_ORIGINAL_ADJUSTED_CLOSE') from e
    guard(isinstance(q,list) and isinstance(adj,list) and len(ts)==len(q)==len(adj),'CHART_AXIS_CONFLICT')
    out={}
    for timestamp,close,adjusted in zip(ts,q,adj):
        guard(type(timestamp) in (int,float),'UNREADABLE_TIMESTAMP')
        d=dt.datetime.fromtimestamp(timestamp,TZ).strftime('%Y%m%d')
        guard(d not in out,'DUPLICATE_VENDOR_SESSION_'+d)
        out[d]={'close':close,'adj':adjusted,'timestamp':timestamp}
    return out

def official_prices(raw,venue,day):
    body=json.loads(raw,parse_constant=lambda c:(_ for _ in ()).throw(ValueError('OFFICIAL_NONFINITE_JSON_'+c)))
    guard(isinstance(body,dict) and body.get('date')==day and str(body.get('stat','')).lower()=='ok',
          'OFFICIAL_EXACT_DAY_STATUS_FAIL_'+venue)
    codekey,namekey,closekey=(('證券代號','證券名稱','收盤價') if venue=='TWSE' else ('代號','名稱','收盤'))
    found={}
    for table in body.get('tables',[]):
        fields=table.get('fields') or []
        if codekey not in fields:continue
        guard(all(fields.count(k)==1 for k in [codekey,namekey,closekey]),'OFFICIAL_FIELDS_CONFLICT')
        ci,ni,pi=(fields.index(k) for k in [codekey,namekey,closekey])
        for row in table.get('data',[]):
            guard(len(row)>max(ci,ni,pi),'OFFICIAL_ROW_TRUNCATED')
            code=str(row[ci]).strip();name=str(row[ni]).strip()
            guard(code and name and code not in found,'OFFICIAL_IDENTITY_DUPLICATED')
            try:price=float(str(row[pi]).replace(',',''))
            except (ValueError,TypeError):price=None
            found[code]={'name':name,'close':price}
    guard(bool(found),'OFFICIAL_TRADING_TABLE_NOT_FOUND')
    return found

def verify_symbol(raw_old,raw_new,code_symbol:str,old_close:float,new_close:float):
    old=chart(raw_old,code_symbol);now=chart(raw_new,code_symbol)
    require_old=old.get(PRIOR_DATE);require_new=now.get(CURRENT_DATE)
    guard(require_old and all(good(require_old[x]) for x in ('close','adj')),
          'ARCHIVED_PREV_DAY_NULL_OR_MISSING')
    guard(require_new and all(good(require_new[x]) for x in ('close','adj')),
          'CURRENT_NEW_DAY_NULL_OR_MISSING')
    guard(acceptable(require_old['close'],old_close),'ARCHIVE_PREV_OFFICIAL_CLOSE_MISMATCH')
    guard(acceptable(require_new['close'],new_close),'CURRENT_NEW_OFFICIAL_CLOSE_MISMATCH')
    common=sorted(set(old)&set(now))
    shared=0;changed=[];missing_before=0
    for d in common:
        aa=old[d];bb=now[d]
        if not all(good(z) for z in [aa['close'],aa['adj'],bb['close'],bb['adj']]):
            missing_before+=1
            continue
        shared+=1
        if not acceptable(aa['close'],bb['close']) or not acceptable(aa['adj'],bb['adj']):
            changed.append(d)
    guard(shared>=5,'TOO_FEW_OVERLAP_DAYS')
    guard(not changed,'HISTORICAL_ADJUSTMENT_BASIS_CHANGED')
    incoming12=now.get(PRIOR_DATE)
    direct_prev=bool(incoming12 and all(good(incoming12[k]) for k in ('close','adj')))
    if direct_prev:
        guard(acceptable(incoming12['close'],old_close) and
              acceptable(incoming12['adj'],require_old['adj']),'SAME_DAY_VENDOR_CONFLICT')
    return {'SourceRole':'RESEARCH_DUAL_ORIGINAL_RAW_NO_CANONICAL_H9',
            'OldOriginalPreClose':require_old['close'],'OldOriginalPreAdjustedClose':require_old['adj'],
            'NewOriginalCurrentClose':require_new['close'],'NewOriginalCurrentAdjustedClose':require_new['adj'],
            'OldBarTimestamp':require_old['timestamp'],'NewBarTimestamp':require_new['timestamp'],
            'VendorCurrentFileHasPreviousSession':direct_prev,
            'ArchivedRawRequiredForPreviousSession':not direct_prev,
            'OverlappingValidOriginalDays':shared,
            'HistoricalPriceMismatchCount':len(changed),
            'ProviderMissingOverlapCount':missing_before,
            'DayReturnPercent':round(100*(require_new['close']/require_old['close']-1),4),
            'FormalEligible':False,'NaturalCredit':0,'OOSCredit':0,
            'CanonicalPredictionWritten':False,
            'Prohibition':'Source is two separately authenticated original Yahoo charts; not a single raw source, issuer exhaustive, calibration, or pre-open sealed ForecastSHA.'}

def run(oldroot,newroot,outdir):
    oldroot=pathlib.Path(oldroot);newroot=pathlib.Path(newroot);outdir=pathlib.Path(outdir)
    oldmeta,oldentry=read_stamped_receipt(oldroot);newmeta,newentry=read_stamped_receipt(newroot)
    guard(oldmeta.get('dates',{}).get('target_date')=='2026-10-13' and
          oldmeta['dates'].get('price_cutoff')==PRIOR_DATE,'OLD_RESEARCH_TARGET_MISMATCH')
    guard(newmeta.get('dates',{}).get('target_date')=='2026-10-14' and
          newmeta['dates'].get('price_cutoff')==CURRENT_DATE and
          newmeta['dates'].get('previous_session')==PRIOR_DATE,'NEW_RESEARCH_TARGET_MISMATCH')
    official={};original_refs={}
    for market in ('TWSE','TPEX'):
        for d in (PRIOR_DATE,CURRENT_DATE):
            name=f'{market}_{d}.json'
            raw,rec=srcfile(newroot,name,newentry)
            official[market,d]=official_prices(raw,market,d)
            original_refs[name]=rec['sha256']
    oldsymbols=sorted(n[len('chart_'):-len('.json')] for n in oldentry if n.startswith('chart_') and n.endswith('.json'))
    newsymbols=sorted(n[len('chart_'):-len('.json')] for n in newentry if n.startswith('chart_') and n.endswith('.json'))
    guard(len(oldsymbols)==len(newsymbols)==68 and oldsymbols==newsymbols,'ORIGINAL_SOURCE_SYMBOL_UNIVERSE_NOT_68')
    records=[]
    for symbol in oldsymbols:
        code,ext=symbol.rsplit('.',1)
        venue='TPEX' if ext=='TWO' else 'TWSE' if ext=='TW' else None
        guard(venue is not None,'SYMBOL_SUFFIX_WRONG')
        before=official[venue,PRIOR_DATE].get(code)
        after=official[venue,CURRENT_DATE].get(code)
        row={'Symbol':code,'VendorSymbol':symbol,'Venue':venue,'OfficialName':before.get('name') if before else (after.get('name') if after else ''),
             'DayBefore':PRIOR_DATE,'DayAfter':CURRENT_DATE,'RecoveryStatus':'SOURCE_HOLD','FormalEligible':False}
        try:
            guard(before and after,'TWO_DAY_OFFICIAL_ROW_MISSING')
            guard(before['name']==after['name'],'OFFICIAL_COMPANY_NAME_CHANGED_HOLD')
            guard(good(before['close']) and good(after['close']),'OFFICIAL_CLOSE_NONPOSITIVE_OR_MISSING')
            name='chart_'+symbol+'.json'
            older,ra=srcfile(oldroot,name,oldentry)
            newer,rb=srcfile(newroot,name,newentry)
            detail=verify_symbol(older,newer,symbol,before['close'],after['close'])
            row.update(detail)
            row.update(OfficialPreviousClose=before['close'],OfficialCurrentClose=after['close'],
                       OldSourceOriginalSHA256=h(older),NewSourceOriginalSHA256=h(newer),
                       OldSourceCapturedAtUTC=ra['retrieved_at'],NewSourceCapturedAtUTC=rb['retrieved_at'],
                       RecoveryStatus='TWO_ORIGINALS_RESEARCH_MATCH')
        except Exception as exc:
            row['MissingReason']=str(exc)[:250]
        records.append(row)
    passed=sum(x['RecoveryStatus']=='TWO_ORIGINALS_RESEARCH_MATCH' for x in records)
    bridges=sum(x.get('ArchivedRawRequiredForPreviousSession',False) for x in records)
    report={'ResearchAsOf':'2026-10-13 postclose, before 2026-10-14 08:09:30 Asia/Taipei',
            'PreviousSession':PRIOR_DATE,'CurrentSession':CURRENT_DATE,'TargetSession':TARGET_DATE,
            'Status':'RESEARCH_TWO_PARENT_68_COMPLETE_NOT_FORMAL' if passed==68 else 'RESEARCH_TWO_PARENT_PARTIAL_HOLD',
            'EligibleResearchRows':passed,'ResearchHolds':68-passed,'OriginalSourceUniverse':len(records),
            'ArchivedPriorSessionRecovered':bridges,'CurrentProviderDirectPriorSession':sum(r.get('VendorCurrentFileHasPreviousSession',False) for r in records),
            'OfficialOriginalRawSHA256':original_refs,'PriorOriginalAcquisitionStartedAtUTC':oldmeta['started_at'],
            'CurrentOriginalAcquisitionStartedAtUTC':newmeta['started_at'],
            'FormalEligible':False,'NaturalCredit':0,'OOSCredit':0,'OldHistoricalPredictionsMutated':False,
            'CanonicalPredictionWritten':False,'CashTradingAuthorized':False,
            'Scope':'Research provenance reconciliation ONLY, not a replacement for one coherent native provider adjusted close input or formal issuer all-actions verification',
            'Rows':records}
    outdir.mkdir(parents=True,exist_ok=True)
    (outdir/'dual_original_research_68.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    lines=['# 2026-10-13｜68檔Yahoo回溯缺價：兩份原始資料逐檔研究銜接','',
           f'研究有效 {passed}/68，需舊原件補前一交易日 {bridges}/68，新原件自帶前一日 {68-bridges} 檔。',
           '保留兩份Yahoo完整原始SHA以及當日和前日TWSE/TPEx官方父SHA。只供研究；正式H9原始來源及Issuer Gate仍未放行。','',
           '|代號|中文全名|10/12官方前收|10/13官方實收|漲跌%|10/12舊原件補齊?|兩份歷史重疊價|結果|',
           '|---|---|---:|---:|---:|---|---:|---|']
    for row in records:
        fmt=lambda k:f"{row[k]:,.2f}" if good(row.get(k)) else 'MISSING'
        lines.append('| '+ ' | '.join([row['Symbol'],row.get('OfficialName') or 'MISSING',fmt('OfficialPreviousClose'),fmt('OfficialCurrentClose'),
          f"{row.get('DayReturnPercent',0):+.2f}%" if row['RecoveryStatus'].startswith('TWO_') else 'MISSING',
          '是' if row.get('ArchivedRawRequiredForPreviousSession') else '否',str(row.get('OverlappingValidOriginalDays','—')),
          row['RecoveryStatus'] if row['RecoveryStatus'].startswith('TWO_') else f"HOLD: {row.get('MissingReason')}"])+' |')
    lines+=['','**資料治理：**舊原件取得時間早於10/13盤前；新原件於10/13盤後取得，僅能用於10/14及之後的研究輸入，不能回填成10/13盤前預測。',
            '**正式資格：** Formal=false、Natural=0、OOS=0、Cash交易=0；嚴禁將兩個原件的研究組合冒充單份未修改的Yahoo原始檔。']
    (outdir/'dual_original_research_68.md').write_text('\n'.join(lines)+'\n',encoding='utf8')
    reread=json.loads((outdir/'dual_original_research_68.json').read_bytes())
    guard(reread['EligibleResearchRows']==passed and reread['OriginalSourceUniverse']==68,
          'RESEARCH_RECEIPT_READBACK_FAILED')
    print(json.dumps({k:v for k,v in report.items() if k in ('Status','EligibleResearchRows','ResearchHolds','ArchivedPriorSessionRecovered','CurrentProviderDirectPriorSession','OriginalSourceUniverse','FormalEligible')},ensure_ascii=False))
    return 0 if passed==68 else 2

def selftest():
    # Unit tests work only with in-memory official-validated source; no external dependency.
    checks={}
    def check(name,fn,reject=False):
        try:
            result=fn();checks[name]='FAIL_NOT_HELD' if reject else ('PASS' if result else 'FAIL')
        except (ValueError,TypeError,KeyError,IndexError):checks[name]='PASS' if reject else 'FAIL_UNEXPECTED'
    tz=TZ
    def fake(symbol='TEST.TW',missing_new_prior=True,old_prior_close=100,now_last_close=95,old_shared=105,new_shared=105):
        times=[dt.datetime(2026,9,20+i,9,tzinfo=tz).timestamp() for i in range(9)] + [dt.datetime(2026,10,8,9,tzinfo=tz).timestamp(),dt.datetime(2026,10,12,9,tzinfo=tz).timestamp(),dt.datetime(2026,10,13,9,tzinfo=tz).timestamp()]
        def payload(close):
            return json.dumps({'chart':{'error':None,'result':[{'meta':{'symbol':symbol},'timestamp':times,
                 'indicators':{'quote':[{'close':close}],'adjclose':[{'adjclose':close}]}}]}},separators=(',',':')).encode('utf8')
        old=payload([old_shared]*10+[old_prior_close,None]);new=payload([new_shared]*10+[None if missing_new_prior else old_prior_close,now_last_close]);return old,new
    a,b=fake()
    check('two_originals_legitimate_recovery',lambda:verify_symbol(a,b,'TEST.TW',100,95)['ArchivedRawRequiredForPreviousSession'])
    check('dual_symbol_no_formal_credit',lambda:verify_symbol(a,b,'TEST.TW',100,95)['FormalEligible'] is False)
    a,b=fake(missing_new_prior=False)
    check('current_provider_direct_valid_stays_direct',lambda:verify_symbol(a,b,'TEST.TW',100,95)['VendorCurrentFileHasPreviousSession'])
    a,b=fake(old_shared=105,new_shared=108)
    check('hold_changed_overlap',lambda:verify_symbol(a,b,'TEST.TW',100,95),True)
    a,b=fake(old_prior_close=120)
    check('hold_old_official_conflict',lambda:verify_symbol(a,b,'TEST.TW',100,95),True)
    a,b=fake(now_last_close=96)
    check('hold_new_official_conflict',lambda:verify_symbol(a,b,'TEST.TW',100,95),True)
    a,b=fake();obj=json.loads(a);obj['chart']['result'][0]['meta']['symbol']='WRONG.TW'
    check('hold_vendor_identity_conflict',lambda:verify_symbol(json.dumps(obj).encode(),b,'TEST.TW',100,95),True)
    a,b=fake();obj=json.loads(a);obj['chart']['result'][0]['timestamp'][1]=obj['chart']['result'][0]['timestamp'][0]
    check('hold_duplicate_provider_timestamp',lambda:verify_symbol(json.dumps(obj).encode(),b,'TEST.TW',100,95),True)
    a,b=fake();obj=json.loads(b);obj['chart']['result'][0]['indicators'].pop('adjclose')
    check('hold_no_adjusted_vendor_series',lambda:verify_symbol(a,json.dumps(obj).encode(),'TEST.TW',100,95),True)
    a,b=fake();obj=json.loads(b);obj['provenance']={'falsified':True}
    check('hold_repackaged_provider_chart',lambda:verify_symbol(a,json.dumps(obj).encode(),'TEST.TW',100,95),True)
    status='PASS' if all(v=='PASS' for v in checks.values()) else 'FAIL'
    result={'status':status,'total':len(checks),'passed':sum(v=='PASS' for v in checks.values()),'scope':'PURE_SYNTHETIC_TWO_RAW_SOURCES_NO_FORMAL','tests':checks}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if status=='PASS' else 2

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--self-test',action='store_true');ap.add_argument('--prior-dir');ap.add_argument('--current-dir');ap.add_argument('--out');a=ap.parse_args()
    if a.self_test:return selftest()
    if not all((a.prior_dir,a.current_dir,a.out)):ap.error('--prior-dir --current-dir --out required')
    return run(a.prior_dir,a.current_dir,a.out)
if __name__=='__main__':raise SystemExit(main())
