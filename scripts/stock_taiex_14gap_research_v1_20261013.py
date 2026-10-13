#!/usr/bin/env python3
"""14 exact dates of TWSE historical TAIEX OHLC missing from archived H9.

First-party Sept and Oct original JSON, dual-SHA verification, RESEARCH ONLY.
No original H9 model/forecast or canonical Config/Prediction/Outcome writes.
"""
from __future__ import annotations
import argparse,datetime as dt,hashlib,http.client,json,math,pathlib,re,time,urllib.error,urllib.request
SEP_SET=('20260918','20260921','20260922','20260923','20260924','20260929','20260930')
OCT_SET=('20261001','20261002','20261005','20261006','20261007','20261008','20261012')
EXPECTED=SEP_SET+OCT_SET
assert len(EXPECTED)==14 and len(set(EXPECTED))==14
URL='https://www.twse.com.tw/indicesReport/MI_5MINS_HIST?date=20260930&response=json'

def digest(blob:bytes)->str:return hashlib.sha256(blob).hexdigest()
def check(condition:bool,reason:str):
    if not condition:raise ValueError(reason)
def gregory(v)->str:
    s=str(v).strip();m=re.fullmatch(r'(\d{2,4})/(\d{1,2})/(\d{1,2})',s)
    check(m is not None,'INVALID_ROC_DATE')
    year,month,day=map(int,m.groups())
    check(year<1911,'NOT_ROC_YEAR')
    return dt.date(year+1911,month,day).strftime('%Y%m%d')
def num(v):
    try:
        x=float(str(v).replace(',',''))
        return x if math.isfinite(x) and x>0 else None
    except (TypeError,ValueError):return None

def official_month(raw:bytes,month:str):
    x=json.loads(raw)
    check(isinstance(x,dict) and str(x.get('stat','')).lower()=='ok','NOT_OFFICIAL_OK')
    check(x.get('date')==month,'MONTH_DATE_CONFLICT')
    required=('日期','開盤指數','最高指數','最低指數','收盤指數')
    fs=x.get('fields')
    check(isinstance(fs,list) and all(fs.count(k)==1 for k in required),'OFFICIAL_REQUIRED_FIELDS')
    indexes=[fs.index(k) for k in required]
    out={}
    rows=x.get('data')
    check(isinstance(rows,list) and bool(rows),'EMPTY_OFFICIAL_DATA')
    for row in rows:
        check(isinstance(row,list) and len(row)>max(indexes),'BAD_INDEX_OHLC_ROW')
        date=gregory(row[indexes[0]])
        check(date.startswith(month[:6]) and date<=month,'INDEX_MONTH_OR_FUTURE_CONFLICT')
        check(date not in out,'INDEX_DUPLICATE_DAY')
        o,h,l,c=[num(row[i]) for i in indexes[1:]]
        check(all(v is not None for v in (o,h,l,c)),'OFFICIAL_MISSING_OHLC')
        check(l<=min(o,c)<=max(o,c)<=h,'INDEX_OHLC_IMPOSSIBLE')
        out[date]={'Open':o,'High':h,'Low':l,'Close':c,'Date':date}
    check(list(out)==sorted(out),'INDEX_NOT_CHRONOLOGICAL')
    return out

def merge(september:bytes,october:bytes):
    sep=official_month(september,'20260930')
    oct=official_month(october,'20261013')
    verified={**sep,**oct}
    missing=[x for x in EXPECTED if x not in verified]
    check(not missing,'MISSING_VERIFIED_MONTH_DAYS_'+','.join(missing))
    check(len(sep.keys() & oct.keys())==0,'DUPLICATE_MONTH_DATE')
    rows=[]
    for date in sorted(EXPECTED):
        x=verified[date].copy()
        x.update(Month='202609' if date in SEP_SET else '202610',
                 OfficialOriginalSHA256=digest(september if date in SEP_SET else october),
                 Qualification='RESEARCH_ONLY_UNSEALED')
        rows.append(x)
    check(len(rows)==14,'INDEX_MISSING_14')
    return {'Status':'RESEARCH_TAIEX_MISSING14_SOURCE_RESTORED',
            'FromOriginalH9Cutoff':'2026-09-17','SourceAsOf':'2026-10-13 official close',
            'TargetResearchDate':'2026-10-14',
            'OriginalSources':{'TWSE_SEP_20260930':{'SHA256':digest(september),'Bytes':len(september),'URL':URL},
                'TWSE_OCT_20261013':{'SHA256':digest(october),'Bytes':len(october)}},
            'Rows':rows,'Count':14,'BeforeOfficialIndexClose':46288.0,
            'FormalEligible':False,'NaturalCredit':0,'OOSCredit':0,
            'NoModelWeightsOrHistoryMutation':True,
            'Caution':'Index gaps are historical first-party input checks, not same-run formal model, not issuer-exhaustive or cash evidence.'}

def fetch_sep(out:pathlib.Path):
    failures=[]
    for attempt in (1,2):
        try:
            req=urllib.request.Request(URL,headers={'Accept':'application/json','User-Agent':'Mozilla/5.0 TaiwanStockResearchInputOnly'})
            with urllib.request.urlopen(req,timeout=20) as f:
                b=f.read(2000000)
            check(b and len(b)<2000000,'BAD_LENGTH')
            official_month(b,'20260930')
            out.write_bytes(b)
            return b
        except Exception as e:
            failures.append({'attempt':attempt,'error':str(e)[:190],'type':type(e).__name__})
            if attempt<2:time.sleep(1)
    out.with_name(out.name+'.failure.json').write_text(json.dumps({'Status':'HOLD_FIRSTPARTY_202609','Failures':failures},ensure_ascii=False,indent=2),encoding='utf8')
    raise ValueError('SEPT_FIRSTPARTY_ORIGINAL_UNAVAILABLE')

def to_markdown(x):
    t=['# 2026-10-14 原始 H9 大盤歷史 14 個缺日期的官方補證（研究）','',
       '來源為交易所九月／十月**兩個原始官方月報**，原始 SHA 各自保存；沒有修改正式 H9。','',
       '| 交易日 | 開盤 | 最高 | 最低 | 收盤 | 官方原件 SHA256 |',
       '|---|---:|---:|---:|---:|---|']
    for r in x['Rows']:
        t.append('| '+ ' | '.join([r['Date'],*(f'{r[k]:,.2f}' for k in ('Open','High','Low','Close')),r['OfficialOriginalSHA256']])+' |')
    t.extend(['','**資格：RESEARCH_ONLY，Formal/Natural/OOS=0**。正式模型還需要完整每檔調整價、issuer actions、same-run封存與Cash7；不可僅憑14個OHLC升格。'])
    return '\n'.join(t)+'\n'

def selftest():
    def payload(month,dates):
        return {'stat':'OK','date':month,'fields':['最低指數','收盤指數','日期','最高指數','開盤指數'],
                'data':[['100','103',f'{int(d[:4])-1911}/{int(d[4:6])}/{int(d[6:])}','107','102'] for d in dates]}
    def raw(x):return json.dumps(x).encode()
    a,b=payload('20260930',SEP_SET),payload('20261013',OCT_SET)
    results={}
    def test(name,cb,expect_error=False):
        try:
            out=cb()
            results[name]='FAIL_NOT_HELD' if expect_error else ('PASS' if out else 'FAIL')
        except (ValueError,TypeError,KeyError,IndexError):
            results[name]='PASS' if expect_error else 'FAIL_UNEXPECTED'
    base=merge(raw(a),raw(b))
    test('exact14',lambda:base['Count']==14)
    test('two_distinct_original_sha',lambda:base['OriginalSources']['TWSE_SEP_20260930']['SHA256']!=base['OriginalSources']['TWSE_OCT_20261013']['SHA256'])
    test('calendar_final_20261012',lambda:base['Rows'][-1]['Date']=='20261012')
    test('never_formal',lambda:not base['FormalEligible'] and base['NaturalCredit']==base['OOSCredit']==0)
    def modified(z,fn):v=json.loads(json.dumps(z));fn(v);return raw(v)
    test('reject_wrong_oct_label',lambda:merge(raw(a),modified(b,lambda z:z.update(date='20261014'))),True)
    test('reject_missing_sept_date',lambda:merge(modified(a,lambda z:z['data'].pop(0)),raw(b)),True)
    test('reject_duplicate_date',lambda:merge(modified(a,lambda z:z['data'].append(z['data'][0][:])),raw(b)),True)
    test('reject_impossible_high',lambda:merge(modified(a,lambda z:z['data'][0].__setitem__(3,'99')),raw(b)),True)
    test('reject_bad_official_stat',lambda:merge(modified(a,lambda z:z.update(stat='ERROR')),raw(b)),True)
    test('reject_missing_field',lambda:merge(modified(a,lambda z:z['fields'].__setitem__(0,'not_low')),raw(b)),True)
    test('reject_future_in_sept',lambda:merge(modified(a,lambda z:z['data'].append(['100','103','115/10/01','107','102'])),raw(b)),True)
    test('reject_negative_ohlc',lambda:merge(modified(a,lambda z:z['data'][0].__setitem__(0,'-100')),raw(b)),True)
    good=all(x=='PASS' for x in results.values())
    return {'status':'PASS' if good else 'FAIL','passed':sum(x=='PASS' for x in results.values()),'total':len(results),'tests':results,
            'scope':'SYNTHETIC_OFFICIAL_INDEX_NO_CASH_NO_FORMAL'}

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--self-test',action='store_true');p.add_argument('--sept-raw');p.add_argument('--oct-raw');p.add_argument('--out',default='taiex_gap14_20261013')
    z=p.parse_args()
    if z.self_test:
        o=selftest();print(json.dumps(o,ensure_ascii=False));return 0 if o['status']=='PASS' else 2
    check(bool(z.oct_raw and z.out),'NEED_OCT_OFFICIAL_SOURCE')
    out=pathlib.Path(z.out);out.mkdir(parents=True,exist_ok=True)
    sept=pathlib.Path(z.sept_raw).read_bytes() if z.sept_raw else fetch_sep(out/'twse_sep_20260930_original.json')
    octo=pathlib.Path(z.oct_raw).read_bytes()
    report=merge(sept,octo)
    (out/'taiex_14gap_source.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,allow_nan=False)+'\n',encoding='utf8')
    (out/'taiex_14gap_source.md').write_text(to_markdown(report),encoding='utf8')
    same=json.loads((out/'taiex_14gap_source.json').read_bytes())
    check(same['Count']==14 and len(same['Rows'])==14 and not same['FormalEligible'],'POST_WRITE_READBACK_FAILED')
    print(json.dumps({'Status':same['Status'],'Count':same['Count'],'SourceSHA':{k:v['SHA256'] for k,v in same['OriginalSources'].items()},'FormalEligible':False},ensure_ascii=False))
    return 0
if __name__=='__main__':raise SystemExit(main())
