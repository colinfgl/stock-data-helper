#!/usr/bin/env python3
"""Fail-closed, non-mutating research report metric lineage guard.

PUBLIC CODE ONLY. No portfolio, brokerage, sealed user predictions, or private
reports are included in this repository. CLI accepts caller-provided JSON with
explicit original RunID, date, source tier and per-symbol prediction lineage.
It does not generate forecasts, change schedules, place orders, promote Formal,
or write any Google Sheets. Runtime integration requires a future governed gate.
"""
from __future__ import annotations
import argparse
import json
import math
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

METRIC_FIELDS = ("RAW_MAPE_PCT", "UNCHANGED_PRICE_BASELINE_MAPE_PCT", "ADJUSTED_MAPE_PCT")
PREDICTION_KINDS = ("RAW", "ADJUSTED")

class MetricLineageError(ValueError):
    pass


def d(value: Any, *, field: str) -> Decimal:
    if isinstance(value, bool) or value is None:
        raise MetricLineageError(f"NOT_NUMERIC:{field}")
    try:
        x = Decimal(str(value))
    except (InvalidOperation, ValueError) as e:
        raise MetricLineageError(f"NOT_NUMERIC:{field}") from e
    if not x.is_finite():
        raise MetricLineageError(f"NONFINITE:{field}")
    return x


def optional(value: Any, field: str) -> Decimal | None:
    if value is None or value == "MISSING":
        return None
    return d(value, field=field)


def direction(current: Decimal, base: Decimal, material_threshold: Decimal) -> int:
    diff = current - base
    if abs(diff) <= abs(base) * material_threshold:
        return 0
    return 1 if diff > 0 else -1


def audit(payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise MetricLineageError("PAYLOAD_NOT_OBJECT")
    target = payload.get("target_date")
    run_id = payload.get("original_run_id")
    if not isinstance(target, str) or len(target) != 10 or not isinstance(run_id, str) or not run_id:
        raise MetricLineageError("MISSING_TARGET_OR_RUN_ID")
    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise MetricLineageError("EMPTY_COHORT")
    if len(rows) > 5000:
        raise MetricLineageError("COHORT_OVERSIZE")
    threshold = d(payload.get("material_direction_threshold_pct", "0.005"), field="direction_threshold_pct")
    if threshold < 0 or threshold > Decimal("0.1"):
        raise MetricLineageError("UNAPPROVED_DIRECTION_THRESHOLD")
    flags=[]
    seen=set()
    matured=[]
    for i,row in enumerate(rows):
        if not isinstance(row, dict):
            raise MetricLineageError("ROW_NOT_OBJECT")
        sym = row.get("symbol")
        if not isinstance(sym,str) or not sym:
            raise MetricLineageError(f"MISSING_SYMBOL:{i}")
        if sym in seen:
            raise MetricLineageError(f"DUPLICATE_SYMBOL:{sym}")
        seen.add(sym)
        if row.get("target_date") != target:
            raise MetricLineageError(f"TARGET_DATE_DRIFT:{sym}")
        if row.get("prediction_run_id") != run_id:
            raise MetricLineageError(f"PREDICTION_RUN_DRIFT:{sym}")
        if row.get("prediction_kind") != "ORIGINALLY_FROZEN_STUDY":
            raise MetricLineageError(f"INVALID_STUDY_PREDICTION_KIND:{sym}")
        prev=d(row.get("previous_close"),field=f"previous_close:{sym}")
        if prev <= 0:
            raise MetricLineageError(f"INVALID_PREVIOUS_CLOSE:{sym}")
        raw=optional(row.get("raw_point"),f"RAW:{sym}")
        adj=optional(row.get("adjusted_point"),f"ADJUSTED:{sym}")
        actual=optional(row.get("actual_official_close"),f"ACTUAL:{sym}")
        if actual is None:
            flags.append(f"PENDING_ACTUAL:{sym}")
            continue
        if actual<=0:
            raise MetricLineageError(f"INVALID_ACTUAL:{sym}")
        matured.append({"symbol":sym,"previous":prev,"raw":raw,"adjusted":adj,"actual":actual})
    base=len(matured)
    if base==0:
        raise MetricLineageError("NO_MATURED_OUTCOMES")
    if "matured_n" in payload and payload["matured_n"] != base:
        raise MetricLineageError("MISLABELED_COHORT_N")

    def compute(key: str):
        v=[r for r in matured if r[key] is not None]
        # All metrics must refer to the SAME physical mature cohort; mixed N not comparable.
        if len(v)!=base:
            return None,len(v)
        e=sum(abs(r[key]-r["actual"])/r["previous"] for r in v)/Decimal(base)*Decimal(100)
        return e,len(v)

    raw,nraw=compute("raw")
    adjusted,nadj=compute("adjusted")
    baseline=sum(abs(r["previous"]-r["actual"])/r["previous"] for r in matured)/Decimal(base)*Decimal(100)
    values={"RAW_MAPE_PCT":raw,"UNCHANGED_PRICE_BASELINE_MAPE_PCT":baseline,"ADJUSTED_MAPE_PCT":adjusted}
    sizes={"RAW_N":nraw,"BASELINE_N":base,"ADJUSTED_N":nadj}
    reported=payload.get("reported_metrics",{})
    if not isinstance(reported,dict):
        raise MetricLineageError("INVALID_REPORTED_METRICS")
    for key in reported:
        if key not in METRIC_FIELDS:
            raise MetricLineageError("UNKNOWN_METRIC_KEY:"+str(key))
        got=reported[key]
        truth=values[key]
        if truth is None:
            if got is not None and got!="MISSING":
                raise MetricLineageError("FORECAST_LINEAGE_MISSING_NO_FALLBACK:"+key)
        elif got is None or got=="MISSING":
            raise MetricLineageError("EXISTING_PREDICTION_WRONGLY_MARKED_MISSING:"+key)
        elif abs(d(got,field=key)-truth) > Decimal("0.001"):
            raise MetricLineageError("METRIC_VALUES_MISMATCH:"+key)
    for key in METRIC_FIELDS:
        if key not in reported:
            flags.append("NOT_REPORTED:"+key)

    index=payload.get("index_comparison")
    idx_result=None
    if index is not None:
        if not isinstance(index,dict):
            raise MetricLineageError("BAD_INDEX_SECTION")
        prev=d(index.get("previous_close"),field="index_previous")
        actual=d(index.get("actual_close"),field="index_actual")
        if prev<=0 or actual<=0:
            raise MetricLineageError("BAD_INDEX_PRICE")
        raw=optional(index.get("raw_prediction"),"index_raw")
        adj=optional(index.get("adjusted_prediction"),"index_adjusted")
        actdir=direction(actual,prev,threshold)
        dir_raw=None if raw is None else direction(raw,prev,threshold)
        dir_adj=None if adj is None else direction(adj,prev,threshold)
        idx_result={"actual_direction":actdir,"RAW_DIRECTION_HIT":None if dir_raw is None else dir_raw==actdir,
                    "ADJUSTED_DIRECTION_HIT":None if dir_adj is None else dir_adj==actdir}
        for name in ("RAW_DIRECTION_HIT","ADJUSTED_DIRECTION_HIT"):
            if name in index:
                if index[name] != idx_result[name]:
                    raise MetricLineageError("INDEX_DIRECTION_LABEL_INVERTED:"+name)
    if payload.get("research_only") is not True:
        raise MetricLineageError("PRODUCTION_STATUS_UNVERIFIED_BLOCK")
    if payload.get("formal_eligible") is True or payload.get("natural_eligible") is True or payload.get("oos_eligible") is True:
        raise MetricLineageError("RESEARCH_DIAGNOSTIC_MUST_NOT_GRANT_FORMAL_NATURAL_OOS")
    return {"status":"RESEARCH_METRIC_LINEAGE_PASS", "target_date":target,"original_run_id":run_id,
            "universe_n":len(rows),"matured_n":base,"series_coverage":sizes,
            "metrics":{k:(None if x is None else round(float(x),8)) for k,x in values.items()},
            "index_direction":idx_result,"warnings":flags,
            "formal_eligible":False,"natural_eligible":False,"oos_eligible":False}


def test():
    def fixture():
        return {"target_date":"2026-01-05","original_run_id":"TEST-FROZEN","material_direction_threshold_pct":"0.0",
                "research_only":True,"formal_eligible":False,"natural_eligible":False,"oos_eligible":False,"matured_n":2,
                "rows":[
                    {"symbol":"SAMPLE-A","target_date":"2026-01-05","prediction_run_id":"TEST-FROZEN","prediction_kind":"ORIGINALLY_FROZEN_STUDY","previous_close":100,"raw_point":105,"adjusted_point":None,"actual_official_close":103},
                    {"symbol":"SAMPLE-B","target_date":"2026-01-05","prediction_run_id":"TEST-FROZEN","prediction_kind":"ORIGINALLY_FROZEN_STUDY","previous_close":200,"raw_point":198,"adjusted_point":None,"actual_official_close":194}
                ],"reported_metrics":{"RAW_MAPE_PCT":2,"UNCHANGED_PRICE_BASELINE_MAPE_PCT":3,"ADJUSTED_MAPE_PCT":"MISSING"},
                "index_comparison":{"previous_close":1000,"actual_close":990,"raw_prediction":1010,"adjusted_prediction":980,"RAW_DIRECTION_HIT":False,"ADJUSTED_DIRECTION_HIT":True}}
    passed=[]
    def run(name, change, good=False):
        p=fixture();change(p)
        try:
            res=audit(p)
            if not good:
                raise AssertionError("BUG_NOT_DETECTED:"+name)
        except MetricLineageError as err:
            if good:raise AssertionError(name+":"+str(err)) from err
        passed.append(name)
    # fixture RAW MAPE: (|103-105|/100 + |194-198|/200)/2*100 =2
    # no-change baseline: (3/100 + 6/200)/2*100 =3
    run("01_valid_synthetic_cohort",lambda p:None,good=True)
    run("02_numeric_adjusted_without_adjusted_forecast",lambda p:p["reported_metrics"].update(ADJUSTED_MAPE_PCT=3.0))
    run("03_raw_marked_missing_although_present",lambda p:p["reported_metrics"].update(RAW_MAPE_PCT="MISSING"))
    run("04_raw_uses_baseline_unlawfully",lambda p:p["reported_metrics"].update(RAW_MAPE_PCT=3.0))
    run("05_duplicate_stock",lambda p:p["rows"][1].update(symbol="SAMPLE-A"))
    run("06_target_date_mismatch",lambda p:p["rows"][0].update(target_date="2026-01-06"))
    run("07_runid_mismatch",lambda p:p["rows"][0].update(prediction_run_id="SOME-OTHER-RUN"))
    run("08_index_raw_direction_inverted",lambda p:p["index_comparison"].update(RAW_DIRECTION_HIT=True))
    run("09_index_adjusted_direction_inverted",lambda p:p["index_comparison"].update(ADJUSTED_DIRECTION_HIT=False))
    run("10_false_formal_promote",lambda p:p.update(formal_eligible=True))
    run("11_false_natural_promote",lambda p:p.update(natural_eligible=True))
    run("12_bad_previous_close",lambda p:p["rows"][0].update(previous_close=0))
    run("13_nonfinite_prediction",lambda p:p["rows"][0].update(raw_point="NaN"))
    run("14_bad_matured_n",lambda p:p.update(matured_n=3))
    run("15_unknown_metric",lambda p:p["reported_metrics"].update(MADE_UP_SCORE=99))
    run("16_partial_raw_should_not_be_scored",lambda p:p["rows"][0].update(raw_point=None))
    run("17_invalid_prediction_kind",lambda p:p["rows"][1].update(prediction_kind="AFTER_OUTCOME_REBUILT"))
    run("18_false_oos_promote",lambda p:p.update(oos_eligible=True))
    run("19_production_status_unknown",lambda p:p.update(research_only=False))
    run("20_actual_missing_matured_n_stale",lambda p:p["rows"][1].update(actual_official_close=None))
    return {"status":"PASS","tests":len(passed),"passed":passed,"production_installed":False,"historical_forecast_changed":False}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group(required=True)
    g.add_argument("--self-test", action="store_true")
    g.add_argument("--input",type=Path)
    p.add_argument("--output",type=Path)
    args=p.parse_args()
    try:
        result=test() if args.self_test else audit(json.loads(args.input.read_text(encoding="utf8")))
    except (MetricLineageError,AssertionError) as e:
        result={"status":"BLOCKED","error":str(e),"production_installed":False}
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 2
    output=json.dumps(result,ensure_ascii=False,indent=2)+"\n"
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(output,encoding="utf8")
    print(output,end="")
    return 0

if __name__=="__main__":raise SystemExit(main())