#!/usr/bin/env python3
"""Fail-closed, research-only point-in-time gate for TWSE/TPEx flow snapshots.

The public historical date is NOT a timestamp proving what a scheduled worker
could see at 08:10 or 19:00. The first observed complete raw snapshot is the
earliest usable evidence unless an independently verified earlier archive is
supplied. This module NEVER grants Formal, Natural, OOS or trade eligibility.

Usage: python scripts/stock_factor_vintage_gate_20261111.py input.json
The input is a JSON object with decision_at, role and snapshots. Output is a
JSON diagnostic on stdout. No network, file write, or model changes occur.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

TAIPEI = ZoneInfo("Asia/Taipei")
HEX_SHA = re.compile(r"[0-9a-f]{64}\Z")
ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}\Z")

# These are distinct report/product identities, not synonyms or a time series
# of interchangeable versions. Paid files require separately held provenance.
SOURCES = {
    "TWSE_T86_WEB": ("TWSE", "INSTITUTIONAL", "WEB_BLOCK_SCOPE_UNVERIFIED"),
    "TWSE_TWT86UC": ("TWSE", "INSTITUTIONAL", "EXCLUDING_BLOCK_TRADES"),
    "TWSE_TWTAIUC": ("TWSE", "INSTITUTIONAL", "INCLUDING_BLOCK_TRADES"),
    "TWSE_MI_MARGN": ("TWSE", "MARGIN", "TODAY_BALANCE_PROVISIONAL"),
    "TWSE_MI_MARGN_FINAL": ("TWSE", "MARGIN", "PREVIOUS_BALANCE_FINAL"),
    "TPEX_MARGIN": ("TPEX", "MARGIN", "TPEX_REPORTED"),
    "TPEX_INSTITUTIONAL": ("TPEX", "INSTITUTIONAL", "TPEX_REPORTED"),
}
ROLES = {"PREMARKET_0810", "SETTLEMENT_1900"}


class VintageError(ValueError):
    """Malformed source evidence; distinct from an ordinary availability HOLD."""


def _timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise VintageError("INVALID_" + field)
    try:
        x = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise VintageError("INVALID_" + field) from exc
    if x.tzinfo is None or x.utcoffset() is None:
        raise VintageError("NAIVE_" + field)
    return x.astimezone(TAIPEI)


def _date(value: Any, field: str) -> date:
    if not isinstance(value, str) or not ISO_DATE.fullmatch(value):
        raise VintageError("INVALID_" + field)
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise VintageError("INVALID_" + field) from exc


def classify(snapshot: dict[str, Any], *, decision_at: str, role: str) -> dict:
    """Return an auditable research decision, never a production qualification."""
    if role not in ROLES:
        raise VintageError("UNKNOWN_DECISION_ROLE")
    if not isinstance(snapshot, dict):
        raise VintageError("SNAPSHOT_NOT_OBJECT")
    cutoff = _timestamp(decision_at, "DECISION_AT")
    seen = _timestamp(snapshot.get("observed_at"), "OBSERVED_AT")
    trade_date = _date(snapshot.get("trade_date"), "TRADE_DATE")
    source = snapshot.get("source")
    if not isinstance(source, str) or source not in SOURCES:
        raise VintageError("UNREGISTERED_SOURCE")
    market, kind, version = SOURCES[source]
    if any(snapshot.get(k) != expected for k, expected in
           (("market", market), ("kind", kind), ("version", version))):
        raise VintageError("MARKET_KIND_VERSION_CONFLICT")
    published = snapshot.get("published_at")
    publication = _timestamp(published, "PUBLISHED_AT") if published is not None else None
    if publication is not None and publication > seen:
        raise VintageError("PUBLICATION_AFTER_CAPTURE")

    sha = snapshot.get("raw_sha256")
    digest_ok = isinstance(sha, str) and bool(HEX_SHA.fullmatch(sha))
    reasons: list[str] = []
    if role == "PREMARKET_0810" and trade_date >= cutoff.date():
        reasons.append("PREMARKET_SOURCE_DATE_NOT_PRIOR")
    if role == "SETTLEMENT_1900" and trade_date > cutoff.date():
        reasons.append("FUTURE_TRADE_DATE")
    if seen > cutoff:
        reasons.append("NOT_YET_OBSERVED_AT_DECISION")
    if publication is not None and publication > cutoff:
        reasons.append("NOT_YET_PUBLISHED_AT_DECISION")
    if not digest_ok:
        reasons.append("COMPLETE_RAW_SHA_MISSING")
    if source == "TWSE_MI_MARGN_FINAL" and seen.date() <= trade_date:
        reasons.append("FINAL_MARGIN_BALANCE_NOT_NEXT_DAY")
    # A claimed paid 20:00 (or 18:00) file captured earlier the same day is
    # internally inconsistent even if evaluated at tomorrow's decision time.
    if source == "TWSE_TWTAIUC" and seen.date() == trade_date and seen.hour < 20:
        reasons.append("TWENTY_HOUR_PRODUCT_NOT_YET_PRODUCED_AT_CAPTURE")
    if source == "TWSE_TWT86UC" and seen.date() == trade_date and seen.hour < 18:
        reasons.append("EIGHTEEN_HOUR_PRODUCT_NOT_YET_PRODUCED_AT_CAPTURE")

    caveats = []
    if source == "TWSE_T86_WEB":
        caveats.append("WEB_T86_NOT_IDENTICAL_TO_PAID_18_OR_20_VERSION")
    if source == "TWSE_MI_MARGN":
        caveats.append("TODAY_BALANCE_MAY_BE_REVISED_NEXT_DAY")
    if publication is None:
        caveats.append("EXACT_EXCHANGE_PUBLICATION_TIME_UNVERIFIED")

    return {
        "source": source,
        "market": market,
        "kind": kind,
        "version": version,
        "trade_date": trade_date.isoformat(),
        "observed_at": seen.isoformat(),
        "decision_at": cutoff.isoformat(),
        "role": role,
        "research_status": "PIT_RESEARCH_SNAPSHOT_ADMISSIBLE" if not reasons else "HOLD",
        "hold_reasons": reasons,
        "caveats": caveats,
        "formal_eligible": False,
        "natural_credit": 0,
        "oos_credit": 0,
        "model_weight_changed": False,
    }


def audit(payload: dict[str, Any]) -> dict:
    if not isinstance(payload, dict):
        raise VintageError("PAYLOAD_NOT_OBJECT")
    xs = payload.get("snapshots")
    if not isinstance(xs, list) or not 1 <= len(xs) <= 1000:
        raise VintageError("BAD_SNAPSHOT_COUNT")
    role = payload.get("role")
    cutoff = payload.get("decision_at")
    results = [classify(s, decision_at=cutoff, role=role) for s in xs]
    keys = [(r["source"], r["trade_date"], r["version"], r["observed_at"])
            for r in results]
    if len(keys) != len(set(keys)):
        raise VintageError("DUPLICATE_SNAPSHOT_VERSION")
    return {
        "status": "RESEARCH_AUDIT_ONLY",
        "decision_at": _timestamp(cutoff, "DECISION_AT").isoformat(),
        "role": role,
        "research_admissible": sum(r["research_status"] != "HOLD" for r in results),
        "held": sum(r["research_status"] == "HOLD" for r in results),
        "formal_natural_oos_credit": 0,
        "model_automatically_updated": False,
        "rows": results,
    }


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: stock_factor_vintage_gate_20261111.py INPUT.json")
    data = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    print(json.dumps(audit(data), ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
