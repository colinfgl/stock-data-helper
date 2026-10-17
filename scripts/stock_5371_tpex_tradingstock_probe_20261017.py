#!/usr/bin/env python3
"""Bounded exact date/symbol original TPEx tradingStock endpoint probe, research-only."""
import argparse, hashlib, json, pathlib, re, urllib.parse, urllib.request
BASE="https://www.tpex.org.tw"
SCRIPTS=["/rsrc/js/tables.js","/rsrc/asset/js/global.js","/rsrc/js/main.js"]
CASES=[
("ROC_month_with_response","/www/zh-tw/afterTrading/tradingStock",{"code":"5371","date":"115/08","response":"json"}),
("Greg_YYYYMM_with_response","/www/zh-tw/afterTrading/tradingStock",{"code":"5371","date":"202608","response":"json"}),
("ROC_month_no_response","/www/zh-tw/afterTrading/tradingStock",{"code":"5371","date":"115/08"}),
("Greg_YYYYMM_no_response","/www/zh-tw/afterTrading/tradingStock",{"code":"5371","date":"202608"}),
("Greg_slash_with_response","/www/zh-tw/afterTrading/tradingStock",{"code":"5371","date":"2026/08","response":"json"}),
("ROC_YYYYMM_no_response","/www/zh-tw/afterTrading/tradingStock",{"code":"5371","date":"11508","response":"json"}),
("ROC_fullmonth_date","/www/zh-tw/afterTrading/tradingStock",{"code":"5371","date":"1150801","response":"json"}),
("alternate_route","/www/zh-tw/mainboard/trading/info/tradingStock",{"code":"5371","date":"115/08","response":"json"})
]
def get(url):
 req=urllib.request.Request(url,headers={"User-Agent":"Mozilla/5.0 public-stock-history-restore","Accept":"application/json,text/html,application/javascript"})
 with urllib.request.urlopen(req,timeout=17) as r:
  raw=r.read(2500001);code=r.status;final=r.geturl();ctype=r.headers.get("Content-Type","")
 if code!=200 or not raw or len(raw)>=2500001 or urllib.parse.urlparse(final).hostname not in ("www.tpex.org.tw","tpex.org.tw"): raise ValueError("BAD_HTTP_HOST_SIZE")
 return raw,ctype,final
def walk(v,target,found,path="root"):
 if isinstance(v,dict):
  for k,item in v.items():walk(item,target,found,path+"."+str(k))
 elif isinstance(v,list):
  if len(v)>1 and any("5371" in str(z) for z in v[:4]):
   s=json.dumps(v,ensure_ascii=False)
   if "5371" in s and any(z in s for z in ("115/08/21","11508021","2026/08/21","20260821","83.50","83.5")):
    found.append((path,s[:500]))
  for i,z in enumerate(v[:1000]):
   if isinstance(z,(list,dict)):walk(z,target,found,path+"["+str(i)+"]")
def main():
 p=argparse.ArgumentParser();p.add_argument("--out",required=True);a=p.parse_args()
 out=pathlib.Path(a.out);out.mkdir(parents=True,exist_ok=False)
 scans=[]
 for n,loc in enumerate(SCRIPTS):
  try:
   raw,ctype,final=get(BASE+loc);txt=raw.decode("utf-8",errors="replace")
   entry={"url":final,"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),"content_type":ctype}
   (out/("script_"+str(n)+".js")).write_bytes(raw)
   for needle in ("API_PATTERN","response","tradingStock","ajax","pattern:","function.*init","getData","date:","form.serialize"):
    inds=[z.start() for z in re.finditer(re.escape(needle),txt,re.I)][:8]
    entry["hit_"+needle]=[txt[max(0,i-160):min(len(txt),i+280)] for i in inds]
   scans.append(entry)
  except Exception as e:scans.append({"path":loc,"status":"HOLD","error":str(e)[:200]})
 for s in scans:
  print("JS",json.dumps(s,ensure_ascii=False)[:5000],flush=True)
 entries=[]
 for i,(tag,path,q) in enumerate(CASES):
  url=BASE+path+"?"+urllib.parse.urlencode(q)
  record={"tag":tag,"url":url,"status":"HOLD"}
  try:
   raw,ctype,final=get(url);txt=raw.decode("utf-8-sig",errors="replace")
   record.update(sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw),content_type=ctype,final=final,text_head=txt[:110])
   (out/f"probe_{i:02d}.bin").write_bytes(raw)
   try:
    obj=json.loads(txt)
    record["keys"]=list(obj.keys())[:12] if isinstance(obj,dict) else []
    found=[];walk(obj,"5371",found)
    record["sample_found"]=found[:3]
    if found:record["status"]="CANDIDATE_MATCH_SOURCE_EXACT_MONTH_VERIFY_DATE_SCHEMA"
    else:record["status"]="HOLD_JSON_NO_EXACT_5371_MONTH_MATCH"
   except ValueError:record["status"]="HOLD_HTML_NOT_MONTHLY_JSON"
  except Exception as e:record.update(status="HOLD_HTTP_OR_SOURCE_ERROR",error_type=type(e).__name__,error=str(e)[:180])
  entries.append(record);print("PROBE",json.dumps(record,ensure_ascii=False)[:1400],flush=True)
 (out/"receipt.json").write_text(json.dumps({"scripts":scans,"attempts":entries,"formal":False},ensure_ascii=False,indent=2)+"\n")
 print("SUMMARY",json.dumps({"candidate":[x["tag"] for x in entries if x["status"].startswith("CANDIDATE")],"count":len(CASES),"nonpromotion":True},ensure_ascii=False))
if __name__=="__main__":main()
