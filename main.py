import asyncio
import logging
import json
import io
import time
import tracemalloc
import os
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, BufferedInputFile
from aiogram.filters import Command
from aiogram.utils.media_group import MediaGroupBuilder
from curl_cffi import requests
from PIL import Image, ImageDraw, ImageFont

# Вмикаємо відстеження виділення пам'яті
tracemalloc.start()

BOT_TOKEN = os.environ.get("BOT_TOKEN")

if not BOT_TOKEN:
    raise ValueError("Помилка: Токен бота не знайдено в змінних оточення!")

MY_GROUP = "GPV54.1"

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

keyboard = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="Графік (Княгині Інгігерди, 15)")],
        [KeyboardButton(text="🛠in progress")]
    ],
    resize_keyboard=True
)

def fetch_schedule_data():
    """Синхронна функція для алгоритмічного парсингу HTML-коду ДТЕК"""
    try:
        url = "https://www.dtek-kem.com.ua/ua/shutdowns"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
        }
        
        
        response = requests.get(url, headers=headers, impersonate="chrome110")

        if response.status_code != 200:
            return {"error": f"❌ Помилка доступу до сайту ДТЕК: {response.status_code}"}
            
        text = response.text
        
        if "Just a moment" in text or "cloudflare" in text.lower() or "challenge-platform" in text:
            return {"error": "❌ Cloudflare заблокував запит (вимагає перевірку браузера)."}

        search_key = "DisconSchedule.fact ="
        if search_key not in text:
            return {"error": "❌ Змінну не знайдено на сторінці."}

        js_code = text.split(search_key)[1]
        start_idx = js_code.find("{")
        
        if start_idx == -1:
            return {"error": "❌ Помилка: не знайдено початок JSON-об'єкта '{'."}

        brace_count = 0
        in_string = False
        escape = False
        end_idx = -1
        
        for i, char in enumerate(js_code[start_idx:]):
            if in_string:
                if escape:
                    escape = False
                elif char == '\\':
                    escape = True
                elif char == '"':
                    in_string = False
            else:
                if char == '"':
                    in_string = True
                elif char == '{':
                    brace_count += 1
                elif char == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end_idx = start_idx + i
                        break
                        
        if end_idx == -1:
            return {"error": "❌ Помилка: не знайдено кінець об'єкта '}'."}

        json_str = js_code[start_idx:end_idx+1]
        fact_data = json.loads(json_str)
        days_data = fact_data.get("data", {})

        if not days_data:
            return {"error": "⚠️ Графіки наразі порожні (відключень немає)."}

        parsed_schedules = {}
        for timestamp_str in sorted(days_data.keys()):
            group_schedule = days_data[timestamp_str].get(MY_GROUP)
            if not group_schedule:
                continue

            dt_utc = datetime.fromtimestamp(int(timestamp_str), timezone.utc)
            dt_kyiv = dt_utc + timedelta(hours=3)
            date_str = dt_kyiv.strftime("%d.%m.%Y")

            day_sched = {}
            for i in range(1, 26):
                day_sched[i] = group_schedule.get(str(i), "yes")
                
            parsed_schedules[date_str] = day_sched

        return parsed_schedules

    except Exception as e:
        return {"error": f"❌ Сталася помилка: {e}"}

def create_schedule_image(schedule):
    """Створює оптимізоване зображення з графіком відключень (без зайвого тексту)"""
    # Зменшено розмір полотна (з 640 до 485 у висоту) для економії оперативної пам'яті сервера
    img = Image.new('RGB', (390, 485), color='#FFFFFF')
    draw = ImageDraw.Draw(img)
    
    try:
        font_text = ImageFont.truetype("arial.ttf", 16)
    except:
        font_text = ImageFont.load_default()
    
    start_y = 15 # Відступ зверху тепер мінімальний
    row_h = 35
    col1_x = 20
    col2_x = 195
    time_w = 75
    stat_w = 75
    
    gray_color = "#D1D5DB"
    dark_gray = "#6B7280"
    header_color = "#F3F4F6"
    
    def draw_header(cx, cy):
        draw.rectangle([cx, cy, cx + time_w, cy + row_h], outline=gray_color, fill=header_color)
        draw.rectangle([cx + time_w, cy, cx + time_w + stat_w, cy + row_h], outline=gray_color, fill=header_color)
        draw.text((cx + 18, cy + 8), "Час", fill="#1F2937", font=font_text)
        
    def draw_cell(x, y, text, status):
        draw.rectangle([x, y, x + time_w, y + row_h], outline=gray_color, fill="white")
        draw.text((x + 13, y + 8), text, fill="black", font=font_text)
        
        sx = x + time_w
        draw.rectangle([sx, y, sx + stat_w, y + row_h], outline=gray_color, fill="white")
        
        if status == "no":
            draw.rectangle([sx, y, sx + stat_w, y + row_h], outline=gray_color, fill=gray_color)
            draw.line([sx+25, y+10, sx+stat_w-25, y+row_h-10], fill=dark_gray, width=3)
            draw.line([sx+stat_w-25, y+10, sx+25, y+row_h-10], fill=dark_gray, width=3)
        elif status == "first":
            draw.rectangle([sx, y, sx + stat_w/2, y + row_h], outline=gray_color, fill=gray_color)
        elif status == "second":
            draw.rectangle([sx + stat_w/2, y, sx + stat_w, y + row_h], outline=gray_color, fill=gray_color)
        elif status == "maybe":
            draw.rectangle([sx, y, sx + stat_w, y + row_h], outline=gray_color, fill="#FEF08A")
            
    draw_header(col1_x, start_y)
    draw_header(col2_x, start_y)
    
    start_y += row_h

    for i in range(1, 13):
        hour_str1 = f"{i-1:02d}-{(i):02d}"
        status1 = schedule.get(i, "yes")
        draw_cell(col1_x, start_y + (i-1)*row_h, hour_str1, status1)
        
        j = i + 12
        if j <= 24:
            hour_str2 = f"{j-1:02d}-{(j):02d}"
            status2 = schedule.get(j, "yes")
            draw_cell(col2_x, start_y + (i-1)*row_h, hour_str2, status2)
            
    bio = io.BytesIO()
    # optimize=True зменшить вагу фінального файлу перед надсиланням
    img.save(bio, format='PNG', optimize=True)
    bio.seek(0)
    return bio

@dp.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привіт! Я твій особистий бот для графіків.\nТисни на кнопки нижче ⬇️",
        reply_markup=keyboard
    )

@dp.message(F.text == "💡 Графік (Княгині Інгігерди, 15)")
async def send_schedule(message: Message):
    start_time = time.perf_counter()
    tracemalloc.clear_traces()

    wait_msg = await message.answer("🔄 Завантажую та малюю актуальний графік...")
    
    data = await asyncio.to_thread(fetch_schedule_data)
    
    if "error" in data:
        await wait_msg.edit_text(data["error"])
    elif not data:
        await wait_msg.edit_text("⚠️ Немає даних для вашої групи.")
    else:
        # Формуємо дати та підпис для повідомлення
        dates = list(data.keys())
        dates_str = ", ".join(dates)
        
        caption_text = (
            f"🗓 Графік на: {dates_str}\n\n"
        )

        if len(data) == 1:
            date_str = dates[0]
            sched = data[date_str]
            img_bytes = await asyncio.to_thread(create_schedule_image, sched)
            photo = BufferedInputFile(img_bytes.read(), filename="schedule.png")
            await message.answer_photo(photo=photo, caption=caption_text)
        else:
            # Для кількох днів легенда буде прикріплена лише до групи
            media_group = MediaGroupBuilder(caption=caption_text)
            for date_str, sched in data.items():
                img_bytes = await asyncio.to_thread(create_schedule_image, sched)
                photo = BufferedInputFile(img_bytes.read(), filename=f"schedule_{date_str}.png")
                media_group.add_photo(media=photo)
            await message.answer_media_group(media=media_group.build())

    await wait_msg.delete()

    end_time = time.perf_counter()
    current_mem, peak_mem = tracemalloc.get_traced_memory()
    
    logging.info("\n" + "="*45)
    logging.info("resourse stat:")
    logging.info(f"Time: {end_time - start_time:.3f} сек")
    logging.info(f"Ram: {current_mem / 1024 / 1024:.3f} MB")
    logging.info(f"max Ram: {peak_mem / 1024 / 1024:.3f} MB")
    logging.info("="*45 + "\n")

@dp.message(F.text == "🛠 Майбутня задача")
async def handle_future_task(message: Message):
    await message.answer("🚧 Ця функція знаходиться в розробці. Тут буде ваш новий функціонал!")

async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
