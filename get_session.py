from pyrogram import Client
import os
from dotenv import load_dotenv

load_dotenv()

api_id = int(os.getenv("API_ID"))
api_hash = os.getenv("API_HASH")

print("Создаю новую сессию...")

app = Client(
    "temp_session",
    api_id=api_id,
    api_hash=api_hash,
    in_memory=True
)

with app:
    session_string = app.export_session_string()
    
    with open("session_string.txt", "w", encoding="utf-8") as f:
        f.write(session_string)
    
    print("\n====================================")
    print("Сессия успешно создана!")
    print("Длина строки:", len(session_string))
    print("Файл session_string.txt сохранён")
    print("====================================")