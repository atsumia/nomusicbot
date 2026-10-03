import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from dotenv import load_dotenv
from downloader import download_track, search_tracks

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Сессии поиска: { user_id: { "results": [...], "urls": { short_id: url } } }
USER_SESSIONS = {}

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer(
        "👋 **NoMusic**\n\n"
        "• Отправь **ссылку** на трек\n"
        "• Или просто напиши **название** — я найду варианты для скачивания.",
        parse_mode="Markdown"
    )

def build_search_keyboard(user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    session = USER_SESSIONS.get(user_id, {})
    results = session.get("results", [])
    
    items_per_page = 5
    total_pages = max(1, (len(results) + items_per_page - 1) // items_per_page)
    page = max(0, min(page, total_pages - 1))
    
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_items = results[start_idx:end_idx]

    buttons = []
    for idx, item in enumerate(current_items, start=start_idx + 1):
        short_id = f"{user_id}_{item['id']}"[:50]
        session.setdefault("urls", {})[short_id] = item['url']
        
        btn_text = f"{idx}. {item['uploader']} - {item['title']}"
        if len(btn_text) > 42:
            btn_text = btn_text[:39] + "..."
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dl:{short_id}")])

    # Пагинация (Назад / Страница / Вперёд)
    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️ Назад", callback_data=f"page:{page - 1}"))
    
    nav_row.append(InlineKeyboardButton(text=f"📄 {page + 1}/{total_pages}", callback_data="noop"))
    
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="Вперёд ➡️", callback_data=f"page:{page + 1}"))

    buttons.append(nav_row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def process_and_send_audio(chat_id: int, url: str, status_msg: types.Message):
    try:
        await status_msg.edit_text("⏳ Обрабатываю аудиозапись...")
        track = await download_track(url)
        file_path = track['file_path']

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 49.5:
            await status_msg.edit_text("❌ Размер файла превышает лимит Telegram (50 МБ).")
            if os.path.exists(file_path):
                os.remove(file_path)
            return

        await status_msg.edit_text("🚀 Отправляю файл...")
        audio = FSInputFile(
            path=file_path,
            filename=f"{track['artist']} - {track['title']}.mp3"
        )
        await bot.send_audio(
            chat_id=chat_id,
            audio=audio,
            performer=track['artist'],
            title=track['title'],
            duration=track['duration']
        )
        await status_msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Ошибка загрузки: {str(e)}")

@dp.message(F.text.regexp(r'https?://[^\s]+'))
async def handle_url(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ Загрузка...")
    await process_and_send_audio(message.chat.id, url, status_msg)

@dp.message(F.text)
async def handle_search(message: types.Message):
    query = message.text.strip()
    status_msg = await message.answer("🔎 Ищу варианты...")
    
    try:
        results = await search_tracks(query, limit=15)
        if not results:
            await status_msg.edit_text("Ничего не нашлось. Попробуй изменить запрос.")
            return

        USER_SESSIONS[message.from_user.id] = {
            "results": results,
            "urls": {}
        }

        kb = build_search_keyboard(message.from_user.id, page=0)
        await status_msg.edit_text("Выбери трек из списка:", reply_markup=kb)
    except Exception as e:
        await status_msg.edit_text(f"Ошибка поиска: {str(e)}")

@dp.callback_query(F.data.startswith("page:"))
async def callback_pagination(callback: CallbackQuery):
    page = int(callback.data.split("page:")[1])
    kb = build_search_keyboard(callback.from_user.id, page=page)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery):
    await callback.answer()

@dp.callback_query(F.data.startswith("dl:"))
async def callback_download(callback: CallbackQuery):
    short_id = callback.data.split("dl:")[1]
    user_id = callback.from_user.id
    
    url = None
    if user_id in USER_SESSIONS:
        url = USER_SESSIONS[user_id].get("urls", {}).get(short_id)

    await callback.answer()
    if not url:
        await callback.message.edit_text("Срок действия выбора истёк. Повтори поиск.")
        return

    status_msg = await callback.message.edit_text("⏳ Загрузка выбранного трека...")
    await process_and_send_audio(callback.message.chat.id, url, status_msg)

async def handle_health_check(request):
    return web.Response(text="NoMusic bot is running!")

async def start_dummy_web_server():
    app = web.Application()
    app.router.add_get('/', handle_health_check)
    app.router.add_get('/health', handle_health_check)
    
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()

async def main():
    await start_dummy_web_server()
    print("Бот запущен...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
