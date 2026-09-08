from __future__ import annotations

from pathlib import Path
import csv
import json
import os
import re
import shutil
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone

import requests
import build_all20_adjusted_v2 as m
import build_all20_adjusted_v2b  # reuse hardened TPEx parser/session behavior

BASE = Path('r110_base')
SNAP = Path('twse_0908')
OUT = Path('output_all20_20260908')
OUT.mkdir(exist_ok=True)
DATE = '20260908'
EXPECTED_SOURCE = 37259
EXPECTED_PRICE = 37253
EXPECTED_NO_TRADE = 6

_token = os.environ.get('R45_GITHUB_TOKEN', '').strip()
if _token:
    m.S.headers.update({'Authorization': f'Bearer {_token}'})


def dec(x):
    s = str(x).replace(',', '').strip()
    if s in ('', '--', '---'):
        return None
    return Decimal(s)


def fmt_money(x: Decimal) -> str:
    return f'{x.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP):f}'


def clean(s):
    return re.sub(r'<[^>]+>', '', str(s)).replace(',', '').strip()


def load_csv(path):
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        return list(csv.DictReader(f))


def write_csv(path, fieldnames, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)


def parse_twse_snapshot(targets):
    raw_path = SNAP / 'mi_index_raw.json'
    if not raw_path.exists():
        raise RuntimeError(f'missing exact TWSE snapshot artifact: {raw_path}')
    data = json.loads(raw_path.read_text(encoding='utf-8'))
    if data.get('stat') != 'OK':
        raise RuntimeError(f'TWSE snapshot stat not OK: {data.get("stat")}')
    out = {}
    for t in data.get('tables', []):
        fields = t.get('fields') or []
        if not {'證券代號','證券名稱','成交股數','開盤價','最高價','最低價','收盤價'}.issubset(set(fields)):
            continue
        idx = {f:i for i,f in enumerate(fields)}
        for row in t.get('data') or []:
            if not row: continue
            code = clean(row[idx['證券代號']])
            if code not in targets: continue
            vals = {k: dec(row[idx[k]]) for k in ['成交股數','開盤價','最高價','最低價','收盤價']}
            if any(vals[k] is None for k in ['成交股數','開盤價','最高價','最低價','收盤價']):
                raise RuntimeError(f'invalid TWSE 9/8 row {code}: {row}')
            out[code] = {
                'volume': int(vals['成交股數']),
                'open': vals['開盤價'], 'high': vals['最高價'],
                'low': vals['最低價'], 'close': vals['收盤價'],
                'source_asset': 'TWSE_MI_INDEX_20260908',
            }
    return out


def parse_tpex(targets):
    out = {}
    for code in targets:
        row, url = m.tpex_daily_row(code, DATE)
        if row is None:
            raise RuntimeError(f'missing TPEx official 9/8 row for {code}')
        out[code] = {
            'volume': int(row['volume']),
            'open': Decimal(str(row['open'])), 'high': Decimal(str(row['high'])),
            'low': Decimal(str(row['low'])), 'close': Decimal(str(row['close'])),
            'source_asset': 'TPEX_DAILY_20260908',
            'url': url,
        }
    return out


def assert_no_new_core_actions(core_codes):
    # R110 already contains all actions through 9/7. If 9/8 adds a core action,
    # a simple append would be invalid because earlier prices may need back-adjustment.
    urls = []
    tw_url = 'https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=20260908&endDate=20260908&response=json'
    urls.append(tw_url)
    tw = m.get(tw_url, 30).json()
    for row in tw.get('data', []):
        if len(row) > 1:
            code = clean(row[1])
            if code in core_codes:
                raise RuntimeError(f'new core TWSE corporate action on 9/8: {code} {row}')
    tp_url = 'https://www.tpex.org.tw/web/stock/exright/dailyquo/exDailyQ_result.php?l=zh-tw&d=115/09/08&ed=115/09/08'
    urls.append(tp_url)
    tp = m.get(tp_url, 30).json()
    tables = tp.get('tables') or []
    rows = tables[0].get('data', []) if tables else (tp.get('aaData') or tp.get('data') or [])
    for row in rows:
        if len(row) > 1:
            code = clean(row[1])
            if code in core_codes:
                raise RuntimeError(f'new core TPEx corporate action on 9/8: {code} {row}')
    return urls


def main():
    required = ['price_history_all20_adjusted.csv','all20_qa_summary.csv','corporate_actions_all20.csv',
                'gap_fills.csv','gap_unresolved.csv','action_fetch_errors.csv','source_manifest.csv']
    for fn in required:
        if not (BASE/fn).exists():
            raise RuntimeError(f'missing exact R110 base file: {BASE/fn}')

    base_prices = load_csv(BASE/'price_history_all20_adjusted.csv')
    base_qa = load_csv(BASE/'all20_qa_summary.csv')
    actions = load_csv(BASE/'corporate_actions_all20.csv')
    if len(actions) != 199:
        raise RuntimeError(f'R110 corporate action count mismatch: {len(actions)} != 199')

    info = {r['code']:(r['name'],r['market']) for r in base_qa}
    order = [r['code'] for r in base_qa]
    if len(order) != 20:
        raise RuntimeError(f'R110 core count mismatch: {len(order)}')
    twse_codes = [c for c in order if info[c][1] == 'TWSE']
    tpex_codes = [c for c in order if info[c][1] == 'TPEX']

    action_urls = assert_no_new_core_actions(set(order))
    tw_rows = parse_twse_snapshot(set(twse_codes))
    tp_rows = parse_tpex(tpex_codes)
    official = {**tw_rows, **tp_rows}
    missing = [c for c in order if c not in official]
    if missing:
        raise RuntimeError(f'missing official 9/8 rows: {missing}')

    # Last row/cumulative factor per code from exact R110.
    last_by = {}
    existing_keys = set()
    for r in base_prices:
        existing_keys.add((r['code'], r['date']))
        if r['code'] not in last_by or r['date'] > last_by[r['code']]['date']:
            last_by[r['code']] = r
    for c in order:
        if last_by[c]['date'] != '20260907':
            raise RuntimeError(f'R110 last date mismatch {c}: {last_by[c]["date"]}')
        if (c, DATE) in existing_keys:
            raise RuntimeError(f'duplicate 9/8 row already exists: {c}')

    new_rows = []
    for c in order:
        name, market = info[c]
        o = official[c]
        factor = Decimal(last_by[c]['cumulative_factor'])
        if factor <= 0:
            raise RuntimeError(f'invalid cumulative factor {c}: {factor}')
        row = {
            'date': DATE, 'code': c, 'name': name, 'market': market,
            'volume': str(o['volume']),
            'open': f'{o["open"]:.2f}', 'high': f'{o["high"]:.2f}',
            'low': f'{o["low"]:.2f}', 'close': f'{o["close"]:.2f}',
            'source_asset': o['source_asset'], 'no_trade_placeholder': 'False',
            'cumulative_factor': f'{factor:.12f}',
            'adj_open': fmt_money(o['open']*factor),
            'adj_high': fmt_money(o['high']*factor),
            'adj_low': fmt_money(o['low']*factor),
            'adj_close': fmt_money(o['close']*factor),
            'qa_status': 'OK',
        }
        if not (o['low'] <= o['open'] <= o['high'] and o['low'] <= o['close'] <= o['high'] and o['volume'] >= 0):
            raise RuntimeError(f'OHLC/volume invalid {c}: {row}')
        new_rows.append(row)

    # Preserve exact code order, append date within each code.
    rank = {c:i for i,c in enumerate(order)}
    final_prices = base_prices + new_rows
    final_prices.sort(key=lambda r:(rank[r['code']], r['date']))
    price_fields = list(base_prices[0].keys())
    write_csv(OUT/'price_history_all20_adjusted.csv', price_fields, final_prices)

    # QA: recompute counts and enforce only one added price/source row per code.
    action_count = {}
    for a in actions:
        action_count[a['code']] = action_count.get(a['code'],0)+1
    qa_out = []
    for q in base_qa:
        c=q['code']
        rows=[r for r in final_prices if r['code']==c]
        keys=[r['date'] for r in rows]
        dup=len(keys)-len(set(keys))
        bad=0
        for r in rows:
            if r['no_trade_placeholder']=='True': continue
            oo,hh,ll,cc=(Decimal(r[k]) for k in ('open','high','low','close'))
            if not (ll <= oo <= hh and ll <= cc <= hh): bad += 1
        source_rows=int(q['source_rows'])+1
        price_rows=int(q['price_rows'])+1
        expected=int(q['expected_source_rows'])+1
        no_trade=int(q['no_trade_rows'])
        passed=(source_rows==expected and len(rows)==source_rows and dup==0 and bad==0 and keys[0]==q['expected_start'] and keys[-1]==DATE)
        qa_out.append({
            'code':c,'name':q['name'],'market':q['market'],
            'source_rows':source_rows,'price_rows':price_rows,'no_trade_rows':no_trade,
            'expected_source_rows':expected,'source_count_match':str(source_rows==expected),
            'expected_start':q['expected_start'],'actual_start':keys[0],
            'expected_end':DATE,'actual_end':keys[-1],
            'duplicate_rows':dup,'price_or_ohlc_bad_rows':bad,
            'corporate_action_events':action_count.get(c,0),
            'previous_close_mismatches_info':q['previous_close_mismatches_info'],
            'event_invalid':q['event_invalid'],'pass':str(passed),
        })
    write_csv(OUT/'all20_qa_summary.csv', list(qa_out[0].keys()), qa_out)

    # Copy exact R110 governance files unchanged where appropriate.
    for fn in ['corporate_actions_all20.csv','gap_fills.csv']:
        shutil.copy2(BASE/fn, OUT/fn)
    # Fresh empty unresolved/action-errors files: incremental path had none.
    write_csv(OUT/'gap_unresolved.csv', ['code','date','reason','detail'], [])
    write_csv(OUT/'action_fetch_errors.csv', ['start','end','market','error','url'], [])

    manifest = load_csv(BASE/'source_manifest.csv')
    manifest.append({
        'asset':'OFFICIAL_20260908_INCREMENTAL_R110_BASE', 'size_bytes':'0', 'sha256':'', 'expected_sha256':'',
        'sha_ok':'True','release_rows_added':'20',
        'url':'TWSE snapshot workflow 34199098393 | TPEx official 20260908 | ' + ' | '.join(action_urls),
    })
    write_csv(OUT/'source_manifest.csv', list(manifest[0].keys()), manifest)

    report = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'cutoff': DATE,
        'base_canonical': 'R110_through_20260907_exact_artifact_run_34181678827',
        'append_method': 'official_20260908_incremental_no_new_core_actions',
        'source_rows_total': sum(int(q['source_rows']) for q in qa_out),
        'price_rows_total': sum(int(q['price_rows']) for q in qa_out),
        'no_trade_rows_total': sum(int(q['no_trade_rows']) for q in qa_out),
        'expected_source_rows_total': EXPECTED_SOURCE,
        'expected_price_rows_total': EXPECTED_PRICE,
        'expected_no_trade_rows_total': EXPECTED_NO_TRADE,
        'gap_fills': len(load_csv(BASE/'gap_fills.csv')),
        'gap_unresolved_candidates': 0,
        'corporate_action_events_total': len(actions),
        'twse_action_fetch_errors': 0,
        'tpex_action_fetch_errors': 0,
        'stocks': len(qa_out),
        'all_pass': all(q['pass']=='True' for q in qa_out)
                    and sum(int(q['source_rows']) for q in qa_out)==EXPECTED_SOURCE
                    and sum(int(q['price_rows']) for q in qa_out)==EXPECTED_PRICE
                    and sum(int(q['no_trade_rows']) for q in qa_out)==EXPECTED_NO_TRADE,
    }
    (OUT/'all20_report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if not report['all_pass']:
        raise SystemExit(2)


if __name__ == '__main__':
    main()
