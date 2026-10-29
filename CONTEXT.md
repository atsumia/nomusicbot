# Project Context & Architecture Ledger: NoMusic Bot (@nomscbot)

## 1. Project Overview & Infrastructure
- **Bot Name / Username:** NoMusic Bot (`@nomscbot`)
- **Repository:** `https://github.com/atsumia/nomusicbot.git` (branch `main`)
- **Hosting Platform:** Railway (`pleasant-compassion` project, `nomusicbot` service)
- **Public Domain:** `https://nomusicbot-production.up.railway.app`
- **Core Stack:** Python 3.11, `aiogram` 3.x, `aiohttp`, `yandex-music` (ClientAsync), SQLite (`database.db`), `mutagen` (ID3 tagging), `Pillow`.

## 2. Key Architectural Decisions

### Inline Mode Architecture (Direct Yandex Music Search & Smart Streaming)
- **Live Search Direct from Yandex Music:**
  - Inline queries `@nomscbot <query>` directly query the official Yandex Music catalog via `search_yandex_catalog(query, limit=10)`.
  - Smart search (`type_='all'`) prioritizes the best match: if an artist is detected (e.g. "Макан"), the artist's real hit tracks are prepended; if a specific track is matched, it is placed at the top.
  - Queries `< 2` characters immediately return empty results (`cache_time=5, is_personal=False`), eliminating unnecessary API calls on single keystrokes.
- **Railway Load & Bandwidth Optimization:**
  - **Telegram Edge Caching:** Inline results are served with `cache_time=300` (5 minutes) and `is_personal=False`. Telegram edge servers serve cached query results directly to users, shielding Railway from keystroke flooding.
  - **In-Memory TTL Cache:** `_INLINE_QUERY_CACHE` (15 min TTL) caches search results in RAM, serving repeated queries in <1ms without hitting Yandex Music or Railway CPU.
  - **Zero Audio Overhead on Search:** Only metadata (title, artist, duration) is fetched during search. No MP3 files or stream URLs are downloaded during keystrokes.
- **Dual Audio Delivery Pipeline:**
  1. **Cached Audio:** If a track has already been sent to Telegram (stored in `downloads` with `telegram_file_id`), it is served as `InlineQueryResultCachedAudio`. Telegram delivers it instantly from its CDN without touching Railway.
  2. **Streaming Audio:** If not in DB, it is served as `InlineQueryResultAudio` pointing to `https://nomusicbot-production.up.railway.app/api/stream/{track_full_id}.mp3`.
  3. **On-Demand Concurrency Lock:** Railway only downloads the track if and when the user actually chooses it. The `/api/stream/{track_id}` endpoint features an `asyncio.Lock` per track to prevent duplicate downloads and race conditions during simultaneous requests.
