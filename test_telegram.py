import asyncio
import os
import sys
from app.core.alerts import send_telegram_alert

from app.core.config import settings

def main():
    if not settings.TELEGRAM_BOT_TOKEN or not settings.TELEGRAM_ADMIN_CHAT_ID:
        print("Error: TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID must be set in .env")
        sys.exit(1)
        
    print(f"Sending live test alert to Telegram (Chat ID: {settings.TELEGRAM_ADMIN_CHAT_ID})...")
    send_telegram_alert("🚀 <b>Live Test Alert</b>\n\nIf you are reading this, the Telegram alerting pipeline is working successfully!")
    print("Alert sent. Please check your Telegram app.")

if __name__ == "__main__":
    main()
