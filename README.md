# Finland Spot Price Telegram Alert: Ubuntu Setup & Architecture Guide

A lightweight, zero-dependency monitoring agent that tracks Finnish day-ahead electricity spot prices and pushes a concise, color-coded daily digest to Telegram at **15:00 Europe/Helsinki** time from an Ubuntu server using a native `systemd` timer.

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
│              Ubuntu Host (systemd --user timer)           │
│          Scheduled: 15:00 Europe/Helsinki Daily           │
│          Persistent=true (runs missed jobs on boot)       │
│                                                           │
│  1. Loads credentials from ~/finland-spot-price-bot/.env  │
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
~/finland-spot-price-bot/
├── .env                         # Local secret configuration (git-ignored)
├── .env.example                 # Template for .env credentials
├── .gitignore                   # Ensures .env and logs are never committed
├── finland_spot_bot.py          # Zero-dependency Python 3 data fetch & Telegram alert script
├── systemd/
│   ├── finland-spot-bot.service # systemd user service definition (with auto-retry)
│   └── finland-spot-bot.timer   # systemd user timer (15:00 Europe/Helsinki, Persistent=true)
└── README.md                    # System overview and operational runbook
```

* **Zero External Dependencies**: `finland_spot_bot.py` uses only Python's built-in standard library (`urllib.request`, `json`, `datetime`, `zoneinfo`). No `pip install` or virtual environment (`.venv`) is required on Ubuntu.

---

## 3. Telegram Bot & Token Configuration

### 3.1 Obtain Telegram Credentials
1. **Bot Token (`TELEGRAM_BOT_TOKEN`)**:
   * Open Telegram and message `@BotFather`.
   * Send `/newbot` (or `/token` for an existing bot) and copy the HTTP API token (e.g., `123456789:ABCdefGHIjklMNOpqrSTUvwxYZ`).
2. **Chat ID (`TELEGRAM_CHAT_ID`)**:
   * Open a chat with your bot in Telegram and click **Start** (`/start`).
   * Message `@userinfobot` in Telegram with `/start` and copy your numeric `Id` (e.g., `123456789`).

### 3.2 Update Tokens in `.env`
All credentials live in `~/finland-spot-price-bot/.env` (which is ignored by Git so your tokens are never pushed to GitHub).

To edit your tokens on Ubuntu (`adnan@192.168.2.2`):

```bash
nano ~/finland-spot-price-bot/.env
```

Fill in your values:

```ini
TELEGRAM_BOT_TOKEN=123456789:ABCdefGHIjklMNOpqrSTUvwxYZ
TELEGRAM_CHAT_ID=123456789
```

Restrict file permissions so only your user account can read the file:

```bash
chmod 600 ~/finland-spot-price-bot/.env
```

---

## 4. Ubuntu Deployment & Scheduling (`systemd` Timer)

### Why `systemd` Timer Instead of Cron?
* **Timezone & DST Aware**: `OnCalendar=*-*-* 15:00:00 Europe/Helsinki` automatically adjusts between winter time (EET, UTC+2) and summer time (EEST, UTC+3).
* **Missed-Run Recovery (`Persistent=true`)**: If the Ubuntu host is powered off or rebooting at 15:00, `systemd` triggers the alert immediately once the system comes back online.
* **Automatic Network Retry**: Both the Python script (3 attempts with exponential backoff) and the `systemd` unit (`Restart=on-failure`, `RestartSec=60`) automatically recover from temporary network glitches.
* **Centralized Logging**: Every run is logged with timestamps via `journalctl`.

### 4.1 Install and Enable the User Timer
On your Ubuntu machine (`adnan@192.168.2.2`):

```bash
# 1. Create the user systemd directory
mkdir -p ~/.config/systemd/user

# 2. Copy the service and timer unit files
cp ~/finland-spot-price-bot/systemd/finland-spot-bot.service ~/.config/systemd/user/
cp ~/finland-spot-price-bot/systemd/finland-spot-bot.timer ~/.config/systemd/user/

# 3. Reload systemd user daemon and enable the timer
systemctl --user daemon-reload
systemctl --user enable --now finland-spot-bot.timer

# 4. Ensure user timers run even when logged out of SSH
loginctl enable-linger "$USER"
```

### 4.2 Alternative: Classic Cronjob (Optional)
If you ever prefer a traditional `crontab` instead of the `systemd` timer, disable the timer (`systemctl --user disable --now finland-spot-bot.timer`) and add the following to `crontab -e`:

```cron
CRON_TZ=Europe/Helsinki
0 15 * * * /usr/bin/python3 /home/adnan/finland-spot-price-bot/finland_spot_bot.py >> /home/adnan/finland-spot-price-bot/spot_bot.log 2>&1
```

---

## 5. Operational Management & Manual Testing

### 5.1 Test Price Fetching Without Sending to Telegram (`--dry-run`)
Verify API connectivity and preview the formatted message in your terminal without needing valid Telegram credentials:

```bash
python3 ~/finland-spot-price-bot/finland_spot_bot.py --dry-run
```

### 5.2 Trigger an Immediate Telegram Alert
Once your `.env` file has your real `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`, test the full end-to-end alert at any time:

```bash
# Run directly via Python:
python3 ~/finland-spot-price-bot/finland_spot_bot.py

# Or trigger through systemd:
systemctl --user start finland-spot-bot.service
```

### 5.3 Check Timer Schedule & Next Run Time
```bash
systemctl --user list-timers finland-spot-bot.timer
```

### 5.4 View Execution Logs
```bash
# View recent logs from the service
journalctl --user -u finland-spot-bot.service -n 50 --no-pager

# Follow logs in real time
journalctl --user -u finland-spot-bot.service -f
```

---

## 6. Reference Code

### `finland_spot_bot.py`
```python
#!/usr/bin/env python3
"""Finland Spot Price Telegram Alert Bot."""

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
```
*(See [`finland_spot_bot.py`](./finland_spot_bot.py) in this repository for the full script.)*

### `systemd/finland-spot-bot.service`
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

### `systemd/finland-spot-bot.timer`
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

## 7. Sample Notification Output

The alert renders inside a monospace `<pre>` block to ensure uniform tabular alignment across mobile and desktop clients:

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

## 8. Troubleshooting & Operational Runbook

| Observation | Root Cause | Remediation Procedure |
| :--- | :--- | :--- |
| `Missing or placeholder TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID` | `.env` still contains placeholder values | Edit `~/finland-spot-price-bot/.env` and replace `YOUR_BOT_TOKEN_HERE` and `YOUR_CHAT_ID_HERE` with your actual credentials. |
| Telegram returns `HTTP 401 Unauthorized` | Invalid bot token | Verify `TELEGRAM_BOT_TOKEN` in `.env` has no extra spaces or prefixes. |
| Telegram returns `HTTP 400 Bad Request` | Bot interaction not initiated or invalid `CHAT_ID` | Open the bot in Telegram and send `/start`, and verify your numeric `TELEGRAM_CHAT_ID` via `@userinfobot`. |
| Timer does not fire when logged out of SSH | User lingering not enabled | Run `loginctl enable-linger adnan` on Ubuntu so `systemd --user` stays active without an active SSH session. |
| Next-day prices only show until midnight | Executed before 14:00 EET | Nord Pool publishes next-day prices between 13:45 and 14:00 EET. Running at 15:00 guarantees the full 24-hour window (`14:00–14:00`) is available. |
