#!/usr/bin/env python3
"""Read-only, fail-closed recovery of 3481's 2024-08-26 official TWSE TWTAUU row.
RESEARCH ONLY: does not write or qualify predictions, model, config, cash or OOS.
"""
import csv, datetime as dt, hashlib, html, io, json, pathlib, re, urllib.parse, urllib.request
from html.parser import HTMLParser

SYMBOL="3481"
DATE="2024-08-26"
ROC_DATE="113/08/26"
BASE="https://www.twse.com.tw"
ENDPOINTS=[
  "/exchangeReport/TWTAUU",
  "/rwd/zh/announcement/reduction/twtauu",
  "/rwd/zh/exRight/TWTAUU",
  "/rwd/zh/exchangeReport/TWTAUU",
]
PARAMS=[
  {"startDate":"20240826","endDate":"20240826","response":"html"},
  {"startDate":"20240826","endDate":"20240826","response":"json"},
  {"strDate":"20240826","endDate":"20240826","response":"html"},
  {"startDate":"1130826","endDate":"1130826","response":"json"},
]
class HTMLRows(HTMLParser):
 def __init__(self): super().__init__(); self.td=False;self.cur=[];self.buf=[];self.rows=[]
 def handle_starttag(self,t,a):
  if t=="tr":self.cur=[]
  if t in ("td","th"):self.td=True;self.buf=[]
 def handle_data(self,data):
  if self.td:self.buf.append(data)
 def handle_endtag(self,t):
  if t in ("td","th") and self.td:self.cur.append(re.sub(r"\s+"," ",html.unescape("".join(self.buf))).strip());self.td=False
  if t=="tr" and self.cur:self.rows.append(self.cur);self.cur=[]
def parse_record(raw,ctype):
 text=raw.decode("utf-8-sig")
 rows=[]
 try:
  obj=json.loads(text)
  if isinstance(obj,dict):
   for k in ("data","aaData","rows"):
    if isinstance(obj.get(k),list):
     rows+=obj[k]
 except (ValueError,UnicodeError):pass
 parser=HTMLRows();parser.feed(text)
 rows+=parser.rows
 try: rows+=list(csv.reader(io.StringIO(text)))
 except csv.Error:pass
 found=[]
 for row in rows:
  if not isinstance(row,list): continue
  cells=[re.sub(r"\s+"," ",str(x)).strip() for x in row]
  if SYMBOL not in cells: continue
  rtext=" ".join(cells)
  exact=bool(re.search(r"(?:113[年/\-]0?8[月/\-]26|2024[/\-]0?8[/\-]26|1130826|20240826)",rtext))
  if exact:found.append(cells)
 return found
def selftest():
 fixture="""<h2>113年08月26日 至 113年08月26日</h2><table><tr><td>113/08/26</td><td>3481</td><td>群創</td><td>14.55</td><td>15.17</td><td>15.15</td></tr></table>""".encode()
 assert len(parse_record(fixture,"text/html"))==1
 assert not parse_record(fixture.replace(b"113/08/26",b"113/08/27"),"text/html")
 assert not parse_record(fixture.replace(b"3481",b"3482"),"text/html")
 assert len(parse_record(json.dumps({"data":[["113/08/26","3481","群創","14.55","15.17","15.15"]]}).encode(),"application/json"))==1
 return {"tests":4,"passed":4,"scope":"RESEARCH_ONLY_EXACT_ROW"}
def main():
 import argparse
 p=argparse.ArgumentParser();p.add_argument("--out",required=True);a=p.parse_args()
 out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=False)
 checks=selftest(); results=[]; any_pass=False
 for ei,e in enumerate(ENDPOINTS):
  for pi,q in enumerate(PARAMS):
   url=BASE+e+"?"+urllib.parse.urlencode(q)
   entry={"endpoint":e,"params":q,"status":"HOLD","url":url,"exact_issuer_exhaustiveness":False,"formal":False}
   try:
    req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 public-research-exact-3481","Accept":"text/html,application/json"})
    with urllib.request.urlopen(req,timeout=15) as h:
     data=h.read(1500001);ctype=h.headers.get("Content-Type","");http=h.status;final=h.geturl()
    if len(data)>1500000 or http!=200 or urllib.parse.urlsplit(final).hostname not in {"www.twse.com.tw","wwwc.twse.com.tw"}:raise ValueError("HOST_OR_SIZE_OR_HTTP_MISMATCH")
    entry.update(http=http,content_type=ctype,sha256=hashlib.sha256(data).hexdigest(),byte_count=len(data),redirect=final)
    f="official_attempt_%02d_%02d.bin"%(ei,pi);(out/f).write_bytes(data);entry["file"]=f
    rows=parse_record(data,ctype)
    if rows:
     entry.update(status="PASS_FIRSTPARTY_EXACT_DATE_SYMBOL_ROW",row_count=len(rows),rows=rows[:5]);any_pass=True
    else:entry["status"]="HOLD_NO_EXACT_3481_20240826_ROW"
   except Exception as ex: entry.update(status="HOLD_REQUEST_OR_PARSE_ERROR",error_type=type(ex).__name__,error=str(ex)[:250])
   results.append(entry)
 report={"target_symbol":SYMBOL,"target_date":DATE,"qa":checks,"attempts":results,"exact_match_attempts":sum(x["status"].startswith("PASS") for x in results),"overall":"PASS_FIRSTPARTY_SCOPE_ONLY" if any_pass else "HOLD_OFFICIAL_ORIGINAL_NOT_OBTAINED","formal_score":0,"no_prediction_or_cash_writes":True}
 (out/"receipt.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
 print(json.dumps({"status":report["overall"],"attempts":len(results),"exact_matches":report["exact_match_attempts"],"failures":sum(x["status"].startswith("HOLD") for x in results),"qa":checks},ensure_ascii=False))
 for x in results: print(json.dumps({"path":x["endpoint"],"params":x["params"],"status":x["status"],"matched":x.get("rows",[])[:1],"error":x.get("error")},ensure_ascii=False))
if __name__=="__main__":main()
