"""Push a Telegram headline when a sitrep was published (changed mornings).

Deterministic and model-free. Sends the headline and the dashboard link,
never the report body - dashboard.html stays the single artifact every
claim traces to; channels only point at it.

Needs TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in the environment (repository
secrets in CI, .env is not read here). Missing config is a silent skip so
the workflow runs fine before the secrets are set up. A failed send warns
but exits 0: the dashboard still published, and the morning must not be
marked broken over a chat message.
"""

import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FACTS_PATH = REPO_ROOT / "data" / "facts.json"
DASHBOARD_URL = "https://godofgaren1.github.io/hadr-starter/dashboard.html"

LEVEL_ICON = {"red": "\U0001F534", "orange": "\U0001F7E0", "yellow": "\U0001F7E1"}
MAX_LINES = 3


def compose(facts: dict) -> str:
    significant = facts.get("significant", [])
    stale = facts.get("stale_transitions", [])
    lines = []
    if significant:
        lines.append("HADR sitrep updated - {} item(s) need attention:".format(
            len(significant)))
        for item in significant[:MAX_LINES]:
            event = item["event"]
            lines.append("{} {} [{}]".format(
                LEVEL_ICON.get(event.get("alert_level"), "⚪"),
                event.get("title") or item["key"],
                item["reason"].replace("_", " ")))
        if len(significant) > MAX_LINES:
            lines.append("...and {} more".format(len(significant) - MAX_LINES))
    if stale:
        lines.append("⚠️ Source outage: " + ", ".join(
            sorted(t["source"] for t in stale)))
    if not lines:
        lines.append("HADR sitrep updated.")
    lines.append(DASHBOARD_URL)
    return "\n".join(lines)


def main() -> int:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("telegram: TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID not configured - skipping")
        return 0
    with open(FACTS_PATH, encoding="utf-8") as handle:
        facts = json.load(handle)
    body = urllib.parse.urlencode({
        "chat_id": chat_id,
        "text": compose(facts),
        "disable_web_page_preview": "true",
    }).encode()
    request = urllib.request.Request(
        "https://api.telegram.org/bot{}/sendMessage".format(token), data=body,
        headers={"User-Agent": "hadr-monitor-notify/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            json.load(response)
        print("telegram: notification sent")
    except Exception as exc:
        print("telegram: send FAILED ({}: {}) - dashboard still published".format(
            type(exc).__name__, exc), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
