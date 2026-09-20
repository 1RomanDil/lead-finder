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
from pyrogram.errors import FloodWait

from fastapi import FastAPI
import uvicorn

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Text, select, delete, BigInteger

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID"))
API_ID = int(os.getenv("API_ID"))
API_HASH = os.getenv("API_HASH")
SESSION_STRING = os.getenv("SESSION_STRING")
DATABASE_URL = os.getenv("DATABASE_URL")

# Приводим URL к async-формату
if DATABASE_URL and DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://", 1)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

app = Client(
    "lead_finder_session",
    session_string=SESSION_STRING,
    api_id=API_ID,
    api_hash=API_HASH,
    in_memory=True
)

# ========== БАЗА ДАННЫХ ==========

engine = create_async_engine(DATABASE_URL, echo=False)
Session = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class Category(Base):
    __tablename__ = "categories"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)

class Keyword(Base):
    __tablename__ = "keywords"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(100))
    word: Mapped[str] = mapped_column(String(200))

class Chat(Base):
    __tablename__ = "chats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(100), unique=True)
    title: Mapped[str] = mapped_column(String(200))

class ExcludeWord(Base):
    __tablename__ = "exclude_words"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    word: Mapped[str] = mapped_column(String(100), unique=True)

class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[str] = mapped_column(String(50), unique=True)
    categories: Mapped[str] = mapped_column(Text, default="[]")  # JSON список

class SentMessage(Base):
    __tablename__ = "sent_messages"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    msg_key: Mapped[str] = mapped_column(String(100), unique=True)

class Stat(Base):
    __tablename__ = "stats"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    total_starts: Mapped[int] = mapped_column(Integer, default=0)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Создаём запись статистики, если её нет
    async with Session() as session:
        result = await session.execute(select(Stat))
        if not result.scalar_one_or_none():
            session.add(Stat(total_starts=0))
            await session.commit()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

async def get_categories_dict():
    async with Session() as session:
        cats = (await session.execute(select(Category))).scalars().all()
        result = {}
        for cat in cats:
            kws = (await session.execute(
                select(Keyword.word).where(Keyword.category == cat.name)
            )).scalars().all()
            result[cat.name] = list(kws)
        return result

async def get_user_categories(user_id: str):
    async with Session() as session:
        user = (await session.execute(
            select(User).where(User.user_id == user_id)
        )).scalar_one_or_none()
        if not user:
            return []
        return json.loads(user.categories or "[]")

async def set_user_categories(user_id: str, categories: list):
    async with Session() as session:
        user = (await session.execute(
            select(User).where(User.user_id == user_id)
        )).scalar_one_or_none()
        if user:
            user.categories = json.dumps(categories, ensure_ascii=False)
        else:
            session.add(User(user_id=user_id, categories=json.dumps(categories, ensure_ascii=False)))
        await session.commit()

# ========== КОМАНДЫ ПОЛЬЗОВАТЕЛЯ ==========

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = str(message.from_user.id)

    async with Session() as session:
        user = (await session.execute(
            select(User).where(User.user_id == user_id)
        )).scalar_one_or_none()

        if not user:
            session.add(User(user_id=user_id, categories="[]"))
            stat = (await session.execute(select(Stat))).scalar_one()
            stat.total_starts += 1
            await session.commit()

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
    cats_dict = await get_categories_dict()
    user_cats = await get_user_categories(user_id)

    if not cats_dict:
        await callback.message.edit_text("Пока нет доступных категорий.\nАдминистратор ещё не добавил их.")
        await callback.answer()
        return

    builder = InlineKeyboardBuilder()
    for cat_name in cats_dict.keys():
        mark = "✅ " if cat_name in user_cats else ""
        builder.button(text=f"{mark}{cat_name}", callback_data=f"toggle_{cat_name}")
    builder.button(text="Сохранить", callback_data="save_categories")
    builder.adjust(1)

    await callback.message.edit_text(
        "Выбери нужные категории (можно несколько):\n✅ — категория выбрана",
        reply_markup=builder.as_markup()
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("toggle_"))
async def toggle_category(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    cat_name = callback.data.replace("toggle_", "")
    user_cats = await get_user_categories(user_id)

    if cat_name in user_cats:
        user_cats.remove(cat_name)
    else:
        user_cats.append(cat_name)

    await set_user_categories(user_id, user_cats)

    cats_dict = await get_categories_dict()
    builder = InlineKeyboardBuilder()
    for cat in cats_dict.keys():
        mark = "✅ " if cat in user_cats else ""
        builder.button(text=f"{mark}{cat}", callback_data=f"toggle_{cat}")
    builder.button(text="Сохранить", callback_data="save_categories")
    builder.adjust(1)

    await callback.message.edit_reply_markup(reply_markup=builder.as_markup())
    await callback.answer()

@dp.callback_query(F.data == "save_categories")
async def save_categories(callback: CallbackQuery):
    user_id = str(callback.from_user.id)
    user_cats = await get_user_categories(user_id)

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

    async with Session() as session:
        stat = (await session.execute(select(Stat))).scalar_one()
        total = stat.total_starts
        users = (await session.execute(select(User))).scalars().all()
        active = sum(1 for u in users if json.loads(u.categories or "[]"))
        chats_count = len((await session.execute(select(Chat))).scalars().all())
        excludes_count = len((await session.execute(select(ExcludeWord))).scalars().all())
        cats = (await session.execute(select(Category))).scalars().all()

    cats_info = ""
    for cat in cats:
        async with Session() as session:
            count = len((await session.execute(
                select(Keyword).where(Keyword.category == cat.name)
            )).scalars().all())
        cats_info += f"\n• {cat.name} ({count} слов)"

    await message.answer(
        f"📊 Статистика\n\n"
        f"Всего нажали /start: {total}\n"
        f"В работе: {active}\n"
        f"Просто зашли: {total - active}\n"
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

    async with Session() as session:
        exists = (await session.execute(
            select(Category).where(Category.name == cat_name)
        )).scalar_one_or_none()
        if exists:
            await message.answer("Такая категория уже существует.")
            return
        session.add(Category(name=cat_name))
        await session.commit()

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

    async with Session() as session:
        cat = (await session.execute(
            select(Category).where(Category.name == cat_name)
        )).scalar_one_or_none()
        if not cat:
            await message.answer("Такой категории нет.")
            return

        await session.execute(delete(Keyword).where(Keyword.category == cat_name))
        await session.delete(cat)

        # Убираем категорию у пользователей
        users = (await session.execute(select(User))).scalars().all()
        for user in users:
            cats = json.loads(user.categories or "[]")
            if cat_name in cats:
                cats.remove(cat_name)
                user.categories = json.dumps(cats, ensure_ascii=False)

        await session.commit()

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

    async with Session() as session:
        cat = (await session.execute(
            select(Category).where(Category.name == cat_name)
        )).scalar_one_or_none()
        if not cat:
            await message.answer("Такой категории нет.")
            return

        exists = (await session.execute(
            select(Keyword).where(Keyword.category == cat_name, Keyword.word == keyword)
        )).scalar_one_or_none()
        if exists:
            await message.answer("Такое слово уже есть.")
            return

        session.add(Keyword(category=cat_name, word=keyword))
        await session.commit()

    await message.answer(f"Слово «{keyword}» добавлено в «{cat_name}».")

@dp.message(Command("addwords"))
async def cmd_addwords(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("Использование:\n/addwords Название_категории слово1, слово2, слово3")
        return

    cat_name = parts[1].strip()
    raw_keywords = parts[2]
    keywords = [kw.strip().lower() for kw in raw_keywords.split(",") if kw.strip()]

    async with Session() as session:
        cat = (await session.execute(
            select(Category).where(Category.name == cat_name)
        )).scalar_one_or_none()
        if not cat:
            await message.answer("Такой категории нет.")
            return

        added = []
        skipped = []
        for kw in keywords:
            exists = (await session.execute(
                select(Keyword).where(Keyword.category == cat_name, Keyword.word == kw)
            )).scalar_one_or_none()
            if exists:
                skipped.append(kw)
            else:
                session.add(Keyword(category=cat_name, word=kw))
                added.append(kw)
        await session.commit()

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

    parts = message.text.split(maxsplit=1)

    if len(parts) == 1:
        cats_dict = await get_categories_dict()
        if not cats_dict:
            await message.answer("Категорий пока нет.")
            return

        text = "📂 Список категорий:\n\n"
        for cat, words in cats_dict.items():
            text += f"• <b>{cat}</b> — {len(words)} слов\n"
        text += "\nЧтобы посмотреть слова:\n/categories Название"
        await message.answer(text, parse_mode="HTML")
        return

    cat_name = parts[1].strip()
    cats_dict = await get_categories_dict()

    if cat_name not in cats_dict:
        await message.answer("Такой категории нет.")
        return

    words = cats_dict[cat_name]
    if not words:
        await message.answer(f"В категории «{cat_name}» пока нет слов.")
        return

    text = f"<b>{cat_name}</b> ({len(words)} слов):\n\n" + ", ".join(words)
    if len(text) > 4000:
        text = text[:4000] + "\n\n... (показана только часть)"
    await message.answer(text, parse_mode="HTML")

@dp.message(Command("addexclude"))
async def cmd_addexclude(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование:\n/addexclude слово1, слово2, слово3")
        return

    words = [w.strip().lower() for w in parts[1].split(",") if w.strip()]

    async with Session() as session:
        added = []
        skipped = []
        for w in words:
            exists = (await session.execute(
                select(ExcludeWord).where(ExcludeWord.word == w)
            )).scalar_one_or_none()
            if exists:
                skipped.append(w)
            else:
                session.add(ExcludeWord(word=w))
                added.append(w)
        await session.commit()

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

    async with Session() as session:
        w = (await session.execute(
            select(ExcludeWord).where(ExcludeWord.word == word)
        )).scalar_one_or_none()
        if not w:
            await message.answer("Такого слова-исключения нет.")
            return
        await session.delete(w)
        await session.commit()

    await message.answer(f"Слово «{word}» удалено из исключений.")

@dp.message(Command("excludes"))
async def cmd_excludes(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with Session() as session:
        words = (await session.execute(select(ExcludeWord.word))).scalars().all()

    if not words:
        await message.answer("Слов-исключений пока нет.")
        return

    text = "🚫 Слова-исключения:\n\n" + "\n".join(f"• {w}" for w in words)
    await message.answer(text)

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

    async with Session() as session:
        exists = (await session.execute(
            select(Chat).where(Chat.chat_id == chat_id)
        )).scalar_one_or_none()
        if exists:
            await message.answer("Такой чат уже добавлен.")
            return
        session.add(Chat(chat_id=chat_id, title=title))
        await session.commit()

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

    async with Session() as session:
        chat = (await session.execute(
            select(Chat).where(Chat.chat_id == chat_id)
        )).scalar_one_or_none()
        if not chat:
            await message.answer("Такой чат не найден.")
            return
        title = chat.title
        await session.delete(chat)
        await session.commit()

    await message.answer(f"Чат «{title}» удалён.")

@dp.message(Command("chats"))
async def cmd_chats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return

    async with Session() as session:
        chats = (await session.execute(select(Chat))).scalars().all()

    if not chats:
        await message.answer("Чатов пока нет.")
        return

    text = "Список чатов:\n\n"
    for chat in chats:
        text += f"• {chat.title}\n  `{chat.chat_id}`\n\n"
    await message.answer(text, parse_mode="Markdown")

# ========== ПОИСК СООБЩЕНИЙ ==========

async def check_new_messages():
    async with Session() as session:
        chats = (await session.execute(select(Chat))).scalars().all()
        if not chats:
            return

        keywords = (await session.execute(select(Keyword))).scalars().all()
        if not keywords:
            return

        exclude_words = [w.word for w in (await session.execute(select(ExcludeWord))).scalars().all()]
        sent_keys = set((await session.execute(select(SentMessage.msg_key))).scalars().all())

        keyword_map = {}
        for kw in keywords:
            if kw.word not in keyword_map:
                keyword_map[kw.word] = []
            keyword_map[kw.word].append(kw.category)

    time_from = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=15)

    for chat in chats:
        try:
            async for message in app.search_messages(chat.chat_id, limit=20):
                if not message.text and not message.caption:
                    continue

                msg_date = message.date.replace(tzinfo=None)
                if msg_date < time_from:
                    continue

                msg_key = f"{chat.chat_id}_{message.id}"
                if msg_key in sent_keys:
                    continue

                text = (message.text or message.caption or "").lower()

                if any(ex in text for ex in exclude_words):
                    continue

                matched = set()
                for word, cats in keyword_map.items():
                    if word in text:
                        matched.update(cats)

                if not matched:
                    continue

                # Сохраняем, что уже отправили
                async with Session() as session:
                    session.add(SentMessage(msg_key=msg_key))
                    await session.commit()
                sent_keys.add(msg_key)

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

                # Кому отправлять
                async with Session() as session:
                    users = (await session.execute(select(User))).scalars().all()

                for user in users:
                    user_cats = json.loads(user.categories or "[]")
                    for cat in matched:
                        if cat in user_cats:
                            await send_lead(user.user_id, cat, text, msg_link, author_link, chat.title)

        except FloodWait as e:
            print(f"FloodWait: спим {e.value} сек")
            await asyncio.sleep(e.value)
        except Exception as e:
            print(f"Ошибка в чате {chat.chat_id}: {e}")

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
        print(f"Не удалось отправить {user_id}: {e}")

async def search_loop():
    print("Фоновый поиск запущен...")
    while True:
        try:
            await check_new_messages()
        except Exception as e:
            print(f"Ошибка в search_loop: {e}")
        await asyncio.sleep(120)

# ========== ВЕБ-СЕРВЕР ==========

web_app = FastAPI()

@web_app.get("/")
async def health():
    return {"status": "ok", "bot": "running"}

# ========== ЗАПУСК ==========

async def main():
    print("Запускаю бота...")
    await init_db()
    print("База данных готова")

    try:
        await bot.delete_webhook(drop_pending_updates=True)
        print("Webhook удалён")
    except Exception as e:
        print(f"Ошибка удаления webhook: {e}")

    await app.start()
    print("Pyrogram запущен")

    asyncio.create_task(search_loop())

    config = uvicorn.Config(web_app, host="0.0.0.0", port=int(os.getenv("PORT", 10000)), log_level="info")
    server = uvicorn.Server(config)

    await asyncio.gather(
        dp.start_polling(bot),
        server.serve()
    )

if __name__ == "__main__":
    asyncio.run(main())