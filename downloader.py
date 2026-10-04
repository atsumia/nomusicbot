import os
import re
import aiohttp
import asyncio
import urllib.parse
from PIL import Image
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3, APIC
from shazamio import Shazam
from yandex_music import ClientAsync
from dotenv import load_dotenv
import yt_dlp

load_dotenv()

shazam = Shazam()
ym_client = None

def normalize_text_ru(text: str) -> str:
    if not text:
        return ""
    cleaned = text.lower().replace('ё', 'е')
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()

async def get_ym_client():
    global ym_client
    if ym_client is not None:
        return ym_client

    yandex_token = os.getenv("YANDEX_MUSIC_TOKEN") or os.getenv("YANDEX_TOKEN")
    yandex_proxy = os.getenv("YANDEX_PROXY") or os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")

    if not yandex_token:
        print("⚠️ [YM]: Токен Яндекс Музыки (YANDEX_MUSIC_TOKEN) не обнаружен в окружении.")

    try:
        kwargs = {}
        if yandex_proxy:
            print(f"🌐 [YM PROXY]: Прокси активирован: {yandex_proxy}")
            kwargs['proxy'] = yandex_proxy

        if yandex_token:
            client = ClientAsync(yandex_token.strip(), **kwargs)
        else:
            client = ClientAsync(**kwargs)

        await client.init()
        ym_client = client
        print("✅ [YM SUCCESS]: Клиент Яндекс Музыки успешно авторизован.")
    except Exception as e:
        print(f"❌ [YM INIT ERROR]: Сбой инициализации Яндекс Музыки: {e}")
        ym_client = None

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

def normalize_search_query(query: str) -> str:
    if not query:
        return ""
    q_norm = normalize_text_ru(query)
    for k in sorted(ARTIST_ALIASES.keys(), key=len, reverse=True):
        k_norm = normalize_text_ru(k)
        pattern = r'\b' + re.escape(k_norm) + r'\b'
        if re.search(pattern, q_norm):
            q_norm = re.sub(pattern, ARTIST_ALIASES[k], q_norm)
            return q_norm.strip()
    return query.strip()

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

def deduplicate_tracks(tracks: list) -> list:
    seen = set()
    unique = []
    for t in tracks:
        key = f"{normalize_text_ru(t.get('uploader', ''))} - {normalize_text_ru(t.get('title', ''))}"
        if key not in seen:
            seen.add(key)
            unique.append(t)
    return unique

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

def strict_text_filter(tracks: list, original_query: str, normalized_query: str) -> list:
    filtered = []
    def extract_words(text):
        clean = normalize_text_ru(text)
        return set([w for w in clean.split() if len(w) >= 2])

    orig_words = extract_words(original_query)
    norm_words = extract_words(normalized_query)
    check_words = orig_words.union(norm_words)

    if not check_words:
        return tracks

    for t in tracks:
        track_text = normalize_text_ru(f"{t.get('uploader', '')} {t.get('title', '')}")
        track_words = set(track_text.split())
        if any(any(tw.startswith(w) or w in tw for tw in track_words) or w in track_text for w in check_words):
            filtered.append(t)
    return filtered

async def search_apple_catalog(query: str, limit: int = 15):
    normalized = normalize_search_query(query)
    term = urllib.parse.quote(normalized)
    url = f"https://itunes.apple.com/search?term={term}&country=ru&entity=song&limit={limit * 2}"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }

    results = []
    try:
        timeout = aiohttp.ClientTimeout(total=4.0)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    for item in data.get('results', []):
                        if item.get('kind') != 'song':
                            continue
                        tid = str(item.get('trackId'))
                        title = item.get('trackName', 'Без названия')
                        artist = item.get('artistName', 'Артист')
                        raw_art = item.get('artworkUrl100', '')
                        cover_hq = raw_art.replace('100x100bb', '600x600bb') if raw_art else None
                        dur_sec = int((item.get('trackTimeMillis') or 0) / 1000)
                        
                        params = {
                            'id': tid,
                            'title': title,
                            'artist': artist,
                            'duration': str(dur_sec),
                            'cover': cover_hq or '',
                            'artist_id': str(item.get('artistId', '')),
                            'album_id': str(item.get('collectionId', '')),
                            'album_title': item.get('collectionName', '')
                        }
                        encoded_url = "am://" + urllib.parse.urlencode(params)
                        
                        results.append({
                            'id': f"am_{tid}",
                            'raw_id': tid,
                            'title': title,
                            'uploader': artist,
                            'url': encoded_url,
                            'duration': dur_sec,
                            'artist_id': str(item.get('artistId', '')) or None,
                            'album_id': str(item.get('collectionId', '')) or None,
                            'album_title': item.get('collectionName') or None,
                            'cover_url': cover_hq,
                            'source': 'official'
                        })
    except Exception as e:
        print(f"❌ [APPLE MUSIC SEARCH ERROR]: {e}")

    unique = deduplicate_tracks(results)
    filtered = strict_text_filter(unique, query, normalized)
    return filtered[:limit] if filtered else unique[:limit]

async def search_tracks_by_lyrics(query: str, limit: int = 15) -> list:
    query_clean = query.strip()
    if not query_clean or len(query_clean) < 2:
        return []

    async def fetch_lrclib():
        try:
            url = f"https://lrclib.net/api/search?q={urllib.parse.quote(query_clean)}"
            headers = {'User-Agent': 'NoMusicBot/1.0 (Telegram Music Bot)'}
            timeout = aiohttp.ClientTimeout(total=4.5)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        if isinstance(data, list):
                            return [
                                (item.get('artistName', '').strip(), item.get('trackName', '').strip())
                                for item in data
                                if item.get('trackName') and item.get('artistName')
                            ]
        except Exception as e:
            print(f"LRCLIB lyrics lookup error: {e}")
        return []

    async def fetch_yandex_lyrics():
        try:
            client = await get_ym_client()
            if client:
                sr = await client.search(text=query_clean, type_='track', page=0)
                if sr and getattr(sr, 'tracks', None) and getattr(sr.tracks, 'results', None):
                    res = []
                    for t in sr.tracks.results:
                        art = ", ".join([a.name for a in t.artists]) if t.artists else "Артист"
                        res.append((art.strip(), t.title.strip()))
                    return res
        except Exception as e:
            print(f"YM lyrics lookup error: {e}")
        return []

    lrclib_res, ym_res = await asyncio.gather(fetch_lrclib(), fetch_yandex_lyrics(), return_exceptions=True)

    candidates = []
    seen_candidates = set()

    for candidate_list in [ym_res, lrclib_res]:
        if isinstance(candidate_list, list):
            for art, tit in candidate_list:
                if not art or not tit:
                    continue
                pair_norm = (normalize_text_ru(art), normalize_text_ru(tit))
                if pair_norm not in seen_candidates:
                    seen_candidates.add(pair_norm)
                    candidates.append((art, tit))

    if not candidates:
        return await search_apple_catalog(query_clean, limit=limit)

    lookup_tasks = []
    for art, tit in candidates[:8]:
        lookup_tasks.append(search_apple_catalog(f"{art} {tit}", limit=1))

    resolved_items = await asyncio.gather(*lookup_tasks, return_exceptions=True)
    final_tracks = []
    seen_tracks = set()

    for sublist in resolved_items:
        if isinstance(sublist, list) and sublist:
            trk = sublist[0]
            track_key = f"{normalize_text_ru(trk.get('uploader', ''))} - {normalize_text_ru(trk.get('title', ''))}"
            if track_key not in seen_tracks:
                seen_tracks.add(track_key)
                final_tracks.append(trk)

    if not final_tracks:
        for art, tit in candidates[:limit]:
            params = {
                'id': f"txt_{abs(hash(art + tit))}",
                'title': tit,
                'artist': art,
                'duration': "180",
                'cover': '',
                'artist_id': '',
                'album_id': '',
                'album_title': ''
            }
            final_tracks.append({
                'id': f"am_txt_{abs(hash(art + tit))}",
                'title': tit,
                'uploader': art,
                'url': "am://" + urllib.parse.urlencode(params),
                'duration': 180,
                'artist_id': None,
                'album_id': None,
                'album_title': None,
                'cover_url': None,
                'source': 'official'
            })

    return deduplicate_tracks(final_tracks)[:limit]

async def search_artist_discography(artist_query: str, mode: str = "official", limit: int = 50):
    clean_query = str(artist_query).strip()
    normalized_artist = normalize_search_query(clean_query)
    target_name = normalized_artist or clean_query

    if mode == "official":
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }

        artist_id = None
        artist_display_name = target_name

        if clean_query.isdigit():
            artist_id = clean_query
        else:
            term = urllib.parse.quote(target_name)
            artist_search_url = f"https://itunes.apple.com/search?term={term}&country=ru&entity=musicArtist&limit=3"

            try:
                timeout = aiohttp.ClientTimeout(total=4.0)
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.get(artist_search_url) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            if data.get('results'):
                                artist_id = str(data['results'][0].get('artistId'))
                                artist_display_name = data['results'][0].get('artistName', target_name)
            except Exception as e:
                print(f"Apple Artist ID lookup error: {e}")

            if not artist_id:
                try:
                    song_search_url = f"https://itunes.apple.com/search?term={term}&country=ru&entity=song&limit=5"
                    timeout = aiohttp.ClientTimeout(total=4.0)
                    async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                        async with session.get(song_search_url) as resp:
                            if resp.status == 200:
                                data = await resp.json(content_type=None)
                                for item in data.get('results', []):
                                    if item.get('artistId'):
                                        artist_id = str(item.get('artistId'))
                                        artist_display_name = item.get('artistName', target_name)
                                        break
                except Exception as e:
                    print(f"Apple Artist ID from song fallback error: {e}")

        tracks = []
        if artist_id:
            lookup_url = f"https://itunes.apple.com/lookup?id={artist_id}&entity=song&limit={limit}&country=ru"
            try:
                timeout = aiohttp.ClientTimeout(total=5.0)
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.get(lookup_url) as resp:
                        if resp.status == 200:
                            data = await resp.json(content_type=None)
                            for item in data.get('results', []):
                                if item.get('wrapperType') == 'artist':
                                    artist_display_name = item.get('artistName', artist_display_name)
                                elif item.get('wrapperType') == 'track' and item.get('kind') == 'song':
                                    tid = str(item.get('trackId'))
                                    title = item.get('trackName', 'Без названия')
                                    artist = item.get('artistName', artist_display_name)
                                    raw_art = item.get('artworkUrl100', '')
                                    cover_hq = raw_art.replace('100x100bb', '600x600bb') if raw_art else None
                                    dur_sec = int((item.get('trackTimeMillis') or 0) / 1000)
                                    
                                    params = {
                                        'id': tid,
                                        'title': title,
                                        'artist': artist,
                                        'duration': str(dur_sec),
                                        'cover': cover_hq or '',
                                        'artist_id': str(artist_id),
                                        'album_id': str(item.get('collectionId', '')),
                                        'album_title': item.get('collectionName', '')
                                    }
                                    encoded_url = "am://" + urllib.parse.urlencode(params)
                                    
                                    tracks.append({
                                        'id': f"am_{tid}",
                                        'raw_id': tid,
                                        'title': title,
                                        'uploader': artist,
                                        'url': encoded_url,
                                        'duration': dur_sec,
                                        'artist_id': str(artist_id),
                                        'album_id': str(item.get('collectionId', '')) or None,
                                        'album_title': item.get('collectionName') or None,
                                        'cover_url': cover_hq,
                                        'artist_display_name': artist_display_name,
                                        'source': 'official'
                                    })
            except Exception as e:
                print(f"Apple Lookup tracks error: {e}")

        if not tracks and not clean_query.isdigit():
            tracks = await search_apple_catalog(target_name, limit=limit)
            for t in tracks:
                t['artist_display_name'] = artist_display_name
                t['source'] = 'official'

        return deduplicate_tracks(tracks)[:limit]

    else:
        loop = asyncio.get_event_loop()
        sc_results = await loop.run_in_executor(None, search_sc_sync, target_name, limit, clean_query)
        for item in sc_results:
            item['artist_display_name'] = target_name
            item['source'] = 'soundcloud'
        return sc_results[:limit]

async def get_am_album_tracks(album_id: str):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }
    url = f"https://itunes.apple.com/lookup?id={album_id}&entity=song&country=ru"
    tracks = []
    try:
        timeout = aiohttp.ClientTimeout(total=5.0)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    results = data.get('results', [])
                    album_title = 'Альбом'
                    for item in results:
                        if item.get('wrapperType') == 'collection':
                            album_title = item.get('collectionName', album_title)
                        elif item.get('wrapperType') == 'track' and item.get('kind') == 'song':
                            tid = str(item.get('trackId'))
                            title = item.get('trackName', 'Без названия')
                            artist = item.get('artistName', 'Артист')
                            raw_art = item.get('artworkUrl100', '')
                            cover_hq = raw_art.replace('100x100bb', '600x600bb') if raw_art else None
                            dur_sec = int((item.get('trackTimeMillis') or 0) / 1000)

                            params = {
                                'id': tid,
                                'title': title,
                                'artist': artist,
                                'duration': str(dur_sec),
                                'cover': cover_hq or '',
                                'artist_id': str(item.get('artistId', '')),
                                'album_id': str(album_id),
                                'album_title': album_title
                            }
                            encoded_url = "am://" + urllib.parse.urlencode(params)

                            tracks.append({
                                'id': f"am_{tid}",
                                'title': title,
                                'uploader': artist,
                                'url': encoded_url,
                                'duration': dur_sec,
                                'artist_id': str(item.get('artistId', '')) or None,
                                'album_id': str(album_id),
                                'album_title': album_title,
                                'cover_url': cover_hq,
                                'source': 'official'
                            })
    except Exception as e:
        print(f"Apple Album lookup error: {e}")
    return deduplicate_tracks(tracks)

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

async def download_official_track(url_data: str, output_dir: str = "/tmp") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    raw_query = url_data.replace("am://", "")
    params = urllib.parse.parse_qs(raw_query)

    track_id = params.get('id', ['0'])[0]
    title = params.get('title', ['Трек'])[0]
    artist = params.get('artist', ['Артист'])[0]
    duration = int(params.get('duration', ['0'])[0])
    cover_url = params.get('cover', [''])[0]
    artist_id = params.get('artist_id', [None])[0]
    album_id = params.get('album_id', [None])[0]
    album_title = params.get('album_title', [None])[0]

    mp3_path = os.path.join(output_dir, f"am_{track_id}.mp3")
    cover_raw_path = os.path.join(output_dir, f"am_{track_id}_raw.jpg")
    cover_thumb_path = os.path.join(output_dir, f"am_{track_id}_thumb.jpg")

    download_success = False

    client = await get_ym_client()
    if not client:
        raise Exception("Официальный музыкальный сервер временно недоступен. Попробуйте режим SoundCloud.")

    try:
        ym_query = f"{artist} - {title}"
        sr = await client.search(text=ym_query, type_='track', page=0)
        if sr and getattr(sr, 'tracks', None) and getattr(sr.tracks, 'results', None):
            target_ym_track = sr.tracks.results[0]
            await target_ym_track.download_async(filename=mp3_path, codec='mp3', bitrate_in_kbps=320)
            download_success = True
            print(f"✅ [YM STREAM SUCCESS]: Успешно выгружен MP3 из официального источника для {ym_query}")
        else:
            alt_query = f"{artist} {title}"
            sr = await client.search(text=alt_query, type_='track', page=0)
            if sr and getattr(sr, 'tracks', None) and getattr(sr.tracks, 'results', None):
                target_ym_track = sr.tracks.results[0]
                await target_ym_track.download_async(filename=mp3_path, codec='mp3', bitrate_in_kbps=320)
                download_success = True
                print(f"✅ [YM STREAM SUCCESS]: Успешно выгружен MP3 (по alt-запросу) для {alt_query}")
    except Exception as e:
        print(f"❌ [YM STREAM ERROR]: Ошибка загрузки из официального каталога: {e}")
        raise Exception("Не удалось выгрузить аудиозапись с официальной площадки (ограничение прав или региона).")

    if not download_success or not os.path.exists(mp3_path):
        raise Exception("Аудиозапись не найдена в официальной медиатеке. Попробуй найти её в SoundCloud.")

    thumb_path = None
    if cover_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(cover_url) as resp:
                    if resp.status == 200:
                        raw_data = await resp.read()
                        with open(cover_raw_path, "wb") as f:
                            f.write(raw_data)
                        thumb_path = prepare_telegram_cover(cover_raw_path, cover_thumb_path)
                        if os.path.exists(cover_raw_path):
                            os.remove(cover_raw_path)
        except Exception:
            pass

    try:
        try:
            audio = EasyID3(mp3_path)
        except Exception:
            audio = EasyID3()
        audio['title'] = title
        audio['artist'] = artist
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
        'title': title,
        'artist': artist,
        'duration': duration,
        'artist_id': artist_id,
        'album_id': album_id,
        'album_title': album_title
    }

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
            raise Exception("Ошибка загрузки аудиозаписи из SoundCloud.")
        except Exception as e:
            raise Exception(f"Ошибка загрузки SoundCloud: {str(e)}")

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
    if mode == "official":
        return await search_apple_catalog(query, limit=limit)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, search_sc_sync, query, limit, query)

async def download_track(url: str) -> dict:
    if url.startswith("am://"):
        return await download_official_track(url)
    else:
        return await download_sc_track(url)