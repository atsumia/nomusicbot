FROM python:3.11-slim

# Устанавливаем системные пакеты и ffmpeg
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg git && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Копируем зависимости и устанавливаем
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копируем исходники бота
COPY . .

# Запуск бота
CMD ["python", "bot.py"]
