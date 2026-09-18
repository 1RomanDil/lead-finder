from pyrogram import Client
import os
from dotenv import load_dotenv

load_dotenv()

print("Проверяю сессию...")

app = Client(
    "test",
    session_string=os.getenv("SESSION_STRING"),
    api_id=int(os.getenv("API_ID")),
    api_hash=os.getenv("API_HASH"),
    in_memory=True
)

with app:
    me = app.get_me()
    print("Успех!")
    print("Имя:", me.first_name)
    print("ID:", me.id)