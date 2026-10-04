import os
import asyncio
from dotenv import load_dotenv

load_dotenv()

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    FSInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    ReplyKeyboardMarkup,
    KeyboardButton,
    BotCommand,
    BotCommandScopeDefault,
    BotCommandScopeChat,
    InlineQuery,
    InlineQueryResultCachedAudio,
    InlineQueryResultArticle,
    InputTextMessageContent
)

import database
from downloader import (
    download_track, 
    search_tracks, 
    search_artist_discography,
    search_tracks_by_lyrics,
    get_am_album_tracks,
    get_ym_client
)

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не задан!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

USER_SESSIONS = {}
LONG_TRACK_THRESHOLD = 240

def parse_admin_ids() -> set:
    raw = os.getenv("ADMIN_IDS") or os.getenv("ADMIN_ID") or ""
    admins = set()
    for item in str(raw).replace(" ", "").split(","):
        if item.isdigit():
            admins.add(int(item))
    return admins

ADMIN_IDS = parse_admin_ids()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def format_duration(seconds) -> str:
    try:
        total_sec = int(float(seconds or 0))
    except (ValueError, TypeError):
        return ""
    m = total_sec // 60
    s = total_sec % 60
    return f"{m}:{s:02d}"

def get_bottom_reply_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    user = database.get_user(user_id)
    mode_label = "Режим: Официальные" if user['search_mode'] == 'official' else "Режим: SoundCloud"
    
    keyboard = [
        [KeyboardButton(text="🔎 Поиск"), KeyboardButton(text="🎙 Поиск артиста")],
        [KeyboardButton(text="📝 Поиск по тексту"), KeyboardButton(text=f"🎧 {mode_label}")],
        [KeyboardButton(text="👤 Мой кабинет")]
    ]
    return ReplyKeyboardMarkup(keyboard=keyboard, resize_keyboard=True)

def get_main_menu(user_id: int) -> InlineKeyboardMarkup:
    user = database.get_user(user_id)
    mode_text = "Официальные релизы" if user['search_mode'] == 'official' else "Ремиксы (SoundCloud)"
    
    keyboard = [
        [InlineKeyboardButton(text="🔎 Поиск музыки", callback_data="menu:search"),
         InlineKeyboardButton(text="🎙 Поиск артиста", callback_data="menu:artist_search")],
        [InlineKeyboardButton(text="📝 Поиск по тексту песни", callback_data="menu:lyrics_search")],
        [InlineKeyboardButton(text="👤 Мой кабинет", callback_data="menu:profile")],
        [InlineKeyboardButton(text=f"🎧 Режим: {mode_text}", callback_data="menu:toggle_mode")]
    ]

    if is_admin(user_id):
        keyboard.append([InlineKeyboardButton(text="⚡️ Панель администратора", callback_data="admin:menu")])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def get_profile_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❤️ Избранное", callback_data="menu:favorites"),
         InlineKeyboardButton(text="📜 История", callback_data="menu:history")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu:main")]
    ])

def get_admin_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Аналитика и статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="👥 Список пользователей", callback_data="admin:users_list")],
        [InlineKeyboardButton(text="📢 Рассылка сообщений", callback_data="admin:broadcast_prompt")],
        [InlineKeyboardButton(text="🩺 Диагностика системы", callback_data="admin:diag")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="menu:main")]
    ])

@dp.message(Command("admin"))
async def admin_command_handler(message: types.Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("⚡ <b>Панель управления NoMusic</b>", reply_markup=get_admin_menu(), parse_mode="HTML")

@dp.callback_query(F.data == "admin:menu")
async def admin_menu_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    await callback.message.edit_text("⚡️ <b>Панель управления NoMusic</b>", reply_markup=get_admin_menu(), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin:stats")
async def admin_stats_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    stats = database.get_admin_stats()
    
    top_str = ""
    if stats['top_tracks']:
        top_str = "\n".join([f"  {idx}. <b>{art} — {tit}</b> ({cnt} скач.)" for idx, (art, tit, cnt) in enumerate(stats['top_tracks'], 1)])
    else:
        top_str = "  <i>Пока нет данных</i>"

    text = (
        "📊 <b>Статистика сервиса NoMusic:</b>\n\n"
        f"👥 Всего пользователей: <b>{stats['total_users']}</b>\n"
        f"📥 Скачиваний треков: <b>{stats['total_downloads']}</b>\n"
        f"⚡️ Закэшировано в Telegram: <b>{stats['cached_tracks']}</b>\n"
        f"❤️ Добавлено в избранное: <b>{stats['total_favorites']}</b>\n\n"
        f"🔥 <b>Топ-5 скачиваемых треков:</b>\n{top_str}"
    )

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:stats")],
        [InlineKeyboardButton(text="🔙 Назад в админку", callback_data="admin:menu")]
    ])
    await callback.message.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin:users_list")
async def admin_users_list_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    users = database.get_all_users_info()
    if not users:
        await callback.answer("В базе пока нет пользователей.", show_alert=True)
        return

    lines = []
    for idx, u in enumerate(users, 1):
        uname = f"@{u['username']}" if u['username'] else "<i>нет username</i>"
        lines.append(f"{idx}. {uname} | <code>{u['user_id']}</code> | Скачано: <b>{u['downloads']}</b>")

    full_body = "\n".join(lines)
    header = f"👥 <b>Пользователи бота ({len(users)} чел.):</b>\n\n"

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="admin:users_list")],
        [InlineKeyboardButton(text="🔙 Назад в админку", callback_data="admin:menu")]
    ])

    if len(header + full_body) <= 3900:
        await callback.message.edit_text(header + full_body, reply_markup=back_kb, parse_mode="HTML")
    else:
        file_path = "/tmp/users_list.txt"
        with open(file_path, "w", encoding="utf-8") as f:
            for idx, u in enumerate(users, 1):
                uname = f"@{u['username']}" if u['username'] else "нет username"
                f.write(f"{idx}. {uname} | ID: {u['user_id']} | Скачано: {u['downloads']} | Регистрация: {u['created_at']}\n")

        await callback.message.answer_document(
            document=FSInputFile(file_path, filename="users_list.txt"),
            caption=f"👥 <b>Полный список пользователей ({len(users)} чел.):</b>",
            parse_mode="HTML"
        )
        if os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass

    await callback.answer()

@dp.callback_query(F.data == "admin:diag")
async def admin_diag_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return

    ym_token_present = bool(os.getenv("YANDEX_MUSIC_TOKEN") or os.getenv("YANDEX_TOKEN"))
    client = await get_ym_client()
    ym_status = "🟢 Авторизован и активен" if client else "🔴 Ошибка авторизации / недоступен"
    
    token_badge = "✅ Задан в Environment" if ym_token_present else "❌ Не обнаружен"

    text = (
        "🩺 <b>Диагностика состояния бота:</b>\n\n"
        f"🔑 Токен официального стрима: <b>{token_badge}</b>\n"
        f"🎵 Статус аудио-клиента: <b>{ym_status}</b>\n"
        f"🌍 Apple Music Каталог: <b>🟢 Storefront (RU) активен</b>\n"
        f"⚡️ Инлайн кэширование: <b>🟢 Работает по file_id</b>\n"
        f"👑 ID администраторов: <code>{', '.join(map(str, ADMIN_IDS)) or 'Не заданы'}</code>"
    )

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Проверить заново", callback_data="admin:diag")],
        [InlineKeyboardButton(text="🔙 Назад в админку", callback_data="admin:menu")]
    ])
    await callback.message.edit_text(text, reply_markup=back_kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin:broadcast_prompt")
async def admin_broadcast_prompt(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    
    USER_SESSIONS.setdefault(callback.from_user.id, {})["awaiting"] = "broadcast_input"
    cancel_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data="admin:menu")]
    ])
    await callback.message.edit_text(
        "📢 <b>Рассылка сообщений пользователям</b>\n\n"
        "Отправьте следующим сообщением текст (с поддержкой форматирования HTML или ссылками), "
        "который будет разослан всем пользователям бота.",
        reply_markup=cancel_kb,
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "admin:broadcast_confirm")
async def admin_broadcast_confirm(callback: CallbackQuery):
    admin_id = callback.from_user.id
    if not is_admin(admin_id):
        return

    broadcast_data = USER_SESSIONS.get(admin_id, {}).get("broadcast_draft")
    if not broadcast_data:
        await callback.answer("Сообщение для рассылки не найдено.", show_alert=True)
        return

    USER_SESSIONS[admin_id]["broadcast_draft"] = None
    await callback.message.edit_text("⏳ <i>Рассылка запущена... Пожалуйста, подождите.</i>", parse_mode="HTML")
    
    user_ids = database.get_all_user_ids()
    total_users = len(user_ids)
    success = 0
    blocked = 0

    for uid in user_ids:
        try:
            await bot.send_message(uid, broadcast_data, parse_mode="HTML", disable_web_page_preview=True)
            success += 1
            await asyncio.sleep(0.04)
        except Exception:
            blocked += 1

    report_text = (
        "✅ <b>Рассылка успешно завершена!</b>\n\n"
        f"📊 Всего получателей в базе: <b>{total_users}</b>\n"
        f"🟢 Доставлено сообщений: <b>{success}</b>\n"
        f"🔴 Заблокировали бота / сбои: <b>{blocked}</b>"
    )
    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 В админку", callback_data="admin:menu")]
    ])
    await callback.message.answer(report_text, reply_markup=back_kb, parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "admin:broadcast_cancel")
async def admin_broadcast_cancel(callback: CallbackQuery):
    admin_id = callback.from_user.id
    if admin_id in USER_SESSIONS:
        USER_SESSIONS[admin_id]["broadcast_draft"] = None
        USER_SESSIONS[admin_id]["awaiting"] = None
    await callback.message.edit_text("❌ Рассылка отменена.", reply_markup=get_admin_menu())
    await callback.answer()

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    user_id = message.from_user.id
    username = message.from_user.username or message.from_user.first_name
    database.get_user(user_id, username)
    
    reply_kb = get_bottom_reply_keyboard(user_id)
    inline_kb = get_main_menu(user_id)
    
    welcome_text = (
        "👋 <b>Привет! Это NoMusic.</b>\n\n"
        "Сервис предназначен для поиска и загрузки аудиозаписей.\n\n"
        "<blockquote>💡 <i>Чтобы найти трек, отправь его название, строчку из текста или ссылку. "
        "Для дискографии нажми «🎙 Поиск артиста».</i></blockquote>"
    )
    await message.answer(welcome_text, reply_markup=reply_kb, parse_mode="HTML")
    await message.answer("🎛 <b>Навигация и управление:</b>", reply_markup=inline_kb, parse_mode="HTML")

@dp.message(Command("artist"))
@dp.message(F.text == "🎙 Поиск артиста")
async def artist_search_start(message: types.Message):
    user_id = message.from_user.id
    user = database.get_user(user_id)
    mode_label = "официальных площадок" if user['search_mode'] == 'official' else "SoundCloud"
    USER_SESSIONS.setdefault(user_id, {})["awaiting"] = "artist"
    await message.answer(
        "🎙 <b>Поиск по артисту</b>\n\n"
        f"Отправь имя исполнителя (например: <code>MACAN</code>, <code>CUPSIZE</code>, <code>Серёга Пират</code>).\n"
        f"Я выгружу его дискографию с <b>{mode_label}</b> с сортировкой по популярности.",
        parse_mode="HTML"
    )

@dp.message(Command("lyrics"))
@dp.message(F.text == "📝 Поиск по тексту")
async def lyrics_search_start(message: types.Message):
    user_id = message.from_user.id
    USER_SESSIONS.setdefault(user_id, {})["awaiting"] = "lyrics"
    await message.answer(
        "📝 <b>Поиск трека по тексту песни</b>\n\n"
        "Отправь запомнившиеся слова или строчку из трека (например: <i>«я помню белые обои»</i> или <i>«засыпай на моих руках»</i>).\n"
        "Я найду песню на официальных площадках по совпадению текста!",
        parse_mode="HTML"
    )

@dp.message(F.text == "🔎 Поиск")
async def reply_search_handler(message: types.Message):
    user_id = message.from_user.id
    if user_id in USER_SESSIONS:
        USER_SESSIONS[user_id]["awaiting"] = None
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
    await message.answer(f"✅ Режим поиска переключен на: <b>{mode_name}</b>", reply_markup=reply_kb, parse_mode="HTML")

@dp.callback_query(F.data == "menu:main")
async def show_main_menu(callback: CallbackQuery):
    await callback.message.edit_text("🎛 <b>Навигация и управление:</b>", reply_markup=get_main_menu(callback.from_user.id), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu:search")
async def menu_search(callback: CallbackQuery):
    user_id = callback.from_user.id
    if user_id in USER_SESSIONS:
        USER_SESSIONS[user_id]["awaiting"] = None
    await callback.message.answer("📝 Отправь мне название трека или ссылку для поиска!")
    await callback.answer()

@dp.callback_query(F.data == "menu:artist_search")
async def menu_artist_search(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = database.get_user(user_id)
    mode_label = "официальных площадок" if user['search_mode'] == 'official' else "SoundCloud"
    USER_SESSIONS.setdefault(user_id, {})["awaiting"] = "artist"
    await callback.message.answer(
        f"🎙 <b>Поиск по артисту:</b>\nОтправь имя исполнителя для выгрузки дискографии ({mode_label}).",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.callback_query(F.data == "menu:lyrics_search")
async def menu_lyrics_search(callback: CallbackQuery):
    user_id = callback.from_user.id
    USER_SESSIONS.setdefault(user_id, {})["awaiting"] = "lyrics"
    await callback.message.answer(
        "📝 <b>Поиск по тексту песни:</b>\n"
        "Отправь запомнившиеся слова или строчку из трека.\n"
        "Я найду песню на официальных площадках по тексту!",
        parse_mode="HTML"
    )
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
        buttons.append([InlineKeyboardButton(text=f"{artist} - {title}"[:40], callback_data=f"dl_db:history:{db_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="menu:profile")])
    await callback.message.edit_text("📜 <b>Последние скачанные треки:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data == "menu:favorites")
async def show_favorites(callback: CallbackQuery):
    records = database.get_favorites(callback.from_user.id)
    if not records:
        await callback.answer("У тебя пока нет избранных треков ❤️", show_alert=True)
        return
    buttons = []
    for db_id, track_id, title, artist, url in records:
        buttons.append([InlineKeyboardButton(text=f"❤️ {artist} - {title}"[:40], callback_data=f"dl_db:favorites:{db_id}")])
    buttons.append([InlineKeyboardButton(text="🔙 Назад в кабинет", callback_data="menu:profile")])
    await callback.message.edit_text("❤️ <b>Твое избранное:</b>", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons), parse_mode="HTML")
    await callback.answer()

@dp.callback_query(F.data.startswith("fav:"))
async def toggle_fav_callback(callback: CallbackQuery):
    track_id = callback.data.split("fav:")[1]
    is_now_fav = database.toggle_favorite(callback.from_user.id, track_id)
    btn_text = "❤️ В избранном" if is_now_fav else "🤍 В избранное"
    
    kb_dict = callback.message.reply_markup.model_dump()
    for row in kb_dict['inline_keyboard']:
        for btn in row:
            if btn.get('callback_data') == callback.data:
                btn['text'] = btn_text
                
    await callback.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(**kb_dict))
    await callback.answer("Избранное обновлено!")

def build_search_keyboard(user_id: int, page: int = 0) -> InlineKeyboardMarkup:
    session = USER_SESSIONS.get(user_id, {})
    results = session.get("results", [])
    search_mode = session.get("mode", "official")
    is_discography = session.get("is_discography", False)
    
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
        
        duration = int(float(item.get('duration', 0) or 0))
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
    if nav_row:
        buttons.append(nav_row)

    if is_discography:
        if search_mode == "official":
            buttons.append([InlineKeyboardButton(text="☁️ Искать артиста в SoundCloud", callback_data="switch_artist:remix")])
        else:
            buttons.append([InlineKeyboardButton(text="🎵 Искать на оф. площадках", callback_data="switch_artist:official")])
    else:
        if search_mode == "official":
            buttons.append([InlineKeyboardButton(text="☁️ Искать в SoundCloud", callback_data="switch:remix")])
        else:
            buttons.append([InlineKeyboardButton(text="🎵 Официальные площадки", callback_data="switch:official")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def perform_search_and_send(chat_id: int, user_id: int, query: str, user_mode: str):
    status_msg = await bot.send_message(chat_id, "🔎 Ищу варианты...")
    try:
        results = await search_tracks(query, mode=user_mode, limit=15)

        if not results:
            mode_lbl = "на официальных площадках" if user_mode == "official" else "в SoundCloud"
            switch_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="☁️️ Попробовать в SoundCloud" if user_mode == "official" else "🎵 Попробовать на оф. площадках",
                    callback_data="switch:remix" if user_mode == "official" else "switch:official"
                )
            ]])
            USER_SESSIONS[user_id] = {"query": query, "mode": user_mode}
            await status_msg.edit_text(f"Ничего не нашлось {mode_lbl}. Попробуй изменить запрос или сменить источник:", reply_markup=switch_kb)
            return

        USER_SESSIONS[user_id] = {
            "query": query,
            "mode": user_mode,
            "results": results,
            "items": {},
            "current_page": 0,
            "is_discography": False,
            "awaiting": None
        }

        kb = build_search_keyboard(user_id, page=0)
        mode_title = "🎵 Официальные релизы" if user_mode == "official" else "☁️️ Ремиксы (SoundCloud)"
        await status_msg.edit_text(f"Результаты: <b>{mode_title}</b>", reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(f"Ошибка поиска: {str(e)}")

async def perform_lyrics_search_and_send(chat_id: int, user_id: int, lyrics_query: str):
    status_msg = await bot.send_message(chat_id, "📝 <i>Ищу трек по словам...</i>", parse_mode="HTML")
    try:
        results = await search_tracks_by_lyrics(lyrics_query, limit=15)

        if not results:
            await status_msg.edit_text(
                f"По тексту «{lyrics_query}» ничего не найдено 😔\n\n"
                "<blockquote>Попробуй отправить другую строчку или имя артиста с названием трека.</blockquote>",
                parse_mode="HTML"
            )
            return

        USER_SESSIONS[user_id] = {
            "query": lyrics_query,
            "mode": "official",
            "results": results,
            "items": {},
            "current_page": 0,
            "is_discography": False,
            "awaiting": None
        }

        kb = build_search_keyboard(user_id, page=0)
        header_text = (
            f"📝 <b>Результаты поиска по тексту:</b>\n"
            f"«<i>{lyrics_query}</i>»\n"
            f"🎧 <b>Источник:</b> 🎵 Официальные релизы\n"
            f"📊 Найдено совпадений: <b>{len(results)}</b>"
        )
        await status_msg.edit_text(header_text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(f"Ошибка поиска по тексту: {str(e)}")

async def perform_artist_search_and_send(chat_id: int, user_id: int, artist_query: str, user_mode: str = "official"):
    mode_name = "официальных площадок" if user_mode == "official" else "SoundCloud"
    status_msg = await bot.send_message(chat_id, f"🎙 <i>Формирую дискографию с {mode_name}...</i>", parse_mode="HTML")
    try:
        results = await search_artist_discography(artist_query, mode=user_mode, limit=50)

        if not results:
            switch_kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(
                    text="☁️ Искать в SoundCloud" if user_mode == "official" else "🎵 Искать на оф. площадках",
                    callback_data="switch_artist:remix" if user_mode == "official" else "switch_artist:official"
                )
            ]])
            USER_SESSIONS[user_id] = {"query": artist_query, "mode": user_mode}
            await status_msg.edit_text(
                f"Исполнитель «{artist_query}» не найден {('на официальных площадках' if user_mode == 'official' else 'в SoundCloud')} 😔",
                reply_markup=switch_kb
            )
            return

        first_track = results[0]
        artist_display_name = first_track.get('artist_display_name') or first_track.get('uploader') or artist_query
        source_label = "🎵 Официальные релизы" if user_mode == 'official' else "☁️ SoundCloud"

        USER_SESSIONS[user_id] = {
            "query": artist_display_name,
            "mode": user_mode,
            "results": results,
            "items": {},
            "current_page": 0,
            "is_discography": True,
            "awaiting": None
        }

        kb = build_search_keyboard(user_id, page=0)
        header_text = (
            f"👤 <b>Дискография:</b> {artist_display_name}\n"
            f"🎧 <b>Источник:</b> {source_label}\n"
            f"📊 Найдено треков: <b>{len(results)}</b>\n"
            "<blockquote>🔥 Отсортировано по популярности</blockquote>"
        )
        await status_msg.edit_text(header_text, reply_markup=kb, parse_mode="HTML")
    except Exception as e:
        await status_msg.edit_text(f"Ошибка при поиске артиста: {str(e)}")

@dp.message(F.text.regexp(r'https?://[^\s]+'))
async def handle_url(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ Загрузка ссылки...")
    await process_and_send_audio(message.chat.id, message.from_user.id, "link_track", url, status_msg)

@dp.message(F.text)
async def handle_text_messages(message: types.Message):
    user_id = message.from_user.id
    text = message.text.strip()
    user = database.get_user(user_id, message.from_user.username or message.from_user.first_name)
    mode = user['search_mode']
    
    session = USER_SESSIONS.get(user_id, {})

    if is_admin(user_id) and session.get("awaiting") == "broadcast_input":
        session["awaiting"] = None
        session["broadcast_draft"] = text

        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Запустить рассылку", callback_data="admin:broadcast_confirm")],
            [InlineKeyboardButton(text="❌ Отменить", callback_data="admin:broadcast_cancel")]
        ])
        preview_text = (
            "📢 <b>Предпросмотр сообщения для рассылки:</b>\n\n"
            f"{text}\n\n"
            "<blockquote>Подтвердите отправку всем пользователям бота.</blockquote>"
        )
        await message.answer(preview_text, reply_markup=confirm_kb, parse_mode="HTML")
        return

    if session.get("awaiting") == "artist":
        session["awaiting"] = None
        await perform_artist_search_and_send(message.chat.id, user_id, text, user_mode=mode)
        return

    if session.get("awaiting") == "lyrics":
        session["awaiting"] = None
        await perform_lyrics_search_and_send(message.chat.id, user_id, text)
        return

    await perform_search_and_send(message.chat.id, user_id, text, mode)

@dp.callback_query(F.data.startswith("dl:"))
async def callback_download(callback: CallbackQuery):
    short_id = callback.data.split("dl:")[1]
    user_id = callback.from_user.id
    
    item = USER_SESSIONS.get(user_id, {}).get("items", {}).get(short_id)
    if not item:
        await callback.answer("Срок действия выбора истёк. Повтори поиск.", show_alert=True)
        return

    duration = int(float(item.get('duration', 0) or 0))

    if duration > LONG_TRACK_THRESHOLD:
        await callback.answer()
        dur_text = format_duration(duration)
        warn_text = (
            f"⏳ <b>Внимание: длинная аудиозапись!</b>\n\n"
            f"🎵 <b>{item['uploader']} — {item['title']}</b>\n"
            f"⏱ Длительность: <b>{dur_text}</b>\n\n"
            f"<blockquote>Этот трек длится больше 4 минут. Скачать его?</blockquote>"
        )
        confirm_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⚡️ Да, скачать трек", callback_data=f"confirm_dl:{short_id}")],
            [InlineKeyboardButton(text="🔙 Вернуться к списку", callback_data="back_to_results")]
        ])
        await callback.message.edit_text(text=warn_text, reply_markup=confirm_kb, parse_mode="HTML")
        return

    await callback.answer()
    status_msg = await callback.message.answer("⏳ Загрузка выбранного трека...")
    
    await process_and_send_audio(
        callback.message.chat.id, 
        user_id, 
        item['id'], 
        item['url'], 
        status_msg,
        artist_id=item.get('artist_id'),
        album_id=item.get('album_id')
    )

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
    mode = USER_SESSIONS.get(user_id, {}).get("mode", "official")
    mode_title = "Официальные релизы" if mode == "official" else "Ремиксы (SoundCloud)"
    
    try:
        await callback.message.edit_text(text=f"Результаты: <b>{mode_title}</b>", reply_markup=kb, parse_mode="HTML")
    except Exception:
        pass

    status_msg = await callback.message.answer("⏳ Загрузка подтвержденного трека...")
    await process_and_send_audio(
        callback.message.chat.id, 
        user_id, 
        item['id'], 
        item['url'], 
        status_msg,
        artist_id=item.get('artist_id'),
        album_id=item.get('album_id')
    )

@dp.callback_query(F.data == "back_to_results")
async def callback_back_to_results(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = USER_SESSIONS.get(user_id, {}).get("current_page", 0)
    kb = build_search_keyboard(user_id, page=page)
    mode = USER_SESSIONS.get(user_id, {}).get("mode", "official")
    mode_title = "Официальные релизы" if mode == "official" else "Ремиксы (SoundCloud)"

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

@dp.callback_query(F.data.startswith("album:"))
async def callback_album(callback: CallbackQuery):
    album_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    await callback.answer("Загружаю альбом...")
    status_msg = await callback.message.answer("💿 <i>Загружаю треклист альбома...</i>", parse_mode="HTML")
    tracks = await get_am_album_tracks(album_id)
    
    if not tracks:
        await status_msg.edit_text("Не удалось загрузить треки альбома 🥲")
        return

    album_title = tracks[0].get('album_title') or 'Альбом'

    USER_SESSIONS[user_id] = {
        "query": album_title,
        "mode": "official",
        "results": tracks,
        "items": {},
        "current_page": 0,
        "is_discography": True
    }
    
    kb = build_search_keyboard(user_id, page=0)
    await status_msg.edit_text(f"💿 <b>Альбом:</b> {album_title}\nТреков: <b>{len(tracks)}</b>", reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("artist_top:"))
async def callback_artist_top(callback: CallbackQuery):
    artist_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    
    await callback.answer("Загружаю дискографию...")
    status_msg = await callback.message.answer("👤 <i>Загружаю дискографию артиста...</i>", parse_mode="HTML")
    tracks = await search_artist_discography(artist_id, mode="official", limit=50)
    
    if not tracks:
        await status_msg.edit_text("Не удалось загрузить дискографию артиста 🥲")
        return

    artist_name = tracks[0].get('artist_display_name') or tracks[0].get('uploader') or 'Артист'

    USER_SESSIONS[user_id] = {
        "query": artist_name,
        "mode": "official",
        "results": tracks,
        "items": {},
        "current_page": 0,
        "is_discography": True
    }
    
    kb = build_search_keyboard(user_id, page=0)
    card_text = (
        f"👤 <b>Дискография:</b> {artist_name}\n"
        f"📊 Всего треков: <b>{len(tracks)}</b>\n"
        "<blockquote>🔥 Отсортировано по популярности</blockquote>"
    )
    await status_msg.edit_text(card_text, reply_markup=kb, parse_mode="HTML")

@dp.callback_query(F.data.startswith("switch:"))
async def callback_switch_source(callback: CallbackQuery):
    target_mode = callback.data.split(":")[1]
    user_id = callback.from_user.id
    session = USER_SESSIONS.get(user_id, {})
    query = session.get("query")
    
    if not query:
        await callback.answer("Сессия устарела. Отправьте запрос заново.", show_alert=True)
        return

    await callback.message.delete()
    await perform_search_and_send(callback.message.chat.id, user_id, query, target_mode)

@dp.callback_query(F.data.startswith("switch_artist:"))
async def callback_switch_artist_source(callback: CallbackQuery):
    target_mode = callback.data.split(":")[1]
    user_id = callback.from_user.id
    session = USER_SESSIONS.get(user_id, {})
    query = session.get("query")
    
    if not query:
        await callback.answer("Сессия устарела. Отправьте запрос заново.", show_alert=True)
        return

    await callback.message.delete()
    await perform_artist_search_and_send(callback.message.chat.id, user_id, query, user_mode=target_mode)

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

async def process_and_send_audio(chat_id: int, user_id: int, track_id: str, url: str, status_msg: types.Message, 
                               artist_id: str = None, album_id: str = None):
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

        await status_msg.edit_text("🚀 Отправляю файл...")
        audio = FSInputFile(path=file_path, filename=f"{track['artist']} - {track['title']}.mp3")
        thumbnail = FSInputFile(thumb_path) if thumb_path and os.path.exists(thumb_path) else None

        kb_rows = []
        smart_row = []
        
        final_album_id = track.get('album_id') or album_id
        final_artist_id = track.get('artist_id') or artist_id

        if final_album_id and str(final_album_id).strip() not in ["None", "", "0"]:
            smart_row.append(InlineKeyboardButton(text="💿 Альбом", callback_data=f"album:{final_album_id}"))
            
        if final_artist_id and str(final_artist_id).strip() not in ["None", "", "0"]:
            smart_row.append(InlineKeyboardButton(text="👤 Все треки", callback_data=f"artist_top:{final_artist_id}"))
            
        if smart_row:
            kb_rows.append(smart_row)

        is_fav = database.is_favorite(user_id, track_id)
        fav_text = "❤️ В избранном" if is_fav else "🤍 В избранное"
        kb_rows.append([InlineKeyboardButton(text=fav_text, callback_data=f"fav:{track_id}")])

        kb = InlineKeyboardMarkup(inline_keyboard=kb_rows)

        sent_msg = await bot.send_audio(
            chat_id=chat_id,
            audio=audio,
            performer=track['artist'],
            title=track['title'],
            duration=track['duration'],
            thumbnail=thumbnail,
            reply_markup=kb
        )

        tg_fid = sent_msg.audio.file_id if sent_msg.audio else None
        database.add_download(user_id, track_id, track['title'], track['artist'], url, tg_fid)
        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"⚠️ Ошибка загрузки: {str(e)}")
    finally:
        if file_path and os.path.exists(file_path):
            try:
                os.remove(file_path)
            except Exception:
                pass
        if thumb_path and os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except Exception:
                pass

@dp.inline_query()
async def inline_search_handler(inline_query: InlineQuery):
    query = inline_query.query.strip()
    
    if not query or len(query) < 2:
        await inline_query.answer([], cache_time=2, is_personal=True)
        return

    try:
        cached_tracks = database.search_cached_tracks(query, limit=12)
        valid_results = []
        
        inline_kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🎧 Найти песню", switch_inline_query_current_chat="")
        ]])

        for idx, track in enumerate(cached_tracks):
            track_id, title, artist, file_id = track
            valid_results.append(
                InlineQueryResultCachedAudio(
                    id=f"c_{idx}_{track_id}"[:50],
                    audio_file_id=file_id,
                    reply_markup=inline_kb
                )
            )

        if not valid_results:
            bot_info = await bot.get_me()
            bot_username = bot_info.username or "nomscbot"
            
            valid_results.append(
                InlineQueryResultArticle(
                    id="not_found_cache",
                    title="Трек не найден в базе 😔",
                    description="Отправь название трека напрямую в бот, чтобы он появился здесь",
                    input_message_content=InputTextMessageContent(
                        message_text=(
                            f"Чтобы этот трек появился в инлайн-поиске, его нужно один раз скачать напрямую в боте @{bot_username}.\n\n"
                            "После этого он станет доступен для отправки в любой чат моментально!"
                        )
                    ),
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                        InlineKeyboardButton(text="Перейти в бота", url=f"https://t.me/{bot_username}")
                    ]])
                )
            )

        await inline_query.answer(valid_results, cache_time=5, is_personal=True)

    except Exception as e:
        print(f"❌ [INLINE LOCAL DB ERROR]: {e}")
        await inline_query.answer([], cache_time=2, is_personal=True)

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
    user_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="artist", description="Поиск дискографии артиста"),
        BotCommand(command="lyrics", description="Поиск трека по тексту"),
    ]
    await bot.set_my_commands(user_commands, scope=BotCommandScopeDefault())

    admin_commands = [
        BotCommand(command="start", description="Главное меню"),
        BotCommand(command="artist", description="Поиск дискографии артиста"),
        BotCommand(command="lyrics", description="Поиск трека по тексту"),
        BotCommand(command="admin", description="Панель управления"),
    ]
    for admin_id in ADMIN_IDS:
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=admin_id))
        except Exception:
            pass

async def main():
    database.init_db()
    await set_bot_commands()
    await start_dummy_web_server()
    
    await bot.delete_webhook(drop_pending_updates=True)
    print("Бот NoMusic успешно запущен...")
    
    await dp.start_polling(
        bot,
        allowed_updates=["message", "callback_query", "inline_query", "chosen_inline_result"]
    )

if __name__ == "__main__":
    asyncio.run(main())