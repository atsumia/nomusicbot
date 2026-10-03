import os
import asyncio
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile
from dotenv import load_dotenv
from downloader import download_track

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN is not defined in environment variables!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

@dp.message(CommandStart())
async def start_handler(message: types.Message):
    await message.answer(
        "👋 **Привет! Я бот для экспорта треков.**\n\n"
        "Отправь мне ссылку на трек из **SoundCloud** или **VK**.\n"
        "Я скачаю его, сверю аудио с официальной базой через Shazam "
        "и пришлю чистый MP3 с правильными тегами и обложкой.",
        parse_mode="Markdown"
    )

@dp.message(F.text.regexp(r'https?://[^\s]+'))
async def handle_url(message: types.Message):
    url = message.text.strip()
    status_msg = await message.answer("⏳ Скачиваю и распознаю трек через Shazam...")

    try:
        # Скачивание и обогащение метаданными
        track = await download_track(url)
        file_path = track['file_path']

        # Проверка размера (лимит Bot API — 50MB)
        file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
        if file_size_mb > 49.5:
            await status_msg.edit_text("❌ Файл превышает лимит Telegram Bot API (50 МБ).")
            if os.path.exists(file_path):
                os.remove(file_path)
            return

        await status_msg.edit_text("🚀 Загружаю аудио в Telegram...")

        # Отправка трека как аудиофайла (с нативным плеером)
        audio = FSInputFile(
            path=file_path, 
            filename=f"{track['artist']} - {track['title']}.mp3"
        )
        await message.answer_audio(
            audio=audio,
            performer=track['artist'],
            title=track['title'],
            duration=track['duration']
        )

        # Удаляем временное сообщение статуса и локальный файл
        await status_msg.delete()
        if os.path.exists(file_path):
            os.remove(file_path)

    except Exception as e:
        await status_msg.edit_text(f"⚠️ Ошибка при обработке ссылки: {str(e)}")

async def main():
    print("Бот успешно запущен и слушает входящие сообщения...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
