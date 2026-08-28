import json, requests
from datetime import date
S=requests.Session(); S.headers.update({'User-Agent':'Mozilla/5.0','Referer':'https://www.twse.com.tw/'})
urls=[
('twse_legacy_month','https://www.twse.com.tw/exchangeReport/TWT49U?response=json&strDate=20260801&endDate=20260817'),
('twse_rwd_month','https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20260801&endDate=20260817&response=json'),
('twse_legacy_known','https://www.twse.com.tw/exchangeReport/TWT49U?response=json&strDate=20260803&endDate=20260803'),
('tpex_old_month','https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?l=zh-tw&d=115/08/01&ed=115/08/17'),
('tpex_www_month','https://www.tpex.org.tw/www/zh-tw/announce/market/ex/cal?startDate=115/08/01&endDate=115/08/17'),
('tpex_www_greg','https://www.tpex.org.tw/www/zh-tw/announce/market/ex/cal?startDate=2026/08/01&endDate=2026/08/17'),
('tpex_api_date','https://www.tpex.org.tw/www/zh-tw/announce/market/ex/cal?date=115/08/01'),
]
for name,u in urls:
    print('\n###',name,u)
    try:
        r=S.get(u,timeout=30)
        print('status',r.status_code,'ct',r.headers.get('content-type'),'len',len(r.content))
        print(r.text[:2000].replace('\n',' '))
        try:
            j=r.json(); print('JSON_KEYS',list(j)[:20]);
            for k in ('stat','status','data','aaData','tables','total'):
                if k in j:
                    v=j[k]
                    print(k, (len(v) if isinstance(v,(list,dict)) else v), str(v)[:1000])
        except Exception as e: print('not json',type(e).__name__)
    except Exception as e: print('ERROR',repr(e))
