import os
import asyncio
import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageFilter

WIDTH, HEIGHT = 1000, 500

# Цвета в стиле Apple Music (светлая тема)
APPLE_BG = (245, 245, 247)
APPLE_CARD_BG = (255, 255, 255)
APPLE_TEXT_DARK = (29, 29, 31)
APPLE_TEXT_GRAY = (134, 134, 139)
APPLE_CORAL = (250, 45, 72)

# Прямые ссылки на шрифты (чтобы не загружать их вручную с телефона)
FONT_BOLD_URL = "https://github.com/googlefonts/montserrat/raw/main/fonts/ttf/Montserrat-Bold.ttf"
FONT_REG_URL = "https://github.com/googlefonts/montserrat/raw/main/fonts/ttf/Montserrat-Regular.ttf"

async def download_file(url, filename):
    """Скачивает файл, если его еще нет локально."""
    if not os.path.exists(filename):
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as resp:
                if resp.status == 200:
                    with open(filename, 'wb') as f:
                        f.write(await resp.read())

async def ensure_fonts():
    """Проверяет и скачивает нужные шрифты асинхронно."""
    await asyncio.gather(
        download_file(FONT_BOLD_URL, "Montserrat-Bold.ttf"),
        download_file(FONT_REG_URL, "Montserrat-Regular.ttf")
    )

def draw_rounded_rect_with_shadow(img, box, radius, fill, shadow_color=(0,0,0,30), shadow_blur=15, shadow_offset=(0, 10)):
    """Рисует плашку с закругленными углами и объемной мягкой тенью."""
    # Тень
    shadow = Image.new('RGBA', img.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_box = [box[0] + shadow_offset[0], box[1] + shadow_offset[1], 
                  box[2] + shadow_offset[0], box[3] + shadow_offset[1]]
    shadow_draw.rounded_rectangle(shadow_box, radius=radius, fill=shadow_color)
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
    img.alpha_composite(shadow)
    
    # Основная плашка
    main_draw = ImageDraw.Draw(img)
    main_draw.rounded_rectangle(box, radius=radius, fill=fill)
    return img

def ms_to_min_sec(ms):
    if not ms: return "0:00"
    seconds = int((ms / 1000) % 60)
    minutes = int((ms / (1000 * 60)) % 60)
    return f"{minutes}:{seconds:02d}"

async def generate_apple_card(artist_name: str, tracks: list, photo_url: str = None, output_path: str = "/tmp/artist_card.png"):
    """Генерирует карточку артиста в стиле Apple Music."""
    # Убеждаемся, что шрифты скачаны
    await ensure_fonts()
    
    img = Image.new("RGBA", (WIDTH, HEIGHT), APPLE_BG)
    draw = ImageDraw.Draw(img)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    try:
        font_title = ImageFont.truetype("Montserrat-Bold.ttf", 52)
        font_sub = ImageFont.truetype("Montserrat-Bold.ttf", 18)
        font_track = ImageFont.truetype("Montserrat-Bold.ttf", 22)
        font_time = ImageFont.truetype("Montserrat-Regular.ttf", 20)
    except:
        font_title = font_sub = font_track = font_time = ImageFont.load_default()

    # --- 1. ЛЕВАЯ ЧАСТЬ: ФОТО АРТИСТА ---
    photo_box = [40, 40, 390, 460] # Размер 350x420
    photo_radius = 24
    
    # Подложка-тень для фото
    draw_rounded_rect_with_shadow(img, photo_box, photo_radius, APPLE_CARD_BG, shadow_blur=20)
    
    photo_raw_path = "/tmp/artist_photo_raw.jpg"
    photo_ready = False

    if photo_url:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(photo_url) as resp:
                    if resp.status == 200:
                        raw_data = await resp.read()
                        with open(photo_raw_path, "wb") as f:
                            f.write(raw_data)
                        photo_ready = True
        except Exception:
            pass

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
                
                # Маска скругления для фото
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

    # --- 2. ПРАВАЯ ЧАСТЬ: ЗАГОЛОВКИ И ТРЕКИ ---
    text_x = 440
    
    # Заголовок
    draw.text((text_x, 45), "ГЛАВНЫЕ ТРЕКИ", fill=APPLE_CORAL, font=font_sub)
    
    # Имя артиста (обрезаем, если слишком длинное)
    display_name = artist_name.upper()
    if len(display_name) > 16:
        display_name = display_name[:14] + "..."
    draw.text((text_x, 70), display_name, fill=APPLE_TEXT_DARK, font=font_title)
    
    # Линия-разделитель
    draw.line([(text_x, 140), (950, 140)], fill=(220, 220, 225, 255), width=2)
    
    # Список треков
    y = 160
    for idx, t in enumerate(tracks[:5], 1):
        # Плашка трека с мягкой тенью
        draw_rounded_rect_with_shadow(img, [text_x, y, 950, y+50], radius=12, 
                                      fill=APPLE_CARD_BG, shadow_blur=8, shadow_offset=(0, 4), shadow_color=(0,0,0,12))
        
        # Индекс
        draw.text((text_x + 15, y + 12), f"{idx:02d}", fill=APPLE_TEXT_GRAY, font=font_time)
        
        # Название трека
        title = t.get('title', 'Без названия')
        if len(title) > 28:
            title = title[:25] + "..."
        draw.text((text_x + 60, y + 10), title, fill=APPLE_TEXT_DARK, font=font_track)
        
        # Длительность
        dur = ms_to_min_sec(t.get('duration_ms', 0))
        draw.text((885, y + 12), dur, fill=APPLE_CORAL, font=font_time)
        
        y += 65

    img.convert("RGB").save(output_path, quality=95)
    return output_path
