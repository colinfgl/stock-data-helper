from __future__ import annotations

import json
import re
from pathlib import Path
from decimal import Decimal

import requests

OUT = Path('output_twse_close_20260908')
OUT.mkdir(exist_ok=True)
S = requests.Session()
S.headers.update({'User-Agent': 'Mozilla/5.0 stock-data-helper/1.0'})


def get_json(url: str):
    r = S.get(url, timeout=30)
    r.raise_for_status()
    data = r.json()
    return data


def clean(s):
    return re.sub(r'<[^>]+>', '', str(s)).replace(',', '').strip()


def num(s):
    x = clean(s)
    if x in ('', '--', '---'):
        return None
    try:
        return float(x)
    except Exception:
        return None


def parse_sign(htmlish):
    s = str(htmlish)
    if '+' in s:
        return 1
    if '-' in s or 'green' in s.lower():
        return -1
    return 0


def parse_mi_index(data):
    result = {
        'date': '20260908',
        'stat': data.get('stat'),
        'taiex': None,
        'taiex_change': None,
        'taiex_change_pct': None,
        'turnover': None,
        'breadth': {},
        'stocks': {},
    }
    tables = data.get('tables') or []
    for t in tables:
        title = t.get('title', '') or ''
        fields = t.get('fields') or []
        rows = t.get('data') or []
        # TAIEX index table
        if any('指數名稱' in str(f) for f in fields) and any('收盤指數' in str(f) for f in fields):
            for row in rows:
                if row and '發行量加權股價指數' in clean(row[0]):
                    # Common layout: 指數名稱, 收盤指數, 漲跌(+/-), 漲跌點數, 漲跌百分比
                    result['taiex'] = num(row[1]) if len(row) > 1 else None
                    sign = parse_sign(row[2]) if len(row) > 2 else 0
                    chg = num(row[3]) if len(row) > 3 else None
                    pct = num(row[4]) if len(row) > 4 else None
                    if chg is not None:
                        result['taiex_change'] = sign * abs(chg) if sign else chg
                    if pct is not None:
                        result['taiex_change_pct'] = sign * abs(pct) / 100 if sign else pct / 100
        # Market turnover table
        if any('成交金額' in str(f) for f in fields) and ('大盤統計資訊' in title or '成交統計' in title):
            for row in rows:
                if row and ('總計' in clean(row[0]) or '股票' == clean(row[0])):
                    # Store the largest turnover candidate in raw NTD.
                    candidates = [num(x) for x in row[1:]]
                    candidates = [x for x in candidates if x is not None]
                    if candidates:
                        mx = max(candidates)
                        if result['turnover'] is None or mx > result['turnover']:
                            result['turnover'] = mx
        # Breadth table: often title includes 漲跌證券數合計 and rows 股票/ETF...
        if '漲跌證券數' in title or any('上漲' in str(f) for f in fields) and any('下跌' in str(f) for f in fields):
            for row in rows:
                if row and clean(row[0]) == '股票':
                    # Known layout: 類型, 上漲(漲停), 下跌(跌停), 持平, 未成交, 無比價
                    vals = [clean(x) for x in row]
                    result['breadth']['raw_row'] = vals
                    # Prefer field mapping when available.
                    for i, f in enumerate(fields):
                        if i >= len(row):
                            continue
                        fs = clean(f)
                        rv = clean(row[i])
                        m = re.match(r'^(\d+)(?:\((\d+)\))?$', rv)
                        if '上漲' in fs and m:
                            result['breadth']['up'] = int(m.group(1))
                            if m.group(2): result['breadth']['limit_up'] = int(m.group(2))
                        elif '下跌' in fs and m:
                            result['breadth']['down'] = int(m.group(1))
                            if m.group(2): result['breadth']['limit_down'] = int(m.group(2))
                        elif ('持平' in fs or '平盤' in fs) and rv.isdigit():
                            result['breadth']['flat'] = int(rv)
                    # Fallback by positions.
                    if not result['breadth'].get('up') and len(row) >= 4:
                        for key, idx in [('up',1),('down',2),('flat',3)]:
                            m = re.match(r'^(\d+)(?:\((\d+)\))?$', clean(row[idx]))
                            if m:
                                result['breadth'][key] = int(m.group(1))
                                if key == 'up' and m.group(2): result['breadth']['limit_up'] = int(m.group(2))
                                if key == 'down' and m.group(2): result['breadth']['limit_down'] = int(m.group(2))
        # Individual listed stocks table.
        if '證券代號' in fields and '證券名稱' in fields and '收盤價' in fields:
            idx = {clean(f): i for i, f in enumerate(fields)}
            targets = {'2345','2368','2330','2317','2376','2308','2383','6770','2885','1503','2303'}
            for row in rows:
                if not row:
                    continue
                code = clean(row[idx.get('證券代號',0)])
                if code not in targets:
                    continue
                def gv(name):
                    i = idx.get(name)
                    return row[i] if i is not None and i < len(row) else None
                result['stocks'][code] = {
                    'name': clean(gv('證券名稱')),
                    'open': num(gv('開盤價')),
                    'high': num(gv('最高價')),
                    'low': num(gv('最低價')),
                    'close': num(gv('收盤價')),
                    'volume': num(gv('成交股數')),
                }
    b = result['breadth']
    if b.get('up') is not None and b.get('down'):
        b['ad_ratio'] = b['up'] / b['down']
        total = b.get('up',0) + b.get('down',0) + b.get('flat',0)
        b['up_ratio'] = b['up'] / total if total else None
    return result


def parse_bfi(data):
    result = {'date':'20260908','stat':data.get('stat'),'rows':{},'total':None}
    fields = data.get('fields') or []
    rows = data.get('data') or []
    if not rows:
        # Some newer responses use tables.
        tables = data.get('tables') or []
        if tables:
            fields = tables[0].get('fields') or []
            rows = tables[0].get('data') or []
    for row in rows:
        if not row: continue
        name = clean(row[0])
        vals = [num(x) for x in row[1:4]]
        result['rows'][name] = vals
        if name == '合計' and len(vals) >= 3:
            result['total'] = vals[2]
    return result


mi_url='https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=20260908&type=ALLBUT0999&response=json'
bfi_urls=[
    'https://www.twse.com.tw/rwd/zh/fund/BFI82U?dayDate=20260908&type=day&response=json',
    'https://www.twse.com.tw/rwd/zh/fund/BFI82U?date=20260908&response=json',
]

mi_raw=get_json(mi_url)
mi=parse_mi_index(mi_raw)

bfi=None
bfi_url_used=None
bfi_errors=[]
for u in bfi_urls:
    try:
        d=get_json(u)
        parsed=parse_bfi(d)
        if parsed.get('rows'):
            bfi=parsed; bfi_url_used=u; break
        bfi_errors.append({'url':u,'stat':d.get('stat'),'keys':list(d.keys())})
    except Exception as e:
        bfi_errors.append({'url':u,'error':repr(e)})

output={
    'mi_url':mi_url,
    'mi':mi,
    'bfi_url_used':bfi_url_used,
    'bfi':bfi,
    'bfi_errors':bfi_errors,
}
(OUT/'snapshot_20260908.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'mi_index_raw.json').write_text(json.dumps(mi_raw,ensure_ascii=False,indent=2),encoding='utf-8')
if bfi is not None:
    (OUT/'bfi82u_20260908.json').write_text(json.dumps(bfi,ensure_ascii=False,indent=2),encoding='utf-8')

print(json.dumps(output,ensure_ascii=False,indent=2))
