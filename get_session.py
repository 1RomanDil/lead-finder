from pyrogram import Client
import os
from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")

print("Запускаю создание сессии...")
print("Сейчас попросит номер телефона и код из Telegram")

with Client("my_account", api_id=api_id, api_hash=api_hash) as app:
    session_string = app.export_session_string()
    print("\n\n========== ТВОЯ SESSION STRING ==========\n")
    print(session_string)
    print("\n=========================================")
    print("\nСкопируй строку выше целиком")