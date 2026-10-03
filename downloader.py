import os
import re
import aiohttp
import asyncio
import yt_dlp
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from shazamio import Shazam

shazam = Shazam()

def clean_title(title: str) -> str:
    """Очистка от мусорных приписок, если Shazam не найдет трек."""
    trash_patterns = [
        r'\[.*?\]',
        r'\(.*?official.*?\)',
        r'\(.*?audio.*?\)',
        r'\(.*?prod\..*?\)',
        r'\(.*?bass boosted.*?\)',
        r't\.me/\S+',
        r'vk\.com/\S+'
    ]
    for pattern in trash_patterns:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE)
    return title.strip()

async def download_track(url: str, output_dir: str = "/tmp") -> dict:
    """
    Скачивает аудиопоток через yt-dlp, извлекает MP3, 
    распознает через Shazam и вшивает официальные теги.
    """
    os.makedirs(output_dir, exist_ok=True)
    temp_template = os.path.join(output_dir, '%(id)s.%(ext)s')

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_template,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
        'quiet': True,
        'no_warnings': True,
    }

    loop = asyncio.get_event_loop()

    # 1. Скачиваем аудио через yt-dlp
    def run_ydl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            # Файл после FFmpegExtractAudio всегда имеет расширение .mp3
            base, _ = os.path.splitext(filename)
            mp3_path = f"{base}.mp3"
            return mp3_path, info

    mp3_path, raw_info = await loop.run_in_executor(None, run_ydl)

    # 2. Исходные данные (на случай, если Shazam не распознает)
    fallback_title = clean_title(raw_info.get('title', 'Unknown Track'))
    fallback_artist = raw_info.get('uploader') or raw_info.get('channel', 'Unknown Artist')
    
    final_title = fallback_title
    final_artist = fallback_artist
    cover_url = None

    # 3. Аудиоотпечаток через Shazam
    try:
        out = await shazam.recognize(mp3_path)
        track_info = out.get('track')
        if track_info:
            final_title = track_info.get('title', fallback_title)
            final_artist = track_info.get('subtitle', fallback_artist)
            # Извлекаем качественную обложку Apple Music/Shazam
            images = track_info.get('images', {})
            cover_url = images.get('coverarthq') or images.get('coverart')
    except Exception as e:
        print(f"Shazam recognition error: {e}")

    # 4. Вшиваем метаданные (ID3-теги) в файл
    try:
        try:
            audio = EasyID3(mp3_path)
        except Exception:
            audio = EasyID3()
        audio['title'] = final_title
        audio['artist'] = final_artist
        audio.save(mp3_path)

        # 5. Если есть обложка — вшиваем изображение
        if cover_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        id3 = ID3(mp3_path)
                        id3.add(APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,  # Front cover
                            desc='Cover',
                            data=image_data
                        ))
                        id3.save()
    except Exception as e:
        print(f"Tag writing error: {e}")

    return {
        'file_path': mp3_path,
        'title': final_title,
        'artist': final_artist,
        'duration': int(raw_info.get('duration', 0))
    }
