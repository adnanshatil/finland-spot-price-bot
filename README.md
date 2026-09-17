# Finland Spot Price Telegram Alert: Setup & Architecture Guide

A zero-maintenance, serverless monitoring agent that tracks Finnish day-ahead electricity spot prices and pushes a concise, color-coded daily digest to Telegram at 15:00 Europe/Helsinki time.

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
│             GitHub Actions Serverless Runner              │
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
└────────────────────────────────────────────────────────┘
```

---

## 2. Project File Structure

To keep deployment clean and dependency-free, this architecture requires only two files in the repository:

```text
finland-spot-bot/
├── .github/
│   └── workflows/
│       └── daily_spot.yml    # Cron orchestration and environment mapping
├── spot_bot.py               # Data extraction, interval grouping, API dispatch
└── README.md                 # System overview and operational runbook
```

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
2. Click **Start** to open a channel between your personal profile and the bot.
3. Search for the account `@userinfobot` in Telegram and send `/start`.
4. Copy the numeric ID from the response (e.g., `123456789`). This is your `TELEGRAM_CHAT_ID`.

---

## 4. GitHub Secret Storage

Credentials must never be hard-coded into version control repositories. Store them as encrypted secrets:

1. Open your repository on GitHub.
2. Navigate to **Settings** along the primary tab bar.
3. On the left navigation pane, expand **Secrets and variables** and select **Actions**.
4. In the **Repository secrets** section, click **New repository secret**.
5. Add the first variable:
   * **Name**: `TELEGRAM_BOT_TOKEN`
   * **Secret**: *(Paste your token obtained from BotFather)*
6. Click **Add secret**.
7. Click **New repository secret** again to add the second variable:
   * **Name**: `TELEGRAM_CHAT_ID`
   * **Secret**: *(Paste your numeric Telegram Chat ID)*
8. Click **Add secret**.

---

## 5. Workflow Scheduling & Timezone Logic

The automation schedule utilizes GitHub's native cron syntax paired with the `Europe/Helsinki` IANA timezone identifier:

```yaml
schedule:
  - cron: '0 15 * * *'
    timezone: 'Europe/Helsinki'
```

### Why Native Timezones Matter
* **Daylight Saving Time (DST) Handling**: Finland shifts between Eastern European Time (EET, UTC+2) during winter and Eastern European Summer Time (EEST, UTC+3) during summer. Specifying `timezone: 'Europe/Helsinki'` ensures execution remains pinned to 15:00 local time year-round without manual cron edits in October and March.
* **Execution Window Alignment**: Nord Pool prices for the following day are finalized and released by 13:45–14:00 EET. Triggering daily at 15:00 guarantees 100% data availability for both the current afternoon and the full 24-hour forward lookahead.

---

## 6. Price Grouping & Aggregation Engine

Raw feeds emit 24 individual hourly records. Scanning 24 discrete rows on mobile devices introduces visual clutter. The aggregation engine condenses this stream using contiguous block grouping.

### Classification Matrix
| Tier Threshold | Visual Indicator | Energy Implication |
| :--- | :---: | :--- |
| Below 10.00 c/kWh | 🟢 | **Favorable**: Ideal for EV charging, heating water, major appliances |
| 10.00 to 19.99 c/kWh | 🟠 | **Moderate**: Baseline consumption; standard household operation |
| 20.00 c/kWh and above | 🔴 | **Peak Alert**: Restrict heavy loads, pause automated EV charging |

### Contiguous Grouping Mechanism
Rather than bucketing arbitrary periods, the script walks chronological hours and aggregates adjacent hours if and only if they maintain the same color tier:
* If 14:00, 15:00, and 16:00 are all under 10c, they are merged into one entry: `14:00–17:00 (3h)`.
* When the price enters the orange bracket at 17:00, the previous block closes, and a new group begins.
* For each block, the engine displays:
  * Inclusive start and exclusive end time
  * Total duration in hours
  * Mathematical average price (`avg X.XX c`)
  * Lowest and highest boundaries in brackets (`[min - max c]`)

---

## 7. Sample Notification Output

The alert is pushed in a monospace container to ensure aligned tabular formatting across iOS, Android, macOS, and Windows Telegram clients:

```text
⚡ Finland Spot Prices
📅 17.09 14:00 – 18.09 14:00

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

## 8. Manual Triggering & Verification

You can verify the deployment immediately without waiting for the 15:00 schedule:

1. In your GitHub repository, click the **Actions** tab.
2. Under **All workflows** on the left menu, select **Daily Finland Spot Price Alert**.
3. In the blue notification banner on the right, open the **Run workflow** dropdown.
4. Leave the target branch set to `main` and click **Run workflow**.
5. Within 15 to 30 seconds, a green checkmark will appear under the run history, and the notification will arrive in your Telegram app.

---

## 9. Failure Modes & Operational Runbook

| Observation | Root Cause | Remediation Procedure |
| :--- | :--- | :--- |
| GitHub Action fails with exit code `1` | Missing repository secrets | Verify exact spelling of `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` under repository settings. |
| Telegram returns `HTTP 401 Unauthorized` | Invalid bot authentication | Verify that no extraneous whitespace or quotation marks were pasted into the GitHub secret. |
| Telegram returns `HTTP 400 Bad Request` | Bot chat not initiated | Open the bot in Telegram and send `/start` to establish communication. |
| Script reports incomplete pricing window | Premature execution | Nord Pool occasionally encounters publishing delays. The 15:00 schedule provides a 60-minute buffer beyond the standard 14:00 market close. |
| Workflow starts a few minutes past 15:00 | GitHub Actions shared runner queue | GitHub queues scheduled workflows during periods of peak worldwide load. The script queries a fixed 14:00–14:00 target window, meaning calculations remain accurate regardless of minor queue delays. |