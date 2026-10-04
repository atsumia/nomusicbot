import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent
)
from dotenv import load_dotenv

import database
from downloader import download_track, search_tracks
from visualizer import generate_apple_card

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

USER_SESSIONS = {}

LONG_TRACK_THRESHOLD = 240

def format_duration(seconds) -> str:
    try:
        total_sec = int(float(seconds or 0))
    except (ValueError, TypeError):
        return ""
    m = total_sec // 60
    s = total_sec % 60
    return f"{m}:{s:02d}"

# --- Постоянная нижняя клавиатура (Reply Keyboard) ---

def get_bottom_reply_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    user = database.get_user(user_id)
    mode_label = "Режим: Официальные" if user['search_mode'] == 'official' else "Режим: SoundCloud"
    
    keyboard = [
        [KeyboardButton(text="🔎 Поиск"), KeyboardButton(text="👤 Мой кабинет")],
        [KeyboardButton(text=f"🎧 {mode_label}")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

# --- Генераторы инлайн-клавиатур меню ---

def get_main_menu(user_id: int) -> InlineKeyboardMarkup:
    user = database.get_user(user_id)
    mode_text = "Официальные релизы" if user['search_mode'] == 'official' else "Ремиксы (SoundCloud)"
    
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔎 Поиск музыки", callback_data="menu:search")],
        [InlineKeyboardButton(text="👤 Мой кабинет", callback_data="menu:profile")],
        [InlineKeyboardButton(text=f"🎧 Режим: {mode_text}", callback_data="menu:toggle_mode")]
    ])

def get_profile_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Избранное", callback_data="menu:favorites"),
         InlineKeyboardButton(text="📜 История", callback_data="menu:history")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu:main")]
    ])

# --- Стартовый хэндлер ---

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    username = message.from_user.username or message.from_user.first_name
    database.get_user(message.from_user.id, username)
    
    reply_kb = get_bottom_reply_keyboard(message.from_user.id)
    inline_kb = get_main_menu(message.from_user.id)
    
    welcome_text = (
        "👋 <b>Привет! Это NoMusic.</b>\n\n"
        "Сервис предназначен для поиска и загрузки аудиозаписей в качестве до <b>320 kbps</b>.\n\n"
        "<blockquote>💡 <i>Чтобы найти трек, просто отправь его название, имя артиста или ссылку на композицию.</i></blockquote>"
    )
    await message.answer(welcome_text, reply_markup=reply_kb, parse_mode="HTML")
    await message.answer("🎛 <b>Навигация и управление:</b>", reply_markup=inline_kb, parse_mode="HTML")

# --- Обработка нажатий на нижние кнопки Reply-клавиатуры ---

@dp.message(F.text == "🔎 Поиск")
async def reply_search_handler(message: types.Message):
    await message.answer("📝 Напиши название трека, имя артиста или отправь ссылку:")

@dp.message(F.text == "👤 Мой кабинет")
async def reply_profile_handler(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    user = database.get_user(user_id, username)
    
    mode_name = "Официальные площадки" if user['search_mode'] == "official" else "SoundCloud (Ремиксы)"
    
    profile_text = (
        f"👤 <b>Профиль:</b> @{username}\n"
        f"🆔 <code>{user_id}</code>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Загружено треков: <b>{user['download_count']}</b>\n"
        f"• Активный источник: <b>{mode_name}</b>\n\n"
        "<blockquote>Используй кнопки ниже для доступа к медиатеке.</blockquote>"
    )
    await message.answer(profile_text, reply_markup=get_profile_menu(), parse_mode="HTML")

@dp.message(F.text.startswith("🎧 Режим:"))
async def reply_toggle_mode_handler(message: types.Message):
    user_id = message.from_user.id
    user = database.get_user(user_id)
    new_mode = "remix" if user['search_mode'] == "official" else "official"
    
    database.set_mode(user_id, new_mode)
    reply_kb = get_bottom_reply_keyboard(user_id)
    
    mode_name = "Официальные площадки" if new_mode == "official" else "SoundCloud"
    await message.answer(
        f"✅ Режим поиска переключен на: <b>{mode_name}</b>",
        reply_markup=reply_kb,
        parse_mode="HTML"
    )

# --- Инлайн-навигация главного меню ---

@dp.callback_query(F.data == "menu:main")
async def show_main_menu(callback: CallbackQuery):
    await callback.message.edit_text(
        "🎛 <b>Навигация и управление:</b>",
        reply_markup=get_main_menu(callback.from_user.id),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "menu:search")
async def menu_search(callback: CallbackQuery):
    await callback.message.answer("📝 Отправь мне название трека или ссылку для поиска!")
    await callback.answer()

@dp.callback_query(F.data == "menu:toggle_mode")
async def menu_toggle_mode(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = database.get_user(user_id)
    new_mode = "remix" if user['search_mode'] == "official" else "official"
    
    database.set_mode(user_id, new_mode)
    await callback.message.edit_reply_markup(reply_markup=get_main_menu(user_id))
    
    mode_name = "Официальные площадки" if new_mode == "official" else "SoundCloud"
    await callback.answer(f"✅ Режим изменен на: {mode_name}", show_alert=True)

@dp.callback_query(F.data == "menu:profile")
async def show_profile(callback: CallbackQuery):
    user_id = callback.from_user.id
    username = callback.from_user.username or callback.from_user.first_name
    user = database.get_user(user_id, username)
    
    mode_name = "Официальные площадки" if user['search_mode'] == "official" else "SoundCloud (Ремиксы)"
    
    profile_text = (
        f"👤 <b>Профиль:</b> @{username}\n"
        f"🆔 <code>{user_id}</code>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"• Загружено треков: <b>{user['download_count']}</b>\n"
        f"• Активный источник: <b>{mode_name}</b>\n\n"
        "<blockquote>Используй кнопки ниже для доступа к медиатеке.</blockquote>"
    )
    await callback.message.edit_text(profile_text, reply_markup=get_profile_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu:history")
async def show_history(callback: CallbackQuery):
    records = database.get_history(callback.from_user.id)
    if not records:
        await callback.answer("Твоя история пока пуста 🥲", show_alert=True)
        return
    
    buttons = []
    for db_id, track_id, title, artist, url in records:
        btn_text = f"{artist} - {title}"[:40]
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dl_db:history:{db_id}")])
        
    buttons.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="menu:profile")])
    await callback.message.edit_text(
        "📜 <b>Последние скачанные треки:</b>\n<i>Нажми на любой трек, чтобы скачать его снова</i>", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "menu:favorites")
async def show_favorites(callback: CallbackQuery):
    records = database.get_favorites(callback.from_user.id)
    if not records:
        await callback.answer("У тебя пока нет избранных треков ❤️", show_alert=True)
        return
    
    buttons = []
    for db_id, track_id, title, artist, url in records:
        btn_text = f"❤️ {artist} - {title}"[:40]
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dl_db:favorites:{db_id}")])
        
    buttons.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="menu:profile")])
    await callback.message.edit_text(
        "❤️ <b>Твое избранное:</b>\n<i>Нажми на трек для скачивания</i>", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
        parse_mode="HTML"
    )
    await callback.answer()

# --- Кнопка "В избранное" под скачанным треком ---

@dp.callback_query(F.data.startswith("fav:"))
async def toggle_fav_callback(callback: CallbackQuery):
    track_id = callback.data.split("fav:")[1]
    user_id = callback.from_user.id
    
    is_now_fav = database.toggle_favorite(user_id, track_id)
    btn_text = "❤️ В избранном" if is_now_fav else "🤍 В избранное"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=btn_text, callback_data=f"fav:{track_id}")
    ]])
    
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer("Избранное обновлено!")

# --- Логика обычного поиска треков ---

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
        session.setdefault("items", {})[short_id] = item 
        
        raw_duration = item.get('duration', 0)
        try:
            duration = int(float(raw_duration or 0))
        except (ValueError, TypeError):
            duration = 0

        dur_str = format_duration(duration) if duration > 0 else ""
        is_long = duration > LONG_TRACK_THRESHOLD
        warn_badge = f" ⏳ {dur_str}" if is_long and dur_str else ""
        
        title_artist = f"{item['uploader']} - {item['title']}"
        max_title_len = 34 if is_long else 40
        if len(title_artist) > max_title_len:
            title_artist = title_artist[:max_title_len - 3] + "..."
            
        btn_text = f"{idx}. {title_artist}{warn_badge}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"dl:{short_id}")])

    nav_row = []
    if page > 0:
        nav_row.append(InlineKeyboardButton(text="⬅️", callback_data=f"page:{page - 1}"))
    nav_row.append(InlineKeyboardButton(text=f"{page + 1}/{total_pages}", callback_data="noop"))
    if page < total_pages - 1:
        nav_row.append(InlineKeyboardButton(text="➡️", callback_data=f"page:{page + 1}"))
    buttons.append(nav_row)

    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def process_and_send_audio(chat_id: int, user_id: int, track_id: str, url: str, status_msg: types.Message):
    file_path = None
    thumb_path = None
    try:
        await status_msg.edit_text("⏳ Загружаю аудиозапись...")
        track = await download_track(url)
        file_path = track['file_path']
        thumb_path = track.get('thumb_path')

        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 49.5:
            await status_msg.edit_text("❌ Размер файла превышает лимит Telegram (50 МБ).")
            return

        database.add_download(user_id, track_id, track['title'], track['artist'], url)

        await status_msg.edit_text("🚀 Отправляю файл...")
        audio = FSInputFile(path=file_path, filename=f"{track['artist']} - {track['title']}.mp3")
        thumbnail = FSInputFile(thumb_path) if thumb_path and os.path.exists(thumb_path) else None

        is_fav = database.is_favorite(user_id, track_id)
        fav_text = "❤️ В избранном" if is_fav else "🤍 В избранное"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=fav_text, callback_data=f"fav:{track_id}")
        ]])

        await bot.send_audio(
            chat_id=chat_id,
            audio=audio,
            performer=track['artist'],
            title=track['title'],
            duration=track['duration'],
            thumbnail=thumbnail,
            reply_markup=kb
        )
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Ошибка загрузки: {str(e)}")
    finally:
        if file_path and os.path.exists(file_path):
            os.remove(file_path)
        if thumb_path and os.path.exists(thumb_path):
            os.remove(thumb_path)

@dp.message(F.text.regexp(r'https?://[^\s]+'))
async def handle_url(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ Загрузка ссылки...")
    await process_and_send_audio(message.chat.id, message.from_user.id, "link_track", url, status_msg)

@dp.message(F.text)
async def handle_search(message: types.Message):
    query = message.text.strip()
    user_id = message.from_user.id
    
    user = database.get_user(user_id, message.from_user.username or message.from_user.first_name)
    mode = user['search_mode']
    
    status_msg = await message.answer("🔎 Ищу варианты...")
    try:
        results = await search_tracks(query, mode=mode, limit=15)
        if not results:
            await status_msg.edit_text("Ничего не нашлось. Попробуй изменить запрос.")
            return

        is_artist = isinstance(results, dict) and results.get('type') == 'artist'
        tracks_list = results['tracks'] if is_artist else results

        USER_SESSIONS[user_id] = {
            "query": query,
            "results": tracks_list,
            "items": {},
            "current_page": 0
        }

        kb = build_search_keyboard(user_id, page=0)
        mode_title = "Официальные релизы" if mode == "official" else "Ремиксы (SoundCloud)"

        if is_artist:
            await status_msg.edit_text("🎨 Генерирую карточку артиста...")
            try:
                image_path = await generate_apple_card(
                    artist_name=results['artist_name'],
                    tracks=results['tracks'],
                    photo_url=results.get('artist_photo')
                )
                photo = FSInputFile(image_path)
                await message.answer_photo(
                    photo=photo, caption=f"🎧 Результаты: <b>{mode_title}</b>",
                    reply_markup=kb, parse_mode="HTML"
                )
                await status_msg.delete()
                if os.path.exists(image_path):
                    os.remove(image_path)
            except Exception:
                await status_msg.edit_text(f"Результаты: <b>{mode_title}</b>", reply_markup=kb, parse_mode="HTML")
        else:
            await status_msg.edit_text(f"Результаты: <b>{mode_title}</b>", reply_markup=kb, parse_mode="HTML")
            
    except Exception as e:
        await status_msg.edit_text(f"Ошибка поиска: {str(e)}")

@dp.callback_query(F.data.startswith("page:"))
async def callback_pagination(callback: CallbackQuery):
    page = int(callback.data.split("page:")[1])
    if callback.from_user.id in USER_SESSIONS:
        USER_SESSIONS[callback.from_user.id]["current_page"] = page
    kb = build_search_keyboard(callback.from_user.id, page=page)
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery):
    await callback.answer()

# --- Выбор трека и проверка на длительность ---

@dp.callback_query(F.data.startswith("dl:"))
async def callback_download(callback: CallbackQuery):
    short_id = callback.data.split("dl:")[1]
    user_id = callback.from_user.id
    
    item = USER_SESSIONS.get(user_id, {}).get("items", {}).get(short_id)
    if not item:
        await callback.answer("Срок действия выбора истёк. Повтори поиск.", show_alert=True)
        return

    try:
        duration = int(float(item.get('duration', 0) or 0))
    except (ValueError, TypeError):
        duration = 0

    if duration > LONG_TRACK_THRESHOLD:
        await callback.answer()
        dur_text = format_duration(duration)
        warn_text = (
            f"⏳ <b>Внимание: длинная аудиозапись!</b>\n\n"
            f"🎵 <b>{item['uploader']} — {item['title']}</b>\n"
            f"⏱ Длительность: <b>{dur_text}</b>\n\n"
            f"<blockquote>Этот трек длится больше 4 минут. Возможно, это полный альбом, микс или длинная live-версия. Скачать его?</blockquote>"
        )
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡️ Да, скачать трек", callback_data=f"confirm_dl:{short_id}")],
            [InlineKeyboardButton(text="🔙 Вернуться к списку", callback_data="back_to_results")]
        ])
        
        if callback.message.caption:
            await callback.message.edit_caption(caption=warn_text, reply_markup=confirm_kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=warn_text, reply_markup=confirm_kb, parse_mode="HTML")
        return

    await callback.answer()
    status_msg = await callback.message.answer("⏳ Загрузка выбранного трека...")
    await process_and_send_audio(callback.message.chat.id, user_id, item['id'], item['url'], status_msg)

@dp.callback_query(F.data.startswith("confirm_dl:"))
async def callback_confirm_download(callback: CallbackQuery):
    short_id = callback.data.split("confirm_dl:")[1]
    user_id = callback.from_user.id
    
    item = USER_SESSIONS.get(user_id, {}).get("items", {}).get(short_id)
    await callback.answer()
    
    if not item:
        await callback.message.answer("Срок действия выбора истёк. Повтори поиск.")
        return

    page = USER_SESSIONS.get(user_id, {}).get("current_page", 0)
    kb = build_search_keyboard(user_id, page=page)
    user = database.get_user(user_id)
    mode_title = "Официальные релизы" if user['search_mode'] == "official" else "Ремиксы (SoundCloud)"
    
    try:
        if callback.message.caption:
            await callback.message.edit_caption(caption=f"🎧 Результаты: <b>{mode_title}</b>", reply_markup=kb, parse_mode="HTML")
        else:
            await callback.message.edit_text(text=f"Результаты: <b>{mode_title}</b>", reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass

    status_msg = await callback.message.answer("⏳ Загрузка подтвержденного трека...")
    await process_and_send_audio(callback.message.chat.id, user_id, item['id'], item['url'], status_msg)

@dp.callback_query(F.data == "back_to_results")
async def callback_back_to_results(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = USER_SESSIONS.get(user_id, {}).get("current_page", 0)
    kb = build_search_keyboard(user_id, page=page)
    user = database.get_user(user_id)
    mode_title = "Официальные релизы" if user['search_mode'] == "official" else "Ремиксы (SoundCloud)"

    if callback.message.caption:
        await callback.message.edit_caption(caption=f"🎧 Результаты: <b>{mode_title}</b>", reply_markup=kb, parse_mode="HTML")
    else:
        await callback.message.edit_text(text=f"Результаты: <b>{mode_title}</b>", reply_markup=kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("dl_db:"))
async def callback_dl_db(callback: CallbackQuery):
    parts = callback.data.split(":")
    table = parts[1]
    db_id = parts[2]
    
    record = database.get_track_by_db_id(table, db_id)
    await callback.answer()
    
    if not record:
        await callback.message.answer("Ошибка: трек не найден в базе.")
        return
        
    url, title, artist, track_id = record
    status_msg = await callback.message.answer("⏳ Загрузка трека из базы...")
    await process_and_send_audio(callback.message.chat.id, callback.from_user.id, track_id, url, status_msg)

# --- ИНЛАЙН РЕЖИМ (Работа во всех диалогах) ---

@dp.inline_query()
async def inline_search_handler(inline_query: InlineQuery):
    query = inline_query.query.strip()
    
    if not query or len(query) < 2:
        await inline_query.answer([], cache_time=2, is_personal=True)
        return

    print(f"🔥 [INLINE QUERY] Получен запрос: '{query}'")

    try:
        results = await search_tracks(query, mode="official", limit=8)
        if not results:
            await inline_query.answer([], cache_time=5, is_personal=True)
            return

        is_artist = isinstance(results, dict) and results.get('type') == 'artist'
        tracks_list = results['tracks'] if is_artist else results

        bot_info = await bot.get_me()
        bot_username = bot_info.username or "nomscbot"

        items = []
        for idx, t in enumerate(tracks_list[:8]):
            track_title = t.get('title', 'Без названия')
            artist_name = t.get('uploader', 'Артист')
            duration = int(float(t.get('duration') or 0))
            dur_str = format_duration(duration) if duration > 0 else ""

            inline_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="🎧 Нажми, чтобы найти песню",
                    switch_inline_query_current_chat=""
                )
            ]])

            items.append(
                InlineQueryResultArticle(
                    id=f"in_{idx}_{t['id']}"[:50],
                    title=f"{artist_name} — {track_title}",
                    description=f"⏱ {dur_str} • Нажмите, чтобы отправить" if dur_str else "Нажмите, чтобы отправить в чат",
                    input_message_content=InputTextMessageContent(
                        message_text=(
                            f"🎵 <b>{artist_name} — {track_title}</b>\n"
                            f"⏱ <i>Длительность: {dur_str}</i>\n\n"
                            f"🎧 Отправлено через @{bot_username}"
                        ),
                        parse_mode="HTML"
                    ),
                    reply_markup=inline_kb
                )
            )

        await inline_query.answer(items, cache_time=10, is_personal=True)
        print(f"✅ [INLINE SUCCESS] Отправлено {len(items)} результатов")

    except Exception as e:
        print(f"❌ [INLINE ERROR]: {e}")
        await inline_query.answer([], cache_time=2, is_personal=True)

# --- ВЕБ-сервер и запуск ---

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

async def set_bot_commands():
    commands = [
        BotCommand(command="start", description="Главное меню и клавиатура"),
    ]
    await bot.set_my_commands(commands)

async def main():
    database.init_db()
    await set_bot_commands()
    await start_dummy_web_server()
    
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот успешно запущен и слушает события...")
    
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "inline_query", "chosen_inline_result"]
    )

if __name__ == "__main__":
    asyncio.run(main())
