#!/usr/bin/env python3
"""Repair selected failed native charts, without re-fetching successful sources.
This is a historical/source-repair utility, not a production-input qualification.
Requires the unchanged adjacent premarket_daily_inputs.py. No credentials or
portfolio data are accepted, and no price is synthesized.
"""
from __future__ import annotations
import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs
import premarket_daily_inputs as core


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def checked_source(root: Path, record: dict) -> dict:
    name = record.get('path', '')
    if not name or Path(name).name != name:
        raise ValueError('UNSAFE_SOURCE_PATH')
    path = root / name
    if path.is_symlink():
        raise ValueError('SYMLINK_NOT_ALLOWED')
    data = path.read_bytes()
    if digest(data) != record.get('sha256'):
        raise ValueError('SOURCE_HASH_MISMATCH:' + name)
    if len(data) != record.get('bytes'):
        raise ValueError('SOURCE_SIZE_MISMATCH:' + name)
    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        raise ValueError('SOURCE_NOT_OBJECT:' + name)
    return parsed


def make_plan(root: Path, receipt_hash: str, target: str, symbols: list[str]) -> dict:
    raw = (root / 'acquisition_receipt.json').read_bytes()
    if digest(raw) != receipt_hash:
        raise ValueError('RECEIPT_HASH_MISMATCH')
    receipt = json.loads(raw)
    dates = receipt['dates']
    if target != dates['target_date']:
        raise ValueError('TARGET_MISMATCH_NEW_DATE_REQUIRES_NEW_INPUTS')
    days = [dates['previous_session'], dates['price_cutoff']]
    if not core.date_of(days[0]) < core.date_of(days[1]) < core.date_of(target):
        raise ValueError('INVALID_SESSION_ORDER')
    if len(symbols) != len(set(symbols)) or not symbols:
        raise ValueError('EMPTY_OR_DUPLICATE_SYMBOLS')
    records = {}
    for rec in receipt['sources']:
        if rec['path'] in records:
            raise ValueError('DUPLICATE_SOURCE_PATH')
        records[rec['path']] = rec
    old_charts = {}
    for result in receipt['charts']:
        if result['symbol'] in old_charts:
            raise ValueError('DUPLICATE_CHART_RESULT')
        old_charts[result['symbol']] = result
    retry = []
    for symbol in symbols:
        if not re.fullmatch(r'[A-Z0-9]{4,8}\.(TW|TWO)', symbol):
            raise ValueError('INVALID_SYMBOL')
        if old_charts.get(symbol, {}).get('status') != 'FAIL':
            raise ValueError('ONLY_EXISTING_FAILED_CHARTS:' + symbol)
        chart_rec = records.get('chart_' + symbol + '.json')
        if not chart_rec:
            raise ValueError('CHART_SOURCE_NOT_REGISTERED')
        url = urlsplit(chart_rec['url'])
        query = parse_qs(url.query)
        if (url.scheme != 'https' or url.hostname not in
            ('query1.finance.yahoo.com', 'query2.finance.yahoo.com') or
            url.path != '/v8/finance/chart/' + symbol or url.username or
            url.password or url.port not in (None, 443) or url.fragment or
            query.get('interval') != ['1d'] or
            query.get('includeAdjustedClose') != ['true']):
            raise ValueError('UNAPPROVED_CHART_ENDPOINT')
        market = 'TPEX' if symbol.endswith('.TWO') else 'TWSE'
        official = {}
        refs = []
        for day in days:
            name = market + '_' + day + '.json'
            rec = records[name]
            if rec.get('status') != 'FETCHED':
                raise ValueError('OFFICIAL_SOURCE_NOT_FETCHED')
            payload = checked_source(root, rec)
            official[day] = core.official_quotes(payload, market, day).get(symbol.split('.')[0])
            if official[day] is None:
                raise ValueError('OFFICIAL_SYMBOL_MISSING')
            refs.append({k: rec.get(k) for k in ('path', 'sha256', 'bytes', 'url', 'retrieved_at')})
        retry.append({'symbol': symbol, 'url': chart_rec['url'],
                      'official_closes': official, 'official_source_refs': refs,
                      'original_error': old_charts[symbol].get('error')})
    return {'mode': 'EXACT_SNAPSHOT_SOURCE_REPAIR', 'target_date': target,
            'sessions': days, 'baseline_receipt_sha256': receipt_hash,
            'baseline_started_at': receipt.get('started_at'),
            'baseline_completed_at': receipt.get('completed_at'),
            'retry_charts': retry, 'network_requests_planned': len(retry),
            'official_refetches_planned': 0, 'successful_chart_refetches_planned': 0,
            'formal_input_qualified': False, 'model_run_required': False,
            'limits': ['Same historical source snapshot only; not a new-date input run.',
                       'Complete universe, corporate actions and original gate remain required.',
                       'A plan or successful native-price retry is not production qualification.']}


def repair(root: Path, out: Path, plan: dict) -> dict:
    # Do not overwrite previous success/failure evidence or the original receipt.
    if out.exists():
        raise ValueError('OUTPUT_ALREADY_EXISTS')
    out.mkdir(parents=True, exist_ok=False)
    core.dump(out / 'retry_plan.json', plan)
    result = {'started_at': core.stamp(), 'mode': plan['mode'], 'target_date': plan['target_date'],
              'baseline_receipt_sha256': plan['baseline_receipt_sha256'], 'results': [],
              'official_refetches': 0, 'successful_chart_refetches': 0,
              'formal_input_qualified': False, 'prediction_generated': False}
    core.dump(out / 'retry_receipt.json', result)
    for item in plan['retry_charts']:
        symbol = item['symbol']
        payload, source = core.get_json(item['url'], out / ('chart_' + symbol + '.json'), attempt_limit=2)
        try:
            validation = core.validate_chart(payload, symbol, plan['sessions'], item['official_closes'])
        except Exception as exc:
            validation = {'symbol': symbol, 'status': 'FAIL', 'error': str(exc),
                          'formal_input_qualified': False}
        result['results'].append({'source': source, 'validation': validation,
                                  'official_source_refs': item['official_source_refs']})
        result['completed_at'] = core.stamp()
        result['native_retry_pass'] = all(x['validation']['status'] != 'FAIL' for x in result['results'])
        core.dump(out / 'retry_receipt.json', result)
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--receipt-sha256', required=True)
    ap.add_argument('--target-date', required=True)
    ap.add_argument('--symbols', required=True)
    ap.add_argument('--execute', action='store_true', help='Otherwise only print a no-network plan.')
    ap.add_argument('--out', type=Path)
    args = ap.parse_args()
    try:
        plan = make_plan(args.baseline, args.receipt_sha256, args.target_date, args.symbols.split(','))
        if args.execute:
            if args.out is None:
                raise ValueError('NEW_OUTPUT_DIRECTORY_REQUIRED')
            result = repair(args.baseline, args.out, plan)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result['native_retry_pass'] else 2
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print(json.dumps({'status': 'REJECTED', 'error': str(exc), 'formal_input_qualified': False}))
        return 2

if __name__ == '__main__':
    raise SystemExit(main())
