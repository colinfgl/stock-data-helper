import csv,json
from pathlib import Path
import requests
OUT=Path('output_core20_industry'); OUT.mkdir(exist_ok=True)
TARGETS={'0050','00400A','009820','2207','2308','2317','2330','2368','2376','2382','2383','2454','2634','2834','2885','3293','3491','3665','4916','6770'}
r=requests.get('https://api.finmindtrade.com/api/v4/data',params={'dataset':'TaiwanStockInfo'},timeout=60); r.raise_for_status(); j=r.json()
rows=[x for x in j.get('data',[]) if str(x.get('stock_id','')) in TARGETS]
fields=['date','stock_id','stock_name','industry_category','type']
with (OUT/'core20_industry_map.csv').open('w',encoding='utf-8-sig',newline='') as f:
 w=csv.DictWriter(f,fieldnames=fields,extrasaction='ignore');w.writeheader();w.writerows(rows)
rep={'rows':len(rows),'codes':sorted(str(x.get('stock_id')) for x in rows),'all_pass':len(rows)==20}
(OUT/'report.json').write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(rep,ensure_ascii=False))
if not rep['all_pass']: raise SystemExit(2)
