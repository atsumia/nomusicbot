import os
import re
import aiohttp
import asyncio
import urllib.parse
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

ARTIST_ALIASES = {
    'макан': 'MACAN',
    'macan': 'MACAN',
    'оксимирон': 'Oxxxymiron',
    'окси': 'Oxxxymiron',
    'oxxxymiron': 'Oxxxymiron',
    'мияги': 'Miyagi',
    'miyagi': 'Miyagi',
    'эндшпиль': 'Andy Panda',
    'скриптонит': 'Скриптонит',
    'scriptonite': 'Скриптонит',
    'фараон': 'PHARAOH',
    'pharaoh': 'PHARAOH',
    'тейп': 'Big Baby Tape',
    'биг бейби тейп': 'Big Baby Tape',
    'кизару': 'kizaru',
    'kizaru': 'kizaru',
    'моргенштерн': 'MORGENSHTERN',
    'morgenshtern': 'MORGENSHTERN',
    'френдли таг': 'FRIENDLY THUG 52 NGG',
    'френдлитаг': 'FRIENDLY THUG 52 NGG',
    'таг': 'FRIENDLY THUG 52 NGG',
    'лсп': 'ЛСП',
    'lsp': 'ЛСП',
    'кино': 'Кино',
    'баста': 'Баста',
    'гуф': 'GUF',
    'инстасамка': 'INSTASAMKA',
    'каста': 'Каста',
    'король и шут': 'Король и Шут',
    'киш': 'Король и Шут',
    'капсайз': 'CUPSIZE',
    'cupsize': 'CUPSIZE',
    'плм': 'ПОЛМАТЕРИ',
    'полматери': 'ПОЛМАТЕРИ',
    'серега пират': 'Серёга Пират',
    'серёга пират': 'Серёга Пират'
}

MAX_CACHE_SIZE = 500
DYNAMIC_ALIASES_CACHE = {}

def normalize_search_query(query: str) -> str:
    if not query:
        return ""
    q_low = query.strip().lower()
    if q_low in ARTIST_ALIASES:
        return ARTIST_ALIASES[q_low]
    normalized = query
    for k in sorted(ARTIST_ALIASES.keys(), key=len, reverse=True):
        pattern = r'(?i)\b' + re.escape(k) + r'\b'
        normalized = re.sub(pattern, ARTIST_ALIASES[k], normalized)
    return normalized.strip()

async def resolve_dynamic_query(query: str) -> str:
    if not query:
        return ""
    query_lower = query.strip().lower()
    if query_lower in ARTIST_ALIASES:
        return ARTIST_ALIASES[query_lower]

    normalized = normalize_search_query(query)
    if normalized.lower() != query_lower:
        return normalized

    if query_lower in DYNAMIC_ALIASES_CACHE:
        return DYNAMIC_ALIASES_CACHE[query_lower]

    safe_term = urllib.parse.quote(query)
    url = f"https://itunes.apple.com/search?term={safe_term}&entity=song&limit=1"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }

    try:
        timeout = aiohttp.ClientTimeout(total=2.0)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    if data.get('results'):
                        item = data['results'][0]
                        artist = item.get('artistName', '')
                        track = item.get('trackName', '')
                        resolved = f"{artist} {track}".strip() if (artist and track) else (artist or query)
                        if len(DYNAMIC_ALIASES_CACHE) >= MAX_CACHE_SIZE:
                            first_key = next(iter(DYNAMIC_ALIASES_CACHE))
                            del DYNAMIC_ALIASES_CACHE[first_key]
                        DYNAMIC_ALIASES_CACHE[query_lower] = resolved
                        return resolved
    except Exception as e:
        print(f"iTunes Fallback for '{query}': {e}")
    return query

def parse_sc_title_and_artist(raw_title: str, uploader: str):
    tag_detected = None
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

    trash = [
        r'\[.*?\]', 
        r'\(.*?official.*?\)', 
        r'\(.*?audio.*?\)',
        r'\(.*?prod\..*?\)', 
        r'\(.*?(slowed|sped up|speed up|reverb|remix).*?\)',
        r'\b(slowed\s*(?:\+|&|and)\s*reverb)\b',
        r'\b(slowed|sped up|speed up|reverb|remix)\b',
        r't\.me/\S+', 
        r'vk\.com/\S+'
    ]
    temp_cleaned = raw_title
    for p in trash:
        temp_cleaned = re.sub(p, '', temp_cleaned, flags=re.IGNORECASE)

    temp_cleaned = re.sub(r'\(\s*\)', '', temp_cleaned)
    temp_cleaned = re.sub(r'\s+', ' ', temp_cleaned).strip()
    temp_cleaned = re.sub(r'[-–—]\s*$', '', temp_cleaned).strip()
    cleaned = temp_cleaned if temp_cleaned else raw_title

    parts = re.split(r'\s*[-–—]\s*', cleaned, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        base_artist = parts[0].strip()
        base_title = parts[1].strip()
    else:
        base_artist = uploader.strip()
        base_title = cleaned.strip()

    first_letter_match = re.search(r'[a-zA-Zа-яА-ЯёЁ]', base_title)
    is_lower = first_letter_match.group(0).islower() if first_letter_match else False

    tag_suffix = ""
    if tag_detected:
        if is_lower:
            formatted_tag = tag_detected.lower()
        else:
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
    real_track = getattr(track, 'track', None) or track
    
    try:
        artists = ", ".join([a.name for a in real_track.artists if getattr(a, 'name', None)])
    except Exception:
        artists = "Артист"

    artist_id = str(real_track.artists[0].id) if getattr(real_track, 'artists', None) and len(real_track.artists) > 0 else None
    album_id = None
    album_title = None
    if getattr(real_track, 'albums', None) and len(real_track.albums) > 0:
        album_id = str(real_track.albums[0].id)
        album_title = str(getattr(real_track.albums[0], 'title', 'Альбом'))

    track_id = getattr(real_track, 'id', None) or getattr(track, 'id', '0')
    title = getattr(real_track, 'title', None) or getattr(track, 'title', 'Без названия')
    duration_ms = getattr(real_track, 'duration_ms', 0) or getattr(track, 'duration_ms', 0) or 0

    return {
        'id': f"ym_{track_id}",
        'raw_id': str(track_id),
        'title': title,
        'uploader': artists or "Артист",
        'url': f"ym://{track_id}",
        'duration_ms': duration_ms,
        'duration': int(duration_ms / 1000),
        'artist_id': artist_id,
        'album_id': album_id,
        'album_title': album_title,
        'source': 'official'
    }

def deduplicate_tracks(tracks: list) -> list:
    seen = set()
    unique = []
    for t in tracks:
        key = f"{t.get('uploader', '').strip().lower()} - {t.get('title', '').strip().lower()}"
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique

def strict_text_filter(tracks: list, original_query: str, normalized_query: str) -> list:
    filtered = []
    def extract_words(text):
        clean = re.sub(r'[^\w\s]', '', text.lower())
        return set([w for w in clean.split() if len(w) >= 2])

    orig_words = extract_words(original_query)
    norm_words = extract_words(normalized_query)
    check_words = orig_words.union(norm_words)

    if not check_words:
        return tracks

    for t in tracks:
        track_text = f"{t.get('uploader', '')} {t.get('title', '')}".lower()
        if any(word in track_text for word in check_words):
            filtered.append(t)
    return filtered

async def search_yandex(query: str, limit: int = 15, original_query: str = ""):
    client = await get_ym_client()
    if not client: 
        return []

    all_tracks = []
    try:
        sr = await client.search(text=query, type_='all', page=0)
        if sr:
            if getattr(sr, 'artists', None) and getattr(sr.artists, 'results', None):
                for artist in sr.artists.results:
                    if artist.name and artist.name.lower() == query.lower():
                        try:
                            artist_info = await client.artists_brief_info(artist.id)
                            if artist_info and getattr(artist_info, 'popular_tracks', None):
                                all_tracks.extend([format_ym_track(t) for t in artist_info.popular_tracks])
                        except Exception:
                            pass
                        break 

            if getattr(sr, 'best', None):
                if getattr(sr.best, 'type', None) == 'artist':
                    art_id = sr.best.result.id
                    try:
                        artist_info = await client.artists_brief_info(art_id)
                        if artist_info and getattr(artist_info, 'popular_tracks', None):
                            all_tracks.extend([format_ym_track(t) for t in artist_info.popular_tracks])
                    except Exception:
                        pass
                elif getattr(sr.best, 'type', None) == 'track':
                    all_tracks.append(format_ym_track(sr.best.result))

            if getattr(sr, 'tracks', None) and getattr(sr.tracks, 'results', None):
                all_tracks.extend([format_ym_track(t) for t in sr.tracks.results])

    except Exception as e:
        print(f"YM search error for '{query}': {e}")

    unique_tracks = deduplicate_tracks(all_tracks)
    query_to_check = original_query if original_query else query
    filtered_tracks = strict_text_filter(unique_tracks, query_to_check, query)
    return filtered_tracks[:limit]

async def search_artist_discography(artist_query: str, mode: str = "official", limit: int = 50):
    normalized_artist = await resolve_dynamic_query(artist_query)
    target_name = normalized_artist or artist_query

    # 1. Режим: Только официальные площадки (БЕЗ переходов на SoundCloud)
    if mode == "official":
        client = await get_ym_client()
        if not client: 
            return []

        all_artist_tracks = []
        target_artist_id = None
        target_artist_name = target_name

        try:
            # А. Поиск через тип 'all'
            sr_all = await client.search(text=target_name, type_='all', page=0)
            if not sr_all and target_name.lower() != artist_query.lower():
                sr_all = await client.search(text=artist_query, type_='all', page=0)

            if sr_all:
                if getattr(sr_all, 'best', None) and getattr(sr_all.best, 'type', None) == 'artist':
                    target_artist_id = sr_all.best.result.id
                    target_artist_name = getattr(sr_all.best.result, 'name', target_name)
                elif getattr(sr_all, 'artists', None) and getattr(sr_all.artists, 'results', None) and len(sr_all.artists.results) > 0:
                    target_artist_id = sr_all.artists.results[0].id
                    target_artist_name = getattr(sr_all.artists.results[0], 'name', target_name)
                elif getattr(sr_all, 'tracks', None) and getattr(sr_all.tracks, 'results', None) and len(sr_all.tracks.results) > 0:
                    first_track = sr_all.tracks.results[0]
                    if getattr(first_track, 'artists', None) and len(first_track.artists) > 0:
                        target_artist_id = first_track.artists[0].id
                        target_artist_name = getattr(first_track.artists[0], 'name', target_name)

            # Б. Выгрузка популярных треков по ID
            if target_artist_id:
                try:
                    artist_info = await client.artists_brief_info(int(target_artist_id))
                    if artist_info and getattr(artist_info, 'popular_tracks', None):
                        all_artist_tracks.extend([format_ym_track(t) for t in artist_info.popular_tracks])
                except Exception as e:
                    print(f"Artist brief info error: {e}")

                try:
                    more_tracks = await client.artists_tracks(int(target_artist_id), page=0, page_size=limit)
                    if more_tracks and getattr(more_tracks, 'tracks', None):
                        for t in more_tracks.tracks:
                            try:
                                all_artist_tracks.append(format_ym_track(t))
                            except Exception:
                                pass
                except Exception as e:
                    print(f"Artist tracks fetch error: {e}")

            # В. Прямой поиск официальных треков исполнителя
            if len(all_artist_tracks) < 10:
                try:
                    sr_tracks = await client.search(text=target_name, type_='track', page=0)
                    if sr_tracks and getattr(sr_tracks, 'tracks', None) and getattr(sr_tracks.tracks, 'results', None):
                        all_artist_tracks.extend([format_ym_track(t) for t in sr_tracks.tracks.results])
                except Exception as e:
                    print(f"Direct tracks search error: {e}")

        except Exception as e:
            print(f"YM Artist discography search error for '{artist_query}': {e}")

        unique_ym = deduplicate_tracks(all_artist_tracks)
        filtered_ym = strict_text_filter(unique_ym, target_name, artist_query)
        final_list = filtered_ym if filtered_ym else unique_ym

        for t in final_list:
            t['artist_display_name'] = target_artist_name
            t['source'] = 'official'

        return final_list[:limit]

    # 2. Режим: Только SoundCloud
    else:
        loop = asyncio.get_event_loop()
        sc_results = await loop.run_in_executor(None, search_sc_sync, target_name, limit, artist_query)
        if not sc_results and target_name.lower() != artist_query.lower():
            sc_results = await loop.run_in_executor(None, search_sc_sync, artist_query, limit, artist_query)

        for item in sc_results:
            item['artist_display_name'] = target_name
            item['source'] = 'soundcloud'

        return sc_results[:limit]

async def get_ym_album_tracks(album_id: str):
    client = await get_ym_client()
    if not client: 
        return []
    try:
        album = await client.albums_with_tracks(int(album_id))
        if album and getattr(album, 'volumes', None):
            tracks = []
            album_title = getattr(album, 'title', 'Альбом')
            for volume in album.volumes:
                for t in volume:
                    formatted = format_ym_track(t)
                    formatted['album_id'] = str(album_id)
                    formatted['album_title'] = album_title
                    tracks.append(formatted)
            return deduplicate_tracks(tracks)
    except Exception as e:
        print(f"Album tracks error: {e}")
    return []

async def get_ym_artist_top(artist_id: str):
    client = await get_ym_client()
    if not client: 
        return []
    try:
        tracks = []
        artist_info = await client.artists_brief_info(int(artist_id))
        if artist_info and getattr(artist_info, 'popular_tracks', None):
            tracks.extend([format_ym_track(t) for t in artist_info.popular_tracks])

        try:
            more = await client.artists_tracks(int(artist_id), page=0, page_size=50)
            if more and getattr(more, 'tracks', None):
                for t in more.tracks:
                    try:
                        tracks.append(format_ym_track(t))
                    except Exception:
                        pass
        except Exception:
            pass

        return deduplicate_tracks(tracks)[:50]
    except Exception as e:
        print(f"Artist top error: {e}")
    return []

async def download_yandex_track(track_id: str, output_dir: str = "/tmp") -> dict:
    client = await get_ym_client()
    os.makedirs(output_dir, exist_ok=True)

    full_tracks = await client.tracks_with_info([track_id])
    if not full_tracks:
        full_tracks = await client.tracks([track_id])
    if not full_tracks:
        raise Exception("Трек не найден на официальных площадках")

    track = full_tracks[0]
    try:
        artists = ", ".join([a.name for a in track.artists if getattr(a, 'name', None)])
    except Exception:
        artists = "Артист"

    title = track.title or "Без названия"
    duration = int(track.duration_ms / 1000) if getattr(track, 'duration_ms', None) else 0

    artist_id = str(track.artists[0].id) if getattr(track, 'artists', None) and len(track.artists) > 0 else None
    album_id = str(track.albums[0].id) if getattr(track, 'albums', None) and len(track.albums) > 0 else None
    album_title = str(getattr(track.albums[0], 'title', 'Альбом')) if album_id else None

    mp3_path = os.path.join(output_dir, f"ym_{track_id}.mp3")
    cover_raw_path = os.path.join(output_dir, f"ym_{track_id}_raw.jpg")
    cover_thumb_path = os.path.join(output_dir, f"ym_{track_id}_thumb.jpg")

    await track.download_async(filename=mp3_path, codec='mp3', bitrate_in_kbps=320)

    thumb_path = None
    if getattr(track, 'cover_uri', None):
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
        'duration': duration,
        'artist_id': artist_id,
        'album_id': album_id,
        'album_title': album_title
    }

def search_sc_sync(query: str, limit: int = 15, original_query: str = ""):
    search_opts = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': 'in_playlist',
    }
    entries = []
    with yt_dlp.YoutubeDL(search_opts) as ydl:
        try:
            res = ydl.extract_info(f"scsearch{limit}:{query}", download=False)
            entries = res.get('entries', []) or []
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
            'duration': entry.get('duration') or 0,
            'source': 'soundcloud'
        })

    unique_tracks = deduplicate_tracks(results)
    query_to_check = original_query if original_query else query
    filtered_tracks = strict_text_filter(unique_tracks, query_to_check, query)
    return filtered_tracks[:limit]

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
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                base, _ = os.path.splitext(filename)
                mp3_path = f"{base}.mp3"
                return mp3_path, base, info
        except yt_dlp.utils.DownloadError as e:
            if "DRM protected" in str(e) or "DRM" in str(e):
                raise Exception("Трек защищен правообладателем (DRM SoundCloud Premium) и недоступен для скачивания 😔")
            raise Exception("Ошибка загрузки аудиозаписи.")
        except Exception as e:
            raise Exception(f"Ошибка загрузки: {str(e)}")

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
            id3.add(APIC(encoding=3, mime='image/jpeg', type=3, desc='Cover', data=img_data))
            id3.save()
    except Exception:
        pass

    return {
        'file_path': mp3_path,
        'thumb_path': thumb_path,
        'title': final_title,
        'artist': final_artist,
        'duration': int(raw_info.get('duration', 0)),
        'artist_id': None,
        'album_id': None,
        'album_title': None
    }

async def search_tracks(query: str, mode: str = "official", limit: int = 15):
    normalized_query = await resolve_dynamic_query(query)
    
    # Режим "Официальные" строго изолирован: никакого fallback на SoundCloud!
    if mode == "official":
        ym_results = await search_yandex(normalized_query, limit=limit, original_query=query)
        if not ym_results and query.strip().lower() != normalized_query.lower():
            ym_results = await search_yandex(query.strip(), limit=limit, original_query=query)
        return ym_results

    # Режим "SoundCloud" строго изолирован
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_sc_sync, normalized_query, limit, query)

async def download_track(url: str) -> dict:
    if url.startswith("ym://"):
        track_id = url.replace("ym://", "")
        return await download_yandex_track(track_id)
    else:
        return await download_sc_track(url)