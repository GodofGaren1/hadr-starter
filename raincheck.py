#!/usr/bin/env python3
"""raincheck — a tiny CLI that tells you whether to bring an umbrella.

Uses the free Open-Meteo API (no API key, no third-party packages).

Examples:
    python raincheck.py "Singapore"
    python raincheck.py "London" --hours 24
    python raincheck.py --lat 1.29 --lon 103.85 --days 5
    python raincheck.py "Tokyo" --json

Exit codes:
    0  success, no rain expected in the window
    1  success, rain expected in the window
    2  usage / network / lookup error
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
USER_AGENT = "raincheck-cli/1.0 (+https://open-meteo.com)"

# A place is "likely to rain" for verdict purposes at or above this chance.
RAIN_PROB_THRESHOLD = 50
# ...or if this much precipitation is expected regardless of the stated chance.
RAIN_MM_THRESHOLD = 0.2


class RainCheckError(Exception):
    """Any expected, user-facing failure (bad input, network, no results)."""


def fetch_json(url: str, params: dict) -> dict:
    """GET a URL with query params and parse the JSON body."""
    full = url + "?" + urlencode(params)
    req = Request(full, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise RainCheckError(f"service returned HTTP {exc.code} for {url}") from exc
    except URLError as exc:
        raise RainCheckError(f"could not reach {url}: {exc.reason}") from exc
    except (ValueError, TimeoutError) as exc:
        raise RainCheckError(f"bad response from {url}: {exc}") from exc


def geocode(name: str, hint: str = None) -> dict:
    """Resolve a place name to coordinates and a display label.

    `hint` is an optional country/region (the part after a comma) used to
    disambiguate — e.g. "Jurong" alone matches China, but hint "Singapore"
    selects the right one.
    """
    data = fetch_json(GEOCODE_URL, {"name": name, "count": 10, "language": "en"})
    results = data.get("results") or []
    if not results:
        raise RainCheckError(f"no place found matching {name!r}")

    if hint:
        needle = hint.strip().lower()
        for r in results:
            haystack = " ".join(
                str(r.get(k, "")) for k in ("country", "country_code", "admin1", "admin2")
            ).lower()
            if needle in haystack:
                results = [r]
                break

    top = results[0]
    label_parts = [top.get("name")]
    if top.get("admin1") and top["admin1"] != top.get("name"):
        label_parts.append(top["admin1"])
    if top.get("country"):
        label_parts.append(top["country"])
    return {
        "lat": top["latitude"],
        "lon": top["longitude"],
        "label": ", ".join(p for p in label_parts if p),
    }


def get_forecast(lat: float, lon: float) -> dict:
    """Fetch hourly and daily precipitation forecast for a coordinate."""
    return fetch_json(
        FORECAST_URL,
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": "precipitation_probability,precipitation",
            "daily": "precipitation_probability_max,precipitation_sum",
            "forecast_days": 16,
            "timezone": "auto",
        },
    )


def local_now(forecast: dict) -> datetime:
    """Current time in the forecast location's timezone."""
    offset = forecast.get("utc_offset_seconds", 0)
    tz = timezone(timedelta(seconds=offset))
    return datetime.now(timezone.utc).astimezone(tz)


def parse_hour(stamp: str) -> datetime:
    """Open-Meteo hourly timestamps look like '2026-07-07T15:00'."""
    return datetime.strptime(stamp, "%Y-%m-%dT%H:%M")


def upcoming_hours(forecast: dict, hours: int) -> list:
    """Return [(datetime, prob%, mm)] for the next `hours` from now."""
    hourly = forecast.get("hourly", {})
    times = hourly.get("time", [])
    probs = hourly.get("precipitation_probability", [])
    mm = hourly.get("precipitation", [])
    now = local_now(forecast).replace(minute=0, second=0, microsecond=0, tzinfo=None)

    rows = []
    for i, stamp in enumerate(times):
        when = parse_hour(stamp)
        if when < now:
            continue
        prob = probs[i] if i < len(probs) and probs[i] is not None else 0
        precip = mm[i] if i < len(mm) and mm[i] is not None else 0.0
        rows.append((when, prob, precip))
        if len(rows) >= hours:
            break
    return rows


def daily_outlook(forecast: dict, days: int) -> list:
    """Return [(date_str, prob%, mm)] for the next `days` days."""
    daily = forecast.get("daily", {})
    dates = daily.get("time", [])
    probs = daily.get("precipitation_probability_max", [])
    mm = daily.get("precipitation_sum", [])

    rows = []
    for i, day in enumerate(dates[:days]):
        prob = probs[i] if i < len(probs) and probs[i] is not None else 0
        precip = mm[i] if i < len(mm) and mm[i] is not None else 0.0
        rows.append((day, prob, precip))
    return rows


def will_rain(max_prob: int, total_mm: float) -> bool:
    return max_prob >= RAIN_PROB_THRESHOLD or total_mm >= RAIN_MM_THRESHOLD


def bar(prob: int, width: int = 10) -> str:
    filled = round(prob / 100 * width)
    return "#" * filled + "." * (width - filled)


def render_human(place: dict, forecast: dict, hour_rows: list, day_rows: list) -> bool:
    """Print a human-readable report. Returns True if rain is expected."""
    now = local_now(forecast)
    print(f"Rain check for {place['label']} ({place['lat']:.2f}, {place['lon']:.2f})")
    print(f"Local time: {now:%Y-%m-%d %H:%M %Z}")
    print()

    if hour_rows:
        max_prob = max(p for _, p, _ in hour_rows)
        total_mm = sum(m for _, _, m in hour_rows)
        window = len(hour_rows)
        rain = will_rain(max_prob, total_mm)
        if rain:
            print(f"Verdict: RAIN LIKELY -- {max_prob}% peak chance over the next "
                  f"{window}h, ~{total_mm:.1f} mm expected. Bring an umbrella.")
        else:
            print(f"Verdict: probably dry -- {max_prob}% peak chance over the next "
                  f"{window}h, ~{total_mm:.1f} mm expected.")
        print()
        print(f"Next {window} hours:")
        for when, prob, mm in hour_rows:
            note = f"  {mm:.1f}mm" if mm > 0 else ""
            print(f"  {when:%a %H:%M}   {prob:3d}%  [{bar(prob)}]{note}")
    else:
        rain = False
        print("Verdict: no hourly data available for this location.")

    if day_rows:
        print()
        print(f"{len(day_rows)}-day outlook:")
        for day, prob, mm in day_rows:
            when = datetime.strptime(day, "%Y-%m-%d")
            note = f"  {mm:.1f}mm" if mm > 0 else ""
            print(f"  {when:%a %d %b}  {prob:3d}%  [{bar(prob)}]{note}")

    return rain


def build_payload(place: dict, forecast: dict, hour_rows: list, day_rows: list) -> dict:
    max_prob = max((p for _, p, _ in hour_rows), default=0)
    total_mm = sum(m for _, _, m in hour_rows)
    return {
        "location": place,
        "local_time": local_now(forecast).isoformat(),
        "window_hours": len(hour_rows),
        "peak_probability_pct": max_prob,
        "expected_mm": round(total_mm, 2),
        "rain_expected": will_rain(max_prob, total_mm),
        "hourly": [
            {"time": w.isoformat(), "probability_pct": p, "mm": round(m, 2)}
            for w, p, m in hour_rows
        ],
        "daily": [
            {"date": d, "probability_pct": p, "mm": round(m, 2)}
            for d, p, m in day_rows
        ],
    }


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="raincheck",
        description="Tell whether it's going to rain, for any place.",
    )
    parser.add_argument("location", nargs="?", help="place name, e.g. \"Singapore\"")
    parser.add_argument("--lat", type=float, help="latitude (use with --lon instead of a name)")
    parser.add_argument("--lon", type=float, help="longitude (use with --lat)")
    parser.add_argument("--hours", type=int, default=12,
                        help="how many hours ahead to check (default: 12)")
    parser.add_argument("--days", type=int, default=3,
                        help="days of daily outlook to show (default: 3, max 16)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("-i", "--interactive", action="store_true",
                        help="prompt for places one at a time (default when no location given)")
    return parser.parse_args(argv)


def resolve_input(text: str, lat=None, lon=None) -> dict:
    """Turn a name, a 'lat, lon' string, or --lat/--lon flags into a place."""
    if lat is not None or lon is not None:
        if lat is None or lon is None:
            raise RainCheckError("--lat and --lon must be given together")
        return {"lat": lat, "lon": lon, "label": f"{lat:.2f}, {lon:.2f}"}

    text = (text or "").strip()
    if not text:
        raise RainCheckError("give a location name, or --lat and --lon")

    # "1.29, 103.85" -> coordinates; "Woodlands, Singapore" -> name + region hint.
    if "," in text:
        name_part, _, hint = text.partition(",")
        name_part, hint = name_part.strip(), hint.strip()
        try:
            la, lo = float(name_part), float(hint)
            return {"lat": la, "lon": lo, "label": f"{la:.2f}, {lo:.2f}"}
        except ValueError:
            return geocode(name_part, hint)
    return geocode(text)


def check_and_report(place: dict, hours: int, days: int, as_json: bool) -> bool:
    """Fetch a forecast for a resolved place and print it. Returns True if rain."""
    if hours < 1:
        raise RainCheckError("--hours must be at least 1")
    days = max(1, min(days, 16))

    forecast = get_forecast(place["lat"], place["lon"])
    hour_rows = upcoming_hours(forecast, hours)
    day_rows = daily_outlook(forecast, days)

    if as_json:
        payload = build_payload(place, forecast, hour_rows, day_rows)
        print(json.dumps(payload, indent=2))
        return payload["rain_expected"]
    return render_human(place, forecast, hour_rows, day_rows)


def strip_bom(s: str) -> str:
    """Drop a leading byte-order mark, whether it arrives as U+FEFF or as the
    raw UTF-8 bytes EF BB BF decoded to three characters (seen when a Windows
    shell pipes into stdin)."""
    for prefix in ("﻿", "\xef\xbb\xbf"):
        if s.startswith(prefix):
            return s[len(prefix):]
    return s


def interactive(args: argparse.Namespace) -> int:
    """Loop reading places from the user until they type quit/exit."""
    print("raincheck interactive mode")
    print("  enter a place name (or 'lat, lon'); type 'quit' to exit.")
    print()
    while True:
        try:
            text = strip_bom(input("raincheck> ")).strip()
        except EOFError:
            print()
            break
        if not text:
            continue
        if text.lower() in ("quit", "exit", "q"):
            break
        try:
            place = resolve_input(text)
            check_and_report(place, args.hours, args.days, args.json)
        except RainCheckError as exc:
            print(f"raincheck: {exc}", file=sys.stderr)
        print()
    print("bye.")
    return 0


def run(args: argparse.Namespace) -> int:
    no_target = not args.location and args.lat is None and args.lon is None
    if args.interactive or no_target:
        return interactive(args)

    place = resolve_input(args.location, args.lat, args.lon)
    rain = check_and_report(place, args.hours, args.days, args.json)
    return 1 if rain else 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except RainCheckError as exc:
        print(f"raincheck: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nraincheck: interrupted", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
