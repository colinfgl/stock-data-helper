#!/usr/bin/env python3
"""Offline regression for TWSE 2026 calendar rollover. No private/formal writes."""
from __future__ import annotations
import hashlib
import json
import pathlib
import sys
import tempfile

ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import premarket_daily_inputs_3y_20261013 as mod

def assert_hold(label,call):
    try: call()
    except mod.InputError: return
    raise AssertionError(label+' accepted invalid calendar')

def main():
    raw=(ROOT/'data/twse_annual_calendars/2026.json').read_bytes()
    expected_sha='7fefe785ea7155a5004a2eb74486ad865ea5c4b5f02ee0cffbbdacb1ca2ea390'
    assert len(raw)==2783 and hashlib.sha256(raw).hexdigest()==expected_sha
    proof=json.loads((ROOT/'data/twse_annual_calendars/2026.provenance.json').read_text(encoding='utf-8'))
    assert proof['original_sha256']==expected_sha
    assert proof['archival_source']['github_actions_artifact_id']==13876227590
    original=json.loads(raw)
    _,years=mod.calendar_days([original]); assert years=={2026}
    rolled={'stat':'ok','queryYear':2027,'date':'20270101','data':[['2027-01-01','元旦','市場休市']]}
    future={'stat':'ok','queryYear':2028,'date':'20280101','data':[['2028-01-01','元旦','市場休市']]}
    cases=[]
    assert mod.select_annual_calendar_payload(2026,original)==(original,False)
    cases.append('live_matching_year')
    assert mod.select_annual_calendar_payload(2026,rolled,raw)==(original,True)
    cases.append('rolled_2027_to_sha_pinned_2026')
    assert_hold('no archived original',lambda:mod.select_annual_calendar_payload(2026,rolled))
    cases.append('reject_missing_archive')
    assert_hold('mutated original',lambda:mod.select_annual_calendar_payload(2026,rolled,raw+b'x'))
    cases.append('reject_modified_archive')
    assert_hold('other rollover',lambda:mod.select_annual_calendar_payload(2026,future,raw))
    cases.append('reject_2028_response')
    assert_hold('wrong requested year',lambda:mod.select_annual_calendar_payload(2025,rolled,raw))
    cases.append('reject_2025_request')
    def fake_fetch(payload):
        def fetch(url,path,attempt_limit=2):
            body=json.dumps(payload,ensure_ascii=False).encode('utf-8')
            path=pathlib.Path(path);path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(body)
            return payload,{'url':url,'path':path.name,'sha256':hashlib.sha256(body).hexdigest(),
                'bytes':len(body),'retrieved_at':'MOCK_ONLY','attempts':1,'errors':[],
                'diagnostics':[],'status':'FETCHED'}
        return fetch
    saved=mod.get_json
    try:
        with tempfile.TemporaryDirectory() as temp:
            dst=pathlib.Path(temp)/'calendar.json'
            mod.get_json=fake_fetch(rolled)
            archive,meta=mod.get_verified_twse_annual_calendar(2026,dst,endpoint='plain')
            assert archive==original and dst.read_bytes()==raw
            assert meta['status']=='ARCHIVED_ORIGINAL_YEAR_ROLLOVER_VERIFIED'
            assert meta['original_raw_sha256_verified'] is True
            assert meta['sha256']==expected_sha
            assert meta['live_response_years']==[2027]
            assert json.loads((pathlib.Path(temp)/'calendar_live.json').read_text())==rolled
            assert meta['formal_input_qualified'] is False and meta['calendar_archive_only'] is True
            cases.append('preserves_live_and_archived_original_bytes')
            mod.get_json=fake_fetch(original)
            fresh,fresh_meta=mod.get_verified_twse_annual_calendar(2026,dst)
            assert fresh==original and fresh_meta['status']=='FETCHED'
            assert dst.read_bytes()==(pathlib.Path(temp)/'calendar_live.json').read_bytes()
            cases.append('fresh_2026_remains_fresh')
            mod.get_json=fake_fetch(future)
            assert_hold('future calendar',lambda:mod.get_verified_twse_annual_calendar(2026,dst))
            cases.append('year_mismatch_does_not_fallback')
    finally:
        mod.get_json=saved
    print(json.dumps({'status':'PASS','passed':len(cases),'total':len(cases),'cases':cases,
                      'scope':'OFFLINE_SOURCE_ORIGINAL_REPLAY_NO_FORMAL_NO_NATURAL'},ensure_ascii=False))
if __name__=='__main__':main()
