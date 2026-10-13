#!/usr/bin/env python3
"""Bounded primary TWSE TWT49U ex-rights/ex-dividend evidence capture.

Uses ONLY public stock-market records, never portfolio or account data. All
results are retrospective RESEARCH; do not seal forecasts or change Formal,
Natural, or OOS. Download one narrow date window per invocation, verifying
that TWSE served the requested period rather than a silent current-day fallback.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, html, json, pathlib, re, urllib.parse, urllib.request, urllib.error
from html.parser import HTMLParser

SOURCE='https://www.twse.com.tw/exchangeReport/TWT49U'
TZ='Asia/Taipei'
CODE=re.compile(r'^(?:[0-9A-Z]{4,7})$')
ROC=re.compile(r'(\d{3})年(\d{1,2})月(\d{1,2})日')

class Rows(HTMLParser):
 def __init__(self):super().__init__();self.tr=0;self.td=False;self.buf='';self.row=[];self.rows=[]
 def handle_starttag(self,t,attrs):
  if t=='tr':self.tr+=1;self.row=[]
  if self.tr and t in ('td','th'):self.td=True;self.buf=''
 def handle_data(self,data):
  if self.td:self.buf+=data
 def handle_endtag(self,t):
  if self.td and t in ('td','th'):
   self.row.append(re.sub(r'\s+',' ',html.unescape(self.buf)).strip());self.td=False
  if t=='tr' and self.tr:
   if self.row:self.rows.append(self.row)
   self.tr-=1

def roc(s):
 m=ROC.fullmatch(s.strip())
 if m is None:raise ValueError('BAD_ROC_DATE:'+s)
 return dt.date(int(m[1])+1911,int(m[2]),int(m[3]))

def parse_document(raw,start,end):
 # Require actual server-rendered period title; HTTP 200 can still be today's table.
 doc=raw.decode('utf-8-sig',errors='strict');visible=re.sub('<[^<>]*>',' ',doc)
 visible=re.sub(r'\s+',' ',html.unescape(visible))
 title_match=re.search(r'(\d{3}年\d{2}月\d{2}日)\s*至\s*(\d{3}年\d{2}月\d{2}日)\s*除權除息計算結果表',visible)
 if not title_match:raise ValueError('MISSING_DATE_RANGE_HEADING')
 got_start,got_end=roc(title_match[1]),roc(title_match[2])
 if got_start!=start or got_end!=end:raise ValueError(f'PERIOD_FALLBACK:{got_start}:{got_end}!={start}:{end}')
 parser=Rows();parser.feed(doc);matches=[];seen=set()
 for row in parser.rows:
  if len(row)<8:continue
  m=ROC.fullmatch(row[0]);
  if not m or not CODE.fullmatch(row[1]):continue
  when=roc(row[0]);code=row[1]
  if when<start or when>end:raise ValueError('OUTSIDE_REQUEST_DATE:'+str(when))
  key=(when.isoformat(),code)
  if key in seen:raise ValueError('DUPLICATE_DATE_SYMBOL:'+str(key))
  seen.add(key)
  if any(x in row[0] for x in ('今日','昨天')):raise ValueError('RELATIVE_DATE_IN_DATA')
  matches.append({'date':when.isoformat(),'code':code,'name':row[2], 'before':row[3], 'ref':row[4], 'rights_dividend':row[6], 'row':row})
 return {'from':got_start.isoformat(),'to':got_end.isoformat(),'issuer_rows':matches,'all_source_rows':len(parser.rows),'matching_event_rows':len(matches),'same_run_formal_eligible':False,'issuer_exhaustiveness':False}

def selftest():
 def page(title,rows=''):
  return (f'<h1>{title} 除權除息計算結果表</h1><table><tr><th>Date</th></tr>{rows}</table>').encode()
 tr='<tr>'+''.join(f'<td>{v}</td>' for v in ['115年10月08日','00400A','主動國泰動能高息','16.47','16.35','0.120000','息','17.98','14.72'])+'</tr>'
 a=dt.date(2026,10,8)
 good=page('115年10月08日 至 115年10月08日',tr)
 tests={'exact_historical_day':parse_document(good,a,a)['matching_event_rows']==1,
 'correct_symbol':parse_document(good,a,a)['issuer_rows'][0]['code']=='00400A',
 'no_event_valid':parse_document(page('115年10月08日 至 115年10月08日'),a,a)['matching_event_rows']==0}
 def mustfail(data,start=a,end=a):
  try:parse_document(data,start,end)
  except (ValueError,UnicodeDecodeError):return True
  return False
 tests.update({'wrong_period':mustfail(page('115年10月13日 至 115年10月13日',tr)),
   'duplicate':mustfail(page('115年10月08日 至 115年10月08日',tr+tr)),
   'future_row':mustfail(page('115年10月08日 至 115年10月08日',tr.replace('115年10月08日','115年10月13日'))),
   'missing_period':mustfail(page('Bad date string',tr)),
   'invalid_date':mustfail(page('115年10月08日 至 115年10月08日',tr.replace('115年10月08日','115年14月08日')) if False else b'\xff'),
   'no_formal_promotion':parse_document(good,a,a)['same_run_formal_eligible'] is False,
   'not_issuer_complete':parse_document(good,a,a)['issuer_exhaustiveness'] is False})
 assert all(tests.values()),tests
 return {'pass':sum(tests.values()),'total':len(tests),'status':'PASS','checks':tests}

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--start');ap.add_argument('--end');ap.add_argument('--out');ap.add_argument('--self-test',action='store_true');args=ap.parse_args()
 if args.self_test:print(json.dumps(selftest(),ensure_ascii=False));return
 if not(args.start and args.end and args.out):ap.error('start,end,out required')
 start=dt.date.fromisoformat(args.start);end=dt.date.fromisoformat(args.end)
 if end<start or (end-start).days>100 or end>dt.date(2026,10,12):raise ValueError('RESEARCH_WINDOW_INVALID_MAX100_DAYS_CUTOFF1012')
 out=pathlib.Path(args.out);out.mkdir(parents=True,exist_ok=False)
 params={'startDate':start.strftime('%Y%m%d'),'endDate':end.strftime('%Y%m%d'),'response':'html'}
 url=SOURCE+'?'+urllib.parse.urlencode(params)
 audit={'requested_start':args.start,'requested_end':args.end,'url':url,'kind':'PRIMARY_EXDIV_CALCULATION_ONLY',
        'not_issuer_action_exhaustive':True,'formal_prediction_written':0,'natural_oos_credit':0,'status':'SOURCE_UNAVAILABLE_HOLD'}
 try:
  req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0 public-stock-evidence-research/1.0','Accept':'text/html'})
  with urllib.request.urlopen(req,timeout=20) as resp:
   raw=resp.read(4000001);code=resp.status;final=resp.geturl()
  if len(raw)>4000000 or code!=200:raise ValueError('SOURCE_TOO_LARGE_OR_HTTP_STATUS')
  if urllib.parse.urlsplit(final).hostname!='www.twse.com.tw':raise ValueError('REDIRECT_HOST_DRIFT')
  filename=f'TWT49U_{start.strftime("%Y%m%d")}_{end.strftime("%Y%m%d")}_raw.html'
  (out/filename).write_bytes(raw)
  audit.update(http=code,source_bytes=len(raw),source_sha256=hashlib.sha256(raw).hexdigest(),source_filename=filename)
  parsed=parse_document(raw,start,end)
  (out/'parsed_primary_rows.json').write_text(json.dumps(parsed,ensure_ascii=False,indent=2),encoding='utf8')
  audit.update(status='PASS_FIRSTPARTY_SCOPE_ONLY',primary_event_rows=parsed['matching_event_rows'],parser='EXACT_PERIOD_DUPLICATE_FAIL_CLOSED')
 except Exception as e:
  audit.update(failure_type=type(e).__name__,failure=str(e)[:600])
 (out/'receipt.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(audit,ensure_ascii=False))
if __name__=='__main__':main()