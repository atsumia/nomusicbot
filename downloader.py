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

def search_tracks_sync(query: str, limit: int = 15):
    """Поиск треков с сортировкой по соответствию словам запроса независимо от их порядка."""
    search_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
    }
    with yt_dlp.YoutubeDL(search_opts) as ydl:
        res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
        entries = res.get('entries', []) or []
        
        words = set(re.findall(r'\w+', query.lower()))
        results = []

        for entry in entries:
            title = entry.get('title', 'Без названия')
            uploader = entry.get('uploader', 'Неизвестный автор')
            full_text = f"{uploader} {title}".lower()
            
            # Считаем, сколько слов из запроса совпало с треком
            matches = sum(1 for w in words if w in full_text)

            results.append({
                'id': str(entry.get('id')),
                'title': title,
                'uploader': uploader,
                'url': entry.get('url') or entry.get('webpage_url'),
                'duration': entry.get('duration') or 0,
                'matches': matches
            })

        # Сортируем: сначала те, где больше всего совпадений слов
        results.sort(key=lambda x: x['matches'], reverse=True)
        return results

async def search_tracks(query: str, limit: int = 15):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_tracks_sync, query, limit)

async def download_track(url: str, output_dir: str = "/tmp") -> dict:
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

    def run_ydl():
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            base, _ = os.path.splitext(filename)
            mp3_path = f"{base}.mp3"
            return mp3_path, info

    mp3_path, raw_info = await loop.run_in_executor(None, run_ydl)

    fallback_title = clean_title(raw_info.get('title', 'Track'))
    fallback_artist = raw_info.get('uploader') or raw_info.get('channel', 'Artist')
    
    final_title = fallback_title
    final_artist = fallback_artist
    cover_url = None

    try:
        out = await shazam.recognize(mp3_path)
        track_info = out.get('track')
        if track_info:
            final_title = track_info.get('title', fallback_title)
            final_artist = track_info.get('subtitle', fallback_artist)
            images = track_info.get('images', {})
            cover_url = images.get('coverarthq') or images.get('coverart')
    except Exception as e:
        print(f"Shazam error: {e}")

    try:
        try:
            audio = EasyID3(mp3_path)
        except Exception:
            audio = EasyID3()
        audio['title'] = final_title
        audio['artist'] = final_artist
        audio.save(mp3_path)

        if cover_url:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        image_data = await resp.read()
                        id3 = ID3(mp3_path)
                        id3.add(APIC(
                            encoding=3,
                            mime='image/jpeg',
                            type=3,
                            desc='Cover',
                            data=image_data
                        ))
                        id3.save()
    except Exception as e:
        print(f"ID3 tags error: {e}")

    return {
        'file_path': mp3_path,
        'title': final_title,
        'artist': final_artist,
        'duration': int(raw_info.get('duration', 0))
    }
