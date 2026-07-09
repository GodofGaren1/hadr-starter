"""Telegram bot for asking the HADR monitor for updates.

/status answers with the latest published monitoring picture, read from the
repo's committed data/facts.json on GitHub - the same facts every dashboard
statement derives from. Any other message is treated as a question and
answered by Claude (via the locally installed Claude Code CLI in headless
mode, `claude -p` - your existing login, no API key), grounded in those same
facts. The bot never fetches feeds or runs the pipeline.

One-time setup:
  1. In Telegram, message @BotFather: /newbot -> pick a name and username.
  2. Put the token in .env at the repo root (gitignored, never committed):
       TELEGRAM_BOT_TOKEN=123456:ABC...
  3. Run:  python scripts/telegram_bot.py
  4. Message your bot once - it replies with your chat id. Add
       TELEGRAM_CHAT_ID=<that id>
     to .env and restart to lock the bot to you alone.

python scripts/telegram_bot.py --preview        prints the /status reply
python scripts/telegram_bot.py --ask "..."      answers one question
(both exit immediately: no Telegram, no bot token needed)
"""

import json
import shutil
import subprocess
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
    "/status - latest published monitoring picture\n"
    "/dashboard - link to the live situation report\n"
    "/help - this message\n\n"
    "Anything else you type is answered by Claude, grounded in the "
    "monitor's published facts (e.g. 'anything serious near Japan?').\n\n"
    "Data comes from the monitor's last committed run; a new sitrep is "
    "published every morning by 08:30 SGT when anything changed."
)

CLAUDE_TIMEOUT_SECONDS = 180
MAX_REPLY_CHARS = 3900  # Telegram rejects messages over 4096 chars


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


def ask_claude(question: str) -> str:
    """Answer a free-form question with Claude, grounded in the published
    facts. Uses the Claude Code CLI headless (`claude -p`) so it rides the
    operator's existing login - no API key, no pip dependency. Every failure
    path degrades to the deterministic status reply instead of an error."""
    claude = shutil.which("claude")
    if not claude:
        return ("(Claude CLI not found on this machine, so free-form answers "
                "are off. Standard status instead:)\n\n" + get_status_message())
    try:
        facts_blob = json.dumps(http_json(FACTS_URL, timeout=30))
    except Exception:
        facts_blob = ("UNAVAILABLE - the published facts could not be "
                      "fetched; say so if asked about current monitor state.")
    prompt = (
        "You are the Telegram chat interface of a HADR (humanitarian "
        "disaster) monitoring agent. Its entire knowledge of the current "
        "world situation is the facts JSON below, produced by its last "
        "pipeline run. Rules: ground every claim about current disasters or "
        "monitor state in that JSON, and say plainly when it does not cover "
        "something - never invent events. General knowledge questions (e.g. "
        "what a PAGER alert level means) may be answered normally. Reply in "
        "plain text, no markdown, a few short sentences - this is a phone "
        "chat. Dashboard link if useful: " + DASHBOARD_URL
        + "\n\nFACTS JSON:\n" + facts_blob
        + "\n\nUSER QUESTION: " + question
    )
    try:
        # Prompt goes via stdin: facts JSON can exceed Windows argv limits.
        result = subprocess.run(
            [claude, "-p", "--output-format", "text"],
            input=prompt, capture_output=True, text=True, encoding="utf-8",
            timeout=CLAUDE_TIMEOUT_SECONDS,
        )
        answer = (result.stdout or "").strip()
        if result.returncode != 0 or not answer:
            raise RuntimeError((result.stderr or "empty answer").strip()[:200])
        return answer[:MAX_REPLY_CHARS]
    except Exception as exc:
        return ("(Claude could not answer that right now: {}. Standard "
                "status instead:)\n\n".format(exc) + get_status_message())


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
            text = (message.get("text") or "").strip()
            command = text.lower()
            if not chat_id or not text:
                continue
            if allowed_chat and chat_id != allowed_chat:
                continue  # not our user; stay silent
            if not allowed_chat:
                telegram(token, "sendMessage", {
                    "chat_id": chat_id,
                    "text": "Your chat id is {}. Put TELEGRAM_CHAT_ID={} in "
                            ".env to lock this bot to you.".format(chat_id, chat_id)})
            if command in ("/help", "/start"):
                reply = HELP_TEXT
            elif command == "/dashboard":
                reply = DASHBOARD_URL
            elif command == "/status":
                reply = get_status_message()
            else:  # free-form question -> Claude, grounded in the facts
                reply = ask_claude(text)
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
    if "--ask" in sys.argv:
        index = sys.argv.index("--ask")
        if index + 1 >= len(sys.argv):
            print("usage: telegram_bot.py --ask \"your question\"", file=sys.stderr)
            return 2
        print(ask_claude(sys.argv[index + 1]))
        return 0
    try:
        return run_bot()
    except KeyboardInterrupt:
        print("\nstopped")
        return 0


if __name__ == "__main__":
    sys.exit(main())
