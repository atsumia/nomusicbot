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

def normalize_text_ru(text: str) -> str:
    if not text:
        return ""
    cleaned = text.lower().replace('ё', 'е')
    cleaned = re.sub(r'[^\w\s]', ' ', cleaned)
    return re.sub(r'\s+', ' ', cleaned).strip()

def search_cached_tracks(query: str, limit: int = 15):
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT track_id, title, artist, telegram_file_id 
        FROM downloads 
        WHERE telegram_file_id IS NOT NULL 
        GROUP BY track_id
    ''')
    rows = c.fetchall()
    conn.close()

    norm_query = normalize_text_ru(query)
    if not norm_query:
        return []

    aliased_query = norm_query
    for key, val in sorted(ARTIST_ALIASES.items(), key=lambda x: len(x[0]), reverse=True):
        pattern = r'\b' + re.escape(normalize_text_ru(key)) + r'\b'
        aliased_query = re.sub(pattern, normalize_text_ru(val), aliased_query)

    query_variants = list(set([norm_query, aliased_query]))
    words_sets = [
        set([w for w in qv.split() if len(w) >= 2])
        for qv in query_variants
        if qv
    ]

    results = []

    for row in rows:
        track_id, raw_title, raw_artist, file_id = row
        title_norm = normalize_text_ru(raw_title)
        artist_norm = normalize_text_ru(raw_artist)
        combined_norm = f"{artist_norm} {title_norm}"
        track_words = set(combined_norm.split())

        matched = False
        for w_set in words_sets:
            if not w_set:
                continue
            if all(any(tw.startswith(qw) or qw in tw for tw in track_words) or qw in combined_norm for qw in w_set):
                matched = True
                break

        if matched:
            results.append((row, title_norm, artist_norm, combined_norm))

    def sort_key(item):
        _, t_norm, a_norm, comb_norm = item
        score = 0

        for qv in query_variants:
            if qv == t_norm or qv == comb_norm:
                score += 300
            elif qv in comb_norm:
                score += 150
            elif qv in t_norm:
                score += 100

        for w_set in words_sets:
            for w in w_set:
                if w in t_norm:
                    score += 20
                if w in a_norm:
                    score += 10

        return score

    results.sort(key=sort_key, reverse=True)
    return [item[0] for item in results][:limit]

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

def get_admin_stats() -> dict:
    conn = get_connection()
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    total_users = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM downloads")
    total_downloads = c.fetchone()[0]

    c.execute("SELECT COUNT(DISTINCT track_id) FROM downloads WHERE telegram_file_id IS NOT NULL")
    cached_tracks = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM favorites")
    total_favorites = c.fetchone()[0]

    c.execute('''
        SELECT artist, title, COUNT(*) as cnt 
        FROM downloads 
        GROUP BY artist, title 
        ORDER BY cnt DESC 
        LIMIT 5
    ''')
    top_tracks = c.fetchall()

    conn.close()

    return {
        'total_users': total_users,
        'total_downloads': total_downloads,
        'cached_tracks': cached_tracks,
        'total_favorites': total_favorites,
        'top_tracks': top_tracks
    }

def get_all_user_ids() -> list:
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_id FROM users")
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows if r[0]]

def get_all_users_info() -> list:
    conn = get_connection()
    c = conn.cursor()
    c.execute('''
        SELECT u.user_id, u.username, u.created_at, COUNT(d.id) as dl_count
        FROM users u
        LEFT JOIN downloads d ON u.user_id = d.user_id
        GROUP BY u.user_id
        ORDER BY u.created_at DESC
    ''')
    rows = c.fetchall()
    conn.close()
    return [
        {
            'user_id': r[0],
            'username': r[1],
            'created_at': r[2],
            'downloads': r[3]
        }
        for r in rows
    ]