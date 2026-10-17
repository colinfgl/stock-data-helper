#!/usr/bin/env python3
"""Independent issuer-vendor event-amount crosscheck over immutable Yahoo chart bytes.
Research-only. A vendor chart adjustment can be internally consistent while
the original dividend event amount differs from the issuer-published amount.
Neither this diagnostic nor a secondary issuer announcement validates
historical as-of corporate actions, Formal, Natural, Cash or OOS.
"""
from __future__ import annotations
import argparse, datetime as dt, hashlib, json, math, pathlib, re
from stock_dividend_factor_reconciliation_v1_20261013 import reconcile

HEX64 = re.compile(r"[0-9a-f]{64}")
SYMBOL = re.compile(r"[0-9A-Z]{4,8}\.(?:TW|TWO)")
EVIDENCE_ROLES = {"ISSUER_MOPS_REPRINT_SECONDARY", "ISSUER_ORIGINAL_FIRSTPARTY_WITH_RAW_SHA"}
EVENT_FORMAT = re.compile(r"\d{4}-\d{2}-\d{2}")
def require(ok, text):
    if not ok:
        raise ValueError(text)
def positive(v):
    return type(v) in (int, float) and math.isfinite(v) and v > 0
def run(chart_bytes: bytes, symbol: str, evidence: dict, issuer_source_bytes: bytes | None = None) -> dict:
    require(isinstance(chart_bytes, bytes) and len(chart_bytes) > 100, "VENDOR_ORIGINAL_BYTES_MISSING")
    require(isinstance(symbol, str) and SYMBOL.fullmatch(symbol), "INVALID_SYMBOL")
    require(isinstance(evidence, dict) and evidence.get("Symbol") == symbol, "EVIDENCE_SYMBOL_CONFLICT")
    require(evidence.get("FormalEligible") is False and evidence.get("NaturalCredit") == 0 and evidence.get("OOSCredit") == 0, "MUST_BE_RESEARCH_ONLY")
    issuer_events = evidence.get("IssuerEvents")
    require(isinstance(issuer_events, list) and 1 <= len(issuer_events) <= 32, "ISSUER_EVENTS_NOT_FINITE")
    receipt = reconcile(chart_bytes, symbol, threshold=0.05)
    require(receipt["FormalEligible"] is False and receipt["NaturalCredit"] == receipt["OOSCredit"] == 0, "VENDOR_RECONCILE_FALSE_CREDIT")
    original_vendor_sha = hashlib.sha256(chart_bytes).hexdigest()
    pinned = evidence.get("VendorOriginalRawSHA256")
    require(isinstance(pinned, str) and HEX64.fullmatch(pinned) and pinned == original_vendor_sha, "VENDOR_RAW_SHA_CONFLICT")
    vendor = {r["EventDate"]: r for r in receipt["Events"]}
    seen, rows = set(), []
    for item in issuer_events:
        require(isinstance(item, dict), "ISSUER_EVENT_SCHEMA")
        day = item.get("EventDate")
        require(isinstance(day, str) and EVENT_FORMAT.fullmatch(day), "ISSUER_EVENT_DATE_MISSING")
        require(day not in seen, "ISSUER_DUPLICATE_EVENT_DATE")
        seen.add(day)
        issuer_amt = item.get("IssuerFinalPerShare")
        require(positive(issuer_amt), "ISSUER_NONPOSITIVE_AMOUNT")
        role = item.get("EvidenceRole")
        require(role in EVIDENCE_ROLES, "ISSUER_SOURCE_ROLE_INVALID")
        issuer_sha = item.get("IssuerSourceRawSHA256")
        require(isinstance(issuer_sha, str) and HEX64.fullmatch(issuer_sha), "ISSUER_SOURCE_SHA_INVALID")
        published_at = item.get("PublishedAt")
        try:
            require(dt.date.fromisoformat(published_at) <= dt.date.fromisoformat(day), "ISSUER_PUBLICATION_AFTER_EVENT")
        except (TypeError, ValueError) as exc:
            raise ValueError("ISSUER_SOURCE_PUBLISHEDAT_INVALID") from exc
        if role == "ISSUER_ORIGINAL_FIRSTPARTY_WITH_RAW_SHA":
            require(isinstance(issuer_source_bytes, bytes) and len(issuer_source_bytes) > 100, "PRIMARY_ISSUER_BYTES_NOT_PROVIDED")
            require(hashlib.sha256(issuer_source_bytes).hexdigest() == issuer_sha, "ISSUER_PRIMARY_RAW_SHA_MISMATCH")
        raw_event = vendor.get(day)
        if raw_event is None:
            status = "HOLD_ISSUER_EVENT_NOT_IN_CHART"
            vendor_amt, drift, rel_drift, jump = None, None, None, None
        else:
            vendor_amt = raw_event["Dividend"]
            drift = round(vendor_amt - issuer_amt, 10)
            rel_drift = round(100 * drift / issuer_amt, 8)
            jump = raw_event.get("ObservedFactorJumpPct")
            tolerance = max(0.0001, issuer_amt * .00001)
            status = "HOLD_VENDOR_ISSUER_AMOUNT_CONFLICT" if abs(drift) > tolerance else "RESEARCH_ISSUER_VENDOR_AMOUNT_MATCH"
        rows.append({
            "Symbol":symbol,"EventDate":day,"VendorChartAmount":vendor_amt,
            "IssuerFinalPerShare":issuer_amt,"DifferenceVendorMinusIssuer":drift,
            "DifferencePercentIssuer":rel_drift,
            "VendorAdjustedFactorJumpPct":jump,
            "VendorInternalChartFactorStatus":raw_event.get("Status") if raw_event else "NO_VENDOR_EVENT",
            "SourceRole":role,"IssuerEvidenceSHA256":issuer_sha,"PublishedAt":published_at,
            "Status":status,"FormalEligible":False,"NaturalCredit":0,"OOSCredit":0
        })
    return {
        "Status":"RESEARCH_VENDOR_ISSUER_AMOUNT_HOLD" if any(z["Status"].startswith("HOLD") for z in rows) else "RESEARCH_VENDOR_ISSUER_AMOUNT_MATCH_NOT_FORMAL",
        "Symbol":symbol,"VendorRawSHA256":original_vendor_sha,"IssuerEventCount":len(rows),
        "ConflictCount":sum(z["Status"]=="HOLD_VENDOR_ISSUER_AMOUNT_CONFLICT" for z in rows),
        "MissingEventCount":sum(z["Status"]=="HOLD_ISSUER_EVENT_NOT_IN_CHART" for z in rows),
        "OriginalChartInternalReconcile":receipt["Status"],
        "Rows":rows,"ReportScope":"RESEARCH_VENDOR_AMOUNT_AND_ISSUER_SOURCE_PROVENANCE_ONLY",
        "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
        "IssuerExhaustive":False,"HistoricalAdjustedPriceBasisApproved":False,
        "IssuerSourceRoleValidated":True,"OriginalForecastAltered":False,
        "Warning":"Vendor chart internally matched adjusted-close does not imply issuer dividend amount match or PIT validity."
    }
def selftest():
    import copy
    tz=dt.timezone(dt.timedelta(hours=8))
    day0=int(dt.datetime(2025,8,18,9,tzinfo=tz).timestamp())
    day1=int(dt.datetime(2025,8,19,9,tzinfo=tz).timestamp())
    chart={"chart":{"error":None,"result":[{"meta":{"symbol":"3017.TW"},
      "timestamp":[day0,day1],"indicators":{"quote":[{"close":[100.,95.]}],
      "adjclose":[{"adjclose":[90.,95.]}]},
      "events":{"dividends":{"d":{"date":day1,"amount":10.0}}}}]}}
    raw=json.dumps(chart,sort_keys=True).encode()
    e={"Symbol":"3017.TW","VendorOriginalRawSHA256":hashlib.sha256(raw).hexdigest(),
       "FormalEligible":False,"NaturalCredit":0,"OOSCredit":0,
       "IssuerEvents":[{"EventDate":"2025-08-19","IssuerFinalPerShare":9.996,
        "PublishedAt":"2025-07-29","EvidenceRole":"ISSUER_MOPS_REPRINT_SECONDARY",
        "IssuerSourceRawSHA256":"b"*64}]}
    assert run(raw,"3017.TW",e)["Status"]=="RESEARCH_VENDOR_ISSUER_AMOUNT_HOLD"
    assert run(raw,"3017.TW",e)["Rows"][0]["VendorInternalChartFactorStatus"]=="MATCHED_INCLUDED_BY_THRESHOLD"
    assert not run(raw,"3017.TW",e)["FormalEligible"]
    ok=copy.deepcopy(e);ok["IssuerEvents"][0]["IssuerFinalPerShare"]=10.0
    assert run(raw,"3017.TW",ok)["Status"]=="RESEARCH_VENDOR_ISSUER_AMOUNT_MATCH_NOT_FORMAL"
    miss=copy.deepcopy(e);miss["IssuerEvents"][0]["EventDate"]="2025-08-20"
    assert run(raw,"3017.TW",miss)["MissingEventCount"]==1
    bads=[]
    bad=copy.deepcopy(e);bad["VendorOriginalRawSHA256"]="0"*64;bads.append(bad)
    bad=copy.deepcopy(e);bad["Symbol"]="3018.TW";bads.append(bad)
    bad=copy.deepcopy(e);bad["FormalEligible"]=True;bads.append(bad)
    bad=copy.deepcopy(e);bad["IssuerEvents"][0]["PublishedAt"]="2025-08-20";bads.append(bad)
    bad=copy.deepcopy(e);bad["IssuerEvents"][0]["IssuerSourceRawSHA256"]="FAKE";bads.append(bad)
    bad=copy.deepcopy(e);bad["IssuerEvents"][0]["EvidenceRole"]="ISSUER_ORIGINAL_FIRSTPARTY_WITH_RAW_SHA";bads.append(bad)
    bad=copy.deepcopy(e);bad["IssuerEvents"].append(copy.deepcopy(bad["IssuerEvents"][0]));bads.append(bad)
    failed=0
    for v in bads:
        try:run(raw,"3017.TW",v)
        except ValueError:failed+=1
    assert failed==len(bads),(failed,len(bads))
    return {"status":"PASS","cases":5+len(bads),"invalid_rejected":failed,
        "no_false_formal_credit":True,"vendor_internal_vs_issuer_gate_is_independent":True}
def main():
    p=argparse.ArgumentParser()
    p.add_argument("--self-test",action="store_true")
    p.add_argument("--chart");p.add_argument("--symbol");p.add_argument("--issuer-evidence");p.add_argument("--out")
    p.add_argument("--issuer-original",help="Optional original issuer byte file, only when source role is actual firstparty original")
    args=p.parse_args()
    if args.self_test:
        print(json.dumps(selftest(),ensure_ascii=False));return 0
    if not all((args.chart,args.symbol,args.issuer_evidence,args.out)):
        p.error("--chart --symbol --issuer-evidence --out required")
    payload=json.loads(pathlib.Path(args.issuer_evidence).read_bytes())
    original=pathlib.Path(args.issuer_original).read_bytes() if args.issuer_original else None
    result=run(pathlib.Path(args.chart).read_bytes(),args.symbol,payload,original)
    path=pathlib.Path(args.out);path.parent.mkdir(parents=True,exist_ok=True)
    data=json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n"
    path.write_text(data,encoding="utf-8")
    assert path.read_bytes()==data.encode("utf-8"),"RECEIPT_READBACK_FAILED"
    print(json.dumps({"status":result["Status"],"symbol":result["Symbol"],"raw_sha256":result["VendorRawSHA256"],"issuer_events":result["IssuerEventCount"],"conflicts":result["ConflictCount"],"rows":result["Rows"],"formal":False},ensure_ascii=False))
    return 0 # research HOLD is a truthful successful diagnostic; Formal remains blocked
if __name__=="__main__":
    raise SystemExit(main())
