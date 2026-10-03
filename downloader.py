import os
import re
import aiohttp
import asyncio
import yt_dlp
from PIL import Image
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from shazamio import Shazam

shazam = Shazam()

STOP_WORDS_REMIX = [
    'remix', 'slowed', 'reverb', 'sped up', 'speed up', 'edit', 'flip', 
    'bootleg', 'mashup', 'bass boosted', 'instrumental', 'karaoke'
]

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

def get_base_ydl_opts(output_template: str = None) -> dict:
    opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        # Обход блокировок хостингов: маскировка под мобильные клиенты
        'extractor_args': {
            'youtube': {
                'player_client': ['ios', 'android', 'mweb']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1'
        }
    }
    if output_template:
        opts['outtmpl'] = output_template
        opts['writethumbnail'] = True
        opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '320',
        }]
    return opts

def search_tracks_sync(query: str, mode: str = "official", limit: int = 15):
    clean_q = re.sub(r'([a-zA-Zа-яА-Я])(\d+)', r'\1 \2', query)
    clean_q = re.sub(r'(\d+)([a-zA-Zа-яА-Я])', r'\1 \2', clean_q)
    
    if mode == "official":
        search_engine = f"ytsearch{limit * 2}:{clean_q}"
    else:
        search_engine = f"scsearch{limit}:{clean_q}"

    opts = get_base_ydl_opts()
    opts['extract_flat'] = 'in_playlist'

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            res = ydl.extract_info(search_engine, download=False)
            entries = res.get('entries', []) or []
        except Exception:
            entries = []

        words = set(re.findall(r'\w+', clean_q.lower()))
        results = []

        for entry in entries:
            if not entry:
                continue
            title = entry.get('title', 'Без названия')
            uploader = entry.get('uploader') or entry.get('channel') or 'Артист'
            full_text = f"{uploader} {title}".lower()

            if mode == "official" and any(sw in full_text for sw in STOP_WORDS_REMIX):
                continue

            matches = sum(1 for w in words if w in full_text)
            url = entry.get('url')
            if not url or not url.startswith('http'):
                url = entry.get('webpage_url')

            results.append({
                'id': str(entry.get('id')),
                'title': title,
                'uploader': uploader,
                'url': url,
                'duration': entry.get('duration') or 0,
                'matches': matches
            })

            if len(results) >= limit:
                break

        results.sort(key=lambda x: x['matches'], reverse=True)
        return results

async def search_tracks(query: str, mode: str = "official", limit: int = 15):
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_tracks_sync, query, mode, limit)

def prepare_telegram_cover(raw_img_path: str, output_path: str):
    try:
        with Image.open(raw_img_path) as img:
            img = img.convert('RGB')
            # Обрезаем до идеального квадрата по центру
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

async def download_track(url: str, output_dir: str = "/tmp") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    temp_template = os.path.join(output_dir, '%(id)s.%(ext)s')
    ydl_opts = get_base_ydl_opts(temp_template)

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
    cover_url = None

    try:
        out = await shazam.recognize(mp3_path)
        track_info = out.get('track')
        if track_info:
            final_title = track_info.get('title', fallback_title)
            final_artist = track_info.get('subtitle', fallback_artist)
            images = track_info.get('images', {})
            cover_url = images.get('coverarthq') or images.get('coverart')
    except Exception:
        pass

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

    if not thumb_path:
        for ext in ['.jpg', '.webp', '.png', '.jpeg']:
            possible = f"{base_path}{ext}"
            if os.path.exists(possible):
                thumb_path = prepare_telegram_cover(possible, cover_file)
                try:
                    os.remove(possible)
                except Exception:
                    pass
                break

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
