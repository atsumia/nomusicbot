import sqlite3

DB_NAME = "nomusic.db"

def init_db():
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        # Таблица пользователей
        c.execute('''CREATE TABLE IF NOT EXISTS users
                     (user_id INTEGER PRIMARY KEY, username TEXT, download_count INTEGER DEFAULT 0, search_mode TEXT DEFAULT 'official')''')
        # История скачиваний
        c.execute('''CREATE TABLE IF NOT EXISTS history
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, track_id TEXT, title TEXT, artist TEXT, url TEXT)''')
        # Избранные треки
        c.execute('''CREATE TABLE IF NOT EXISTS favorites
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, track_id TEXT, title TEXT, artist TEXT, url TEXT)''')
        conn.commit()

def get_user(user_id, username="Пользователь"):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        c.execute("SELECT user_id, username, download_count, search_mode FROM users WHERE user_id=?", (user_id,))
        user = c.fetchone()
        if not user:
            c.execute("INSERT INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
            conn.commit()
            return {"user_id": user_id, "username": username, "download_count": 0, "search_mode": "official"}
        return {"user_id": user[0], "username": user[1], "download_count": user[2], "search_mode": user[3]}

def set_mode(user_id, mode):
    with sqlite3.connect(DB_NAME) as conn:
        conn.execute("UPDATE users SET search_mode=? WHERE user_id=?", (mode, user_id))
        conn.commit()

def add_download(user_id, track_id, title, artist, url):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        # Увеличиваем счетчик
        c.execute("UPDATE users SET download_count = download_count + 1 WHERE user_id=?", (user_id,))
        # Добавляем в историю
        c.execute("INSERT INTO history (user_id, track_id, title, artist, url) VALUES (?, ?, ?, ?, ?)", 
                     (user_id, track_id, title, artist, url))
        # Храним только последние 10 треков в истории (чтобы не засорять память)
        c.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history WHERE user_id=? ORDER BY id DESC LIMIT 10)", (user_id,))
        conn.commit()

def is_favorite(user_id, track_id):
    with sqlite3.connect(DB_NAME) as conn:
        res = conn.execute("SELECT 1 FROM favorites WHERE user_id=? AND track_id=?", (user_id, track_id)).fetchone()
        return bool(res)

def toggle_favorite(user_id, track_id):
    with sqlite3.connect(DB_NAME) as conn:
        c = conn.cursor()
        if is_favorite(user_id, track_id):
            c.execute("DELETE FROM favorites WHERE user_id=? AND track_id=?", (user_id, track_id))
            conn.commit()
            return False # Удалено из избранного
        else:
            # Ищем трек в истории, чтобы вытащить его название и ссылку для сохранения в избранное
            c.execute("SELECT title, artist, url FROM history WHERE user_id=? AND track_id=? ORDER BY id DESC LIMIT 1", (user_id, track_id))
            row = c.fetchone()
            if row:
                c.execute("INSERT INTO favorites (user_id, track_id, title, artist, url) VALUES (?, ?, ?, ?, ?)",
                          (user_id, track_id, row[0], row[1], row[2]))
                conn.commit()
                return True # Добавлено в избранное
    return False

def get_favorites(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("SELECT id, track_id, title, artist, url FROM favorites WHERE user_id=? ORDER BY id DESC LIMIT 15", (user_id,)).fetchall()

def get_history(user_id):
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute("SELECT id, track_id, title, artist, url FROM history WHERE user_id=? ORDER BY id DESC", (user_id,)).fetchall()

def get_track_by_db_id(table, db_id):
    with sqlite3.connect(DB_NAME) as conn:
        return conn.execute(f"SELECT url, title, artist, track_id FROM {table} WHERE id=?", (db_id,)).fetchone()
