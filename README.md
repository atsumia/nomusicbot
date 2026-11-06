# NoMusic Bot (@nomscbot)

Развёрнут на Instabox, машина `vanya-agent` (`m_agqzxzix6jgflu7f2lvxmwjsc4`).

- Web App / музыкальный API: https://18080-agqzxzix6jgflu7f2lvxmwjsc4.instabox.tech
- Приложение: `/data/nomusicbot/app`, SQLite: `/data/nomusicbot/data/database.db`.
- Python 3.11 в Docker, HTTPS webhook Telegram с проверкой `WEBHOOK_SECRET`.
- Настройки и ключи: `/data/nomusicbot/app/deployment.env` (0600, исключён из Git и Docker-образа).
- Docker автоматически поднимает контейнер после запуска машины и перезапускает при падении процесса.

На машине, из `/data/nomusicbot/app`:

```bash
bash deploy.sh
docker compose -p nomusicbot logs --tail 100 -f
docker compose -p nomusicbot restart
docker compose -p nomusicbot exec -T nomusicbot python -c "import sqlite3; src=sqlite3.connect('/app/data/database.db'); dst=sqlite3.connect('/app/data/database-backup.db'); src.backup(dst); dst.close()"
```

Внешний пинг выполняет GitHub Actions (`Instabox keepalive`) каждые 5 минут.
Входящие webhook-запросы Telegram также будят машину после простоя.
GitHub может задерживать расписание; в публичном репозитории расписания отключаются
после 60 дней без активности. Проверять состояние можно во вкладке Actions.

Instabox Free принудительно приостанавливает машину по лимиту непрерывной работы
(до 8 часов), затем вводит cooldown. Пинг не отменяет эти ограничения:
запросы во время cooldown получают 503, Telegram повторяет доставку после восстановления.
Для круглосуточной работы без обязательных пауз нужен платный тариф Instabox.

При переносе 6 ноября 2026 года сохранённая локальная база была пуста.
У Railway не было постоянного диска, а старые deployments удалены; истории
из их временной файловой системы в доступном источнике нет.
