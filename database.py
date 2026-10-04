import sqlite3
import os
import re

DB_NAME = "database.db"

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            search_mode TEXT DEFAULT 'official',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            track_id TEXT,
            title TEXT,
            artist TEXT,
            url TEXT,
            telegram_file_id TEXT,
            download_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    c.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            track_id TEXT,
            title TEXT,
            artist TEXT,
            url TEXT,
            telegram_file_id TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, track_id)
        )
    ''')

    try:
        c.execute("ALTER TABLE downloads ADD COLUMN telegram_file_id TEXT")
    except Exception:
        pass

    try:
        c.execute("ALTER TABLE favorites ADD COLUMN telegram_file_id TEXT")
    except Exception:
        pass

    conn.commit()
    conn.close()

def get_user(user_id: int, username: str = None):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id, username, search_mode FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    
    if not row:
        c.execute(
            "INSERT INTO users (user_id, username, search_mode) VALUES (?, ?, 'official')",
            (user_id, username or "")
        )
        conn.commit()
        mode = 'official'
    else:
        mode = row[2]
        if username and row[1] != username:
            c.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
            conn.commit()

    c.execute("SELECT COUNT(*) FROM downloads WHERE user_id = ?", (user_id,))
    count = c.fetchone()[0]
    conn.close()

    return {
        'user_id': user_id,
        'username': username or "",
        'search_mode': mode,
        'download_count': count
    }

def set_mode(user_id: int, mode: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE users SET search_mode = ? WHERE user_id = ?", (mode, user_id))
    conn.commit()
    conn.close()

def add_download(user_id: int, track_id: str, title: str, artist: str, url: str, telegram_file_id: str = None):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "INSERT INTO downloads (user_id, track_id, title, artist, url, telegram_file_id) VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, track_id, title, artist, url, telegram_file_id)
    )
    conn.commit()
    conn.close()

def save_telegram_file_id(track_id: str, file_id: str):
    conn = get_connection()
    c = conn.cursor()
    c.execute("UPDATE downloads SET telegram_file_id = ? WHERE track_id = ?", (file_id, track_id))
    c.execute("UPDATE favorites SET telegram_file_id = ? WHERE track_id = ?", (file_id, track_id))
    conn.commit()
    conn.close()

def get_cached_file_id(track_id: str) -> str:
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT telegram_file_id FROM downloads WHERE track_id = ? AND telegram_file_id IS NOT NULL ORDER BY id DESC LIMIT 1",
        (track_id,)
    )
    row = c.fetchone()
    if not row:
        c.execute(
            "SELECT telegram_file_id FROM favorites WHERE track_id = ? AND telegram_file_id IS NOT NULL ORDER BY id DESC LIMIT 1",
            (track_id,)
        )
        row = c.fetchone()
    conn.close()
    return row[0] if row else None

# --- Универсальный локальный словарь (синхронизирован с downloader.py) ---
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
    'полматери': 'ПОЛМАТЕРИ'
}

def normalize_inline_query(query: str) -> str:
    """Функция нормализации для мгновенного инлайн-поиска"""
    if not query: return ""
    query_lower = query.strip().lower()
    if query_lower in ARTIST_ALIASES:
        return ARTIST_ALIASES[query_lower].lower()
    return query_lower

def search_cached_tracks(query: str, limit: int = 15):
    conn = get_connection()
    c = conn.cursor()
    # Вытягиваем все закэшированные треки
    c.execute('''
        SELECT track_id, title, artist, telegram_file_id 
        FROM downloads 
        WHERE telegram_file_id IS NOT NULL 
        GROUP BY track_id
    ''')
    rows = c.fetchall()
    conn.close()

    # 1. Оригинальный запрос пользователя (например, "капсайз маша")
    original_q = query.lower().strip()
    
    # 2. Нормализованный запрос (например, "cupsize маша")
    # Если введено несколько слов, пытаемся перевести первое слово или использовать целиком
    normalized_q = original_q
    first_word = original_q.split()[0] if original_q.split() else ""
    
    if original_q in ARTIST_ALIASES:
        normalized_q = ARTIST_ALIASES[original_q].lower()
    elif first_word in ARTIST_ALIASES:
        normalized_q = original_q.replace(first_word, ARTIST_ALIASES[first_word].lower(), 1)

    # Разбиваем запросы на слова для гибкого поиска
    search_words = set(re.findall(r'\b\w{3,}\b', normalized_q)).union(set(re.findall(r'\b\w{3,}\b', original_q)))
    
    if not search_words:
        # Если слова слишком короткие, ищем прямым вхождением
        search_words = {original_q, normalized_q}

    results = []
    
    for row in rows:
        track_id, title, artist, file_id = row
        t_low = (title or "").lower()
        a_low = (artist or "").lower()
        combined_text = f"{t_low} {a_low}"

        # Проверяем: если ВСЕ слова из нормализованного (или оригинального) запроса есть в названии/авторе
        # Это обеспечивает высокую точность. Например: запрос "плм маша" -> "полматери маша". Оба слова должны быть в треке.
        
        match_normalized = all(word in combined_text for word in re.findall(r'\b\w{3,}\b', normalized_q)) if len(normalized_q)>2 else (normalized_q in combined_text)
        match_original = all(word in combined_text for word in re.findall(r'\b\w{3,}\b', original_q)) if len(original_q)>2 else (original_q in combined_text)
        
        if match_normalized or match_original:
             results.append(row)

        if len(results) >= limit:
            break

    # Сортировка: точные совпадения (когда запрос целиком есть в названии) поднимаем наверх
    def sort_key(row):
        score = 0
        comb = f"{row[1]} {row[2]}".lower()
        if normalized_q in comb: score += 10
        if original_q in comb: score += 5
        return score
        
    results.sort(key=sort_key, reverse=True)

    return results

def get_history(user_id: int, limit: int = 5):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id, track_id, title, artist, url FROM downloads WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return rows

def toggle_favorite(user_id: int, track_id: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT id FROM favorites WHERE user_id = ? AND track_id = ?", (user_id, track_id))
    row = c.fetchone()

    if row:
        c.execute("DELETE FROM favorites WHERE id = ?", (row[0],))
        conn.commit()
        conn.close()
        return False
    else:
        c.execute(
            "SELECT title, artist, url, telegram_file_id FROM downloads WHERE track_id = ? ORDER BY id DESC LIMIT 1",
            (track_id,)
        )
        track = c.fetchone()
        if track:
            c.execute(
                "INSERT OR IGNORE INTO favorites (user_id, track_id, title, artist, url, telegram_file_id) VALUES (?, ?, ?, ?, ?, ?)",
                (user_id, track_id, track[0], track[1], track[2], track[3])
            )
            conn.commit()
        conn.close()
        return True

def is_favorite(user_id: int, track_id: str) -> bool:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT 1 FROM favorites WHERE user_id = ? AND track_id = ?", (user_id, track_id))
    row = c.fetchone()
    conn.close()
    return bool(row)

def get_favorites(user_id: int, limit: int = 5):
    conn = get_connection()
    c = conn.cursor()
    c.execute(
        "SELECT id, track_id, title, artist, url FROM favorites WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    )
    rows = c.fetchall()
    conn.close()
    return rows

def get_track_by_db_id(table: str, row_id: str):
    if table not in ["downloads", "favorites"]:
        return None
    conn = get_connection()
    c = conn.cursor()
    c.execute(f"SELECT url, title, artist, track_id FROM {table} WHERE id = ?", (row_id,))
    row = c.fetchone()
    conn.close()
    return row