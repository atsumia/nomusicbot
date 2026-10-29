# Project Context & Architecture Ledger: NoMusic Bot (@nomscbot)

## 1. Project Overview & Infrastructure
- **Bot Name / Username:** NoMusic Bot (`@nomscbot`)
- **Repository:** `https://github.com/atsumia/nomusicbot.git` (branch `main`)
- **Hosting Platform:** Railway (`pleasant-compassion` project, `nomusicbot` service)
- **Public Domain:** `https://nomusicbot-production.up.railway.app`
- **Core Stack:** Python 3.11, `aiogram` 3.x, `aiohttp`, `yandex-music` (ClientAsync), SQLite (`database.db`), `mutagen` (ID3 tagging), `Pillow`.

## 2. Inline Search Optimization & Architecture
- **Root Cause of Inline Menu Failure:**
  - `import time` was missing in `bot.py` while `time.time()` was called in `inline_search_handler`. This threw an unhandled `NameError: name 'time' is not defined`, forcing the handler into the `except` block, which returned an empty array `[]` on every keystroke.
  - Furthermore, `cache_time=300` caused Telegram to cache the empty failure response for 5 minutes.
- **Applied Fixes & Optimizations:**
  1. **Fixed Imports:** Added `import time` at the top of `bot.py`.
  2. **Sub-second Search (`0.3s`):** `search_yandex_catalog` now uses a single, direct `client.search(text=query, type_='track', page=0)` bounded by `asyncio.wait_for(..., timeout=2.0)`. This completely eliminates Telegram's 2.5-second timeout issues, executing in ~0.35s.
  3. **Short Cache Duration (`cache_time=10, is_personal=True`):** Prevents Telegram from caching temporary empty responses for long periods while protecting Railway from keystroke flooding.
  4. **Unbuffered Logging (`PYTHONUNBUFFERED=1`):** Enabled in `Dockerfile` so Railway logs show `🔍 [INLINE QUERY]` and `✅ [INLINE ANSWER]` in real time.
  5. **Direct Streaming & Local Cache Fallback:**
     - Tracks with existing Telegram `file_id` return `InlineQueryResultCachedAudio` (0ms, 0 server load).
     - New tracks return `InlineQueryResultAudio` pointing to `/api/stream/{track_id}.mp3` with concurrency locking.
