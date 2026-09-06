#!/usr/bin/env python3
"""Read-only Alpaca adapters; use market_data.py for operational commands.

Only the market-data bars/actions endpoints and the paper calendar are used.
The provider's bar labels denote interval boundaries, not trade timestamps.
"""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, time, timedelta, timezone
import json
import math
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
from market_http import DataError, parse_date, parse_time, required_env, utc_now


BARS_URL = "https://data.alpaca.markets/v2/stocks/bars"
ACTIONS_URL = "https://data.alpaca.markets/v1/corporate-actions"
CALENDAR_URL = "https://paper-api.alpaca.markets/v2/calendar"
SYMBOL = re.compile(r"[A-Z][A-Z0-9./-]{0,19}\Z")
ACTION_TYPES = (
    "reverse_split", "forward_split", "unit_split", "cash_dividend",
    "stock_dividend", "spin_off", "cash_merger", "stock_merger",
    "stock_and_cash_merger", "redemption", "name_change", "worthless_removal",
    "rights_distribution", "partial_call", "reorganization",
    "capital_gains_distribution",
)


def _iso(value):
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _symbols(value):
    if not isinstance(value, str):
        raise DataError("invalid_input", "Provide a comma-separated symbol list.")
    symbols = [item.strip().upper() for item in value.split(",")]
    if not 1 <= len(symbols) <= 200 or any(not SYMBOL.fullmatch(s) for s in symbols):
        raise DataError("invalid_input", "Provide 1–200 valid stock symbols; no URLs or exchanges.")
    return list(dict.fromkeys(symbols))


def _auth(client):
    return {
        "APCA-API-KEY-ID": required_env(client.env, "ALPACA_API_KEY"),
        "APCA-API-SECRET-KEY": required_env(client.env, "ALPACA_SECRET_KEY"),
    }


def _budget(args):
    value = getattr(args, "max_pages", 20)
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 200:
        raise DataError("invalid_input", "max_pages must be an integer from 1 to 200.")
    return value


def _pages(client, url, params, headers, budget, decode):
    """Retain validated earlier pages if a later request or page is incomplete."""
    results, warnings, seen_tokens = [], [], set()
    token = None
    complete = False
    count = 0
    for _ in range(budget):
        query = dict(params)
        if token is not None:
            query["page_token"] = token
        try:
            payload = client.get_json(url, params=query, headers=headers)
            if not isinstance(payload, dict):
                raise DataError("invalid_response", "Alpaca returned a non-object page.")
            if "next_page_token" not in payload:
                raise DataError("invalid_response", "Alpaca pagination marker is missing.")
            next_token = payload["next_page_token"]
            if next_token is not None and (not isinstance(next_token, str)
                                           or not next_token or len(next_token) > 4096):
                raise DataError("invalid_response", "Alpaca pagination marker is invalid.")
            parsed = decode(payload)
        except DataError as error:
            if not results:
                raise
            warnings.append("A later page failed validation or retrieval; earlier pages are retained "
                            f"({error.code}).")
            break
        count += 1
        results.append(parsed)
        token = next_token
        if token is None:
            complete = True
            break
        if token in seen_tokens:
            warnings.append("Alpaca repeated a pagination token; retrieval stopped before completion.")
            break
        seen_tokens.add(token)
    else:
        warnings.append("Page budget reached with more provider results available.")
    return results, complete, warnings, {"pages": count, "exhausted": complete}


def _finite(value, *, positive=False, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return (math.isfinite(value) and (value > 0 if positive else value >= 0)
                and (not integer or int(value) == value))
    except (OverflowError, ValueError):
        return False


def _bar(raw, timeframe, start, end):
    ny = ZoneInfo("America/New_York")
    if not isinstance(raw, dict):
        raise DataError("invalid_response", "Alpaca bar is not an object.")
    try:
        stamp = parse_time(raw.get("t"))
    except (DataError, TypeError, ValueError):
        raise DataError("invalid_response", "Alpaca bar timestamp is invalid.") from None
    if not start <= stamp <= end:
        raise DataError("invalid_response", "Alpaca bar falls outside the requested interval.")
    if any(not _finite(raw.get(key), positive=True) for key in ("o", "h", "l", "c", "vw")):
        raise DataError("invalid_response", "Alpaca bar contains an invalid price or VWAP.")
    if (not _finite(raw.get("v")) or not _finite(raw.get("n"), integer=True)
            or raw["h"] < raw["l"]
            or any(not raw["l"] <= raw[key] <= raw["h"] for key in ("o", "c"))):
        raise DataError("invalid_response", "Alpaca bar volume, trade count, or range is invalid.")
    local = stamp.astimezone(ny)
    if timeframe == "1Day":
        if local.timetz().replace(tzinfo=None) != time.min:
            raise DataError("invalid_response", "Daily bar does not start at New York midnight.")
        interval_end = datetime.combine(local.date() + timedelta(days=1), time.min, ny)
    else:
        if stamp.second or stamp.microsecond:
            raise DataError("invalid_response", "Minute bar does not start on a minute boundary.")
        interval_end = stamp + timedelta(minutes=1)
        # A provider may include the bar whose left label equals an inclusive end.
        # Do not admit its later trades into an as-of cut-off.
        if interval_end > end:
            return None
    return {key: raw[key] for key in ("t", "o", "h", "l", "c", "v", "n", "vw")} | {
        "interval_start": _iso(stamp), "interval_end": _iso(interval_end),
        "new_york_date": local.date().isoformat(),
    }


def alpaca_bars(client, args):
    """Retrieve complete bar intervals without silently substituting a feed."""
    ny = ZoneInfo("America/New_York")
    symbols = _symbols(args.symbols)
    start, requested_end = parse_time(args.start), parse_time(args.end)
    now = utc_now()
    if start > requested_end or requested_end > now:
        raise DataError("invalid_input", "Bars require start <= end <= the current time.")
    feed = getattr(args, "feed", "sip")
    if feed not in ("sip", "iex"):
        raise DataError("invalid_input", "The supported feeds are sip and iex.")
    if feed == "sip" and requested_end > now - timedelta(minutes=15):
        raise DataError("invalid_input", "SIP requests must end at least 15 minutes ago; "
                        "the script does not assume paid real-time access or switch to IEX.")
    timeframe = getattr(args, "timeframe", "1Day")
    if timeframe not in ("1Day", "1Min"):
        raise DataError("invalid_input", "The supported timeframes are 1Day and 1Min.")
    adjustment = getattr(args, "adjustment", "raw")
    adjustments = adjustment.split(",") if isinstance(adjustment, str) else []
    if (not adjustments or any(item not in ("raw", "split", "dividend", "spin-off", "all")
                               for item in adjustments)
            or len(set(adjustments)) != len(adjustments)
            or (len(adjustments) > 1 and ("raw" in adjustments or "all" in adjustments))):
        raise DataError("invalid_input", "Use raw, all, split, dividend, spin-off, "
                        "or a comma-separated combination of the three specific adjustments.")
    asof = getattr(args, "asof", None)
    # Explicitly freeze the provider's otherwise time-varying default symbol mapping.
    asof = parse_date(asof).isoformat() if asof is not None else now.astimezone(ny).date().isoformat()
    if parse_date(asof) > now.astimezone(ny).date():
        raise DataError("invalid_input", "Symbol identity asof must not be a future date.")
    budget, headers = _budget(args), _auth(client)
    end = requested_end
    warnings = [
        "Bar timestamps are left interval boundaries, not trade or execution timestamps.",
        "Bar volume includes eligible extended-hours trades; it is not regular-session-only volume.",
        "Provider-adjusted history may reflect later corporate actions and is not point-in-time evidence.",
    ]
    if feed == "iex":
        warnings.append("IEX covers one exchange; its prices and volume are not consolidated U.S. coverage.")
    if timeframe == "1Day":
        end = datetime.combine(requested_end.astimezone(ny).date(), time.min, ny) - timedelta(microseconds=1)
        warnings.append("Daily bars include only New York dates before the requested end date; "
                        "use the following day's end date to include a desired final day. "
                        "This excludes unfinished daily intervals and their future closes.")
    else:
        warnings.append("Minute bars include premarket and after-hours intervals when present; "
                        "use the verified exchange calendar to distinguish regular sessions.")
    params = {"symbols": ",".join(symbols), "start": _iso(start), "end": _iso(end),
              "timeframe": timeframe, "adjustment": adjustment, "asof": asof,
              "feed": feed, "currency": "USD", "limit": 10000, "sort": "asc"}
    bars = {symbol: [] for symbol in symbols}
    skipped = 0

    def decode(payload):
        nonlocal skipped
        values = payload.get("bars")
        if not isinstance(values, dict) or any(symbol not in bars for symbol in values):
            raise DataError("invalid_response", "Alpaca returned missing bars data or an unrequested symbol.")
        parsed = {}
        total = 0
        for symbol, rows in values.items():
            if not isinstance(rows, list):
                raise DataError("invalid_response", "Alpaca symbol bars are not a list.")
            total += len(rows)
            parsed[symbol] = []
            for raw in rows:
                bar = _bar(raw, timeframe, start, end)
                if bar is None:
                    skipped += 1
                else:
                    parsed[symbol].append(bar)
        if total > 10000:
            raise DataError("invalid_response", "Alpaca exceeded the requested page size.")
        return parsed

    if end < start:
        pages, complete, page_warnings, pagination = [], False, [], {"pages": 0, "exhausted": False}
        warnings.append("The requested interval contains no fully elapsed daily interval.")
    else:
        pages, complete, page_warnings, pagination = _pages(
            client, BARS_URL, params, headers, budget, decode)
    warnings.extend(page_warnings)
    seen = {symbol: set() for symbol in symbols}
    for page in pages:
        for symbol, rows in page.items():
            for bar in rows:
                key = bar["interval_start"]
                if key in seen[symbol]:
                    complete = False
                    warnings.append("A duplicate symbol/bar interval was returned; only the first is retained.")
                    continue
                seen[symbol].add(key)
                bars[symbol].append(bar)
    for rows in bars.values():
        rows.sort(key=lambda item: item["interval_start"])
    missing = [symbol for symbol in symbols if not bars[symbol]]
    if missing:
        complete = False
        warnings.append("Some requested symbols have no usable bars; absence is not evidence of zero trading.")
    if skipped:
        warnings.append(f"Excluded {skipped} minute bars whose intervals cross the requested cutoff.")
    latest = max((bar["interval_start"] for rows in bars.values() for bar in rows), default=None)
    return {
        "provider": "alpaca", "resource": "bars", "complete": complete,
        "warnings": list(dict.fromkeys(warnings)), "pagination": pagination,
        "source": {"url": BARS_URL, "documentation": "https://docs.alpaca.markets/us/reference/stockbars",
                   "feed": feed, "latest_bar_interval_start": latest,
                   "coverage": "consolidated U.S. exchanges" if feed == "sip" else "IEX only",
                   "timestamp_basis": "left boundary of aggregation interval"},
        "query": params | {"requested_end": _iso(requested_end)},
        "data": {"requested_symbols": symbols, "bars": bars, "missing_symbols": missing},
    }


def _dates(args):
    start, end = parse_date(args.start), parse_date(args.end)
    if start > end:
        raise DataError("invalid_input", "start must not follow end.")
    return start, end


def alpaca_actions(client, args):
    """Return typed provider records; process dates are not announcement dates."""
    symbols = _symbols(args.symbols)
    start, end = _dates(args)
    types = getattr(args, "types", None)
    requested_types = [item.strip() for item in types.split(",")] if types else []
    if any(item not in ACTION_TYPES for item in requested_types):
        raise DataError("invalid_input", "Unsupported corporate-action type; see --help.")
    params = {"symbols": ",".join(symbols), "start": start.isoformat(), "end": end.isoformat(),
              "limit": 1000, "sort": "asc", "region": "us", "data_quality": "complete"}
    if requested_types:
        params["types"] = ",".join(dict.fromkeys(requested_types))

    def decode(payload):
        groups = payload.get("corporate_actions")
        if not isinstance(groups, dict):
            raise DataError("invalid_response", "Alpaca corporate_actions data is missing or invalid.")
        records = []
        for kind, rows in groups.items():
            if not isinstance(kind, str) or not re.fullmatch(r"[a-z_]{1,64}", kind) or not isinstance(rows, list):
                raise DataError("invalid_response", "Alpaca corporate-action group is invalid.")
            for raw in rows:
                if not isinstance(raw, dict) or not isinstance(raw.get("id"), str) or not raw["id"]:
                    raise DataError("invalid_response", "Alpaca corporate-action identity is missing.")
                try:
                    process_date = parse_date(raw.get("process_date"))
                    # Keep raw typed fields, but do not publish JSON NaN/Infinity as evidence.
                    json.dumps(raw, allow_nan=False)
                    for key, value in raw.items():
                        if key.endswith("_date") and value is not None:
                            parse_date(value)
                except (DataError, TypeError, ValueError, OverflowError):
                    raise DataError("invalid_response", "Alpaca corporate-action dates or values are invalid.") from None
                if not start <= process_date <= end:
                    raise DataError("invalid_response", "Corporate-action process date is outside the query.")
                matched = sorted({value for key, value in raw.items()
                                  if (key == "symbol" or key.endswith("_symbol"))
                                  and isinstance(value, str) and value in symbols})
                if not matched:
                    raise DataError("invalid_response", "Corporate action has no requested symbol identity.")
                records.append({"type": kind, "matched_symbols": matched, "raw": raw})
        if len(records) > 1000:
            raise DataError("invalid_response", "Alpaca exceeded the corporate-action page size.")
        return records

    pages, complete, warnings, pagination = _pages(
        client, ACTIONS_URL, params, _auth(client), _budget(args), decode)
    records, seen = [], set()
    for page in pages:
        for record in page:
            key = record["raw"]["id"]
            if key in seen:
                complete = False
                warnings.append("A duplicate corporate-action ID was returned; only the first is retained.")
                continue
            seen.add(key)
            records.append(record)
    warnings.extend([
        "The date filter selects provider process_date, not ex-date, effective date, or announcement time.",
        "Corporate actions can arrive late; absence does not prove that no action was announced.",
        "data_quality=complete excludes incomplete unprocessed actions; confirm issuer announcements separately.",
        "These are current provider records, not a reconstruction of what was known on the queried dates.",
    ])
    matched = {symbol for record in records for symbol in record["matched_symbols"]}
    return {
        "provider": "alpaca", "resource": "corporate-actions", "complete": complete,
        "warnings": list(dict.fromkeys(warnings)), "pagination": pagination,
        "source": {"url": ACTIONS_URL,
                   "documentation": "https://docs.alpaca.markets/us/reference/corporateactions-1",
                   "date_basis": "process_date; not announcement or economic effective date"},
        "query": params,
        "data": {"requested_symbols": symbols, "actions": records,
                 "symbols_without_actions": [symbol for symbol in symbols if symbol not in matched]},
    }


def alpaca_calendar(client, args):
    """Read actual regular-session times from the paper endpoint, never orders."""
    ny = ZoneInfo("America/New_York")
    start, end = _dates(args)
    if start.year < 1970 or end.year > 2029:
        raise DataError("invalid_input", "Alpaca currently documents calendar coverage for 1970–2029; "
                        "verify another official calendar outside that range.")
    params = {"start": start.isoformat(), "end": end.isoformat(), "date_type": "TRADING"}
    payload = client.get_json(CALENDAR_URL, params=params, headers=_auth(client))
    if not isinstance(payload, list) or len(payload) > (end - start).days + 1:
        raise DataError("invalid_response", "Alpaca calendar data is invalid.")
    sessions, seen = [], set()
    for row in payload:
        if not isinstance(row, dict):
            raise DataError("invalid_response", "Alpaca calendar row is invalid.")
        try:
            day = parse_date(row.get("date"))
            if not start <= day <= end or day in seen:
                raise ValueError("Duplicate or out-of-range session")
            boundaries = {}
            for key in ("open", "close"):
                clock = row.get(key)
                if not isinstance(clock, str) or not re.fullmatch(r"\d{2}:\d{2}", clock):
                    raise ValueError("Missing session boundary")
                boundaries[key] = datetime.combine(day, time.fromisoformat(clock), ny)
            if boundaries["close"] <= boundaries["open"]:
                raise ValueError("Close before open")
        except (DataError, TypeError, ValueError):
            raise DataError("invalid_response", "Alpaca calendar session date or boundaries are invalid.") from None
        seen.add(day)
        sessions.append({"date": day.isoformat(), "open_at": _iso(boundaries["open"]),
                         "close_at": _iso(boundaries["close"]), "raw": row})
    sessions.sort(key=lambda row: row["date"])
    return {
        "provider": "alpaca", "resource": "calendar", "complete": True,
        "warnings": ["Calendar boundaries are scheduled regular-session markers, not observed trade timestamps."],
        "source": {"url": CALENDAR_URL, "documentation": "https://docs.alpaca.markets/us/reference/legacycalendar",
                   "timezone": "America/New_York"},
        "query": params, "data": {"sessions": sessions},
    }


def run_self_test():
    """Offline provider fixtures exercise pagination, chronology, and failures."""
    frozen = datetime(2026, 9, 5, 13, 0, tzinfo=timezone.utc)

    class FakeClient:
        def __init__(self, pages, env=None):
            self.env = {"ALPACA_API_KEY": "fixture-key", "ALPACA_SECRET_KEY": "fixture-secret"} if env is None else env
            self.pages, self.calls = list(pages), []

        def get_json(self, url, params=None, headers=None):
            self.calls.append((url, copy.deepcopy(params), copy.deepcopy(headers)))
            result = self.pages.pop(0)
            if isinstance(result, Exception):
                raise result
            return copy.deepcopy(result)

    def args(**changes):
        defaults = dict(symbols="AAPL,MSFT", start="2026-09-03T04:00:00Z",
                        end="2026-09-05T12:45:00Z", feed="sip", timeframe="1Day",
                        adjustment="raw", asof=None, max_pages=20, types=None)
        return SimpleNamespace(**(defaults | changes))

    def bar(stamp="2026-09-04T04:00:00Z", **changes):
        return {"t": stamp, "o": 100, "h": 105, "l": 98, "c": 102,
                "v": 10000, "n": 120, "vw": 101} | changes

    def page(bars, token=None):
        return {"bars": bars, "next_page_token": token}

    def action_page(rows, token=None, kind="cash_dividends"):
        return {"corporate_actions": {kind: rows}, "next_page_token": token}

    def action(**changes):
        return {"id": "fixture-action", "symbol": "AAPL", "process_date": "2026-09-04",
                "ex_date": "2026-09-08", "rate": 0.25} | changes

    class Cases(unittest.TestCase):
        def setUp(self):
            self.clock = patch(__name__ + ".utc_now", return_value=frozen)
            self.clock.start()

        def tearDown(self):
            self.clock.stop()

        def test_symbol_first_pagination_and_auth(self):
            client = FakeClient([page({"AAPL": [bar()]}, "next"), page({"MSFT": [bar()]})])
            result = alpaca_bars(client, args())
            self.assertTrue(result["complete"])
            self.assertEqual(result["data"]["missing_symbols"], [])
            self.assertEqual(client.calls[1][1]["page_token"], "next")
            self.assertEqual(client.calls[0][2]["APCA-API-SECRET-KEY"], "fixture-secret")
            self.assertNotIn("fixture-secret", json.dumps(result))

        def test_page_budget_retains_missing_symbols(self):
            result = alpaca_bars(FakeClient([page({"AAPL": [bar()]}, "more")]), args(max_pages=1))
            self.assertFalse(result["complete"])
            self.assertEqual(result["data"]["bars"]["MSFT"], [])
            self.assertEqual(result["pagination"]["pages"], 1)

        def test_repeated_token_stops(self):
            client = FakeClient([page({"AAPL": [bar()]}, "same"), page({"MSFT": [bar()]}, "same")])
            result = alpaca_bars(client, args())
            self.assertFalse(result["complete"])
            self.assertEqual(len(client.calls), 2)

        def test_later_network_failure_preserves_first_page(self):
            result = alpaca_bars(FakeClient([page({"AAPL": [bar()]}, "x"),
                                           DataError("rate_limit", "fixture failure")]), args())
            self.assertFalse(result["complete"])
            self.assertEqual(len(result["data"]["bars"]["AAPL"]), 1)

        def test_later_invalid_page_preserves_first_page(self):
            result = alpaca_bars(FakeClient([page({"AAPL": [bar()]}, "x"), page({"ALIEN": [bar()]})]), args())
            self.assertFalse(result["complete"])
            self.assertNotIn("ALIEN", result["data"]["bars"])

        def test_missing_pagination_marker_rejected(self):
            with self.assertRaises(DataError):
                alpaca_bars(FakeClient([{"bars": {}}]), args())

        def test_sip_recent_request_not_downgraded(self):
            client = FakeClient([])
            with self.assertRaises(DataError):
                alpaca_bars(client, args(end="2026-09-05T12:59:00Z"))
            self.assertFalse(client.calls)

        def test_future_bounds_rejected(self):
            with self.assertRaises(DataError):
                alpaca_bars(FakeClient([]), args(feed="iex", end="2026-09-06T00:00:00Z"))

        def test_daily_cutoff_cannot_reveal_future_close(self):
            client = FakeClient([page({"AAPL": [bar()]})])
            result = alpaca_bars(client, args(symbols="AAPL", end="2026-09-05T08:45:00-04:00"))
            self.assertEqual(client.calls[0][1]["end"], "2026-09-05T03:59:59.999999Z")
            self.assertTrue(result["complete"])

        def test_historical_midday_daily_cutoff(self):
            client = FakeClient([page({"AAPL": [bar("2026-09-03T04:00:00Z")]})])
            result = alpaca_bars(client, args(symbols="AAPL", end="2026-09-04T15:00:00Z"))
            self.assertEqual(result["data"]["bars"]["AAPL"][0]["new_york_date"], "2026-09-03")
            self.assertEqual(client.calls[0][1]["end"], "2026-09-04T03:59:59.999999Z")

        def test_same_day_daily_interval_does_not_fetch(self):
            client = FakeClient([])
            result = alpaca_bars(client, args(start="2026-09-05T04:00:00Z"))
            self.assertFalse(result["complete"])
            self.assertFalse(client.calls)

        def test_minute_cutoff_excludes_crossing_interval(self):
            client = FakeClient([page({"AAPL": [bar("2026-09-05T12:44:00Z"), bar("2026-09-05T12:45:00Z")]})])
            result = alpaca_bars(client, args(symbols="AAPL", timeframe="1Min"))
            self.assertEqual(len(result["data"]["bars"]["AAPL"]), 1)
            self.assertEqual(result["data"]["bars"]["AAPL"][0]["interval_end"], "2026-09-05T12:45:00Z")

        def test_iex_warning_and_explicit_mapping(self):
            client = FakeClient([page({"AAPL": [bar()]})])
            result = alpaca_bars(client, args(symbols="AAPL", feed="iex", asof="2026-09-04"))
            self.assertEqual(result["source"]["coverage"], "IEX only")
            self.assertEqual(client.calls[0][1]["asof"], "2026-09-04")

        def test_invalid_price_and_future_bar(self):
            for raw in (bar(o=float("nan")), bar(n=True), bar("2026-09-05T04:00:00Z")):
                with self.subTest(raw=raw), self.assertRaises(DataError):
                    alpaca_bars(FakeClient([page({"AAPL": [raw]})]), args())

        def test_open_and_close_must_be_within_the_bar_range(self):
            # Alpaca's open/close-eligible trades also update high/low. A
            # contradictory candle must not become a momentum/return input.
            for changes in ({"o": 97}, {"o": 106}, {"c": 97}, {"c": 106}):
                with self.subTest(changes=changes), self.assertRaises(DataError):
                    alpaca_bars(FakeClient([page({"AAPL": [bar(**changes)]})]), args(symbols="AAPL"))
            for changes in ({"o": 98, "c": 105}, {"o": 105, "c": 98},
                            {"o": 100, "h": 100, "l": 100, "c": 100, "vw": 100}):
                with self.subTest(changes=changes):
                    result = alpaca_bars(FakeClient([page({"AAPL": [bar(**changes)]})]), args(symbols="AAPL"))
                    self.assertTrue(result["complete"])

        def test_duplicate_bar_never_silently_succeeds(self):
            result = alpaca_bars(FakeClient([page({"AAPL": [bar(), bar()]})]), args(symbols="AAPL"))
            self.assertFalse(result["complete"])
            self.assertEqual(len(result["data"]["bars"]["AAPL"]), 1)

        def test_missing_credentials_never_fetches(self):
            client = FakeClient([], env={})
            with self.assertRaises(DataError):
                alpaca_bars(client, args())
            self.assertFalse(client.calls)

        def test_invalid_inputs(self):
            for changes in ({"symbols": "AAPL,https://example.com"}, {"max_pages": 0},
                            {"adjustment": "all,split"}, {"timeframe": "1Month"},
                            {"asof": "2027-01-01"}, {"feed": "otc"}):
                with self.subTest(changes=changes), self.assertRaises(DataError):
                    alpaca_bars(FakeClient([]), args(**changes))

        def test_actions_preserve_effective_dates_and_pagination(self):
            client = FakeClient([action_page([action()], "next"), action_page([
                action(id="other", symbol="MSFT", ex_date="2026-09-10")])])
            result = alpaca_actions(client, args(start="2026-09-01", end="2026-09-05"))
            self.assertTrue(result["complete"])
            self.assertEqual(result["data"]["actions"][1]["raw"]["ex_date"], "2026-09-10")
            self.assertEqual(client.calls[0][1]["data_quality"], "complete")
            self.assertEqual(client.calls[0][1]["limit"], 1000)

        def test_actions_name_change_identity(self):
            raw = {"id": "name", "old_symbol": "OLD", "new_symbol": "AAPL", "process_date": "2026-09-04"}
            result = alpaca_actions(FakeClient([action_page([raw], kind="name_changes")]),
                                    args(start="2026-09-01", end="2026-09-05", types="name_change"))
            self.assertEqual(result["data"]["actions"][0]["matched_symbols"], ["AAPL"])

        def test_no_actions_is_not_a_price_data_gap(self):
            result = alpaca_actions(FakeClient([action_page([])]), args(start="2026-09-01", end="2026-09-05"))
            self.assertTrue(result["complete"])
            self.assertEqual(result["data"]["symbols_without_actions"], ["AAPL", "MSFT"])

        def test_actions_budget_and_invalid_records(self):
            result = alpaca_actions(FakeClient([action_page([action()], "more")]),
                                    args(start="2026-09-01", end="2026-09-05", max_pages=1))
            self.assertFalse(result["complete"])
            for raw in (action(process_date="2027-01-01"), action(rate=float("inf")), action(symbol="OTHER")):
                with self.subTest(raw=raw), self.assertRaises(DataError):
                    alpaca_actions(FakeClient([action_page([raw])]), args(start="2026-09-01", end="2026-09-05"))

        def test_calendar_early_close_and_dst_offsets(self):
            client = FakeClient([[{"date": "2026-07-02", "open": "09:30", "close": "13:00"},
                                  {"date": "2026-11-27", "open": "09:30", "close": "13:00"}]])
            result = alpaca_calendar(client, args(start="2026-07-01", end="2026-11-30"))
            self.assertEqual(result["data"]["sessions"][0]["close_at"], "2026-07-02T17:00:00Z")
            self.assertEqual(result["data"]["sessions"][1]["close_at"], "2026-11-27T18:00:00Z")
            self.assertEqual(client.calls[0][0], CALENDAR_URL)

        def test_calendar_invalid_sessions(self):
            for row in ({"date": "2026-09-04", "open": "16:00", "close": "09:30"},
                        {"date": "2026-09-06", "open": "09:30", "close": "16:00"}):
                with self.subTest(row=row), self.assertRaises(DataError):
                    alpaca_calendar(FakeClient([[row]]), args(start="2026-09-04", end="2026-09-04"))

        def test_calendar_outside_documented_coverage(self):
            with self.assertRaises(DataError):
                alpaca_calendar(FakeClient([]), args(start="2031-01-01", end="2031-01-02"))

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(Cases)
    outcome = unittest.TextTestRunner(verbosity=0).run(suite)
    passed = outcome.testsRun - len(outcome.failures) - len(outcome.errors)
    print(f"{passed}/{outcome.testsRun} self-test cases pass")
    return outcome.wasSuccessful()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--test", action="store_true", help="Run offline Alpaca response fixtures.")
    args = parser.parse_args()
    if args.test:
        return 0 if run_self_test() else 1
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
