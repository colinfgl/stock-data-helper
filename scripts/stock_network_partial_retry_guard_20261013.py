#!/usr/bin/env python3
"""Regression: exactly one HTTP transport retry and never score partial bytes."""
from __future__ import annotations
import http.client,json,pathlib,tempfile,urllib.error
from unittest.mock import patch
from premarket_daily_inputs_3y_20261013 import get_json,sha

class FakeResponse:
    def __init__(self,body=b'{"stat":"OK","date":"20261013"}'):self.body=body
    def getcode(self):return 200
    def read(self,n):return self.body
    def close(self):pass

def selftest():
    checks={}
    def test(name,fn):
        try:checks[name]="PASS" if fn() else "FAIL_ASSERT"
        except Exception as exc:checks[name]="FAIL_"+type(exc).__name__+"_"+str(exc)[:80]
    with tempfile.TemporaryDirectory() as temp, patch("premarket_daily_inputs_3y_20261013.time.sleep",return_value=None):
        root=pathlib.Path(temp)
        def call(name,values,limit=2):
            file=root/(name+".json")
            with patch("premarket_daily_inputs_3y_20261013.urllib.request.urlopen",side_effect=values) as mocked:
                result,receipt=get_json("https://twse.test/quote?date=20261013",file,attempt_limit=limit)
            return file,result,receipt,mocked.call_count
        part=b'{"stat":'
        file,data,rec,n=call("partial_success",[http.client.IncompleteRead(part,100),FakeResponse()])
        test("partial_followed_by_fresh_complete_success",lambda:n==2 and data["stat"]=="OK" and rec["attempts"]==2)
        test("returned_digest_only_for_complete_bytes",lambda:rec["sha256"]==sha(file.read_bytes()) and file.read_bytes()!=part)
        test("partial_sha_evidence_not_complete",lambda:
             rec["diagnostics"][0]["category"]=="NETWORK_BODY_INCOMPLETE" and
             rec["diagnostics"][0]["body_complete"] is False and
             rec["diagnostics"][0]["partial_received_bytes"]==len(part) and
             (root/"partial_success.json.attempt-1.response.raw").read_bytes()==part)
        file,data,rec,n=call("twice_partial",[http.client.IncompleteRead(part,2),http.client.IncompleteRead(part,3)])
        test("both_partial_fail_closed",lambda:
             n==2 and data is None and not file.exists() and rec["status"]=="FETCH_FAILED"
             and rec["sha256"] is None and
             all(d.get("body_complete") is False for d in rec["diagnostics"]) and
             (root/"twice_partial.json.failure.json").exists())
        file,data,rec,n=call("remote_dropped",[http.client.RemoteDisconnected("closed"),FakeResponse()])
        test("remote_disconnect_bounded_retry",lambda:
             n==2 and data["stat"]=="OK" and rec["diagnostics"][0]["category"]=="NETWORK_CONNECTION_INTERRUPTED")
        file,data,rec,n=call("connection_reset",[ConnectionResetError("reset"),FakeResponse()])
        test("reset_bounded_retry",lambda:n==2 and data["stat"]=="OK")
        error=urllib.error.HTTPError("https://twse.test/",429,"slow",{"Retry-After":"30"},None)
        file,data,rec,n=call("rate_limit",[error,FakeResponse()])
        test("respect_retry_after_no_retry",lambda:
             n==1 and data is None and rec["diagnostics"][0]["retry_deferred_by_provider"] is True)
        file,data,rec,n=call("invalid_json",[FakeResponse(b'{"invalid"'),FakeResponse()])
        test("invalid_JSON_never_promoted",lambda:n==1 and data is None and rec["status"]=="FETCH_FAILED" and not file.exists())
        file,data,rec,n=call("limited",[http.client.IncompleteRead(part,30)],limit=1)
        test("at_most_user_selected_attempt_count",lambda:n==1 and data is None and rec["attempts"]==1)
        try:get_json("https://twse.test/",root/"limit_3.json",attempt_limit=3)
        except ValueError:checks["disallow_three_or_more_attempts"]="PASS"
        else:checks["disallow_three_or_more_attempts"]="FAIL"
    return {"status":"PASS" if all(v=="PASS" for v in checks.values()) else "FAIL",
            "total":len(checks),"passed":sum(v=="PASS" for v in checks.values()),"tests":checks,
            "scope":"MOCK_HTTP_ONLY_NO_NETWORK_NO_CANONICAL_OUTPUT_NO_NATURAL"}
if __name__=="__main__":
    o=selftest()
    print(json.dumps(o,ensure_ascii=False))
    raise SystemExit(0 if o["status"]=="PASS" else 2)
