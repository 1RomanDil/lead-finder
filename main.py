import asyncio
import os
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import Message

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Простая статистика (пока в памяти)
total_starts = 0
active_users = set()

@dp.message(Command("start"))
async def cmd_start(message: Message):
    global total_starts
    total_starts += 1

    await message.answer(
        "Привет! 👋\n\n"
        "Это бот для поиска заказов.\n"
        "Пока я ещё в разработке.\n\n"
        "Скоро здесь можно будет выбирать категории."
    )

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    # Команда только для администратора
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет доступа к этой команде.")
        return

    await message.answer(
        f"📊 Статистика:\n\n"
        f"Всего нажали /start: {total_starts}\n"
        f"Сейчас в работе: {len(active_users)}"
    )

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())