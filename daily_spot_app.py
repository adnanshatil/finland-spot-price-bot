import modal

app = modal.App("daily-spot-bot")

# Build a Debian container with requests and include the bot script
image = (
    modal.Image.debian_slim()
    .pip_install("requests")
    .add_local_file("finland_spot_bot.py", "/root/finland_spot_bot.py")
)

# Runs every day at 15:00 sharp Helsinki time (DST handled automatically)
@app.function(
    schedule=modal.Cron("0 15 * * *", timezone="Europe/Helsinki"),
    image=image,
    secrets=[modal.Secret.from_name("telegram-secrets")]
)
def run_spot_alert():
    import finland_spot_bot
    finland_spot_bot.main()