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
            # Do not retry client configuration errors (e.g. 400 Bad Request, 401 Unauthorized)
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
