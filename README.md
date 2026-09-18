# Finland Spot Price Telegram Alert: Setup & Architecture Guide

A zero-maintenance, serverless monitoring agent that tracks Finnish day-ahead electricity spot prices and pushes a concise, color-coded daily digest to Telegram at 15:00 Europe/Helsinki time using Modal cloud infrastructure.

> **Pricing & Tier Disclaimer**: Modal provides **$30 USD / ~€30 EUR in free compute credits every month** on their Community Tier. A lightweight job running for 3–5 seconds once per day consumes fractions of a cent per month, operating well within the complimentary monthly allowance at zero recurring cost.

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
                            │ HTTPS GET
                            ▼
┌───────────────────────────────────────────────────────────┐
│               Modal Serverless Cloud Runner               │
│          Scheduled: 15:00 Europe/Helsinki Daily           │
│                                                           │
│  1. Pulls pricing data for 14:00 today to 14:00 tomorrow  │
│  2. Evaluates thresholds:                                 │
│       • < 10.00 c/kWh  --> Green  (🟢)                    │
│       • 10.00-19.99 c  --> Orange (🟠)                    │
│       • >= 20.00 c     --> Red    (🔴)                    │
│  3. Compresses 24 discrete hours into grouped blocks      │
│  4. Calculates average, lowest, and highest spread        │
│  5. Formats monospace text for responsive rendering       │
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
└───────────────────────────┌────────────────────────────┘
```

---

## 2. Project File Structure

To deploy the service, organize your project directory as follows:

```text
finland-spot-bot/
├── daily_spot_app.py        # Modal serverless wrapper, container definition, & cron trigger
├── finland_spot_bot.py      # Core data retrieval, interval grouping, & Telegram alert logic
└── README.md                # System overview and operational runbook
```

> **Note on Naming Conventions**: Standard Python module imports require underscores rather than hyphens. Ensure your core script file is named `finland_spot_bot.py` (not `finland-spot-bot.py`) so `daily_spot_app.py` can import it cleanly.

---

## 3. Telegram Bot Configuration

Before deploying the runner, configure an endpoint bot and obtain your personal communication identifiers.

### 3.1 Create the Notification Bot
1. Open the Telegram application and search for the verified account `@BotFather`.
2. Initiate a chat session by clicking **Start** or typing `/start`.
3. Submit the command:
   ```text
   /newbot
   ```
4. Enter a user-friendly display name (e.g., `Finland Electricity Tracker`).
5. Choose a globally unique username ending in `bot` (e.g., `fi_spot_alert_v1_bot`).
6. Copy the HTTP API token emitted by BotFather. Store this string securely; it serves as your `TELEGRAM_BOT_TOKEN`.

### 3.2 Initialize Chat & Retrieve Chat ID
A Telegram bot cannot originate an unsolicited message to an individual account without prior opt-in.
1. Open the direct link provided by `@BotFather` (e.g., `t.me/fi_spot_alert_v1_bot`).
2. Click **Start** to open a direct channel between your personal profile and the bot.
3. Search for the account `@userinfobot` in Telegram and send `/start`.
4. Copy the numeric ID from the response (e.g., `123456789`). This is your `TELEGRAM_CHAT_ID`.

---

## 4. Local Environment Setup & Modal Installation

Modern operating systems (macOS, Debian/Ubuntu) protect system-wide Python with PEP 668 (`externally-managed-environment`), preventing bare `pip install` commands. Always install Modal inside a dedicated virtual environment.

### 4.1 Create and Activate Virtual Environment
Open your terminal inside the `finland-spot-bot` directory and execute:

```bash
# Create an isolated virtual environment named .venv
python3 -m venv .venv

# Activate the virtual environment
# On macOS / Linux:
source .venv/bin/activate

# On Windows (PowerShell):
# .venv\Scripts\Activate.ps1
```

Confirm that your terminal prompt shows `(.venv)`.

### 4.2 Install Modal Client
With your virtual environment activated, install the Modal CLI:

```bash
pip install modal
```

### 4.3 Authenticate Modal CLI
Link your local terminal session to your Modal cloud account:

```bash
modal setup
```

This command opens an authentication window in your default web browser. Sign in using GitHub or Google. Once authenticated, your local terminal registers an encrypted access token automatically.

---

## 5. Modal Secret Configuration

Credentials must never be hardcoded into version control or application files. Store them securely in Modal’s encrypted secret manager:

```bash
modal secret create telegram-secrets TELEGRAM_BOT_TOKEN="YOUR_BOT_TOKEN_HERE" TELEGRAM_CHAT_ID="YOUR_CHAT_ID_HERE"
```

Verify that the secret is registered:

```bash
modal secret list
```

---

## 6. Scheduling, Timezone Logic, & Deployment

### 6.1 Application Implementation Overview
* **`finland_spot_bot.py`**: Handles API requests to `api.porssisahko.net`, computes price metrics, groups adjacent hours by cost thresholds, and dispatches the HTML payload to Telegram.
* **`daily_spot_app.py`**: Defines a lightweight container image based on `debian-slim`, preinstalls `requests`, includes `finland_spot_bot.py`, attaches the `telegram-secrets` vault, and schedules execution with a native timezone cron expression.

### 6.2 Why Modal Cron Solves Daylight Saving Time (DST)
* Finland transitions between Eastern European Time (EET, UTC+2) in winter and Eastern European Summer Time (EEST, UTC+3) in summer.
* Modal natively supports IANA timezone definitions (`timezone="Europe/Helsinki"`) within its cron decorator (`0 15 * * *`). The engine recalculates UTC offsets automatically, executing at 15:00 local time every single day without manual cron adjustments.
* Unlike general CI/CD queues, Modal scheduled functions fire on dedicated serverless infrastructure without queue delays.

### 6.3 Deployment Commands

#### Step 1: Execute an Instant Cloud Test
Verify that your bot script and Telegram secrets operate correctly in the cloud before establishing the daily cron trigger:

```bash
modal run daily_spot_app.py::run_spot_alert
```

Within a few seconds, Modal will spin up a transient cloud container, run the script, and deliver the price alert directly to your Telegram chat.

#### Step 2: Deploy the Persistent Daily Schedule
Publish the scheduled app to run continuously in the cloud:

```bash
modal deploy daily_spot_app.py
```

The terminal will return a deployment summary containing your application's permanent dashboard URL.

---

## 7. Operational Management & Manual Triggers

Once deployed, you do not need to keep your local machine powered on or connected to the internet.

### 7.1 Triggering an On-Demand Run
To test or force a run at any time without altering the 15:00 schedule:

* **Using the Modal CLI**:
  ```bash
  modal run daily_spot_app.py::run_spot_alert
  ```

* **Using Remote Function Lookup (from any Python terminal)**:
  ```bash
  python3 -c "import modal; f = modal.Function.lookup('daily-spot-bot', 'run_spot_alert'); f.remote()"
  ```

* **Using the Web Dashboard**:
  Open the [Modal Web Dashboard](https://modal.com/apps) or run:
  ```bash
  modal dashboard
  ```
  Navigate to `daily-spot-bot` and click **Run** on the `run_spot_alert` function.

### 7.2 Viewing Real-Time Logs
To stream live cloud execution logs directly to your local terminal:

```bash
modal app logs daily-spot-bot
```

### 7.3 Stopping or Deleting the Deployment
If you ever want to pause or delete the scheduled alert:

```bash
modal app stop daily-spot-bot
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
| `externally-managed-environment` error during install | System Python blocks raw pip installs | Create and activate a virtual environment (`python3 -m venv .venv && source .venv/bin/activate`) before running `pip install modal`. |
| Script fails with `Missing TELEGRAM_BOT_TOKEN` | Modal secret not attached or misnamed | Run `modal secret list` to verify `telegram-secrets` exists. Ensure the secret name in `daily_spot_app.py` matches your secret name. |
| Telegram returns `HTTP 401 Unauthorized` | Invalid bot token | Confirm no trailing spaces, quotation marks, or prefixes were included when creating the secret with `modal secret create`. |
| Telegram returns `HTTP 400 Bad Request` | Bot interaction not initiated | Open the bot account in Telegram and press `/start` to allow inbound messages from the bot to your account. |
| `ModuleNotFoundError: No module named 'finland_spot_bot'` | Hyphen in filename or file not added | Ensure your script is named with an underscore (`finland_spot_bot.py`) and is copied into the image definition using `.add_local_file(...)`. |
| Prices for the next day do not appear | Premature execution | Nord Pool publishes final next-day prices between 13:45 and 14:00 EET. The 15:00 schedule provides a reliable 60-minute window for all exchange updates to clear. |