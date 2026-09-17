import os
import sys
import datetime
import zoneinfo
import requests

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN or not CHAT_ID:
    print("Error: Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID environment variables.")
    sys.exit(1)

HELSINKI_TZ = zoneinfo.ZoneInfo("Europe/Helsinki")

def get_tier(price_cents: float) -> str:
    if price_cents < 10.0:
        return "🟢"
    elif price_cents < 20.0:
        return "🟠"
    else:
        return "🔴"

def main():
    now = datetime.datetime.now(HELSINKI_TZ)
    
    start_dt = now.replace(hour=14, minute=0, second=0, microsecond=0)
    end_dt = start_dt + datetime.timedelta(days=1)
    
    url = "https://api.porssisahko.net/v1/latest-prices.json"
    res = requests.get(url, timeout=10)
    res.raise_for_status()
    prices = res.json().get("prices", [])
    
    window_data = []
    for item in prices:
        utc_dt = datetime.datetime.fromisoformat(item["startDate"].replace("Z", "+00:00"))
        local_dt = utc_dt.astimezone(HELSINKI_TZ)
        if start_dt <= local_dt < end_dt:
            window_data.append((local_dt, float(item["price"])))

    window_data.sort(key=lambda x: x[0])
    if not window_data:
        print("No price data found.")
        return

    price_vals = [p for _, p in window_data]
    avg_price = sum(price_vals) / len(price_vals)
    min_price = min(price_vals)
    max_price = max(price_vals)

    blocks = []
    current_block = None

    for dt, snt in window_data:
        tier = get_tier(snt)
        if not current_block or current_block["tier"] != tier:
            if current_block:
                blocks.append(current_block)
            current_block = {
                "tier": tier,
                "start": dt,
                "end": dt + datetime.timedelta(hours=1),
                "prices": [snt]
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
        "<pre>"
    ]

    for b in blocks:
        count = len(b["prices"])
        avg_b = sum(b["prices"]) / count
        min_b, max_b = min(b["prices"]), max(b["prices"])
        time_range = f"{b['start'].strftime('%H:00')}–{b['end'].strftime('%H:00')}"
        price_spread = f"{min_b:.2f} c" if count == 1 else f"{min_b:.2f} - {max_b:.2f} c"
        msg_lines.append(f"{b['tier']} {time_range:<11} ({count}h)  avg {avg_b:>5.2f} c  [{price_spread}]")

    msg_lines.append("</pre>")
    final_message = "\n".join(msg_lines)

    requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": CHAT_ID, "text": final_message, "parse_mode": "HTML"},
        timeout=10
    )

if __name__ == "__main__":
    main()