# Finland Spot Price Telegram Alert: Setup & Architecture Guide

A lightweight, zero-dependency monitoring agent that tracks Finnish day-ahead electricity spot prices and pushes a concise, color-coded daily digest to Telegram at **15:00 Europe/Helsinki** time on Ubuntu/Linux using a native `systemd` timer (or `cron`).

---

## 1. System Architecture

```text
┌────────────────────────────────────────────────────────┐
│          Nord Pool Day-Ahead Electricity Market        │
│        (Finalized & published daily by 14:00 EET)      │
└───────────────────────────┬────────────────────────────┘
                            │
                            ▼
┌────────────────────────────────────────────────────────┐
│             Public API (api.porssisahko.net)           │
│           JSON feed with rolling 48-hour spot rates    │
└───────────────────────────┬────────────────────────────┘
                            │ HTTPS GET (Python stdlib urllib)
                            ▼
┌───────────────────────────────────────────────────────────┐
│              Ubuntu / Linux Host (systemd timer)          │
│          Scheduled: 15:00 Europe/Helsinki Daily           │
│          Persistent=true (runs missed jobs on boot)       │
│                                                           │
│  1. Loads credentials from local .env configuration       │
│  2. Pulls pricing data for 14:00 today to 14:00 tomorrow  │
│  3. Evaluates thresholds:                                 │
│       • < 10.00 c/kWh  --> Green  (🟢)                    │
│       • 10.00-19.99 c  --> Orange (🟠)                    │
│       • >= 20.00 c     --> Red    (🔴)                    │
│  4. Compresses 24 discrete hours into grouped blocks      │
│  5. Calculates average, lowest, and highest spread        │
│  6. Formats monospace text for responsive rendering       │
└───────────────────────────┬───────────────────────────────┘
                            │ HTTPS POST
                            ▼
┌────────────────────────────────────────────────────────┐
│             Telegram Bot API (sendMessage)             │
│            Payload: HTML-wrapped monospace pre         │
└───────────────────────────┬────────────────────────────┘
                            │ Push Notification
                            ▼
┌────────────────────────────────────────────────────────┐
│                   Telegram Subscriber                  │
│             Instant grouped summary view               │
└────────────────────────────────────────────────────────┘
```

---

## 2. Project File Structure

```text
finland-spot-price-bot/
├── .env                         # Local secret configuration (git-ignored, created from .env.example)
├── .env.example                 # Template for .env credentials
├── .gitignore                   # Ensures .env and logs are never committed to version control
├── finland_spot_bot.py          # Zero-dependency Python 3 data retrieval & Telegram alert script
├── systemd/
│   ├── finland-spot-bot.service # systemd user service definition (with automatic network retry)
│   └── finland-spot-bot.timer   # systemd user timer (15:00 Europe/Helsinki, Persistent=true)
└── README.md                    # System overview and operational runbook
```

> **Zero External Dependencies**: `finland_spot_bot.py` uses only Python's built-in standard library (`urllib.request`, `json`, `datetime`, `zoneinfo`). No `pip install` or virtual environment (`.venv`) is required on modern Ubuntu/Debian systems (Python 3.9+).

---

## 3. Telegram Bot Configuration

Before deploying the service, create a Telegram bot and obtain your personal chat identifier.

### 3.1 Create the Notification Bot
1. Open Telegram and search for the verified account `@BotFather`.
2. Start a chat by clicking **Start** or sending `/start`.
3. Submit the command:
   ```text
   /newbot
   ```
4. Enter a display name (e.g., `Finland Electricity Tracker`).
5. Choose a unique username ending in `bot` (e.g., `fi_spot_alert_v1_bot`).
6. Copy the HTTP API token provided by BotFather (e.g., `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`). This is your `TELEGRAM_BOT_TOKEN`.

### 3.2 Initialize Chat & Retrieve Chat ID
A Telegram bot cannot message an individual user until the user initiates a conversation with the bot.
1. Open the direct link provided by `@BotFather` (e.g., `t.me/fi_spot_alert_v1_bot`) and click **Start** (`/start`).
2. Search for `@userinfobot` in Telegram and send `/start`.
3. Copy the numeric `Id` from the response (e.g., `123456789`). This is your `TELEGRAM_CHAT_ID`.

---

## 4. Installation & Secret Configuration

### 4.1 Clone the Repository
Clone this repository into your home directory (`~/finland-spot-price-bot`):

```bash
git clone https://github.com/adnanshatil/finland-spot-price-bot.git ~/finland-spot-price-bot
cd ~/finland-spot-price-bot
```

### 4.2 Configure `.env` Credentials
Credentials are stored in a local `.env` file that is automatically ignored by Git.

1. Copy the template file:
   ```bash
   cp .env.example .env
   chmod 600 .env
   ```
2. Open `.env` in a text editor:
   ```bash
   nano .env
   ```
3. Replace the dummy placeholders with your actual credentials:
   ```ini
   TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
   TELEGRAM_CHAT_ID=123456789
   ```

---

## 5. Application Code & Unit Files

### 5.1 Core Script (`finland_spot_bot.py`)
Handles loading `.env`, querying `api.porssisahko.net` with exponential backoff retries, aggregating hourly price buckets, grouping consecutive hours by price tier, and sending the formatted HTML message to Telegram.

```python
#!/usr/bin/env python3
"""Finland Spot Price Telegram Alert Bot.

Fetches Finnish day-ahead electricity spot prices from api.porssisahko.net,
groups consecutive hours by price tier, and dispatches an HTML-formatted
digest to Telegram. Zero external dependencies (Python standard library only).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import datetime
import json
import logging
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.request
import zoneinfo

HELSINKI_TZ = zoneinfo.ZoneInfo("Europe/Helsinki")
PRICES_API_URL = "https://api.porssisahko.net/v1/latest-prices.json"
DEFAULT_ENV_PATH = Path(__file__).resolve().parent / ".env"

PLACEHOLDER_VALUES = {
    "",
    "YOUR_BOT_TOKEN_HERE",
    "YOUR_CHAT_ID_HERE",
    "changeme",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("finland-spot-bot")


def load_dotenv(env_path: Path = DEFAULT_ENV_PATH) -> None:
    """Load KEY=VALUE pairs from a local .env file without external packages."""
    if not env_path.is_file():
        return

    with env_path.open("r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)


def get_tier(price_cents: float) -> str:
    """Map hourly electricity price (c/kWh) to a color tier indicator."""
    if price_cents < 10.0:
        return "🟢"
    elif price_cents < 20.0:
        return "🟠"
    else:
        return "🔴"


def http_json_request(
    url: str,
    method: str = "GET",
    payload: dict | None = None,
    timeout: int = 15,
    retries: int = 3,
    backoff: float = 2.0,
) -> dict:
    """Execute an HTTP request returning parsed JSON with automatic retry on transient errors."""
    headers = {"User-Agent": "finland-spot-price-bot/2.0"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"

    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            if 400 <= exc.code < 500 and exc.code != 429:
                raise RuntimeError(
                    f"HTTP {exc.code} {exc.reason}: {err_body or 'No details'}"
                ) from exc
            last_exc = RuntimeError(
                f"HTTP {exc.code} {exc.reason}: {err_body or 'Transient server error'}"
            )
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_exc = exc

        if attempt < retries:
            sleep_s = backoff ** attempt
            logger.warning(
                "Attempt %d/%d failed (%s). Retrying in %.1fs...",
                attempt,
                retries,
                last_exc,
                sleep_s,
            )
            time.sleep(sleep_s)

    raise RuntimeError(f"Request failed after {retries} attempts: {last_exc}") from last_exc


def fetch_window_prices(
    start_dt: datetime.datetime, end_dt: datetime.datetime
) -> list[tuple[datetime.datetime, float]]:
    """Fetch spot prices and return sorted hourly (datetime, price_cents) pairs inside [start_dt, end_dt)."""
    logger.info("Fetching latest spot prices from %s", PRICES_API_URL)
    data = http_json_request(PRICES_API_URL, method="GET")
    raw_prices = data.get("prices", [])

    hourly_buckets: dict[datetime.datetime, list[float]] = defaultdict(list)
    for item in raw_prices:
        utc_dt = datetime.datetime.fromisoformat(item["startDate"].replace("Z", "+00:00"))
        local_dt = utc_dt.astimezone(HELSINKI_TZ)
        if start_dt <= local_dt < end_dt:
            hour_dt = local_dt.replace(minute=0, second=0, microsecond=0)
            hourly_buckets[hour_dt].append(float(item["price"]))

    window_data = [
        (hour_dt, sum(vals) / len(vals))
        for hour_dt, vals in hourly_buckets.items()
    ]
    window_data.sort(key=lambda x: x[0])
    return window_data


def build_digest_message(
    start_dt: datetime.datetime,
    end_dt: datetime.datetime,
    window_data: list[tuple[datetime.datetime, float]],
) -> str:
    """Format the 24-hour spot price window into an HTML Telegram digest."""
    price_vals = [p for _, p in window_data]
    avg_price = sum(price_vals) / len(price_vals)
    min_price = min(price_vals)
    max_price = max(price_vals)

    blocks: list[dict] = []
    current_block: dict | None = None

    for dt, snt in window_data:
        tier = get_tier(snt)
        if not current_block or current_block["tier"] != tier:
            if current_block:
                blocks.append(current_block)
            current_block = {
                "tier": tier,
                "start": dt,
                "end": dt + datetime.timedelta(hours=1),
                "prices": [snt],
            }
        else:
            current_block["end"] = dt + datetime.timedelta(hours=1)
            current_block["prices"].append(snt)

    if current_block:
        blocks.append(current_block)

    msg_lines = [
        "⚡ <b>Finland Spot Prices</b>",
        f"📅 <i>{start_dt.strftime('%d.%m %H:%M')} – {end_dt.strftime('%d.%m %H:%M')}</i>\n",
        f"📊 <b>Avg:</b> {avg_price:.2f} c | <b>Min:</b> {min_price:.2f} c | <b>Max:</b> {max_price:.2f} c\n",
        "<pre>",
    ]

    for b in blocks:
        count = len(b["prices"])
        avg_b = sum(b["prices"]) / count
        min_b, max_b = min(b["prices"]), max(b["prices"])
        time_range = f"{b['start'].strftime('%H:00')}–{b['end'].strftime('%H:00')}"
        price_spread = f"{min_b:.2f} c" if count == 1 else f"{min_b:.2f} - {max_b:.2f} c"
        msg_lines.append(
            f"{b['tier']} {time_range:<11} ({count}h)  avg {avg_b:>5.2f} c  [{price_spread}]"
        )

    msg_lines.append("</pre>")
    return "\n".join(msg_lines)


def send_telegram_message(bot_token: str, chat_id: str, html_text: str) -> None:
    """Send an HTML-formatted message via the Telegram Bot API."""
    telegram_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": html_text,
        "parse_mode": "HTML",
    }
    resp = http_json_request(telegram_url, method="POST", payload=payload)
    if not resp.get("ok"):
        raise RuntimeError(f"Telegram API returned error: {resp}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Finland electricity spot prices and send a daily Telegram digest."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_PATH,
        help="Path to the .env configuration file (default: %(default)s)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch prices and print the formatted message without sending to Telegram",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    load_dotenv(args.env_file)

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()

    if not args.dry_run and (
        bot_token in PLACEHOLDER_VALUES or chat_id in PLACEHOLDER_VALUES
    ):
        logger.error(
            "Missing or placeholder TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID. "
            "Please update %s with your actual credentials.",
            args.env_file,
        )
        sys.exit(1)

    now = datetime.datetime.now(HELSINKI_TZ)
    start_dt = now.replace(hour=14, minute=0, second=0, microsecond=0)
    end_dt = start_dt + datetime.timedelta(days=1)

    try:
        window_data = fetch_window_prices(start_dt, end_dt)
    except Exception as exc:
        logger.error("Failed to fetch spot prices: %s", exc)
        sys.exit(1)

    if not window_data:
        logger.warning(
            "No price data found for window %s – %s.",
            start_dt.strftime("%Y-%m-%d %H:%M"),
            end_dt.strftime("%Y-%m-%d %H:%M"),
        )
        return

    final_message = build_digest_message(start_dt, end_dt, window_data)

    if args.dry_run:
        logger.info("Dry run complete (%d hourly slots). Formatted output:\n%s", len(window_data), final_message)
        return

    try:
        logger.info(
            "Sending digest (%d hourly slots) for %s – %s to Telegram...",
            len(window_data),
            start_dt.strftime("%d.%m %H:%M"),
            end_dt.strftime("%d.%m %H:%M"),
        )
        send_telegram_message(bot_token, chat_id, final_message)
        logger.info("Telegram alert delivered successfully.")
    except Exception as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
```

### 5.2 `systemd` Service & Timer Units

* **`systemd/finland-spot-bot.service`** (`%h` automatically resolves to the current user's home directory):
  ```ini
  [Unit]
  Description=Finland Spot Price Telegram Alert Bot
  Wants=network-online.target
  After=network-online.target
  StartLimitIntervalSec=600
  StartLimitBurst=3

  [Service]
  Type=oneshot
  WorkingDirectory=%h/finland-spot-price-bot
  EnvironmentFile=-%h/finland-spot-price-bot/.env
  ExecStart=/usr/bin/python3 %h/finland-spot-price-bot/finland_spot_bot.py
  Restart=on-failure
  RestartSec=60
  StandardOutput=journal
  StandardError=journal
  ```

* **`systemd/finland-spot-bot.timer`**:
  ```ini
  [Unit]
  Description=Run Finland Spot Price Telegram Alert daily at 15:00 Europe/Helsinki

  [Timer]
  OnCalendar=*-*-* 15:00:00 Europe/Helsinki
  Persistent=true
  AccuracySec=1s
  Unit=finland-spot-bot.service

  [Install]
  WantedBy=timers.target
  ```

---

## 6. Scheduling & Deployment on Ubuntu

### 6.1 Option A: `systemd` User Timer (Recommended)
Using a `systemd` timer instead of a traditional cronjob provides:
* **Automatic Daylight Saving Time (DST) handling**: `OnCalendar=*-*-* 15:00:00 Europe/Helsinki` adjusts between EET (UTC+2) and EEST (UTC+3) automatically.
* **Missed-run catch-up (`Persistent=true`)**: If the server is powered off or rebooting at 15:00, the job runs immediately when the system comes back up.
* **Automatic failure recovery**: Retries automatically if the network is temporarily unreachable.

Run the following commands to install and activate the timer:

```bash
# 1. Create the systemd user unit directory
mkdir -p ~/.config/systemd/user

# 2. Copy the service and timer definitions
cp ~/finland-spot-price-bot/systemd/finland-spot-bot.service ~/.config/systemd/user/
cp ~/finland-spot-price-bot/systemd/finland-spot-bot.timer ~/.config/systemd/user/

# 3. Reload systemd and enable the daily timer
systemctl --user daemon-reload
systemctl --user enable --now finland-spot-bot.timer

# 4. Enable lingering so user timers fire even without an active login session
loginctl enable-linger "$USER"
```

### 6.2 Option B: Traditional Cronjob (Alternative)
If you prefer `cron` instead of `systemd`, open your user crontab with `crontab -e` and add:

```cron
CRON_TZ=Europe/Helsinki
0 15 * * * /usr/bin/python3 $HOME/finland-spot-price-bot/finland_spot_bot.py >> $HOME/finland-spot-price-bot/spot_bot.log 2>&1
```

---

## 7. Operational Management & Manual Testing

### 7.1 Dry-Run Test (No Telegram Credentials Needed)
To verify API connectivity and preview the formatted output in the terminal without sending a message to Telegram:

```bash
python3 ~/finland-spot-price-bot/finland_spot_bot.py --dry-run
```

### 7.2 Trigger an On-Demand Telegram Alert
Once `.env` is configured with your token and chat ID, trigger a live notification at any time:

```bash
# Run directly with Python
python3 ~/finland-spot-price-bot/finland_spot_bot.py

# Or trigger via systemd
systemctl --user start finland-spot-bot.service
```

### 7.3 Inspect Timer Status & Logs
```bash
# Check next scheduled execution time
systemctl --user list-timers finland-spot-bot.timer

# View recent execution logs
journalctl --user -u finland-spot-bot.service -n 50 --no-pager

# Follow logs in real time
journalctl --user -u finland-spot-bot.service -f
```

### 7.4 Stopping or Disabling the Timer
```bash
systemctl --user disable --now finland-spot-bot.timer
```

---

## 8. Sample Notification Output

The alert renders inside a monospace `<pre>` block to ensure uniform tabular column alignment across mobile and desktop clients:

```text
⚡ Finland Spot Prices
📅 18.09 14:00 – 19.09 14:00

📊 Avg: 8.42 c | Min: 2.10 c | Max: 24.15 c

🟢 14:00–17:00  (3h)   avg  6.10 c  [4.50 - 8.20 c]
🟠 17:00–21:00  (4h)   avg 14.80 c  [11.20 - 18.90 c]
🔴 21:00–22:00  (1h)   avg 24.15 c  [24.15 c]
🟠 22:00–23:00  (1h)   avg 12.40 c  [12.40 c]
🟢 23:00–07:00  (8h)   avg  3.20 c  [2.10 - 4.80 c]
🟠 07:00–09:00  (2h)   avg 11.50 c  [10.10 - 12.90 c]
🟢 09:00–14:00  (5h)   avg  7.25 c  [5.10 - 9.40 c]
```

---

## 9. Troubleshooting & Operational Runbook

| Observation | Root Cause | Remediation Procedure |
| :--- | :--- | :--- |
| `Missing or placeholder TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID` | `.env` missing or still has dummy values | Copy `.env.example` to `.env` and set your real `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`. |
| Telegram returns `HTTP 401 Unauthorized` | Invalid bot token | Confirm no trailing spaces, quotes, or extra prefixes were included in `TELEGRAM_BOT_TOKEN` inside `.env`. |
| Telegram returns `HTTP 400 Bad Request` | Bot chat not initiated or invalid `CHAT_ID` | Open the bot in Telegram and send `/start` to allow inbound messages, and verify your numeric `TELEGRAM_CHAT_ID`. |
| `systemd` timer does not run when logged out | User lingering not enabled | Run `loginctl enable-linger "$USER"` so the user service manager stays active at boot. |
| Next-day prices only show until midnight | Executed before 14:00 EET | Nord Pool publishes final next-day prices between 13:45 and 14:00 EET. The 15:00 schedule ensures the full 24-hour window (`14:00–14:00`) is published. |
