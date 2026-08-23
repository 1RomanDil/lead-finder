import asyncio
import os
import json
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Файл, в котором будем хранить данные
DATA_FILE = "data.json"

# Загружаем данные при старте
def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "total_starts": 0,
            "users": {},          # user_id: {"categories": []}
            "categories": {}      # category_name: ["keyword1", "keyword2"]
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

data = load_data()

# ========== КОМАНДЫ ПОЛЬЗОВАТЕЛЯ ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = str(message.from_user.id)

    if user_id not in data["users"]:
        data["total_starts"] += 1
        data["users"][user_id] = {"categories": []}
        save_data(data)

    text = (
        "Привет! 👋\n\n"
        "Я ищу заказы и сообщения по выбранным категориям.\n\n"
        "Нажми кнопку ниже, чтобы выбрать категории:"
    )

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выбрать категории", callback_data="choose_categories")]
    ])

    await message.answer(text, reply_markup=keyboard)

@dp.callback_query(F.data == "choose_categories")
async def choose_categories(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    user_cats = data["users"].get(user_id, {}).get("categories", [])

    if not data["categories"]:
        await callback.message.edit_text("Пока нет доступных категорий.\nАдминистратор ещё не добавил их.")
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for cat_name in data["categories"].keys():
        mark = "✅ " if cat_name in user_cats else ""
        builder.button(text=f"{mark}{cat_name}", callback_data=f"toggle_{cat_name}")

    builder.button(text="Сохранить", callback_data="save_categories")
    builder.adjust(1)

    await callback.message.edit_text(
        "Выбери нужные категории (можно несколько):\n"
        "✅ — категория выбрана",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_category(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    cat_name = callback.data.replace("toggle_", "")

    if user_id not in data["users"]:
        data["users"][user_id] = {"categories": []}

    user_cats = data["users"][user_id]["categories"]

    if cat_name in user_cats:
        user_cats.remove(cat_name)
    else:
        user_cats.append(cat_name)

    save_data(data)

    # Обновляем клавиатуру
    builder = InlineKeyboardBuilder()
    for cat in data["categories"].keys():
        mark = "✅ " if cat in user_cats else ""
        builder.button(text=f"{mark}{cat}", callback_data=f"toggle_{cat}")

    builder.button(text="Сохранить", callback_data="save_categories")
    builder.adjust(1)

    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "save_categories")
async def save_categories(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    user_cats = data["users"].get(user_id, {}).get("categories", [])

    if user_cats:
        text = "Ты подписан на категории:\n\n" + "\n".join(f"• {cat}" for cat in user_cats)
        text += "\n\nКак только появятся подходящие сообщения — я пришлю их сюда."
    else:
        text = "Ты пока не выбрал ни одной категории."

    await callback.message.edit_text(text)
    await callback.answer("Сохранено!")

# ========== АДМИН-КОМАНДЫ ==========

@dp.message(Command("stats"))
async def cmd_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    total = data["total_starts"]
    active = sum(1 for u in data["users"].values() if u.get("categories"))
    just_started = total - active

    cats_info = ""
    for cat, keywords in data["categories"].items():
        cats_info += f"\n• {cat} ({len(keywords)} слов)"

    await message.answer(
        f"📊 Статистика\n\n"
        f"Всего нажали /start: {total}\n"
        f"В работе: {active}\n"
        f"Просто зашли: {just_started}\n\n"
        f"Категории:{cats_info if cats_info else ' пока нет'}"
    )

@dp.message(Command("addcat"))
async def cmd_addcat(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование:\n/addcat Название категории")
        return

    cat_name = parts[1].strip()
    if cat_name in data["categories"]:
        await message.answer("Такая категория уже существует.")
        return

    data["categories"][cat_name] = []
    save_data(data)
    await message.answer(f"Категория «{cat_name}» добавлена.")

@dp.message(Command("addword"))
async def cmd_addword(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование:\n/addword Название_категории ключевое слово")
        return

    cat_name = parts[1].strip()
    keyword = parts[2].strip().lower()

    if cat_name not in data["categories"]:
        await message.answer("Такой категории нет. Сначала создай её через /addcat")
        return

    if keyword in data["categories"][cat_name]:
        await message.answer("Такое слово уже есть в этой категории.")
        return

    data["categories"][cat_name].append(keyword)
    save_data(data)
    await message.answer(f"Слово «{keyword}» добавлено в категорию «{cat_name}».")

@dp.message(Command("categories"))
async def cmd_categories(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    if not data["categories"]:
        await message.answer("Категорий пока нет.")
        return

    text = "📂 Список категорий:\n\n"
    for cat, words in data["categories"].items():
        text += f"<b>{cat}</b>\n"
        text += ", ".join(words) if words else "нет слов"
        text += "\n\n"

    await message.answer(text, parse_mode="HTML")

# ========== ЗАПУСК ==========

async def main():
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())