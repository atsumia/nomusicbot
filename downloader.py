import os
import re
import aiohttp
import asyncio
import yt_dlp
from PIL import Image
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from shazamio import Shazam
from yandex_music import ClientAsync

shazam = Shazam()
YANDEX_TOKEN = os.getenv("YANDEX_MUSIC_TOKEN")

# Инициализация клиента Яндекс Музыки
ym_client = None

async def get_ym_client():
    global ym_client
    if ym_client is None and YANDEX_TOKEN:
        try:
            client = ClientAsync(YANDEX_TOKEN)
            await client.init()
            ym_client = client
        except Exception as e:
            print(f"Yandex Music init error: {e}")
    return ym_client

def clean_title(title: str) -> str:
    trash_patterns = [
        r'\[.*?\]',
        r'\(.*?official.*?\)',
        r'\(.*?audio.*?\)',
        r'\(.*?prod\..*?\)',
        r't\.me/\S+',
        r'vk\.com/\S+'
    ]
    for pattern in trash_patterns:
        title = re.sub(pattern, '', title, flags=re.IGNORECASE)
    return title.strip()

def prepare_telegram_cover(raw_img_path: str, output_path: str):
    try:
        with Image.open(raw_img_path) as img:
            img = img.convert('RGB')
            w, h = img.size
            min_dim = min(w, h)
            left = (w - min_dim) / 2
            top = (h - min_dim) / 2
            right = (w + min_dim) / 2
            bottom = (h + min_dim) / 2
            img = img.crop((left, top, right, bottom))
            img.thumbnail((320, 320))
            img.save(output_path, 'JPEG', quality=85)
        return output_path
    except Exception:
        return None

# --- Поиск и загрузка из Яндекс Музыки ---
async def search_yandex(query: str, limit: int = 15):
    client = await get_ym_client()
    if not client:
        return []

    try:
        search_result = await client.search(text=query, type_='track', page=0)
        if not search_result or not search_result.tracks:
            return []

        results = []
        for track in search_result.tracks.results[:limit]:
            artists = ", ".join([a.name for a in track.artists if a.name])
            results.append({
                'id': f"ym_{track.id}",
                'title': track.title,
                'uploader': artists or "Артист",
                'url': f"ym://{track.id}",
                'duration': int(track.duration_ms / 1000) if track.duration_ms else 0
            })
        return results
    except Exception as e:
        print(f"Yandex search error: {e}")
        return []

async def download_yandex_track(track_id: str, output_dir: str = "/tmp") -> dict:
    client = await get_ym_client()
    os.makedirs(output_dir, exist_ok=True)
    
    track = (await client.tracks([track_id]))[0]
    artists = ", ".join([a.name for a in track.artists if a.name])
    title = track.title
    duration = int(track.duration_ms / 1000) if track.duration_ms else 0

    mp3_path = os.path.join(output_dir, f"ym_{track_id}.mp3")
    cover_raw_path = os.path.join(output_dir, f"ym_{track_id}_raw.jpg")
    cover_thumb_path = os.path.join(output_dir, f"ym_{track_id}_thumb.jpg")

    # Скачивание аудио в 320 kbps
    await track.download_async(filename=mp3_path, codec='mp3', bitrate_in_kbps=320)

    # Скачивание официальной обложки
    thumb_path = None
    if track.cover_uri:
        try:
            await track.download_cover_async(filename=cover_raw_path, size='400x400')
            thumb_path = prepare_telegram_cover(cover_raw_path, cover_thumb_path)
            if os.path.exists(cover_raw_path):
                os.remove(cover_raw_path)
        except Exception:
            pass

    # Вшиваем теги ID3
    try:
        audio = EasyID3(mp3_path)
    except Exception:
        audio = EasyID3()
    audio['title'] = title
    audio['artist'] = artists
    audio.save(mp3_path)

    if thumb_path and os.path.exists(thumb_path):
        try:
            with open(thumb_path, 'rb') as f:
                img_data = f.read()
            id3 = ID3(mp3_path)
            id3.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,
                desc='Cover',
                data=img_data
            ))
            id3.save()
        except Exception:
            pass

    return {
        'file_path': mp3_path,
        'thumb_path': thumb_path,
        'title': title,
        'artist': artists,
        'duration': duration
    }

# --- Поиск и загрузка из SoundCloud (для ремиксов) ---
def search_sc_sync(query: str, limit: int = 15):
    clean_q = query.strip()
    search_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
    }
    with yt_dlp.YoutubeDL(search_opts) as ydl:
        try:
            res = ydl.extract_info(f"scsearch{limit}:{clean_q}", download=False)
            entries = res.get('entries', []) or []
        except Exception:
            entries = []

        results = []
        for entry in entries:
            if not entry:
                continue
            url = entry.get('url') or entry.get('webpage_url')
            if not url:
                continue
            results.append({
                'id': f"sc_{entry.get('id')}",
                'title': entry.get('title', 'Без названия'),
                'uploader': entry.get('uploader') or 'Артист',
                'url': url,
                'duration': entry.get('duration') or 0
            })
        return results

async def download_sc_track(url: str, output_dir: str = "/tmp") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    temp_template = os.path.join(output_dir, '%(id)s.%(ext)s')

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_template,
        'writethumbnail': True,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }],
        'quiet': True,
        'no_warnings': True,
    }

    loop = asyncio.get_event_loop()

    def run_ydl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            mp3_path = f"{base}.mp3"
            return mp3_path, base, info

    mp3_path, base_path, raw_info = await loop.run_in_executor(None, run_ydl)

    fallback_title = clean_title(raw_info.get('title', 'Track'))
    fallback_artist = raw_info.get('uploader') or raw_info.get('channel', 'Artist')
    final_title = fallback_title
    final_artist = fallback_artist
    cover_url = raw_info.get('thumbnail')

    cover_file = f"{base_path}_thumb.jpg"
    thumb_path = None

    if cover_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        raw_data = await resp.read()
                        raw_path = f"{base_path}_raw.jpg"
                        with open(raw_path, "wb") as f:
                            f.write(raw_data)
                        thumb_path = prepare_telegram_cover(raw_path, cover_file)
                        if os.path.exists(raw_path):
                            os.remove(raw_path)
        except Exception:
            pass

    try:
        try:
            audio = EasyID3(mp3_path)
        except Exception:
            audio = EasyID3()
        audio['title'] = final_title
        audio['artist'] = final_artist
        audio.save(mp3_path)

        if thumb_path and os.path.exists(thumb_path):
            with open(thumb_path, 'rb') as f:
                img_data = f.read()
            id3 = ID3(mp3_path)
            id3.add(APIC(
                encoding=3,
                mime='image/jpeg',
                type=3,
                desc='Cover',
                data=img_data
            ))
            id3.save()
    except Exception:
        pass

    return {
        'file_path': mp3_path,
        'thumb_path': thumb_path,
        'title': final_title,
        'artist': final_artist,
        'duration': int(raw_info.get('duration', 0))
    }

# --- Главные интерфейсные функции ---
async def search_tracks(query: str, mode: str = "official", limit: int = 15):
    if mode == "official":
        ym_results = await search_yandex(query, limit=limit)
        if ym_results:
            return ym_results
    # Если официальный режим не вернул результатов или выбран режим ремиксов
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_sc_sync, query, limit)

async def download_track(url: str) -> dict:
    if url.startswith("ym://"):
        track_id = url.replace("ym://", "")
        return await download_yandex_track(track_id)
    else:
        return await download_sc_track(url)
