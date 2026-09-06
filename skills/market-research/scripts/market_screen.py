#!/usr/bin/env python3
"""Screen saved Alpaca daily price evidence with declared, deterministic rules.

Reads one JSON bundle and prints one JSON result; no network, credentials,
trades, caches or vault writes. Exit 2 denotes invalid or incomplete evidence.
Daily VWAP times volume is a discovery proxy, not regular-session liquidity.
"""

from __future__ import annotations

import argparse
import calendar
from datetime import datetime, time, timedelta, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sys
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import DataError, parse_date, parse_time


SYMBOL = re.compile(r"[A-Z][A-Z0-9./-]{0,19}\Z")
MAX_INPUT_BYTES = 128 * 1024 * 1024
DEFAULT_RULES = {
    "min_price": 5, "min_average_daily_notional": 20000000,
    "require_above_ma50": True, "require_above_ma200": True,
    "require_positive_relative_return_6m": True,
    "sort_by": "relative_return_6m", "limit": 50,
}
SORT_FIELDS = (
    "relative_return_3m", "relative_return_6m", "relative_return_12m",
    "return_3m", "return_6m", "return_12m", "average_daily_notional",
)
US_EXCHANGES = (
    "NASDAQ", "NYSE", "NYSE AMERICAN", "NYSE ARCA", "CBOE BZX", "CBOE",
    "AMEX", "ARCA", "BATS", "NYSEAMERICAN", "NYSEARCA",
    "XNAS", "XNYS", "XASE", "ARCX",
)
WARNINGS = [
    "A passing discovery screen is not a buying recommendation or a thesis state.",
    "Daily VWAP times volume includes eligible extended-hours activity; verify regular-session liquidity before readiness.",
    "Daily OHLC and volume have different trade eligibility rules; daily volume is not regular-session-only volume.",
    "Split-adjusted price returns are not total returns. Provider history may reflect later corporate actions.",
    "Saved universe membership, ticker mapping dates and adjusted history do not establish information available at a historical cutoff.",
]


def _fail(message):
    raise DataError("invalid_input", message)


def _text(value, label, maximum=2000):
    if (not isinstance(value, str) or not value.strip() or len(value) > maximum
            or any(ord(c) < 32 for c in value)):
        _fail("Invalid " + label + ".")
    return value


def _symbol(value):
    if not isinstance(value, str) or not SYMBOL.fullmatch(value):
        _fail("Invalid provider symbol.")
    return value


def _number(value, *, positive=False):
    try:
        valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                 and math.isfinite(value) and (value > 0 if positive else value >= 0))
    except (OverflowError, ValueError):
        valid = False
    if not valid:
        _fail("Prices, volumes and thresholds must be finite numbers in their declared ranges.")
    return value


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    ensure_ascii=False, allow_nan=False).encode("utf-8")).hexdigest()


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("Duplicate JSON object keys are not allowed.")
        result[key] = value
    return result


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _anniversary(day, months):
    year, month0 = divmod(day.year * 12 + day.month - 1 - months, 12)
    return day.replace(year=year, month=month0 + 1,
                       day=min(day.day, calendar.monthrange(year, month0 + 1)[1]))


def _envelope(value, operation, resource):
    if (not isinstance(value, dict) or type(value.get("market_data")) is not int
            or value["market_data"] != 1 or value.get("operation") != operation
            or value.get("provider") != "alpaca" or value.get("resource") != resource
            or not isinstance(value.get("complete"), bool)
            or not isinstance(value.get("query"), dict) or not isinstance(value.get("data"), dict)
            or not isinstance(value.get("source"), dict)):
        _fail("Use full saved market_data response envelopes for prices and sessions.")
    warnings = value.get("warnings", [])
    if not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
        _fail("Invalid source warnings.")
    requests = value.get("requests", [])
    if not isinstance(requests, list):
        _fail("Invalid source request provenance.")
    return value


def _calendar(envelope, cutoff):
    envelope = _envelope(envelope, "sessions", "calendar")
    if not envelope["complete"]:
        raise DataError("incomplete_data", "A complete declared exchange calendar is required.")
    start, end = parse_date(envelope["query"].get("start")), parse_date(envelope["query"].get("end"))
    ny = ZoneInfo("America/New_York")
    if start > end or end < cutoff.astimezone(ny).date():
        raise DataError("incomplete_data", "Calendar coverage must extend through the cutoff date.")
    rows = envelope["data"].get("sessions")
    if not isinstance(rows, list):
        _fail("Invalid calendar sessions.")
    sessions, seen = [], set()
    for row in rows:
        if not isinstance(row, dict):
            _fail("Invalid calendar session.")
        day = parse_date(row.get("date"))
        opened, closed = parse_time(row.get("open_at")), parse_time(row.get("close_at"))
        if (day in seen or not start <= day <= end or opened >= closed
                or opened.astimezone(ny).date() != day or closed.astimezone(ny).date() != day):
            _fail("Duplicate, inconsistent or out-of-range calendar session.")
        seen.add(day)
        interval_end = datetime.combine(day + timedelta(days=1), time.min, ny)
        if closed <= cutoff and interval_end <= cutoff:
            sessions.append(day)
    sessions.sort()
    if not sessions:
        raise DataError("incomplete_data", "No fully elapsed daily session is available at the cutoff.")
    reference = sessions[-1]
    anchors = {}
    for months in (3, 6, 12):
        target = _anniversary(reference, months)
        preceding = [day for day in sessions if day <= target]
        if start > target or not preceding:
            raise DataError("incomplete_data", "Calendar must include each anniversary and its preceding session; retrieve at least 13 months.")
        anchors[months] = preceding[-1]
    if len(sessions) < 220:
        raise DataError("incomplete_data", "At least 220 completed scheduled sessions are required for moving-average changes.")
    first = min(anchors[12], sessions[-220])
    return reference, anchors, [day for day in sessions if day >= first], seen


def _prices(envelopes, cutoff, calendar_dates):
    if not isinstance(envelopes, list) or not 1 <= len(envelopes) <= 200:
        _fail("Provide 1–200 saved price response objects.")
    ny = ZoneInfo("America/New_York")
    bars, requested, warnings, provenance = {}, set(), [], []
    mapping_date = None
    complete, ignored = True, 0
    for envelope in envelopes:
        envelope = _envelope(envelope, "prices", "bars")
        query = envelope["query"]
        if (query.get("feed") != "sip" or envelope["source"].get("feed") != "sip"
                or query.get("timeframe") != "1Day" or query.get("adjustment") != "split"
                or query.get("currency") != "USD"):
            _fail("All price batches must use Alpaca SIP, USD, split-adjusted 1Day bars.")
        asof = parse_date(query.get("asof"))
        if mapping_date is not None and mapping_date != asof:
            _fail("Price batches use different symbol-mapping dates.")
        mapping_date = asof
        start, end = parse_time(query.get("start")), parse_time(query.get("end"))
        requested_end = parse_time(query.get("requested_end"))
        if start > end or end > requested_end:
            _fail("Invalid price query interval.")
        symbols = envelope["data"].get("requested_symbols")
        values = envelope["data"].get("bars")
        if (not isinstance(symbols, list) or not 1 <= len(symbols) <= 200
                or any(not isinstance(s, str) for s in symbols) or len(set(symbols)) != len(symbols)
                or not isinstance(values, dict) or set(values) - set(symbols)):
            _fail("Invalid requested symbols or price rows.")
        if query.get("symbols") != ",".join(symbols):
            _fail("Price query symbols disagree with the response's requested symbols.")
        for symbol in symbols:
            _symbol(symbol)
            requested.add(symbol)
            by_date = bars.setdefault(symbol, {})
            rows = values.get(symbol, [])
            if not isinstance(rows, list):
                _fail("Invalid symbol price rows.")
            for row in rows:
                if not isinstance(row, dict):
                    _fail("Invalid daily bar.")
                stamp = parse_time(row.get("t"))
                interval_start = parse_time(row.get("interval_start"))
                interval_end = parse_time(row.get("interval_end"))
                day = parse_date(row.get("new_york_date"))
                expected_start = datetime.combine(day, time.min, ny)
                expected_end = datetime.combine(day + timedelta(days=1), time.min, ny)
                if (stamp != interval_start or stamp != expected_start or interval_end != expected_end
                        or not start <= stamp <= end):
                    _fail("Daily bar boundaries do not match the query or New York date.")
                for key in ("o", "h", "l", "c", "vw"):
                    _number(row.get(key), positive=True)
                _number(row.get("v"))
                if row["l"] > min(row["o"], row["c"]) or row["h"] < max(row["o"], row["c"]):
                    _fail("Invalid daily OHLC range.")
                if interval_end > cutoff:
                    ignored += 1
                    continue
                if day not in calendar_dates:
                    _fail("A completed daily bar has no session in the supplied calendar.")
                normalized = {key: row[key] for key in ("o", "h", "l", "c", "vw", "v")}
                if day in by_date and by_date[day] != normalized:
                    _fail("Conflicting duplicate daily bars; reconcile the saved evidence.")
                by_date[day] = normalized
        complete = complete and envelope["complete"]
        warnings.extend(envelope.get("warnings", []))
        provenance.append({"query": query, "source": envelope["source"],
                           "requests": envelope.get("requests", []), "complete": envelope["complete"],
                           "sha256": _digest(envelope)})
    return bars, requested, complete, warnings, provenance, ignored, mapping_date


def _metrics(rows, dates, anchors):
    closes = [rows[day]["c"] for day in dates]
    result = {"price": closes[-1]}
    for months, day in anchors.items():
        result["return_%dm" % months] = closes[-1] / rows[day]["c"] - 1
    for length in (50, 200):
        average = math.fsum(closes[-length:]) / length
        prior = math.fsum(closes[-length - 20:-20]) / length
        result["ma%d" % length] = average
        result["ma%d_change_20_sessions" % length] = average / prior - 1
    result["average_daily_notional"] = math.fsum(rows[d]["vw"] * rows[d]["v"] for d in dates[-20:]) / 20
    if any(not math.isfinite(value) for value in result.values()):
        _fail("Computed metrics overflowed; inspect the supplied values.")
    return result


def screen(bundle):
    """Calculate from saved envelopes, binding the result to this source's digest."""
    if not isinstance(bundle, dict) or type(bundle.get("market_screen_input")) is not int or bundle["market_screen_input"] != 1:
        _fail("Use market_screen_input version 1.")
    cutoff = parse_time(bundle.get("as_of"))
    universe = bundle.get("universe")
    if not isinstance(universe, dict):
        _fail("Provide a declared instrument universe.")
    _text(universe.get("name"), "universe name")
    _text(universe.get("source"), "universe source")
    membership = parse_date(universe.get("membership_date"))
    instruments = universe.get("instruments")
    if not isinstance(instruments, list) or not 1 <= len(instruments) <= 20000:
        _fail("Provide 1–20000 declared universe instruments.")
    seen = set()
    for item in instruments:
        if not isinstance(item, dict):
            _fail("Invalid universe instrument.")
        symbol = _symbol(item.get("symbol"))
        if symbol in seen:
            _fail("Universe symbols must be unique and unambiguous across exchanges.")
        seen.add(symbol)
        for key in ("exchange", "security_type", "currency"):
            _text(item.get(key), "instrument " + key, 100)
    benchmark = _symbol(bundle.get("benchmark"))
    supplied_rules = bundle.get("rules", {})
    if not isinstance(supplied_rules, dict) or set(supplied_rules) - set(DEFAULT_RULES):
        _fail("Invalid or unknown screen rule.")
    rules = DEFAULT_RULES | supplied_rules
    for key in ("min_price", "min_average_daily_notional"):
        _number(rules[key])
    for key in ("require_above_ma50", "require_above_ma200", "require_positive_relative_return_6m"):
        if not isinstance(rules[key], bool):
            _fail("Trend gates must be JSON booleans.")
    if rules["sort_by"] not in SORT_FIELDS or type(rules["limit"]) is not int or not 1 <= rules["limit"] <= 20000:
        _fail("Invalid sort metric or result limit.")
    reference, anchors, dates, calendar_dates = _calendar(bundle.get("sessions"), cutoff)
    bars, requested, complete, source_warnings, provenance, ignored, mapping_date = _prices(
        bundle.get("prices"), cutoff, calendar_dates)
    benchmark_rows = bars.get(benchmark, {})
    benchmark_missing = [d.isoformat() for d in dates if d not in benchmark_rows]
    benchmark_metrics = None if benchmark_missing else _metrics(benchmark_rows, dates, anchors)
    candidates, exclusions = [], []
    evaluated, unavailable, observed = 0, 0, 0
    for item in sorted(instruments, key=lambda row: (row["exchange"], row["symbol"])):
        symbol = item["symbol"]
        rows = bars.get(symbol, {})
        observed += bool(rows)
        identity = {key: item[key] for key in ("symbol", "exchange", "security_type", "currency")}
        eligibility = []
        if item["security_type"] not in ("common_stock", "adr") or item["currency"] != "USD":
            eligibility.append("unsupported_security_type_or_currency")
        if item["exchange"].upper() not in US_EXCHANGES:
            eligibility.append("unsupported_exchange")
        if eligibility:
            exclusions.append(identity | {"kind": "eligibility", "reasons": eligibility})
            evaluated += 1
            continue
        missing = [d.isoformat() for d in dates if d not in rows]
        reasons = []
        if symbol not in requested:
            reasons.append("symbol_not_requested")
        if missing:
            reasons.append("missing_required_sessions")
        if benchmark_missing:
            reasons.append("benchmark_missing_required_sessions")
        if reasons:
            unavailable += 1
            exclusions.append(identity | {"kind": "unavailable", "reasons": reasons, "missing_sessions": missing})
            continue
        metrics = _metrics(rows, dates, anchors)
        for months in (3, 6, 12):
            metrics["relative_return_%dm" % months] = metrics["return_%dm" % months] - benchmark_metrics["return_%dm" % months]
        if metrics["price"] < rules["min_price"]:
            reasons.append("below_min_price")
        if metrics["average_daily_notional"] < rules["min_average_daily_notional"]:
            reasons.append("below_min_average_daily_notional")
        for length in (50, 200):
            if rules["require_above_ma%d" % length] and metrics["price"] <= metrics["ma%d" % length]:
                reasons.append("not_above_ma%d" % length)
        if rules["require_positive_relative_return_6m"] and metrics["relative_return_6m"] <= 0:
            reasons.append("nonpositive_relative_return_6m")
        evaluated += 1
        row = identity | {"metrics": metrics}
        if reasons:
            exclusions.append(row | {"kind": "filter", "reasons": reasons})
        else:
            candidates.append(row)
    candidates.sort(key=lambda row: (-row["metrics"][rules["sort_by"]], row["exchange"], row["symbol"]))
    passing = len(candidates)
    warnings = list(WARNINGS) + source_warnings + bundle["sessions"].get("warnings", [])
    if not complete:
        warnings.append("At least one saved price response has incomplete provider coverage; passing rows remain provisional.")
    if membership > cutoff.astimezone(ZoneInfo("America/New_York")).date():
        warnings.append("Universe membership is dated after the cutoff; this is a retrospective current-universe calculation.")
    definition = {"rules": rules, "benchmark": benchmark, "return_basis": "split_adjusted_price",
                  "return_months": [3, 6, 12], "moving_average_sessions": [50, 200],
                  "moving_average_change_sessions": 20, "liquidity_sessions": 20,
                  "liquidity_basis": "mean_daily_vwap_times_volume_including_extended_hours",
                  "accepted_us_exchange_labels": list(US_EXCHANGES),
                  "metric_units": {
                      "price": "USD, split-adjusted", "ma50": "USD, split-adjusted", "ma200": "USD, split-adjusted",
                      "return_3m": "decimal fraction; 0.10 means 10 percent",
                      "return_6m": "decimal fraction; 0.10 means 10 percent",
                      "return_12m": "decimal fraction; 0.10 means 10 percent",
                      "relative_return_3m": "difference of decimal returns; 0.02 means 2 percentage points",
                      "relative_return_6m": "difference of decimal returns; 0.02 means 2 percentage points",
                      "relative_return_12m": "difference of decimal returns; 0.02 means 2 percentage points",
                      "ma50_change_20_sessions": "decimal fraction; 0.10 means 10 percent",
                      "ma200_change_20_sessions": "decimal fraction; 0.10 means 10 percent",
                      "average_daily_notional": "USD per scheduled session; daily VWAP times volume proxy"},
                  "sort_direction": "descending", "tie_break": ["exchange", "symbol"],
                  "required_history": "every supplied scheduled session from earliest required anchor through reference"}
    return {
        "market_screen": 1, "complete": complete and not unavailable and not benchmark_missing,
        "as_of": _iso(cutoff), "reference_session": reference.isoformat(),
        "input_sha256": _digest(bundle), "rules_sha256": _digest(rules),
        "calculator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "screen_sha256": _digest(definition), "definition": definition, "rules": rules,
        "universe": universe, "benchmark": {"symbol": benchmark, "metrics": benchmark_metrics,
                                              "missing_sessions": benchmark_missing},
        "windows": {"required_start": dates[0].isoformat(), "required_end": reference.isoformat(),
                    "required_sessions": len(dates), "return_start_dates": {str(k): v.isoformat() for k, v in anchors.items()},
                    "liquidity_start": dates[-20].isoformat()},
        "coverage": {"universe": len(instruments), "requested": len(seen & requested),
                     "observed": observed, "evaluated": evaluated, "unavailable": unavailable,
                     "passing": passing, "returned": min(passing, rules["limit"]),
                     "truncated": passing > rules["limit"], "ignored_unfinished_or_future_bars": ignored},
        "candidates": candidates[:rules["limit"]], "exclusions": exclusions,
        "warnings": list(dict.fromkeys(warnings)), "historical_availability": "not_established",
        "sources": {"prices": provenance, "symbol_mapping_date": mapping_date.isoformat(),
                    "sessions": {"query": bundle["sessions"]["query"], "source": bundle["sessions"]["source"],
                                 "requests": bundle["sessions"].get("requests", []), "sha256": _digest(bundle["sessions"])}}
    }


def parser():
    class SafeParser(argparse.ArgumentParser):
        def error(self, message):
            _fail("Invalid arguments; use --help for the input contract.")
    result = SafeParser(description=__doc__)
    result.add_argument("--input", metavar="PATH", help="saved market_screen_input version 1 JSON bundle (maximum 128 MiB)")
    result.add_argument("--test", action="store_true", help="run offline calculation and coverage fixtures")
    return result


def main(argv=None):
    try:
        args = parser().parse_args(argv)
        if args.test:
            return run_self_test()
        if not args.input:
            _fail("Provide --input with a saved JSON bundle.")
        path = Path(args.input)
        if not path.is_file():
            _fail("Input must be a readable regular JSON file.")
        with path.open("rb") as handle:
            raw = handle.read(MAX_INPUT_BYTES + 1)
        if len(raw) > MAX_INPUT_BYTES:
            _fail("Input exceeds the 128 MiB limit; use explicitly declared smaller universe scopes.")
        result = screen(json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                                   parse_constant=lambda value: _fail("JSON non-finite constants are not allowed.")))
        code = 0 if result["complete"] else 2
    except DataError as exc:
        result = {"market_screen": 1, "complete": False, "error": {"code": exc.code, "message": str(exc)}}
        code = 2
    except (ValueError, TypeError, KeyError, OSError, OverflowError, RecursionError):
        result = {"market_screen": 1, "complete": False, "error": {
            "code": "invalid_input", "message": "Invalid saved evidence or unreadable input; no complete screen was assumed."}}
        code = 2
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    return code


def run_self_test():
    """Offline fixtures; synthetic sessions are explicit inputs, not a calendar source."""
    import contextlib
    import copy
    import io
    import tempfile
    import unittest

    def fixture():
        ny = ZoneInfo("America/New_York")
        start, last = parse_date("2024-01-01"), parse_date("2025-03-31")
        days, day = [], start
        while day <= last:
            if day.weekday() < 5:
                days.append(day)
            day += timedelta(days=1)
        sessions = [{"date": d.isoformat(), "open_at": _iso(datetime.combine(d, time(9, 30), ny)),
                     "close_at": _iso(datetime.combine(d, time(16), ny))} for d in days]
        bars = {}
        for symbol, growth in (("AAA", 0.002), ("BBB", 0.001), ("SPY", 0.0005)):
            bars[symbol] = []
            for i, d in enumerate(days):
                price = 100 * (1 + growth) ** i
                stamp = _iso(datetime.combine(d, time.min, ny))
                bars[symbol].append({"t": stamp, "interval_start": stamp,
                    "interval_end": _iso(datetime.combine(d + timedelta(days=1), time.min, ny)),
                    "new_york_date": d.isoformat(), "o": price, "h": price, "l": price,
                    "c": price, "vw": price, "v": 1000000, "n": 100})
        prices = {"market_data": 1, "operation": "prices", "provider": "alpaca", "resource": "bars", "complete": True,
                  "query": {"start": "2024-01-01T05:00:00Z", "end": "2025-04-01T03:59:59Z",
                            "requested_end": "2025-04-01T15:30:00Z", "asof": "2025-04-01", "timeframe": "1Day",
                            "feed": "sip", "adjustment": "split", "currency": "USD"}, "source": {"feed": "sip"},
                  "data": {"requested_symbols": list(bars), "bars": bars, "missing_symbols": []}, "warnings": [], "requests": []}
        prices["query"]["symbols"] = ",".join(bars)
        return {"market_screen_input": 1, "as_of": "2025-04-01T15:30:00Z", "benchmark": "SPY", "prices": [prices],
                "sessions": {"market_data": 1, "operation": "sessions", "provider": "alpaca", "resource": "calendar",
                             "complete": True, "query": {"start": "2024-01-01", "end": "2025-04-01"}, "source": {},
                             "data": {"sessions": sessions}, "warnings": [], "requests": []},
                "universe": {"name": "Synthetic test universe", "membership_date": "2025-04-01", "source": "offline fixture",
                             "instruments": [{"symbol": s, "exchange": "NASDAQ", "security_type": "common_stock", "currency": "USD"}
                                             for s in ("AAA", "BBB")]}, "rules": {}}

    class Cases(unittest.TestCase):
        def setUp(self):
            self.bundle = fixture()

        def test_known_returns_ma_and_relative_strength(self):
            out = screen(self.bundle)
            self.assertTrue(out["complete"])
            self.assertEqual([r["symbol"] for r in out["candidates"]], ["AAA", "BBB"])
            rows = self.bundle["prices"][0]["data"]["bars"]["AAA"]
            by_date = {r["new_york_date"]: r for r in rows}
            metrics = out["candidates"][0]["metrics"]
            for months in (3, 6, 12):
                anchor = out["windows"]["return_start_dates"][str(months)]
                self.assertAlmostEqual(metrics["return_%dm" % months], rows[-1]["c"] / by_date[anchor]["c"] - 1)
            self.assertAlmostEqual(metrics["ma50"], sum(r["c"] for r in rows[-50:]) / 50)
            self.assertAlmostEqual(metrics["ma200_change_20_sessions"], (1.002 ** 20) - 1)
            self.assertAlmostEqual(metrics["average_daily_notional"], sum(r["vw"] * r["v"] for r in rows[-20:]) / 20)

        def test_calendar_month_end_and_leap_anniversary(self):
            self.assertEqual(_anniversary(parse_date("2024-05-31"), 3).isoformat(), "2024-02-29")
            self.assertEqual(_anniversary(parse_date("2025-05-31"), 3).isoformat(), "2025-02-28")

        def test_weekend_anchor_uses_preceding_session(self):
            out = screen(self.bundle)
            self.assertEqual(out["windows"]["return_start_dates"]["12"], "2024-03-29")

        def test_cutoff_excludes_same_day_close_even_after_early_close(self):
            self.bundle["as_of"] = "2025-03-31T18:00:00Z"
            self.bundle["sessions"]["data"]["sessions"][-1]["close_at"] = "2025-03-31T17:00:00Z"
            out = screen(self.bundle)
            self.assertEqual(out["reference_session"], "2025-03-28")
            self.assertEqual(out["coverage"]["ignored_unfinished_or_future_bars"], 3)

        def test_dst_daily_boundary_validated(self):
            self.bundle["prices"][0]["data"]["bars"]["AAA"][-1]["interval_end"] = "2025-04-01T05:00:00Z"
            with self.assertRaises(DataError):
                screen(self.bundle)

        def test_missing_reference_does_not_use_stale_close(self):
            self.bundle["prices"][0]["data"]["bars"]["AAA"].pop()
            out = screen(self.bundle)
            self.assertFalse(out["complete"])
            self.assertEqual(out["coverage"]["unavailable"], 1)
            self.assertIn("2025-03-31", out["exclusions"][0]["missing_sessions"])

        def test_gap_is_not_filled(self):
            self.bundle["prices"][0]["data"]["bars"]["AAA"].pop(-40)
            out = screen(self.bundle)
            self.assertEqual(out["exclusions"][0]["kind"], "unavailable")

        def test_benchmark_gap_blocks_relative_comparison(self):
            self.bundle["prices"][0]["data"]["bars"]["SPY"].pop(-60)
            out = screen(self.bundle)
            self.assertFalse(out["complete"])
            self.assertEqual(out["candidates"], [])
            self.assertIsNone(out["benchmark"]["metrics"])

        def test_partial_source_retains_provisional_rows(self):
            self.bundle["prices"][0]["complete"] = False
            out = screen(self.bundle)
            self.assertFalse(out["complete"])
            self.assertEqual(len(out["candidates"]), 2)

        def test_unrequested_universe_symbol_reported(self):
            self.bundle["universe"]["instruments"][0]["symbol"] = "NEW"
            out = screen(self.bundle)
            self.assertIn("symbol_not_requested", out["exclusions"][0]["reasons"])

        def test_mismatched_feed_adjustment_and_mapping_rejected(self):
            for field, value in (("feed", "iex"), ("adjustment", "raw"), ("currency", "EUR"), ("asof", "2025-03-31")):
                with self.subTest(field=field):
                    bundle = copy.deepcopy(self.bundle)
                    second = copy.deepcopy(bundle["prices"][0])
                    second["query"][field] = value
                    bundle["prices"].append(second)
                    with self.assertRaises(DataError):
                        screen(bundle)

        def test_multiple_batches_and_identical_overlap(self):
            original = self.bundle["prices"][0]
            second = copy.deepcopy(original)
            second["data"]["requested_symbols"] = ["BBB", "SPY"]
            second["query"]["symbols"] = "BBB,SPY"
            second["data"]["bars"].pop("AAA")
            original["data"]["requested_symbols"].remove("BBB")
            original["query"]["symbols"] = "AAA,SPY"
            original["data"]["bars"].pop("BBB")
            self.bundle["prices"].append(second)
            out = screen(self.bundle)
            self.assertTrue(out["complete"])
            self.assertEqual(len(out["candidates"]), 2)

        def test_conflicting_duplicates_rejected(self):
            duplicate = copy.deepcopy(self.bundle["prices"][0]["data"]["bars"]["AAA"][-1])
            duplicate["v"] += 1
            self.bundle["prices"][0]["data"]["bars"]["AAA"].append(duplicate)
            with self.assertRaises(DataError):
                screen(self.bundle)

        def test_nonfinite_negative_and_boolean_prices_rejected(self):
            for value in (float("nan"), float("inf"), -1, True, 0):
                with self.subTest(value=value):
                    bundle = copy.deepcopy(self.bundle)
                    bundle["prices"][0]["data"]["bars"]["AAA"][-1]["c"] = value
                    with self.assertRaises(DataError):
                        screen(bundle)

        def test_recovery_can_disable_all_trend_gates(self):
            for row in self.bundle["prices"][0]["data"]["bars"]["AAA"]:
                for key in ("o", "h", "l", "c", "vw"):
                    row[key] = 10000 / row[key]
            self.assertEqual(screen(self.bundle)["exclusions"][0]["kind"], "filter")
            self.bundle["rules"] = {"require_above_ma50": False, "require_above_ma200": False,
                                    "require_positive_relative_return_6m": False, "sort_by": "relative_return_3m"}
            self.assertEqual(len(screen(self.bundle)["candidates"]), 2)

        def test_display_limit_not_incomplete_and_no_input_mutation(self):
            self.bundle["rules"]["limit"] = 1
            before = copy.deepcopy(self.bundle)
            out = screen(self.bundle)
            self.assertTrue(out["complete"])
            self.assertTrue(out["coverage"]["truncated"])
            self.assertEqual(out["coverage"]["passing"], 2)
            self.assertEqual(self.bundle, before)
            self.assertEqual(out, screen(self.bundle))

        def test_zero_passing_is_valid_complete(self):
            self.bundle["rules"]["min_price"] = 100000
            out = screen(self.bundle)
            self.assertTrue(out["complete"])
            self.assertEqual(out["candidates"], [])

        def test_identity_ties_are_stable_for_all_sort_fields(self):
            self.bundle["prices"][0]["data"]["bars"]["BBB"] = copy.deepcopy(self.bundle["prices"][0]["data"]["bars"]["AAA"])
            self.bundle["universe"]["instruments"].reverse()
            for field in SORT_FIELDS:
                with self.subTest(field=field):
                    self.bundle["rules"]["sort_by"] = field
                    self.assertEqual([r["symbol"] for r in screen(self.bundle)["candidates"]], ["AAA", "BBB"])

        def test_otc_and_unknown_instrument_types_are_exclusions(self):
            self.bundle["universe"]["instruments"][0]["exchange"] = "OTC"
            self.bundle["universe"]["instruments"][1]["security_type"] = "unknown"
            out = screen(self.bundle)
            self.assertTrue(out["complete"])
            self.assertEqual(out["candidates"], [])
            self.assertEqual(len(out["exclusions"]), 2)
            self.assertTrue(all(r["kind"] == "eligibility" for r in out["exclusions"]))

        def test_query_symbol_mismatch_rejected(self):
            self.bundle["prices"][0]["query"]["symbols"] = "AAA,SPY"
            with self.assertRaises(DataError):
                screen(self.bundle)

        def test_rule_hash_changes_without_input_dependent_screen_hash(self):
            first = screen(self.bundle)
            self.bundle["as_of"] = "2025-04-01T16:30:00Z"
            second = screen(self.bundle)
            self.assertNotEqual(first["input_sha256"], second["input_sha256"])
            self.assertEqual(first["screen_sha256"], second["screen_sha256"])
            self.bundle["rules"]["require_above_ma200"] = False
            third = screen(self.bundle)
            self.assertNotEqual(second["rules_sha256"], third["rules_sha256"])

        def test_metric_units_and_calculator_binding_are_explicit(self):
            out = screen(self.bundle)
            self.assertEqual(out["calculator_sha256"], hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
            self.assertIn("decimal fraction", out["definition"]["metric_units"]["return_3m"])
            self.assertIn("percentage points", out["definition"]["metric_units"]["relative_return_3m"])
            self.assertIn("USD per scheduled session", out["definition"]["metric_units"]["average_daily_notional"])

        def test_incomplete_and_short_calendars_rejected(self):
            self.bundle["sessions"]["complete"] = False
            with self.assertRaises(DataError):
                screen(self.bundle)
            self.bundle["sessions"]["complete"] = True
            self.bundle["sessions"]["query"]["end"] = "2025-03-31"
            with self.assertRaises(DataError):
                screen(self.bundle)

        def test_cli_roundtrip_and_safe_failure(self):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "input.json"
                path.write_text(json.dumps(self.bundle), encoding="utf-8")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(["--input", str(path)]), 0)
                self.assertTrue(json.loads(output.getvalue())["complete"])
                path.write_text("private-invalid-payload", encoding="utf-8")
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main(["--input", str(path)]), 2)
                self.assertNotIn("private-invalid-payload", output.getvalue())

        def test_cli_duplicate_keys_and_nonfinite_json_rejected(self):
            with tempfile.TemporaryDirectory() as temp:
                path = Path(temp) / "input.json"
                for raw in ('{"rules":{"limit":1,"limit":2}}', '{"as_of":NaN}'):
                    with self.subTest(raw=raw):
                        path.write_text(raw, encoding="utf-8")
                        output = io.StringIO()
                        with contextlib.redirect_stdout(output):
                            self.assertEqual(main(["--input", str(path)]), 2)
                        self.assertEqual(json.loads(output.getvalue())["error"]["code"], "invalid_input")

    result = unittest.TextTestRunner(verbosity=0).run(unittest.defaultTestLoader.loadTestsFromTestCase(Cases))
    print("%d/%d self-test cases pass" % (result.testsRun - len(result.failures) - len(result.errors), result.testsRun))
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
