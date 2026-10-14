#!/usr/bin/env python3
"""Three immutable Yahoo originals for 2026-10-14 RESEARCH ONLY.

The Oct 12 original anchors historical adjustments; the Oct 13 evening
original proves the Oct 13 close; the Oct 14 morning original may contain
retroactive NULLs. No synthetic provider rows, no formal 68/68 claim,
no Canonical Prediction, Natural, OOS, issuer approval, cash or orders.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib

from stock_dual_origin_prior_close_research_v1_20261013 import (
    CUTOFF, CURRENT_DATE, PRIOR_DATE, TARGET_DATE, TZ, acceptable, chart,
    good, guard, h, official_prices, read_stamped_receipt, srcfile,
    verify_symbol,
)

EXPECTED = 68


def reconcile_originals(prior: bytes, evening: bytes, morning: bytes,
                        symbol: str, previous_official: float,
                        current_official: float) -> dict:
    """Choose one authenticated original; NEVER synthesize merged raw bytes."""
    # A complete older/evening pair must exist even when the morning looks fine.
    base = verify_symbol(prior, evening, symbol,
                         previous_official, current_official)
    evening_rows = chart(evening, symbol)
    morning_rows = chart(morning, symbol)
    count = 0
    for date in sorted(set(evening_rows) & set(morning_rows)):
        e, m = evening_rows[date], morning_rows[date]
        for field in ("close", "adj"):
            a, b = e[field], m[field]
            if good(a) and good(b):
                guard(acceptable(a, b),
                      "MORNING_EVENING_ORIGINAL_PRICE_CONFLICT_" + date)
                count += 1
    guard(count >= 10, "TOO_FEW_THREE_ORIGINAL_OVERLAP_OBSERVATIONS")
    day = morning_rows.get(CURRENT_DATE)
    guard(day is not None, "MORNING_CURRENT_DATE_ABSENT")
    current_e = evening_rows[CURRENT_DATE]
    guard(all(good(current_e[z]) for z in ("close", "adj")),
          "EVENING_CURRENT_ORIGINAL_NOT_VALID")
    fresh_direct = all(good(day[z]) for z in ("close", "adj"))
    if fresh_direct:
        direct = verify_symbol(prior, morning, symbol,
                               previous_official, current_official)
        guard(acceptable(day["adj"], current_e["adj"]),
              "SAME_SESSION_ADJUSTMENT_CONFLICT")
        role = "MORNING_DIRECT_VERIFIED"
        detail = direct
    else:
        # A valid partial morning close is also evidence, never ignored.
        for field in ("close", "adj"):
            if good(day[field]):
                guard(acceptable(day[field], current_e[field]),
                      "PARTIAL_MORNING_SOURCE_CONFLICT_" + field)
        role = "EVENING_ORIGINAL_RESEARCH_FALLBACK"
        detail = base
    return {
        "RecoveryStatus": "THREE_ORIGINALS_RESEARCH_MATCH",
        "SelectedSourceRole": role,
        "MissingMorningPriorSession": not fresh_direct,
        "ThreeSourceOverlapValues": count,
        "PreviousOfficialClose": previous_official,
        "CurrentOfficialClose": current_official,
        "SelectedDayAdjustedClose":
            morning_rows[CURRENT_DATE]["adj"] if fresh_direct
            else evening_rows[CURRENT_DATE]["adj"],
        "PriorSourceRawSHA256": h(prior),
        "EveningSourceRawSHA256": h(evening),
        "MorningSourceRawSHA256": h(morning),
        "SourceLineage": "THREE_SEPARATE_ORIGINAL_RAW_FILES_UNMERGED",
        "FormalEligible": False,
        "NaturalCredit": 0,
        "OOSCredit": 0,
        "IssuerActionsFullyVerified": False,
        "CashTradingAuthorized": False,
        "CanonicalPredictionWritten": False,
        "VerifiedPriorPairCommonDays": detail["OverlappingValidOriginalDays"],
    }


def run(prior_dir: str, evening_dir: str, morning_dir: str,
        output_dir: str) -> int:
    roots = [pathlib.Path(x) for x in
             (prior_dir, evening_dir, morning_dir)]
    resultdir = pathlib.Path(output_dir)
    meta_entries = [read_stamped_receipt(root) for root in roots]
    (old_meta, old_ent), (eve_meta, eve_ent), (am_meta, am_ent) = meta_entries
    guard(old_meta.get("dates", {}).get("target_date") == "2026-10-13"
          and old_meta["dates"].get("price_cutoff") == PRIOR_DATE,
          "PRIOR_SOURCE_DATE_MISMATCH")
    for tag, item in (("EVENING", eve_meta), ("MORNING", am_meta)):
        dates = item.get("dates", {})
        guard(dates.get("target_date") == "2026-10-14"
              and dates.get("price_cutoff") == CURRENT_DATE
              and dates.get("previous_session") == PRIOR_DATE,
              tag + "_SOURCE_DATE_MISMATCH")
    def symbols(table):
        return sorted(z[len("chart_"):-len(".json")] for z in table
                      if z.startswith("chart_") and z.endswith(".json"))
    universe = symbols(old_ent)
    guard(len(universe) == EXPECTED and
          universe == symbols(eve_ent) == symbols(am_ent),
          "THREE_ORIGINAL_SYMBOL_UNIVERSE_MISMATCH")
    originals, official = {}, {}
    for market in ("TWSE", "TPEX"):
        for date in (PRIOR_DATE, CURRENT_DATE):
            name = f"{market}_{date}.json"
            for tag, root, entries in (
                ("evening", roots[1], eve_ent),
                ("morning", roots[2], am_ent),
            ):
                raw, rec = srcfile(root, name, entries)
                official[(tag, market, date)] = official_prices(
                    raw, market, date)
                originals[f"{tag}:{name}"] = rec["sha256"]
    rows = []
    for symbol in universe:
        code, ext = symbol.rsplit(".", 1)
        venue = {"TW": "TWSE", "TWO": "TPEX"}.get(ext)
        guard(venue is not None, "UNRECOGNIZED_VENDOR_SYMBOL")
        before = official[("morning", venue, PRIOR_DATE)].get(code)
        after = official[("morning", venue, CURRENT_DATE)].get(code)
        earlier = official[("evening", venue, PRIOR_DATE)].get(code)
        later = official[("evening", venue, CURRENT_DATE)].get(code)
        row = {"Symbol": code, "VendorSymbol": symbol, "Venue": venue,
               "OfficialName": after["name"] if after else "",
               "RecoveryStatus": "SOURCE_HOLD",
               "FormalEligible": False, "NaturalCredit": 0,
               "OOSCredit": 0, "CashTradingAuthorized": False}
        try:
            guard(all((before, after, earlier, later)),
                  "FIRST_PARTY_OFFICIAL_TWO_DATE_ROW_MISSING")
            guard(before == earlier and after == later,
                  "EVENING_MORNING_OFFICIAL_PRICE_OR_NAME_CONFLICT")
            guard(before["name"] == after["name"],
                  "FIRST_PARTY_SYMBOL_NAME_CHANGED")
            guard(good(before["close"]) and good(after["close"]),
                  "OFFICIAL_CLOSE_INVALID")
            filename = "chart_" + symbol + ".json"
            raw_a, receipt_a = srcfile(roots[0], filename, old_ent)
            raw_b, receipt_b = srcfile(roots[1], filename, eve_ent)
            raw_c, receipt_c = srcfile(roots[2], filename, am_ent)
            guard(dt.datetime.fromisoformat(receipt_b["retrieved_at"])
                  < dt.datetime.fromisoformat(receipt_c["retrieved_at"]),
                  "CAPTURE_TIME_NON_MONOTONIC")
            row.update(reconcile_originals(
                raw_a, raw_b, raw_c, symbol,
                before["close"], after["close"]))
            row.update(
                PriorOriginalRetrievedAt=receipt_a["retrieved_at"],
                EveningOriginalRetrievedAt=receipt_b["retrieved_at"],
                MorningOriginalRetrievedAt=receipt_c["retrieved_at"],
            )
        except (ValueError, OSError, KeyError, TypeError, IndexError) as exc:
            row["MissingReason"] = str(exc)[:250]
        rows.append(row)
    passed = sum(x["RecoveryStatus"] ==
                 "THREE_ORIGINALS_RESEARCH_MATCH" for x in rows)
    direct = sum(x.get("SelectedSourceRole") ==
                 "MORNING_DIRECT_VERIFIED" for x in rows)
    fallback = sum(x.get("SelectedSourceRole") ==
                   "EVENING_ORIGINAL_RESEARCH_FALLBACK" for x in rows)
    report = {
        "Status": ("RESEARCH_THREE_ORIGINALS_68_COMPLETE_NO_FORMAL"
                   if passed == EXPECTED else
                   "RESEARCH_THREE_ORIGINALS_PARTIAL_HOLD"),
        "TargetSession": TARGET_DATE,
        "OriginalSourceUniverse": EXPECTED,
        "EligibleResearchRows": passed,
        "ResearchHolds": EXPECTED - passed,
        "MorningDirect": direct, "EveningFallback": fallback,
        "SourceAcquisitionStartedAtUTC": {
            "prior": old_meta.get("started_at"),
            "evening": eve_meta.get("started_at"),
            "morning": am_meta.get("started_at"),
        },
        "OfficialParentRawSHA256": originals,
        "FrozenPreopenLatestEligibleTime": CUTOFF.isoformat(),
        "FormalEligible": False, "NaturalCredit": 0, "OOSCredit": 0,
        "CanonicalPredictionWritten": False,
        "IssuerActionsFullyVerified": False,
        "CashTradingAuthorized": False,
        "NeverTreatThreeFilesAsOneProviderOriginal": True,
        "Rows": rows,
    }
    resultdir.mkdir(parents=True, exist_ok=True)
    j = resultdir / "three_original_research_68.json"
    j.write_text(json.dumps(report, ensure_ascii=False, indent=2,
                            allow_nan=False) + "\n", encoding="utf8")
    md = [
        "# 2026-10-14｜68檔三份原始來源研究復原（禁止正式升格）",
        "", f"已核對 {passed}/68；早晨原始來源 {direct}/68；"
        f"前一晚研究備援 {fallback}/68；HOLD {EXPECTED-passed}。",
        "每檔三個原始檔各自保留SHA256和取得時間；沒有偽造單一68/68來源。",
        "Formal/Natural/OOS=0，Cash不可下單，正式公司行動/封存仍需獨立通過。",
        "", "|代號|官方中文名|10/13官方前收|來源|結果|",
        "|---|---|---:|---|---|",
    ]
    for x in rows:
        close = x.get("CurrentOfficialClose")
        md.append("| " + " | ".join([
            x["Symbol"], x["OfficialName"] or "MISSING",
            f"{close:.2f}" if good(close) else "MISSING",
            x.get("SelectedSourceRole", "HOLD"),
            x["RecoveryStatus"] if x["RecoveryStatus"].startswith("THREE_")
            else "HOLD:" + str(x.get("MissingReason", "UNKNOWN")),
        ]) + " |")
    (resultdir / "three_original_research_68.md").write_text(
        "\n".join(md) + "\n", encoding="utf8")
    confirmed = json.loads(j.read_bytes())
    guard(confirmed["EligibleResearchRows"] == passed
          and confirmed["OriginalSourceUniverse"] == EXPECTED,
          "THREE_ORIGINAL_REPORT_READBACK_MISMATCH")
    print(json.dumps({x: report[x] for x in (
        "Status", "EligibleResearchRows", "MorningDirect",
        "EveningFallback", "ResearchHolds", "FormalEligible",
        "CanonicalPredictionWritten")}, ensure_ascii=False))
    return 0 if passed == EXPECTED else 2


def selftest() -> int:
    import copy
    def synth(prev=100, curr=95, morning_missing=True):
        symbol = "2330.TW"
        dates = [dt.datetime(2026, 9, 20 + i, 9, tzinfo=TZ)
                 for i in range(9)]
        dates += [dt.datetime(2026, 10, 8, 9, tzinfo=TZ),
                  dt.datetime(2026, 10, 12, 9, tzinfo=TZ),
                  dt.datetime(2026, 10, 13, 9, tzinfo=TZ)]
        times = [int(x.timestamp()) for x in dates]
        def pack(vals):
            return json.dumps({"chart": {"error": None, "result": [{
                "meta": {"symbol": symbol}, "timestamp": times,
                "indicators": {"quote": [{"close": vals}],
                               "adjclose": [{"adjclose": vals}]}
            }]}}, separators=(",", ":")).encode("utf8")
        a = pack([105]*10 + [prev, None])
        b = pack([105]*10 + [None, curr])
        c = pack([105]*10 + [None, None if morning_missing else curr])
        return a, b, c, symbol
    a, b, c, symbol = synth()
    tests = {}
    def check(name, fn, reject=False):
        try:
            ok = fn()
            tests[name] = "PASS" if not reject and ok else "FAIL"
        except (ValueError, TypeError, KeyError, IndexError):
            tests[name] = "PASS" if reject else "FAIL"
    check("evening_fallback_if_morning_null",
          lambda: reconcile_originals(a,b,c,symbol,100,95)
          ["SelectedSourceRole"] == "EVENING_ORIGINAL_RESEARCH_FALLBACK")
    check("fallback_preserves_valid_close",
          lambda: reconcile_originals(a,b,c,symbol,100,95)
          ["SelectedDayAdjustedClose"] == 95)
    check("no_formal_promotion",
          lambda: not reconcile_originals(a,b,c,symbol,100,95)
          ["FormalEligible"])
    check("no_oos_credit",
          lambda: reconcile_originals(a,b,c,symbol,100,95)
          ["OOSCredit"] == 0)
    a,b,c,symbol=synth(morning_missing=False)
    check("morning_preferred_if_complete",
          lambda: reconcile_originals(a,b,c,symbol,100,95)
          ["SelectedSourceRole"] == "MORNING_DIRECT_VERIFIED")
    a,b,c,symbol=synth()
    check("reject_wrong_previous_official",
          lambda: reconcile_originals(a,b,c,symbol,110,95),True)
    check("reject_wrong_current_official",
          lambda: reconcile_originals(a,b,c,symbol,100,94),True)
    bad=json.loads(c);bad["chart"]["result"][0]["indicators"]["quote"][0]["close"][0]=200
    check("reject_morning_historical_conflict",
          lambda: reconcile_originals(a,b,json.dumps(bad).encode(),symbol,100,95),True)
    bad=json.loads(c);bad["chart"]["result"][0]["meta"]["symbol"]="WRONG.TW"
    check("reject_wrong_morning_symbol",
          lambda: reconcile_originals(a,b,json.dumps(bad).encode(),symbol,100,95),True)
    bad=json.loads(b);bad["chart"]["result"][0]["meta"]["symbol"]="WRONG.TW"
    check("reject_wrong_evening_symbol",
          lambda: reconcile_originals(a,json.dumps(bad).encode(),c,symbol,100,95),True)
    bad=json.loads(c);bad["chart"]["result"][0]["indicators"].pop("adjclose")
    check("reject_missing_morning_adjusted_array",
          lambda: reconcile_originals(a,b,json.dumps(bad).encode(),symbol,100,95),True)
    bad=json.loads(c);bad["chart"]["result"][0]["indicators"]["quote"][0]["close"][-1]=96
    check("reject_partial_morning_current_conflict",
          lambda: reconcile_originals(a,b,json.dumps(bad).encode(),symbol,100,95),True)
    status="PASS" if len(tests)==12 and all(x=="PASS" for x in tests.values()) else "FAIL"
    result={"status":status,"total":len(tests),
            "passed":sum(x=="PASS" for x in tests.values()),
            "scope":"SYNTHETIC_THREE_IMMUTABLE_ORIGINALS_RESEARCH_ONLY",
            "tests":tests}
    print(json.dumps(result,ensure_ascii=False))
    return 0 if status=="PASS" else 2


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--self-test",action="store_true")
    ap.add_argument("--prior-dir")
    ap.add_argument("--evening-dir")
    ap.add_argument("--morning-dir")
    ap.add_argument("--out")
    args=ap.parse_args()
    if args.self_test:return selftest()
    if not all((args.prior_dir,args.evening_dir,
                args.morning_dir,args.out)):
        ap.error("--prior-dir --evening-dir --morning-dir --out required")
    return run(args.prior_dir,args.evening_dir,args.morning_dir,args.out)

if __name__=="__main__":
    raise SystemExit(main())
