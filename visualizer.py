import os
import asyncio
import aiohttp
import uuid
import urllib.parse
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1000, 500

# Цвета в стиле Apple Music (светлая тема)
APPLE_BG = (245, 245, 247, 255)
APPLE_CARD_BG = (255, 255, 255, 255)
APPLE_TEXT_DARK = (29, 29, 31, 255)
APPLE_TEXT_GRAY = (134, 134, 139, 255)
APPLE_CORAL = (250, 45, 72, 255)

FONT_BOLD_URL = "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Bold.ttf"
FONT_REG_URL = "https://github.com/googlefonts/roboto/raw/main/src/hinted/Roboto-Regular.ttf"

FONT_BOLD_PATH = "/tmp/Roboto-Bold.ttf"
FONT_REG_PATH = "/tmp/Roboto-Regular.ttf"

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}

async def download_file(url, filename):
    if not os.path.exists(filename):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=HEADERS) as resp:
                    if resp.status == 200:
                        data = await resp.read()
                        with open(filename, 'wb') as f:
                            f.write(data)
        except Exception as e:
            print(f"Ошибка скачивания шрифта: {e}")

async def ensure_fonts():
    await asyncio.gather(
        download_file(FONT_BOLD_URL, FONT_BOLD_PATH),
        download_file(FONT_REG_URL, FONT_REG_PATH)
    )

def draw_rounded_rect_with_shadow(img, box, radius, fill, shadow_color=(0,0,0,30), shadow_blur=15, shadow_offset=(0, 10)):
    shadow = Image.new('RGBA', img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_box = [box[0] + shadow_offset[0], box[1] + shadow_offset[1], 
                  box[2] + shadow_offset[0], box[3] + shadow_offset[1]]
    shadow_draw.rounded_rectangle(shadow_box, radius=radius, fill=shadow_color)
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
    img.alpha_composite(shadow)
    
    main_draw = ImageDraw.Draw(img)
    main_draw.rounded_rectangle(box, radius=radius, fill=fill)
    return img

def ms_to_min_sec(ms):
    if not ms: return "0:00"
    seconds = int((ms / 1000) % 60)
    minutes = int((ms / (1000 * 60)) % 60)
    return f"{minutes}:{seconds:02d}"

async def generate_apple_card(artist_name: str, tracks: list, photo_url: str = None, output_path: str = None):
    uid = str(uuid.uuid4())
    if not output_path:
        output_path = f"/tmp/artist_card_{uid}.png"
        
    await ensure_fonts()
    
    img = Image.new("RGBA", (WIDTH, HEIGHT), APPLE_BG)
    draw = ImageDraw.Draw(img)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        font_title = ImageFont.truetype(FONT_BOLD_PATH, 52)
        font_sub = ImageFont.truetype(FONT_BOLD_PATH, 18)
        font_track = ImageFont.truetype(FONT_BOLD_PATH, 22)
        font_time = ImageFont.truetype(FONT_REG_PATH, 20)
    except Exception:
        font_title = font_sub = font_track = font_time = ImageFont.load_default()

    # --- ЛЕВАЯ ЧАСТЬ: ФОТО АРТИСТА ---
    photo_box = [40, 40, 390, 460]
    photo_radius = 24
    draw_rounded_rect_with_shadow(img, photo_box, photo_radius, APPLE_CARD_BG, shadow_blur=20)
    
    photo_raw_path = f"/tmp/artist_photo_{uid}.jpg"
    photo_ready = False

    # 1. Сначала пробуем скачать фото из Яндекса
    if photo_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(photo_url, headers=HEADERS) as resp:
                    if resp.status == 200:
                        raw_data = await resp.read()
                        with open(photo_raw_path, "wb") as f:
                            f.write(raw_data)
                        photo_ready = True
        except Exception:
            pass

    # 2. ФОЛЛБЭК: Если Яндекс заблокировал (или фото нет), берем обложку из открытого API iTunes (Apple Music)
    if not photo_ready and artist_name:
        try:
            safe_term = urllib.parse.quote(artist_name)
            itunes_url = f"https://itunes.apple.com/search?term={safe_term}&entity=song&limit=1"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(itunes_url) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        if data.get('results'):
                            # Получаем картинку и меняем размер 100x100 на высокое разрешение 600x600
                            cover_url = data['results'][0].get('artworkUrl100', '').replace('100x100bb', '600x600bb')
                            if cover_url:
                                async with session.get(cover_url) as img_resp:
                                    if img_resp.status == 200:
                                        raw_data = await img_resp.read()
                                        with open(photo_raw_path, "wb") as f:
                                            f.write(raw_data)
                                        photo_ready = True
        except Exception as e:
            print(f"iTunes fallback error: {e}")

    # 3. Вставляем готовое фото на карточку
    if photo_ready:
        try:
            with Image.open(photo_raw_path) as avatar:
                avatar = avatar.convert("RGBA")
                aw, ah = avatar.size
                target_ratio = 350 / 420
                current_ratio = aw / ah
                if current_ratio > target_ratio:
                    new_w = int(ah * target_ratio)
                    left = (aw - new_w) / 2
                    avatar = avatar.crop((left, 0, left + new_w, ah))
                else:
                    new_h = int(aw / target_ratio)
                    top = (ah - new_h) / 2
                    avatar = avatar.crop((0, top, aw, top + new_h))
                
                avatar = avatar.resize((350, 420), Image.LANCZOS)
                
                mask = Image.new("L", (350, 420), 0)
                mask_draw = ImageDraw.Draw(mask)
                mask_draw.rounded_rectangle([0, 0, 350, 420], radius=photo_radius, fill=255)
                
                img.paste(avatar, (40, 40), mask)
        except Exception:
            draw.text((150, 230), "NO PHOTO", fill=APPLE_TEXT_GRAY, font=font_title)
        finally:
            if os.path.exists(photo_raw_path):
                os.remove(photo_raw_path)
    else:
        draw.text((150, 230), "ARTIST", fill=APPLE_TEXT_GRAY, font=font_title)

    # --- ПРАВАЯ ЧАСТЬ: ЗАГОЛОВКИ И ТРЕКИ ---
    text_x = 440
    draw.text((text_x, 45), "ГЛАВНЫЕ ТРЕКИ", fill=APPLE_CORAL, font=font_sub)
    
    display_name = artist_name.upper() if artist_name else "ИСПОЛНИТЕЛЬ"
    if len(display_name) > 16:
        display_name = display_name[:14] + "..."
    draw.text((text_x, 70), display_name, fill=APPLE_TEXT_DARK, font=font_title)
    
    draw.line([(text_x, 140), (950, 140)], fill=(220, 220, 225, 255), width=2)
    
    y = 160
    for idx, t in enumerate(tracks[:5], 1):
        draw_rounded_rect_with_shadow(img, [text_x, y, 950, y+50], radius=12, 
                                      fill=APPLE_CARD_BG, shadow_blur=8, shadow_offset=(0, 4), shadow_color=(0,0,0,12))
        
        draw.text((text_x + 15, y + 12), f"{idx:02d}", fill=APPLE_TEXT_GRAY, font=font_time)
        
        title = t.get('title', 'Без названия')
        if len(title) > 28:
            title = title[:25] + "..."
        draw.text((text_x + 60, y + 10), title, fill=APPLE_TEXT_DARK, font=font_track)
        
        ms = t.get('duration_ms') or (t.get('duration', 0) * 1000)
        dur = ms_to_min_sec(ms)
        
        draw.text((885, y + 12), dur, fill=APPLE_CORAL, font=font_time)
        
        y += 65

    img.convert("RGB").save(output_path, quality=95)
    return output_path
