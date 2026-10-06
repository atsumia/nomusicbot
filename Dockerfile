FROM python:3.11-slim
Системные пакеты: ffmpeg критически важен для yt-dlp (MP3 конвертация 320kbps)
RUN apt-get update && apt-get install -y --no-install-recommends 
ffmpeg 
gcc 
libjpeg-dev 
zlib1g-dev 
curl 
&& rm -rf /var/lib/apt/lists/*
WORKDIR /app
Копируем список зависимостей и устанавливаем
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && 
pip install --no-cache-dir -r requirements.txt
Копируем кодовую базу
COPY . .
Создаём каталог для постоянных данных (Volume)
RUN mkdir -p /app/data
Запуск бота
CMD ["python", "bot.py"]