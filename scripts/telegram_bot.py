"""Telegram bot for asking the HADR monitor for updates.

Message it anything (or /status) and it answers with the latest published
monitoring picture, read from the repo's committed data/facts.json on
GitHub - the same facts every dashboard statement derives from. It reports;
it never fetches feeds or runs the pipeline (the model-free half of the
model boundary applies to chat too).

One-time setup:
  1. In Telegram, message @BotFather: /newbot -> pick a name and username.
  2. Put the token in .env at the repo root (gitignored, never committed):
       TELEGRAM_BOT_TOKEN=123456:ABC...
  3. Run:  python scripts/telegram_bot.py
  4. Message your bot once - it replies with your chat id. Add
       TELEGRAM_CHAT_ID=<that id>
     to .env and restart to lock the bot to you alone.

python scripts/telegram_bot.py --preview   prints the /status reply and
exits: no Telegram, no token needed.
"""

import json
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
FACTS_URL = "https://raw.githubusercontent.com/GodofGaren1/hadr-starter/main/data/facts.json"
DASHBOARD_URL = "https://godofgaren1.github.io/hadr-starter/dashboard.html"
USER_AGENT = "hadr-monitor-telegram/0.1"

LEVEL_ICON = {"red": "\U0001F534", "orange": "\U0001F7E0", "yellow": "\U0001F7E1",
              "green": "\U0001F7E2", None: "⚪"}

HELP_TEXT = (
    "HADR monitor bot. Commands:\n"
    "/status - latest published monitoring picture (any text works too)\n"
    "/dashboard - link to the live situation report\n"
    "/help - this message\n\n"
    "Data comes from the monitor's last committed run; a new sitrep is "
    "published every morning by 08:30 SGT when anything changed."
)


def load_env() -> dict:
    values = {}
    env_path = REPO_ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                values[key.strip()] = value.strip()
    return values


def http_json(url: str, params: dict = None, timeout: int = 60) -> dict:
    data = urllib.parse.urlencode(params).encode() if params else None
    request = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def sgt(iso: str) -> str:
    if not iso:
        return "unknown"
    moment = datetime.fromisoformat(iso).astimezone(timezone(timedelta(hours=8)))
    return moment.strftime("%d %b %H:%M") + " SGT"


def format_status(facts: dict) -> str:
    lines = ["HADR monitor - last run {}".format(sgt(facts.get("generated_at")))]

    for note in facts.get("source_notes", []):
        lines.append("⚠️ {} feed unreachable (last success {})".format(
            note["source"], sgt(note.get("stale_since"))))

    significant = facts.get("significant", [])
    if significant:
        lines.append("")
        lines.append("Needs attention ({}):".format(len(significant)))
        for item in significant:
            event = item["event"]
            lines.append("{} {} [{}]".format(
                LEVEL_ICON.get(event.get("alert_level"), "⚪"),
                event.get("title") or item["key"],
                item["reason"].replace("_", " ")))
    else:
        lines.append("Quiet - nothing new needs attention.")

    reported = facts.get("previously_reported", [])
    if reported:
        rank = {"red": 4, "orange": 3, "yellow": 2, "green": 1}
        reported = sorted(reported,
                          key=lambda e: rank.get(e.get("current_level"), 0),
                          reverse=True)
        lines.append("")
        lines.append("Tracking ({} reported incidents):".format(len(reported)))
        for entry in reported:
            level = entry.get("current_level")
            line = "{} {}".format(LEVEL_ICON.get(level, "⚪"),
                                  entry.get("title") or entry["key"])
            if level != entry.get("reported_level"):
                line += "  (was {}, now {})".format(entry.get("reported_level"), level)
            lines.append(line)

    counts = facts.get("counts", {})
    by_source = counts.get("tracked_by_source", {})
    lines.append("")
    lines.append("{} events tracked ({}), {} cross-source incidents.".format(
        counts.get("events_tracked", "?"),
        ", ".join("{} {}".format(v, k) for k, v in sorted(by_source.items())) or "n/a",
        counts.get("correlated_incidents", "?")))
    lines.append("Dashboard: " + DASHBOARD_URL)
    return "\n".join(lines)


def get_status_message() -> str:
    try:
        facts = http_json(FACTS_URL, timeout=30)
    except Exception as exc:
        return ("Could not read the monitor's published facts from GitHub "
                "({}: {}). Try again in a minute, or check {}".format(
                    type(exc).__name__, exc, DASHBOARD_URL))
    return format_status(facts)


def telegram(token: str, method: str, params: dict, timeout: int = 60) -> dict:
    url = "https://api.telegram.org/bot{}/{}".format(token, method)
    return http_json(url, params, timeout=timeout)


def run_bot() -> int:
    env = load_env()
    token = env.get("TELEGRAM_BOT_TOKEN")
    if not token:
        print("TELEGRAM_BOT_TOKEN missing. Create a bot via @BotFather in "
              "Telegram, then put TELEGRAM_BOT_TOKEN=<token> in .env at the "
              "repo root and rerun.", file=sys.stderr)
        return 2
    allowed_chat = env.get("TELEGRAM_CHAT_ID")
    me = telegram(token, "getMe", {})
    print("Bot @{} is up. Talk to it in Telegram; Ctrl+C stops it.".format(
        me["result"]["username"]))
    if not allowed_chat:
        print("NOTE: TELEGRAM_CHAT_ID not set - the bot will tell each new "
              "sender their chat id and answer anyone. Lock it down after "
              "your first message.")

    offset = 0
    while True:
        try:
            updates = telegram(token, "getUpdates",
                               {"offset": offset, "timeout": 50}, timeout=70)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print("getUpdates failed ({}); retrying in 5 s".format(exc))
            time.sleep(5)
            continue
        for update in updates.get("result", []):
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            chat_id = str((message.get("chat") or {}).get("id", ""))
            text = (message.get("text") or "").strip().lower()
            if not chat_id or not text:
                continue
            if allowed_chat and chat_id != allowed_chat:
                continue  # not our user; stay silent
            if not allowed_chat:
                telegram(token, "sendMessage", {
                    "chat_id": chat_id,
                    "text": "Your chat id is {}. Put TELEGRAM_CHAT_ID={} in "
                            ".env to lock this bot to you.".format(chat_id, chat_id)})
            if text in ("/help", "/start"):
                reply = HELP_TEXT
            elif text == "/dashboard":
                reply = DASHBOARD_URL
            else:  # /status and any free-text question
                reply = get_status_message()
            try:
                telegram(token, "sendMessage", {"chat_id": chat_id, "text": reply,
                                                "disable_web_page_preview": "true"})
            except Exception as exc:
                print("sendMessage failed: {}".format(exc))


def main() -> int:
    # Windows consoles default to cp1252, which cannot print the level
    # icons; Telegram itself is UTF-8 and unaffected.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--preview" in sys.argv:
        local = REPO_ROOT / "data" / "facts.json"
        if local.exists():
            with open(local, encoding="utf-8") as handle:
                print(format_status(json.load(handle)))
        else:
            print(get_status_message())
        return 0
    try:
        return run_bot()
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
