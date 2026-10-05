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
import database

load_dotenv()

shazam = Shazam()
ym_client = None

# 1. Поиск визуальных купюр, многоточий и звездочек (Clean/Radio версии)
CENSORSHIP_PATTERN = re.compile(
    r'(?:[\(\[\{]|\b)(clean(?:\s*version)?|censored|radio\s*edit|radio\s*version|цензур(?:а|ная|ный|ом|кой|ка)?|без\s*мата|запикано|cut\s*version)(?:[\)\]\}]|\b)',
    re.IGNORECASE
)

CENSORED_LYRICS_PATTERN = re.compile(
    r'(?:\*{2,}|_{2,}|\[цензура\]|\[вырезано\]|\b[а-яa-z]\*{2,}[а-яa-z]?\b)',
    re.IGNORECASE
)

# 2. Словарь запрещённых тем и веществ (Вариант C)
# Слова и сленговые термины, подлежащие обязательному глушению/запилу звукорежиссёром на стримингах РФ
BANNED_SUBSTANCES_PATTERN = re.compile(
    r'(?:\b(?:'
    r'блант[а-я]*|blunt[s]?|'
    r'джойнт[а-я]*|джоинт[а-я]*|joint[s]?|'
    r'мефедрон[а-я]*|меф[а-я]*|'
    r'кокаин[а-я]*|кокс[а-я]*|'
    r'героин[а-я]*|'
    r'гашиш[а-я]*|гашик[а-я]*|гаш|'
    r'экстази|мдма|mdma|'
    r'амфетамин[а-я]*|'
    r'бульбик[а-я]*|водник[а-я]*|бонг[а-я]*|'
    r'планчик[а-я]*|травк[а-я]*|'
    r'стафф[а-я]*|staff'
    r')\b|'
    r'\b(?:курю|курим|курить|дую|дуем|дуть|забил|забили|взорвал|кручу|тянул)\s+(?:бланты?|траву|план|гаш|шишки|бошки|косяк[а-я]*)\b|'
    r'\b(?:жирный|новый|плотный|целый)\s+косяк[а-я]*\b)',
    re.IGNORECASE
)

def check_lyrics_for_censorship(lyrics_text: str) -> bool:
    """
    Комплексная проверка текста трека на наличие цензуры:
    1. Поиск визуальных купюр (***, [цензура]).
    2. Поиск слов из реестра регулирования контента РФ, которые гарантированно заглушены в дорожке.
    """
    if not lyrics_text or not isinstance(lyrics_text, str) or len(lyrics_text) < 5:
        return False
    if CENSORED_LYRICS_PATTERN.search(lyrics_text):
        return True
    if BANNED_SUBSTANCES_PATTERN.search(lyrics_text):
        return True
    return False

HEADLINER_ARTISTS = {
    'og buda', 'kizaru', 'big baby tape', 'aarne', 'macan', 'oxxxymiron', 'miyagi',
    'andy panda', 'скриптонит', 'pharaoh', 'friendly thug 52 ngg', 'friendly thug',
    'alblak 52', 'toxi$', 'toxis', 'bushido zho', 'scally milano', 'mayot', 'soda luv',
    'платина', 'heronwater', 'saluki', 'markul', 'obladaet', 'король и шут', 'киш',
    'баста', 'guf', 'моргенштерн', 'boulevard depo', 'три дня дождя', 'face', 'хаски',
    'лсп', 'рокет', 'rocket', 'dora', 'дора', 'полматери', 'cupsize', 'серёга пират',
    'серега пират', 'icegergert', 'айсгергерт', 'noize mc', 'anacondaz', 'валентин стрыкало',
    'пошлая молли', 'тима белорусских', 'eldzhey', 'элджей', 'feduk', 'федук', 'lizer',
    'yanix', 'loqiemean', 'локимин', 'замай', 'воскресенский', 'voskresenskii', 'егор крид'
}

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
    'биг бейби тейп аарне': 'Big Baby Tape & Aarne',
    'тейп аарне': 'Big Baby Tape & Aarne',
    'аарне': 'Aarne',
    'aarne': 'Aarne',
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
    'серёга пират': 'Серёга Пират',
    'буда': 'OG Buda',
    'ог буда': 'OG Buda',
    'og buda': 'OG Buda',
    'токсис': 'Toxi$',
    'toxi$': 'Toxi$',
    'toxis': 'Toxi$',
    'бушидо жо': 'BUSHIDO ZHO',
    'bushido zho': 'BUSHIDO ZHO',
    'скалли милано': 'Scally Milano',
    'scally milano': 'Scally Milano',
    'майот': 'MAYOT',
    'mayot': 'MAYOT',
    'сода лав': 'SODA LUV',
    'soda luv': 'SODA LUV',
    'платина': 'Платина',
    'platina': 'Платина',
    'херонвотер': 'Heronwater',
    'heronwater': 'Heronwater',
    'салюки': 'SALUKI',
    'saluki': 'SALUKI',
    'маркул': 'MARKUL',
    'markul': 'MARKUL',
    'обладает': 'OBLADAET',
    'obladaet': 'OBLADAET',
    'егор крид': 'ЕГОР КРИД',
    'крид': 'ЕГОР КРИД'
}

CIS_ARTISTS_CATALOG = HEADLINER_ARTISTS.union({
    'ганвест', 'нурминский', 'диана тагиева', 'гарик кричевский', 'дк', 'дж калиб',
    'jah khalib', 'jony', 'hammali & navai', 'navai', 'hammali', 'rauf & faik', 'mot', 'мот'
})

def normalize_text_ru(text: str) -> str:
    if not text:
        return ""
    cleaned = text.lower().replace('ё', 'е')
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()

def is_cis_entity(artist: str, title: str = "", album: str = "") -> bool:
    norm_artist = normalize_text_ru(artist)
    if norm_artist in CIS_ARTISTS_CATALOG or any(norm_artist.startswith(a) for a in CIS_ARTISTS_CATALOG):
        return True
    for a in CIS_ARTISTS_CATALOG:
        if a in norm_artist:
            return True
    combined = f"{artist} {title} {album}"
    if re.search(r'[а-яА-ЯёЁ]', combined):
        return True
    return False

def is_headliner_artist(artist: str) -> bool:
    norm_artist = normalize_text_ru(artist)
    if norm_artist in HEADLINER_ARTISTS:
        return True
    for h in HEADLINER_ARTISTS:
        if h in norm_artist:
            return True
    return False

def is_track_censored(track_name: str, explicitness: str = "", album_name: str = "", collection_explicitness: str = "") -> bool:
    expl = str(explicitness).lower().strip()
    coll_expl = str(collection_explicitness).lower().strip()
    if expl == 'cleaned' or coll_expl == 'cleaned':
        return True
    combined = f"{track_name} {album_name}"
    if CENSORSHIP_PATTERN.search(combined):
        return True
    return False

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

async def fetch_lrclib_track_censorship(artist: str, title: str) -> bool:
    """
    Опрос LRCLIB на наличие купюр или запрещённых терминов.
    """
    try:
        url = f"https://lrclib.net/api/get?artist_name={urllib.parse.quote(artist)}&track_name={urllib.parse.quote(title)}"
        headers = {'User-Agent': 'NoMusicBot/1.0'}
        timeout = aiohttp.ClientTimeout(total=0.9)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    full_text = data.get('plainLyrics') or data.get('syncedLyrics') or ""
                    if full_text and check_lyrics_for_censorship(full_text):
                        return True
    except Exception:
        pass
    return False

async def check_ym_track_censorship(client: ClientAsync, target_track) -> tuple[bool, bool]:
    """
    Анализ официального текста Яндекс Музыки по купюрам и словарю.
    Возвращает (has_cuts: bool, text_found: bool).
    """
    if not client or not target_track:
        return False, False

    try:
        lyrics_obj = None
        if hasattr(target_track, 'get_lyrics_async'):
            lyrics_obj = await asyncio.wait_for(target_track.get_lyrics_async(format_='TEXT'), timeout=1.1)
        elif hasattr(client, 'tracks_lyrics'):
            lyrics_obj = await asyncio.wait_for(client.tracks_lyrics(target_track.id, format_='TEXT'), timeout=1.1)

        if lyrics_obj:
            lyrics_text = None
            if hasattr(lyrics_obj, 'fetch_lyrics_async'):
                lyrics_text = await asyncio.wait_for(lyrics_obj.fetch_lyrics_async(), timeout=1.2)
            elif hasattr(lyrics_obj, 'full_lyrics') and lyrics_obj.full_lyrics:
                lyrics_text = lyrics_obj.full_lyrics
            elif hasattr(lyrics_obj, 'text') and lyrics_obj.text:
                lyrics_text = lyrics_obj.text

            if lyrics_text and isinstance(lyrics_text, str) and len(lyrics_text) > 5:
                has_cuts = check_lyrics_for_censorship(lyrics_text)
                return has_cuts, True
    except Exception:
        pass

    return False, False

async def fast_resolve_track_censorship(track_dict: dict) -> bool:
    """
    Мгновенно проверяет статус цензуры по SQLite кэшу.
    Если трека в кэше нет — параллельно опрашивает тексты Яндекса и LRCLIB.
    """
    title = track_dict.get('title', '')
    artist = track_dict.get('uploader', '')
    if not title or not artist:
        return track_dict.get('is_censored', False)

    sig = f"{normalize_text_ru(artist)} - {normalize_text_ru(title)}"
    cached = database.get_cached_censorship(sig)
    if cached is True:
        return True

    if track_dict.get('is_censored', False):
        database.set_cached_censorship(sig, True)
        return True

    async def get_ym_verdict():
        try:
            client = await get_ym_client()
            if not client:
                return False, False

            track_id = track_dict.get('raw_id')
            is_ym_direct = str(track_dict.get('id', '')).startswith('am_ym_')
            target_ym_track = None

            if is_ym_direct and track_id and track_id.isdigit():
                tracks_info = await asyncio.wait_for(client.tracks([int(track_id)]), timeout=0.9)
                if tracks_info:
                    target_ym_track = tracks_info[0]
            else:
                sr = await asyncio.wait_for(client.search(text=f"{artist} - {title}", type_='track', page=0), timeout=0.9)
                if sr and getattr(sr, 'tracks', None) and getattr(sr.tracks, 'results', None):
                    target_ym_track = sr.tracks.results[0]

            if target_ym_track:
                return await check_ym_track_censorship(client, target_ym_track)
        except Exception:
            pass
        return False, False

    try:
        # Параллельный опрос обоих источников текстов
        ym_task = get_ym_verdict()
        lrclib_task = fetch_lrclib_track_censorship(artist, title)

        (ym_cut, ym_found), lrclib_cut = await asyncio.gather(ym_task, lrclib_task, return_exceptions=True)

        is_censored = bool((isinstance(ym_cut, bool) and ym_cut) or (isinstance(lrclib_cut, bool) and lrclib_cut))

        if is_censored:
            database.set_cached_censorship(sig, True)
            return True
        elif isinstance(ym_found, bool) and ym_found:
            # Кэшируем False только если текст был успешно прочитан и в нём нет триггеров
            database.set_cached_censorship(sig, False)
            return False
    except Exception:
        pass

    return False

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

def score_and_sort_tracks(tracks: list, query: str) -> list:
    norm_q = normalize_text_ru(query)
    q_words = set(norm_q.split())

    is_established_artist_query = False
    for a in CIS_ARTISTS_CATALOG:
        if norm_q == normalize_text_ru(a):
            is_established_artist_query = True
            break
    if not is_established_artist_query:
        for k, v in ARTIST_ALIASES.items():
            if norm_q in (normalize_text_ru(k), normalize_text_ru(v)):
                is_established_artist_query = True
                break

    def get_score(t):
        score = 0
        t_title = normalize_text_ru(t.get('title', ''))
        t_artist = normalize_text_ru(t.get('uploader', ''))
        t_album = normalize_text_ru(t.get('album_title', ''))
        combined = f"{t_artist} {t_title}"
        combined_rev = f"{t_title} {t_artist}"

        # 1. Связка Артист + Название
        if combined == norm_q or combined_rev == norm_q:
            score += 400
        elif norm_q in combined:
            score += 110

        # 2. Обработка названия трека
        if t_title == norm_q:
            if is_established_artist_query and t_artist != norm_q:
                score += 80
            else:
                score += 350
        elif t_title.startswith(norm_q):
            score += 120
        elif norm_q in t_title:
            score += 60

        # 3. Обработка совпадения по артисту
        if t_artist == norm_q:
            score += 320 if is_established_artist_query else 70
        elif t_artist.startswith(norm_q):
            score += 140 if is_established_artist_query else 60
        elif norm_q in t_artist:
            score += 30

        # 4. Рейтинг верифицированных хедлайнеров
        if is_headliner_artist(t.get('uploader', '')):
            score += 150

        # 5. Региональный СНГ-бонус
        if is_cis_entity(t.get('uploader', ''), t.get('title', ''), t_album):
            score += 180

        # 6. Совпадение отдельных слов
        title_words = set(t_title.split())
        artist_words = set(t_artist.split())
        for qw in q_words:
            if qw in title_words:
                score += 35
            elif any(tw.startswith(qw) for tw in title_words):
                score += 15
            if qw in artist_words:
                score += 30
            elif any(aw.startswith(qw) for aw in artist_words):
                score += 15

        # 7. Не цензурированная версия
        if not t.get('is_censored', False):
            score += 20

        # 8. Приоритет источника
        score += t.get('source_priority', 0)

        return score

    return sorted(tracks, key=get_score, reverse=True)

async def search_apple_catalog(query: str, limit: int = 15):
    normalized = normalize_search_query(query)
    term = urllib.parse.quote(normalized)
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }

    url_song_kz = f"https://itunes.apple.com/search?term={term}&country=kz&entity=song&attribute=songTerm&explicit=Yes&limit=50"
    url_gen_kz = f"https://itunes.apple.com/search?term={term}&country=kz&entity=song&explicit=Yes&limit=50"
    url_gen_ru = f"https://itunes.apple.com/search?term={term}&country=ru&entity=song&explicit=Yes&limit=50"

    results = []

    async def fetch_endpoint(session, url, priority=0):
        try:
            async with session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json(content_type=None)
                    items = []
                    for item in data.get('results', []):
                        if item.get('kind') != 'song':
                            continue
                        tid = str(item.get('trackId'))
                        title = item.get('trackName', 'Без названия')
                        artist = item.get('artistName', 'Артист')
                        album_title = item.get('collectionName', '')
                        explicitness = str(item.get('trackExplicitness', ''))
                        collection_explicitness = str(item.get('collectionExplicitness', ''))
                        
                        censored_flag = is_track_censored(
                            title, 
                            explicitness=explicitness, 
                            album_name=album_title,
                            collection_explicitness=collection_explicitness
                        )
                        
                        raw_art = item.get('artworkUrl100', '')
                        cover_hq = raw_art.replace('100x100bb', '600x600bb') if raw_art else None
                        dur_sec = int((item.get('trackTimeMillis') or 0) / 1000)
                        
                        raw_art_id = str(item.get('artistId', ''))
                        raw_alb_id = str(item.get('collectionId', ''))

                        tagged_artist_id = f"am_{raw_art_id}" if raw_art_id else ""
                        tagged_album_id = f"am_{raw_alb_id}" if raw_alb_id else ""

                        params = {
                            'id': tid,
                            'title': title,
                            'artist': artist,
                            'duration': str(dur_sec),
                            'cover': cover_hq or '',
                            'artist_id': tagged_artist_id,
                            'album_id': tagged_album_id,
                            'album_title': album_title,
                            'censored': '1' if censored_flag else '0'
                        }
                        encoded_url = "am://" + urllib.parse.urlencode(params)
                        
                        items.append({
                            'id': f"am_{tid}",
                            'raw_id': tid,
                            'title': title,
                            'uploader': artist,
                            'url': encoded_url,
                            'duration': dur_sec,
                            'artist_id': tagged_artist_id or None,
                            'album_id': tagged_album_id or None,
                            'album_title': album_title or None,
                            'cover_url': cover_hq,
                            'is_censored': censored_flag,
                            'source': 'official',
                            'source_priority': priority
                        })
                    return items
        except Exception as e:
            print(f"❌ [APPLE SEARCH SUBQUERY ERROR]: {e}")
        return []

    async def fetch_ym_results():
        try:
            client = await get_ym_client()
            if not client:
                return []
            sr = await client.search(text=normalized, type_='track', page=0)
            if sr and getattr(sr, 'tracks', None) and getattr(sr.tracks, 'results', None):
                ym_items = []
                for t in sr.tracks.results[:35]:
                    tid = str(t.id)
                    title = t.title or "Без названия"
                    artists = ", ".join([a.name for a in t.artists]) if t.artists else "Артист"
                    album_name = t.albums[0].title if t.albums else ""
                    raw_alb_id = str(t.albums[0].id) if t.albums else ""
                    raw_art_id = str(t.artists[0].id) if t.artists else ""
                    dur_sec = int((t.duration_ms or 0) / 1000)
                    
                    cover_uri = t.cover_uri or (t.albums[0].cover_uri if t.albums else "")
                    cover_hq = f"https://{cover_uri.replace('%%', '600x600')}" if cover_uri else None
                    censored_flag = is_track_censored(title, album_name=album_name)

                    tagged_artist_id = f"ym_{raw_art_id}" if raw_art_id else ""
                    tagged_album_id = f"ym_{raw_alb_id}" if raw_alb_id else ""
                    
                    params = {
                        'id': tid,
                        'title': title,
                        'artist': artists,
                        'duration': str(dur_sec),
                        'cover': cover_hq or '',
                        'artist_id': tagged_artist_id,
                        'album_id': tagged_album_id,
                        'album_title': album_name,
                        'censored': '1' if censored_flag else '0'
                    }
                    encoded_url = "am://" + urllib.parse.urlencode(params)
                    
                    ym_items.append({
                        'id': f"am_ym_{tid}",
                        'raw_id': tid,
                        'title': title,
                        'uploader': artists,
                        'url': encoded_url,
                        'duration': dur_sec,
                        'artist_id': tagged_artist_id or None,
                        'album_id': tagged_album_id or None,
                        'album_title': album_name or None,
                        'cover_url': cover_hq,
                        'is_censored': censored_flag,
                        'source': 'official',
                        'source_priority': 45
                    })
                return ym_items
        except Exception as e:
            print(f"❌ [YM SEARCH SUBQUERY ERROR]: {e}")
        return []

    try:
        timeout = aiohttp.ClientTimeout(total=4.5)
        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            res_song_kz, res_gen_kz, res_gen_ru, ym_res = await asyncio.gather(
                fetch_endpoint(session, url_song_kz, priority=40),
                fetch_endpoint(session, url_gen_kz, priority=20),
                fetch_endpoint(session, url_gen_ru, priority=10),
                fetch_ym_results(),
                return_exceptions=True
            )
            for r in (res_song_kz, res_gen_kz, res_gen_ru, ym_res):
                if isinstance(r, list):
                    results.extend(r)
    except Exception as e:
        print(f"❌ [OFFICIAL SEARCH AGGREGATOR ERROR]: {e}")

    unique = deduplicate_tracks(results)
    ranked = score_and_sort_tracks(unique, query)[:limit]

    # ПАРАЛЛЕЛЬНАЯ LIVE-ДЕТЕКЦИЯ ЦЕНЗУРЫ ТОП-5 ТРЕКОВ
    top_candidates = ranked[:5]
    if top_candidates:
        censor_tasks = [fast_resolve_track_censorship(t) for t in top_candidates]
        censor_flags = await asyncio.gather(*censor_tasks, return_exceptions=True)
        for idx, flag in enumerate(censor_flags):
            if isinstance(flag, bool) and flag:
                top_candidates[idx]['is_censored'] = True

    return ranked

async def search_tracks_by_lyrics(query: str, limit: int = 15) -> list:
    query_clean = query.strip()
    if not query_clean or len(query_clean) < 2:
        return []

    async def fetch_lrclib():
        try:
            url = f"https://lrclib.net/api/search?q={urllib.parse.quote(query_clean)}"
            headers = {'User-Agent': 'NoMusicBot/1.0'}
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

    return deduplicate_tracks(final_tracks)[:limit]

async def search_artist_discography(artist_query: str, mode: str = "official", limit: int = 50):
    clean_query = str(artist_query).strip()

    if mode == "official":
        if clean_query.startswith("ym_") or clean_query.startswith("ym:"):
            ym_art_id = clean_query.replace("ym_", "").replace("ym:", "").strip()
            client = await get_ym_client()
            if client and ym_art_id.isdigit():
                try:
                    art_info = await client.artists(int(ym_art_id))
                    artist_display_name = art_info[0].name if art_info else "Артист"
                    tracks_resp = await client.artists_tracks(int(ym_art_id), page=0, page_size=limit)
                    if tracks_resp and tracks_resp.tracks:
                        items = []
                        for t in tracks_resp.tracks:
                            tid = str(t.id)
                            title = t.title or "Без названия"
                            artists = ", ".join([a.name for a in t.artists]) if t.artists else artist_display_name
                            album_name = t.albums[0].title if t.albums else ""
                            raw_alb_id = str(t.albums[0].id) if t.albums else ""
                            dur_sec = int((t.duration_ms or 0) / 1000)
                            cover_uri = t.cover_uri or (t.albums[0].cover_uri if t.albums else "")
                            cover_hq = f"https://{cover_uri.replace('%%', '600x600')}" if cover_uri else None
                            censored_flag = is_track_censored(title, album_name=album_name)

                            params = {
                                'id': tid,
                                'title': title,
                                'artist': artists,
                                'duration': str(dur_sec),
                                'cover': cover_hq or '',
                                'artist_id': f"ym_{ym_art_id}",
                                'album_id': f"ym_{raw_alb_id}" if raw_alb_id else '',
                                'album_title': album_name,
                                'censored': '1' if censored_flag else '0'
                            }
                            items.append({
                                'id': f"am_ym_{tid}",
                                'raw_id': tid,
                                'title': title,
                                'uploader': artists,
                                'url': "am://" + urllib.parse.urlencode(params),
                                'duration': dur_sec,
                                'artist_id': f"ym_{ym_art_id}",
                                'album_id': f"ym_{raw_alb_id}" if raw_alb_id else None,
                                'album_title': album_name or None,
                                'cover_url': cover_hq,
                                'artist_display_name': artist_display_name,
                                'is_censored': censored_flag,
                                'source': 'official'
                            })
                        if items:
                            return deduplicate_tracks(items)[:limit]
                except Exception as e:
                    print(f"❌ [YM ARTIST DISCOGRAPHY ERROR]: {e}")

        normalized_artist = normalize_search_query(clean_query.replace("am_", "").replace("am:", ""))
        target_name = normalized_artist or clean_query
        pure_id = clean_query.replace("am_", "").replace("am:", "").strip()

        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'application/json'
        }

        artist_id = pure_id if pure_id.isdigit() else None
        artist_display_name = target_name

        if not artist_id:
            term = urllib.parse.quote(target_name)
            for country in ['kz', 'ru']:
                try:
                    url = f"https://itunes.apple.com/search?term={term}&country={country}&entity=musicArtist&limit=3"
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=3.5), headers=headers) as s:
                        async with s.get(url) as resp:
                            if resp.status == 200:
                                data = await resp.json(content_type=None)
                                if data.get('results'):
                                    artist_id = str(data['results'][0].get('artistId'))
                                    artist_display_name = data['results'][0].get('artistName', target_name)
                                    break
                except Exception:
                    pass

        tracks = []
        if artist_id:
            for country in ['kz', 'ru', 'us']:
                lookup_url = f"https://itunes.apple.com/lookup?id={artist_id}&entity=song&explicit=Yes&limit={limit}&country={country}"
                try:
                    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=4.5), headers=headers) as session:
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
                                        album_title = item.get('collectionName', '')
                                        explicitness = str(item.get('trackExplicitness', ''))
                                        collection_explicitness = str(item.get('collectionExplicitness', ''))
                                        
                                        censored_flag = is_track_censored(
                                            title, 
                                            explicitness=explicitness, 
                                            album_name=album_title,
                                            collection_explicitness=collection_explicitness
                                        )
                                        raw_art = item.get('artworkUrl100', '')
                                        cover_hq = raw_art.replace('100x100bb', '600x600bb') if raw_art else None
                                        dur_sec = int((item.get('trackTimeMillis') or 0) / 1000)

                                        raw_art_id = str(artist_id)
                                        raw_alb_id = str(item.get('collectionId', ''))
                                        
                                        params = {
                                            'id': tid,
                                            'title': title,
                                            'artist': artist,
                                            'duration': str(dur_sec),
                                            'cover': cover_hq or '',
                                            'artist_id': f"am_{raw_art_id}",
                                            'album_id': f"am_{raw_alb_id}" if raw_alb_id else '',
                                            'album_title': album_title,
                                            'censored': '1' if censored_flag else '0'
                                        }
                                        tracks.append({
                                            'id': f"am_{tid}",
                                            'raw_id': tid,
                                            'title': title,
                                            'uploader': artist,
                                            'url': "am://" + urllib.parse.urlencode(params),
                                            'duration': dur_sec,
                                            'artist_id': f"am_{raw_art_id}",
                                            'album_id': f"am_{raw_alb_id}" if raw_alb_id else None,
                                            'album_title': album_title or None,
                                            'cover_url': cover_hq,
                                            'artist_display_name': artist_display_name,
                                            'is_censored': censored_flag,
                                            'source': 'official'
                                        })
                    if tracks:
                        break
                except Exception as e:
                    print(f"❌ [APPLE LOOKUP ERROR {country}]: {e}")

        if not tracks and target_name and not target_name.isdigit():
            tracks = await search_apple_catalog(target_name, limit=limit)
            for t in tracks:
                t['artist_display_name'] = artist_display_name

        return deduplicate_tracks(tracks)[:limit]

    else:
        loop = asyncio.get_event_loop()
        sc_results = await loop.run_in_executor(None, search_sc_sync, clean_query, limit, clean_query)
        for item in sc_results:
            item['artist_display_name'] = clean_query
            item['source'] = 'soundcloud'
        return sc_results[:limit]

async def get_am_album_tracks(album_id: str):
    clean_id = str(album_id).strip()

    if clean_id.startswith("ym_") or clean_id.startswith("ym:"):
        ym_alb_id = clean_id.replace("ym_", "").replace("ym:", "").strip()
        client = await get_ym_client()
        if client and ym_alb_id.isdigit():
            try:
                album_info = await client.albums_with_tracks(int(ym_alb_id))
                if album_info and album_info.volumes:
                    album_title = album_info.title or 'Альбом'
                    artist_name = ", ".join([a.name for a in album_info.artists]) if album_info.artists else 'Артист'
                    art_id = str(album_info.artists[0].id) if album_info.artists else ''
                    items = []
                    for vol in album_info.volumes:
                        for t in vol:
                            tid = str(t.id)
                            title = t.title or "Без названия"
                            artists = ", ".join([a.name for a in t.artists]) if t.artists else artist_name
                            dur_sec = int((t.duration_ms or 0) / 1000)
                            cover_uri = t.cover_uri or album_info.cover_uri or ""
                            cover_hq = f"https://{cover_uri.replace('%%', '600x600')}" if cover_uri else None
                            censored_flag = is_track_censored(title, album_name=album_title)

                            params = {
                                'id': tid,
                                'title': title,
                                'artist': artists,
                                'duration': str(dur_sec),
                                'cover': cover_hq or '',
                                'artist_id': f"ym_{art_id}" if art_id else '',
                                'album_id': f"ym_{ym_alb_id}",
                                'album_title': album_title,
                                'censored': '1' if censored_flag else '0'
                            }
                            items.append({
                                'id': f"am_ym_{tid}",
                                'title': title,
                                'uploader': artists,
                                'url': "am://" + urllib.parse.urlencode(params),
                                'duration': dur_sec,
                                'artist_id': f"ym_{art_id}" if art_id else None,
                                'album_id': f"ym_{ym_alb_id}",
                                'album_title': album_title,
                                'cover_url': cover_hq,
                                'is_censored': censored_flag,
                                'source': 'official'
                            })
                    if items:
                        return deduplicate_tracks(items)
            except Exception as e:
                print(f"❌ [YM ALBUM LOOKUP ERROR]: {e}")

    pure_id = clean_id.replace("am_", "").replace("am:", "").strip()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json'
    }

    tracks = []
    for country in ['kz', 'ru', 'us']:
        url = f"https://itunes.apple.com/lookup?id={pure_id}&entity=song&explicit=Yes&country={country}"
        try:
            timeout = aiohttp.ClientTimeout(total=4.5)
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url) as resp:
                    if resp.status == 200:
                        data = await resp.json(content_type=None)
                        results = data.get('results', [])
                        album_title = 'Альбом'
                        coll_expl = ''
                        for item in results:
                            if item.get('wrapperType') == 'collection':
                                album_title = item.get('collectionName', album_title)
                                coll_expl = str(item.get('collectionExplicitness', ''))
                            elif item.get('wrapperType') == 'track' and item.get('kind') == 'song':
                                tid = str(item.get('trackId'))
                                title = item.get('trackName', 'Без названия')
                                artist = item.get('artistName', 'Артист')
                                explicitness = str(item.get('trackExplicitness', ''))
                                
                                censored_flag = is_track_censored(
                                    title, 
                                    explicitness=explicitness, 
                                    album_name=album_title,
                                    collection_explicitness=coll_expl
                                )
                                
                                raw_art = item.get('artworkUrl100', '')
                                cover_hq = raw_art.replace('100x100bb', '600x600bb') if raw_art else None
                                dur_sec = int((item.get('trackTimeMillis') or 0) / 1000)
                                raw_art_id = str(item.get('artistId', ''))

                                params = {
                                    'id': tid,
                                    'title': title,
                                    'artist': artist,
                                    'duration': str(dur_sec),
                                    'cover': cover_hq or '',
                                    'artist_id': f"am_{raw_art_id}" if raw_art_id else '',
                                    'album_id': f"am_{pure_id}",
                                    'album_title': album_title,
                                    'censored': '1' if censored_flag else '0'
                                }
                                encoded_url = "am://" + urllib.parse.urlencode(params)

                                tracks.append({
                                    'id': f"am_{tid}",
                                    'title': title,
                                    'uploader': artist,
                                    'url': encoded_url,
                                    'duration': dur_sec,
                                    'artist_id': f"am_{raw_art_id}" if raw_art_id else None,
                                    'album_id': f"am_{pure_id}",
                                    'album_title': album_title,
                                    'cover_url': cover_hq,
                                    'is_censored': censored_flag,
                                    'source': 'official'
                                })
            if tracks:
                break
        except Exception as e:
            print(f"❌ [APPLE ALBUM LOOKUP ERROR {country}]: {e}")

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
            'is_censored': False,
            'source': 'soundcloud'
        })

    unique_tracks = deduplicate_tracks(results)
    ranked_tracks = score_and_sort_tracks(unique_tracks, query)
    return ranked_tracks[:limit]

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
    is_censored = params.get('censored', ['0'])[0] == '1'

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
        target_ym_track = None

        if sr and getattr(sr, 'tracks', None) and getattr(sr.tracks, 'results', None):
            target_ym_track = sr.tracks.results[0]
        else:
            alt_query = f"{artist} {title}"
            sr = await client.search(text=alt_query, type_='track', page=0)
            if sr and getattr(sr, 'tracks', None) and getattr(sr.tracks, 'results', None):
                target_ym_track = sr.tracks.results[0]

        if target_ym_track:
            dl_task = target_ym_track.download_async(filename=mp3_path, codec='mp3', bitrate_in_kbps=320)
            lyrics_task = check_ym_track_censorship(client, target_ym_track)

            dl_res, lyrics_result = await asyncio.gather(dl_task, lyrics_task, return_exceptions=True)

            if not isinstance(dl_res, Exception):
                download_success = True
                print(f"✅ [YM STREAM SUCCESS]: Успешно выгружен MP3 для {artist} — {title}")
                
                sig = f"{normalize_text_ru(artist)} - {normalize_text_ru(title)}"
                has_lyrics_cuts = False
                text_was_read = False
                if isinstance(lyrics_result, tuple):
                    has_lyrics_cuts, text_was_read = lyrics_result

                # Если Яндекс не ответил текстом, опрашиваем LRCLIB
                if not has_lyrics_cuts and not text_was_read:
                    has_lyrics_cuts = await fetch_lrclib_track_censorship(artist, title)

                if has_lyrics_cuts:
                    is_censored = True
                    database.set_cached_censorship(sig, True)
                    print(f"✂️ [LYRICS/LEXICAL DETECTED]: Обнаружен триггер цензуры -> сохранён статус Clean")
                elif text_was_read:
                    database.set_cached_censorship(sig, False)
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
        'album_title': album_title,
        'is_censored': is_censored
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
    
    is_censored = False
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
        'album_title': None,
        'is_censored': False
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