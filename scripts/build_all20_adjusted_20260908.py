from pathlib import Path
import csv
import os
import re
from decimal import Decimal

import build_all20_adjusted_v2 as m
import build_all20_adjusted_v2b  # robust TWSE price fetch + corrected R45 source-count gates

_token = os.environ.get('R45_GITHUB_TOKEN', '').strip()
if _token:
    m.S.headers.update({'Authorization': f'Bearer {_token}'})

# Exact R45 methodology extended through 2026-09-08.
m.CUTOFF = '20260908'
m.OUT = Path('output_all20_20260908')
m.OUT.mkdir(exist_ok=True)
BASE_ACTIONS = Path('r45_base/corporate_actions_all20.csv')

# R45 ended 2026-08-17. There are 16 Taiwan trading dates 8/18 through 9/8.
for code, (name, market, start, expected) in list(m.TARGETS.items()):
    m.TARGETS[code] = (name, market, start, expected + 16)

m.EXPECTED_TOTAL_SOURCE = 37259  # 36939 + 20*16
m.EXPECTED_TOTAL_NO_TRADE = 6
m.EXPECTED_TOTAL_PRICE = 37253   # 36933 + 20*16
m.EXPECTED_LAST3_EVENTS['3665'] = 10
m.EXPECTED_LAST3_EVENTS['4916'] = 9
m.EXPECTED_LAST3_EVENTS['6770'] = 4


def release_assets_through_w36():
    rel = m.get(f'https://api.github.com/repos/{m.SOURCE_REPO}/releases/tags/{m.SOURCE_TAG}').json()
    out = []
    for asset in rel.get('assets', []):
        name = asset['name']
        if re.fullmatch(r'yearly_20(18|19|20|21|22|23|24|25)\.zip', name):
            out.append(asset)
        elif re.fullmatch(r'weekly_2026_W\d{2}\.zip', name):
            week = int(re.search(r'W(\d+)', name).group(1))
            if week <= 36:
                out.append(asset)
    return sorted(out, key=lambda a: a['name'])


m.release_assets = release_assets_through_w36
_original_build_release = m.build_release


def build_release_plus_20260907_08():
    by, manifest = _original_build_release()
    official_added = 0
    official_urls = set()
    for target_date in ('20260907', '20260908'):
        for code, (name, market, start, expected) in m.TARGETS.items():
            if market == 'TWSE':
                month_rows, url = m.twse_month_rows(code, '202609')
                row = month_rows.get(target_date)
            else:
                row, url = m.tpex_daily_row(code, target_date)
            official_urls.add(url)
            if row is None:
                raise RuntimeError(f'missing official {target_date} row for {code}')
            old = by[code].get(target_date)
            if old and any(old[k] != row[k] for k in ('volume', 'open', 'high', 'low', 'close')):
                raise RuntimeError(f'{target_date} conflict {code}: release={old} official={row}')
            if not old:
                by[code][target_date] = row
                official_added += 1
    manifest.append([
        'OFFICIAL_20260907_08_ALL20', 0, '', '', True, official_added,
        ' | '.join(sorted(official_urls))
    ])
    return by, manifest


m.build_release = build_release_plus_20260907_08


def load_r45_actions():
    if not BASE_ACTIONS.exists():
        raise RuntimeError(f'missing restored R45 action file: {BASE_ACTIONS}')
    out = []
    with BASE_ACTIONS.open('r', encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            code = row['code'].strip()
            if code not in m.TARGETS:
                continue
            out.append({
                'event_date': row['event_date'].strip(),
                'code': code,
                'name': row['name'].strip(),
                'market': row['market'].strip(),
                'previous_close': Decimal(row['official_previous_close']),
                'reference_price': Decimal(row['official_reference_price']),
                'factor': Decimal(row['factor']),
                'official_source': row['official_source'].strip(),
            })
    if len(out) != 195:
        raise RuntimeError(f'R45 base action count mismatch: {len(out)} != 195')
    return out


def postcutoff_twse_actions():
    url = 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20260818&endDate=20260908&response=json'
    data = m.get(url, 30).json()
    out = []
    for row in data.get('data', []):
        if len(row) < 5:
            continue
        event_date = m.norm_date(row[0])
        code = re.sub(r'<[^>]+>', '', str(row[1])).strip()
        pre = m.dec(row[3]); ref = m.dec(row[4])
        if (code in m.TARGETS and m.TARGETS[code][1] == 'TWSE' and event_date
            and '20260818' <= event_date <= m.CUTOFF and pre is not None and ref is not None and pre > 0 and ref > 0):
            out.append({'event_date':event_date,'code':code,'name':m.TARGETS[code][0],'market':'TWSE',
                        'previous_close':pre,'reference_price':ref,'factor':ref/pre,'official_source':url})
    return out, []


def postcutoff_tpex_actions():
    url = 'https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?l=zh-tw&d=115/08/18&ed=115/09/08'
    data = m.get(url, 30).json()
    tables = data.get('tables') or []
    rows = tables[0].get('data', []) if tables else (data.get('aaData') or data.get('data') or [])
    out = []
    for row in rows:
        if len(row) < 5:
            continue
        event_date = m.norm_date(row[0])
        code = re.sub(r'<[^>]+>', '', str(row[1])).strip()
        pre = m.dec(row[3]); ref = m.dec(row[4])
        if (code in m.TARGETS and m.TARGETS[code][1] == 'TPEX' and event_date
            and '20260818' <= event_date <= m.CUTOFF and pre is not None and ref is not None and pre > 0 and ref > 0):
            out.append({'event_date':event_date,'code':code,'name':m.TARGETS[code][0],'market':'TPEX',
                        'previous_close':pre,'reference_price':ref,'factor':ref/pre,'official_source':url})
    return out, []


def parse_twse_actions_base_plus_post():
    base = [e for e in load_r45_actions() if e['market'] == 'TWSE']
    post, errors = postcutoff_twse_actions()
    return base + post, errors


def parse_tpex_actions_base_plus_post():
    base = [e for e in load_r45_actions() if e['market'] == 'TPEX']
    post, errors = postcutoff_tpex_actions()
    return base + post, errors


m.parse_twse_actions = parse_twse_actions_base_plus_post
m.parse_tpex_actions = parse_tpex_actions_base_plus_post

if __name__ == '__main__':
    m.main()
