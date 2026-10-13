#!/usr/bin/env python3
"""Archive and exactly verify 00400A ex-dividend from TWSE's own dated results table.

Research-only. Any changed date, missing code or ambiguous row fails closed. Never edits any
prediction/portfolio/cash or awards preopen-Natural qualification.
"""
from __future__ import annotations
import argparse,hashlib,html,json,pathlib,re,urllib.request,urllib.error,datetime as dt
from html.parser import HTMLParser
SRC='https://www.twse.com.tw/exchangeReport/TWT49U?date=20261008&response=html'
EXPECTED={'date':'115年10月08日','symbol':'00400A','before':'16.47','after':'16.35','dividend':'0.120000'}
class Table(HTMLParser):
 def __init__(self):super().__init__();self.inside=False;self.cell=False;self.text='';self.row=[];self.rows=[]
 def handle_starttag(self,t,attrs):
  if t=='tr':self.inside=True;self.row=[]
  if t in ('td','th') and self.inside:self.cell=True;self.text=''
 def handle_data(self,v):
  if self.cell:self.text+=v
 def handle_endtag(self,t):
  if t in ('td','th') and self.cell:self.row.append(re.sub(r'\s+',' ',html.unescape(self.text)).strip());self.cell=False
  if t=='tr' and self.inside:
   if self.row:self.rows.append(self.row)
   self.inside=False

def parse(raw):
 doc=raw.decode('utf-8-sig',errors='strict');parser=Table();parser.feed(doc)
 matches=[r for r in parser.rows if len(r)>=8 and '00400A' in r]
 if len(matches)!=1:raise ValueError('MISSING_OR_DUPLICATE_00400A_TWSE_ROW:'+str(len(matches)))
 row=matches[0];i=row.index('00400A')
 if i==0 or EXPECTED['date'] not in row[i-1]:raise ValueError('WRONG_ACTION_DATE')
 before=EXPECTED['before'] in row;after=EXPECTED['after'] in row; dividend=any(re.search(r'(?<!\d)0\.120+\b',cell) for cell in row)
 if not(before and after and dividend):raise ValueError('OFFICIAL_EXDIV_RATIO_MISMATCH:'+str(row))
 return {'symbol':'00400A','action_date':'2026-10-08','cash_dividend_per_unit':'0.120000','before_close':'16.47','reference_ex_close':'16.35','reference_ratio':'16.35/16.47','official_one_row_match':True,'table_row':row}
def selftest():
 sample='<table><tr><th>Date</th><th>Code</th><th>Pre</th><th>Ref</th><th>Dividend</th><th>Text</th><th>X</th><th>Y</th></tr><tr><td>115年10月08日</td><td>00400A</td><td>16.47</td><td>16.35</td><td>0.120000</td><td>A</td><td>B</td><td>C</td></tr></table>'.encode()
 assert parse(sample)['symbol']=='00400A'
 cases={'positive_parser':True,'no_duplicate':None,'no_wrong_date':None,'no_wrong_dividend':None,'no_wrong_before':None,'no_wrong_after':None}
 def fails(w):
  try:parse(w)
  except ValueError:return True
  return False
 cases['no_duplicate']=fails(sample.replace(b'</table>',b'<tr><td>115\xe5\xb9\xb410\xe6\x9c\x8808\xe6\x97\xa5</td><td>00400A</td><td>16.47</td><td>16.35</td><td>0.120000</td><td>A</td><td>B</td><td>C</td></tr></table>'))
 cases['no_wrong_date']=fails(sample.replace('115年10月08日'.encode(),'115年10月09日'.encode()))
 cases['no_wrong_dividend']=fails(sample.replace(b'0.120000',b'0.020000'))
 cases['no_wrong_before']=fails(sample.replace(b'16.47',b'16.99'))
 cases['no_wrong_after']=fails(sample.replace(b'16.35',b'16.99'))
 assert all(cases.values()),cases
 print(json.dumps({'status':'PASS','tests':cases,'passed':len(cases)}));return True
def main():
 a=argparse.ArgumentParser();a.add_argument('--self-test',action='store_true');a.add_argument('--output');args=a.parse_args()
 if args.self_test:selftest();return
 if not args.output:a.error('--output needed')
 p=pathlib.Path(args.output);p.mkdir(parents=True,exist_ok=True)
 request=urllib.request.Request(SRC,headers={'User-Agent':'Mozilla/5.0 source-evidence/1.0','Accept':'text/html'})
 report={'url':SRC,'retrieved_at':dt.datetime.now(dt.timezone.utc).isoformat(),'scope':'POST_CUTOFF_RESEARCH_ONLY','no_natural_credit':True,'status':'HOLD'}
 try:
  with urllib.request.urlopen(request,timeout=20) as resp:
   body=resp.read(2000001);code=resp.status;final=resp.geturl()
  if len(body)>2000000:raise ValueError('BLOB_TOO_LARGE')
  if not final.startswith('https://www.twse.com.tw/'):raise ValueError('HOST_DRIFT')
  if code!=200:raise ValueError('HTTP_NOT_200')
  raw=p/'twse_00400A_20261008.html';raw.write_bytes(body)
  report.update({'source_sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body),'http_status':code,'parse':parse(body),'status':'PASS_OFFICIAL_EXDATE_ROW_RESEARCH'})
 except Exception as e:report.update({'status':'HOLD_SOURCE_OR_PARSER','failure_type':type(e).__name__,'failure':str(e)[:240]})
 (p/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
 print(json.dumps(report,ensure_ascii=False)[:3000])
if __name__=='__main__':main()