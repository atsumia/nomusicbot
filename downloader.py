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

def cyrillic_to_latin(text: str) -> str:
    phonetic_rules = [
        (r'дж', 'j'), (r'таг', 'thug'), (r'френдли', 'friendly'),
        (r'скрип', 'scrip'), (r'клауд', 'cloud'), (r'октобер', 'october'),
        (r'щ', 'shch'), (r'ш', 'sh'), (r'ч', 'ch'), (r'ц', 'ts'),
        (r'кс', 'x'), (r'ю', 'yu'), (r'я', 'ya'), (r'ж', 'zh'),
        (r'х', 'kh'), (r'ай', 'i'), (r'ей', 'ey')
    ]
    t = text.lower()
    for cyr, lat in phonetic_rules:
        t = re.sub(cyr, lat, t)

    char_map = {
        'а': 'a', 'б': 'b', 'в': 'v', 'г': 'g', 'д': 'd', 'е': 'e', 'ё': 'yo',
        'з': 'z', 'и': 'i', 'й': 'y', 'к': 'k', 'л': 'l', 'м': 'm', 'н': 'n',
        'о': 'o', 'п': 'p', 'р': 'r', 'с': 's', 'т': 't', 'у': 'u', 'ф': 'f',
        'ы': 'y', 'э': 'e', 'ъ': '', 'ь': ''
    }
    return "".join([char_map.get(ch, ch) for ch in t]).strip()

def get_search_queries(raw_query: str) -> list:
    q = raw_query.strip().lower()
    variants = [raw_query.strip()]
    spaced = re.sub(r'(френдли)(таг)', r'\1 \2', q)
    spaced = re.sub(r'(friendly)(thug)', r'\1 \2', spaced)
    if spaced not in variants:
        variants.append(spaced)
    lat = cyrillic_to_latin(q)
    if lat not in variants:
        variants.append(lat)
    lat_spaced = cyrillic_to_latin(spaced)
    if lat_spaced not in variants:
        variants.append(lat_spaced)
    return variants

def parse_sc_title_and_artist(raw_title: str, uploader: str):
    tag_detected = None
    # Более точные паттерны для выявления версий
    tag_patterns = [
        (r'\b(slowed\s*(?:\+|&|and)\s*reverb)\b', 'slowed + reverb'),
        (r'\b(slowed)\b', 'slowed'),
        (r'\b(sped\s*up|speed\s*up)\b', 'sped up'),
        (r'\b(remix)\b', 'remix'),
        (r'\b(reverb)\b', 'reverb')
    ]
    
    for pattern, label in tag_patterns:
        if re.search(pattern, raw_title, flags=re.IGNORECASE):
            tag_detected = label
            break

    # Список мусора для удаления. Теперь удаляем и версии без скобок, чтобы не было дублей!
    trash = [
        r'\[.*?\]', 
        r'\(.*?official.*?\)', 
        r'\(.*?audio.*?\)',
        r'\(.*?prod\..*?\)', 
        r'\(.*?(slowed|sped up|speed up|reverb|remix).*?\)', # Удаляем версию внутри скобок
        r'\b(slowed\s*(?:\+|&|and)\s*reverb)\b',              # Удаляем сложный тег просто в тексте
        r'\b(slowed|sped up|speed up|reverb|remix)\b',        # Удаляем простые теги просто в тексте
        r't\.me/\S+', 
        r'vk\.com/\S+'
    ]

    temp_cleaned = raw_title
    for p in trash:
        temp_cleaned = re.sub(p, '', temp_cleaned, flags=re.IGNORECASE)

    # Очищаем пустые скобки, лишние пробелы и тире, оставшиеся после вырезания слов
    temp_cleaned = re.sub(r'\(\s*\)', '', temp_cleaned)
    temp_cleaned = re.sub(r'\s+', ' ', temp_cleaned).strip()
    temp_cleaned = re.sub(r'[-–—]\s*$', '', temp_cleaned).strip()

    # Защита: если после очистки от тегов название стало полностью пустым, возвращаем оригинал
    if temp_cleaned:
        cleaned = temp_cleaned
    else:
        cleaned = raw_title

    # Разбиваем на Исполнителя и Название
    parts = re.split(r'\s*[-–—]\s*', cleaned, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        base_artist = parts[0].strip()
        base_title = parts[1].strip()
    else:
        base_artist = uploader.strip()
        base_title = cleaned.strip()

    # Проверяем регистр первого буквенного символа в названии
    first_letter_match = re.search(r'[a-zA-Zа-яА-ЯёЁ]', base_title)
    is_lower = False
    if first_letter_match:
        is_lower = first_letter_match.group(0).islower()

    # Формируем суффикс версии ровно 1 раз и в скобках
    tag_suffix = ""
    if tag_detected:
        if is_lower:
            formatted_tag = tag_detected.lower()
        else:
            # Делаем заглавными каждое слово (например, Slowed + Reverb)
            formatted_tag = " + ".join([w.strip().capitalize() for w in tag_detected.split('+')])
        tag_suffix = f" ({formatted_tag})"

    return base_artist, f"{base_title}{tag_suffix}"

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

def format_ym_track(track):
    artists = ", ".join([a.name for a in track.artists if a.name])
    return {
        'id': f"ym_{track.id}",
        'raw_id': str(track.id),
        'title': track.title,
        'uploader': artists or "Артист",
        'url': f"ym://{track.id}",
        'duration_ms': track.duration_ms or 0,
        'duration': int(track.duration_ms / 1000) if track.duration_ms else 0
    }

async def search_yandex(query: str, limit: int = 15):
    client = await get_ym_client()
    if not client:
        return []

    queries = get_search_queries(query)

    for q in queries:
        try:
            sr = await client.search(text=q, type_='all', page=0)
            if not sr:
                continue

            is_artist_search = False
            artist_name = q.title()
            cover_url = None

            if sr.best and sr.best.type == 'artist':
                is_artist_search = True
                artist_name = sr.best.result.name
                if sr.best.result.cover and sr.best.result.cover.uri:
                    cover_url = f"https://{sr.best.result.cover.uri.replace('%%', '400x400')}"

            if sr.artists and sr.artists.results:
                art = sr.artists.results[0]
                art_name_lower = art.name.lower()
                q_lower = q.lower()
                
                if q_lower == art_name_lower or q_lower in art_name_lower.split():
                    is_artist_search = True
                
                if is_artist_search and not cover_url:
                    artist_name = art.name
                    if art.cover and art.cover.uri:
                        cover_url = f"https://{art.cover.uri.replace('%%', '400x400')}"

            if sr.tracks and sr.tracks.results:
                tracks = [format_ym_track(t) for t in sr.tracks.results[:limit]]
                
                if is_artist_search:
                    if not cover_url and sr.tracks.results[0].cover_uri:
                        cover_url = f"https://{sr.tracks.results[0].cover_uri.replace('%%', '400x400')}"
                    return {
                        'type': 'artist',
                        'artist_name': artist_name,
                        'artist_photo': cover_url,
                        'tracks': tracks
                    }
                else:
                    return tracks

            tr_sr = await client.search(text=q, type_='track', page=0)
            if tr_sr and tr_sr.tracks and tr_sr.tracks.results:
                return [format_ym_track(t) for t in tr_sr.tracks.results[:limit]]

        except Exception as e:
            print(f"YM search error for '{q}': {e}")

    return []

async def download_yandex_track(track_id: str, output_dir: str = "/tmp") -> dict:
    client = await get_ym_client()
    os.makedirs(output_dir, exist_ok=True)
    
    tracks = await client.tracks([track_id])
    if not tracks:
        raise Exception("Трек не найден")
    track = tracks[0]
    artists = ", ".join([a.name for a in track.artists if a.name])
    title = track.title
    duration = int(track.duration_ms / 1000) if track.duration_ms else 0

    mp3_path = os.path.join(output_dir, f"ym_{track_id}.mp3")
    cover_raw_path = os.path.join(output_dir, f"ym_{track_id}_raw.jpg")
    cover_thumb_path = os.path.join(output_dir, f"ym_{track_id}_thumb.jpg")

    await track.download_async(filename=mp3_path, codec='mp3', bitrate_in_kbps=320)

    thumb_path = None
    if track.cover_uri:
        try:
            await track.download_cover_async(filename=cover_raw_path, size='400x400')
            thumb_path = prepare_telegram_cover(cover_raw_path, cover_thumb_path)
            if os.path.exists(cover_raw_path):
                os.remove(cover_raw_path)
        except Exception:
            pass

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

def search_sc_sync(query: str, limit: int = 15):
    queries = get_search_queries(query)
    search_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
    }
    
    entries = []
    with yt_dlp.YoutubeDL(search_opts) as ydl:
        for q in queries[:2]:
            try:
                res = ydl.extract_info(f"scsearch{limit}:{q}", download=False)
                entries += res.get('entries', []) or []
            except Exception:
                pass

    results = []
    seen_ids = set()
    for entry in entries:
        if not entry:
            continue
        eid = str(entry.get('id'))
        if eid in seen_ids:
            continue
        seen_ids.add(eid)

        url = entry.get('url') or entry.get('webpage_url')
        if not url:
            continue
        
        raw_title = entry.get('title', 'Без названия')
        raw_uploader = entry.get('uploader') or 'Неизвестный автор'
        
        parsed_artist, parsed_title = parse_sc_title_and_artist(raw_title, raw_uploader)

        results.append({
            'id': f"sc_{eid}",
            'title': parsed_title,
            'uploader': parsed_artist,
            'url': url,
            'duration': entry.get('duration') or 0
        })
    return results[:limit]

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

    raw_title = raw_info.get('title', 'Track')
    raw_uploader = raw_info.get('uploader') or raw_info.get('channel', 'Artist')
    
    final_artist, final_title = parse_sc_title_and_artist(raw_title, raw_uploader)
    cover_url = raw_info.get('thumbnail')

    lower_check = f"{final_title} {raw_title}".lower()
    skip_keywords = ['slowed', 'sped up', 'speed up', 'минус', 'instrumental', 'instr', 'karaoke', 'beat', 'remake']
    should_skip_shazam = any(k in lower_check for k in skip_keywords)

    if not should_skip_shazam:
        try:
            out = await shazam.recognize(mp3_path)
            track_info = out.get('track')
            if track_info:
                shazam_title = track_info.get('title', '')
                shazam_artist = track_info.get('subtitle', '')

                orig_context = f"{raw_title} {raw_uploader} {final_title} {final_artist}".lower()
                shazam_words = re.findall(r'[a-zA-Zа-яА-ЯёЁ0-9]{3,}', f"{shazam_title} {shazam_artist}".lower())

                has_match = any(w in orig_context for w in shazam_words) if shazam_words else False

                if has_match:
                    final_title = shazam_title or final_title
                    final_artist = shazam_artist or final_artist
                    images = track_info.get('images', {})
                    cover_url = images.get('coverarthq') or images.get('coverart') or cover_url
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

async def get_direct_stream_url(url: str) -> str:
    """Ускоренное получение прямой ссылки на аудиопоток, подготовленной для плеера Telegram"""
    try:
        if url.startswith("ym://"):
            client = await get_ym_client()
            if not client: return None
            track_id = url.replace("ym://", "")
            tracks = await client.tracks([track_id])
            if tracks:
                info = await tracks[0].get_download_info_async()
                mp3_info = [i for i in info if i.codec == 'mp3']
                best = max(mp3_info, key=lambda x: x.bitrate_in_kbps) if mp3_info else info[0]
                link = await best.get_direct_link_async()
                
                # Маскируем под mp3 для обхода валидации Telegram
                return f"{link}&ext=.mp3" if "?" in link else f"{link}?ext=.mp3"
        else:
            loop = asyncio.get_event_loop()
            def extract_sc_stream():
                # skip_download=True исключает тяжелые процессы конвертации при инлайн-вызове
                ydl_opts = {'format': 'bestaudio', 'quiet': True, 'no_warnings': True, 'skip_download': True}
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    data = ydl.extract_info(url, download=False)
                    return data.get('url')
            return await loop.run_in_executor(None, extract_sc_stream)
    except Exception as e:
        print(f"Stream generation error: {e}")
        return None

async def search_tracks(query: str, mode: str = "official", limit: int = 15):
    if mode == "official":
        ym_results = await search_yandex(query, limit=limit)
        if ym_results:
            return ym_results

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_sc_sync, query, limit)

async def download_track(url: str) -> dict:
    if url.startswith("ym://"):
        track_id = url.replace("ym://", "")
        return await download_yandex_track(track_id)
    else:
        return await download_sc_track(url)
