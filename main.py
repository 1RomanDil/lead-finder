import asyncio
import os
import json
from datetime import datetime, timedelta, timezone
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

app = Client(
    "lead_finder_session",
    session_string=SESSION_STRING,
    api_id=API_ID,
    api_hash=API_HASH,
    in_memory=True
)

DATA_FILE = "data.json"

def load_data():
    if not os.path.exists(DATA_FILE):
        return {
            "total_starts": 0,
            "users": {},
            "categories": {},
            "chats": {},
            "sent_messages": [],
            "exclude_words": []
        }
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    if "sent_messages" not in data:
        data["sent_messages"] = []
    if "exclude_words" not in data:
        data["exclude_words"] = []
    return data

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
    chats_count = len(data.get("chats", {}))
    excludes_count = len(data.get("exclude_words", []))

    cats_info = ""
    for cat, keywords in data["categories"].items():
        cats_info += f"\n• {cat} ({len(keywords)} слов)"

    await message.answer(
        f"📊 Статистика\n\n"
        f"Всего нажали /start: {total}\n"
        f"В работе: {active}\n"
        f"Просто зашли: {just_started}\n"
        f"Чатов для мониторинга: {chats_count}\n"
        f"Слов-исключений: {excludes_count}\n\n"
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

@dp.message(Command("delcat"))
async def cmd_delcat(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование:\n/delcat Название категории")
        return

    cat_name = parts[1].strip()
    if cat_name not in data["categories"]:
        await message.answer("Такой категории нет.")
        return

    del data["categories"][cat_name]
    for user in data["users"].values():
        if cat_name in user.get("categories", []):
            user["categories"].remove(cat_name)

    save_data(data)
    await message.answer(f"Категория «{cat_name}» удалена.")

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
        await message.answer("Такой категории нет.")
        return

    if keyword in data["categories"][cat_name]:
        await message.answer("Такое слово уже есть.")
        return

    data["categories"][cat_name].append(keyword)
    save_data(data)
    await message.answer(f"Слово «{keyword}» добавлено в «{cat_name}».")

@dp.message(Command("addwords"))
async def cmd_addwords(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer(
            "Использование:\n"
            "/addwords Название_категории слово1, слово2, слово3"
        )
        return

    cat_name = parts[1].strip()
    raw_keywords = parts[2]

    if cat_name not in data["categories"]:
        await message.answer("Такой категории нет.")
        return

    keywords = [kw.strip().lower() for kw in raw_keywords.split(",") if kw.strip()]

    if not keywords:
        await message.answer("Не удалось распознать ключевые слова.")
        return

    added = []
    skipped = []

    for kw in keywords:
        if kw in data["categories"][cat_name]:
            skipped.append(kw)
        else:
            data["categories"][cat_name].append(kw)
            added.append(kw)

    save_data(data)

    text = ""
    if added:
        text += f"✅ Добавлено в «{cat_name}» ({len(added)}):\n" + "\n".join(f"• {k}" for k in added)
    if skipped:
        text += f"\n\n⚠️ Уже были ({len(skipped)}):\n" + "\n".join(f"• {k}" for k in skipped)

    await message.answer(text)

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

# ----- Слова-исключения -----

@dp.message(Command("addexclude"))
async def cmd_addexclude(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "Использование:\n"
            "/addexclude слово1, слово2, слово3\n\n"
            "Пример:\n"
            "/addexclude помогу, сделаю, предлагаю, готов"
        )
        return

    raw = parts[1]
    words = [w.strip().lower() for w in raw.split(",") if w.strip()]

    if not words:
        await message.answer("Не удалось распознать слова.")
        return

    added = []
    skipped = []

    for w in words:
        if w in data["exclude_words"]:
            skipped.append(w)
        else:
            data["exclude_words"].append(w)
            added.append(w)

    save_data(data)

    text = ""
    if added:
        text += f"🚫 Добавлены исключения ({len(added)}):\n" + "\n".join(f"• {w}" for w in added)
    if skipped:
        text += f"\n\n⚠️ Уже были:\n" + "\n".join(f"• {w}" for w in skipped)

    await message.answer(text)

@dp.message(Command("delexclude"))
async def cmd_delexclude(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование:\n/delexclude слово")
        return

    word = parts[1].strip().lower()

    if word not in data["exclude_words"]:
        await message.answer("Такого слова-исключения нет.")
        return

    data["exclude_words"].remove(word)
    save_data(data)
    await message.answer(f"Слово «{word}» удалено из исключений.")

@dp.message(Command("excludes"))
async def cmd_excludes(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    words = data.get("exclude_words", [])
    if not words:
        await message.answer("Слов-исключений пока нет.")
        return

    text = "🚫 Слова-исключения:\n\n" + "\n".join(f"• {w}" for w in words)
    await message.answer(text)

# ----- Чаты -----

@dp.message(Command("addchat"))
async def cmd_addchat(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование:\n/addchat ID_или_юзернейм Название чата")
        return

    chat_id = parts[1].strip()
    title = parts[2].strip()

    if "chats" not in data:
        data["chats"] = {}

    data["chats"][chat_id] = {"title": title}
    save_data(data)
    await message.answer(f"Чат «{title}» добавлен.")

@dp.message(Command("delchat"))
async def cmd_delchat(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование:\n/delchat ID_или_юзернейм")
        return

    chat_id = parts[1].strip()
    if chat_id not in data.get("chats", {}):
        await message.answer("Такой чат не найден.")
        return

    title = data["chats"][chat_id]["title"]
    del data["chats"][chat_id]
    save_data(data)
    await message.answer(f"Чат «{title}» удалён.")

@dp.message(Command("chats"))
async def cmd_chats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    chats = data.get("chats", {})
    if not chats:
        await message.answer("Чатов пока нет.")
        return

    text = "Список чатов:\n\n"
    for chat_id, info in chats.items():
        text += f"• {info['title']}\n  `{chat_id}`\n\n"

    await message.answer(text, parse_mode="Markdown")

# ========== ПОИСК СООБЩЕНИЙ ==========

async def check_new_messages():
    if not data.get("chats"):
        return

    keyword_map = {}
    for cat_name, keywords in data["categories"].items():
        for kw in keywords:
            kw = kw.lower()
            if kw not in keyword_map:
                keyword_map[kw] = []
            keyword_map[kw].append(cat_name)

    if not keyword_map:
        return

    exclude_words = [w.lower() for w in data.get("exclude_words", [])]
    time_from = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=15)

    for chat_id, chat_info in data["chats"].items():
        try:
            async for message in app.search_messages(chat_id, limit=20):
                if not message.text and not message.caption:
                    continue

                msg_date = message.date.replace(tzinfo=None)
                if msg_date < time_from:
                    continue

                msg_key = f"{chat_id}_{message.id}"
                if msg_key in data["sent_messages"]:
                    continue

                text = (message.text or message.caption or "").lower()

                # Проверка на слова-исключения
                if any(ex_word in text for ex_word in exclude_words):
                    continue

                matched_categories = set()
                for keyword, cats in keyword_map.items():
                    if keyword in text:
                        matched_categories.update(cats)

                if not matched_categories:
                    continue

                data["sent_messages"].append(msg_key)
                if len(data["sent_messages"]) > 300:
                    data["sent_messages"] = data["sent_messages"][-300:]
                save_data(data)

                try:
                    msg_link = message.link
                except:
                    msg_link = None

                author_link = None
                if message.from_user:
                    if message.from_user.username:
                        author_link = f"https://t.me/{message.from_user.username}"
                    else:
                        author_link = f"tg://user?id={message.from_user.id}"

                for cat in matched_categories:
                    for user_id, user_data in data["users"].items():
                        if cat in user_data.get("categories", []):
                            await send_lead(user_id, cat, text, msg_link, author_link, chat_info["title"])

        except FloodWait as e:
            print(f"FloodWait: спим {e.value} секунд")
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"Ошибка в чате {chat_id}: {e}")

async def send_lead(user_id: str, category: str, text: str, msg_link: str, author_link: str, chat_title: str):
    short_text = text[:400] + "..." if len(text) > 400 else text

    message_text = f"Категория: {category}\n\n{short_text}\n\n"

    if msg_link:
        message_text += f"🔗 [Сообщение]({msg_link})\n"
    if author_link:
        message_text += f"👤 [Автор]({author_link})"

    try:
        await bot.send_message(
            chat_id=int(user_id),
            text=message_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
        await asyncio.sleep(0.05)
    except Exception as e:
        print(f"Не удалось отправить пользователю {user_id}: {e}")

async def search_loop():
    print("Фоновый поиск запущен...")
    while True:
        try:
            has_subscribers = any(u.get("categories") for u in data["users"].values())
            if has_subscribers and data.get("chats") and data.get("categories"):
                await check_new_messages()
        except Exception as e:
            print(f"Ошибка в search_loop: {e}")

        await asyncio.sleep(120)

# ========== ЗАПУСК ==========

async def main():
    print("Запускаю бота и поиск...")
    await app.start()
    print("Pyrogram клиент запущен")

    asyncio.create_task(search_loop())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())