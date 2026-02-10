import asyncio
import io
import logging
import os
import sys
import time
from datetime import datetime

from aiogram import Bot, Dispatcher, types, BaseMiddleware
from aiogram.filters import Command
from aiogram.types import BufferedInputFile
from PIL import Image, ImageColor, ImageDraw
from aiohttp import web
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PORT = int(os.getenv("PORT", 10000))
DEV_NAME = "Czerkl" # Имя автора для публичных команд

if not TOKEN or not CHANNEL_ID:
    logging.critical("ОШИБКА: Проверь BOT_TOKEN и CHANNEL_ID в .env!")
    sys.exit(1)

# Инициализация бота и диспетчера
bot = Bot(token=TOKEN)
dp = Dispatcher()

# Параметры холста 1024x1024
CANVAS_SIZE = 1024
canvas = Image.new('RGB', (CANVAS_SIZE, CANVAS_SIZE), color='white')
canvas_lock = asyncio.Lock() # Защита от одновременного доступа к холсту

# --- ТЕКСТОВЫЕ БЛОКИ ---
COMMANDS_LIST = (
    "🛠 **Инструментарий UnionPB:**\n"
    "• `/add цвет x y` — поставить точку (поддерживает список)\n"
    "• `/line цвет x1 y1 x2 y2` — провести линию\n"
    "• `/circle цвет x y r` — нарисовать круг\n"
    "• `/fill цвет x1 y1 x2 y2` — залить прямоугольник\n"
    "• `/point x y` — узнать цвет в координатах\n"
    "• `/zoom x y` — увеличить сектор 50x50\n"
    "• `/view` — показать весь холст"
)

# --- ЗАЩИТА ОТ СПАМА (Middleware) ---
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=0.6):
        self.last_time = {}
        self.limit = limit
        super().__init__()

    async def __call__(self, handler, event, data):
        uid = event.from_user.id
        if uid in self.last_time and time.time() - self.last_time[uid] < self.limit:
            return # Игнорируем слишком частые запросы
        self.last_time[uid] = time.time()
        return await handler(event, data)

dp.message.middleware(ThrottlingMiddleware())

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def fix_y(y_user):
    """Инверсия Y: (0,0) становится внизу слева"""
    return CANVAS_SIZE - 1 - int(y_user)

def is_valid_color(color):
    """Проверка цвета на валидность для Pillow"""
    try:
        ImageColor.getrgb(color)
        return True
    except:
        return False

async def send_canvas_photo(message, caption):
    """Безопасная отправка текущего состояния холста"""
    async with canvas_lock:
        with io.BytesIO() as out:
            canvas.save(out, format="PNG")
            out.seek(0)
            photo = BufferedInputFile(out.read(), filename="canvas.png")
            await message.answer_photo(photo=photo, caption=caption, parse_mode="Markdown")

async def backup_to_channel():
    """Фоновый бэкап в канал"""
    try:
        async with canvas_lock:
            with io.BytesIO() as out:
                canvas.save(out, format="PNG")
                out.seek(0)
                file = BufferedInputFile(out.read(), filename="matrix.png")
                await bot.send_document(
                    CHANNEL_ID, 
                    file, 
                    caption=f"System Snapshot | v3.8 Lux | {datetime.now().strftime('%H:%M:%S')}", 
                    disable_notification=True
                )
    except Exception as e:
        logging.error(f"Ошибка бэкапа: {e}")

async def load_last_canvas():
    """Загрузка последнего холста при перезапуске сервера"""
    global canvas
    try:
        async for msg in bot.get_chat_history(CHANNEL_ID, limit=10):
            if msg.document and msg.document.file_name == "matrix.png":
                file_info = await bot.get_file(msg.document.file_id)
                content = await bot.download_file(file_info.file_path)
                async with canvas_lock:
                    canvas = Image.open(content).convert('RGB')
                logging.info("Холст успешно восстановлен.")
                return
    except Exception as e:
        logging.error(f"Ошибка восстановления: {e}")

# --- ОБРАБОТЧИКИ КОМАНД ---

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Приветствие как в v3.7"""
    welcome = (
        f"💎 **UnionPB v3.8 Lux Online**\n\n"
        f"Координаты (0,0) — **снизу слева**.\n"
        f"Разработчик: `{DEV_NAME}`\n\n"
    )
    await message.answer(welcome + COMMANDS_LIST, parse_mode="Markdown")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Список команд"""
    await message.answer(COMMANDS_LIST, parse_mode="Markdown")

@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    """Многострочное добавление точек из v3.7"""
    lines = message.text.split('\n')
    success = 0
    async with canvas_lock:
        for i, line in enumerate(lines):
            parts = line.split()
            if i == 0: parts = parts[1:] # Убираем саму команду /add
            if len(parts) != 3: continue
            try:
                color, x, y_raw = parts[0], int(parts[1]), int(parts[2])
                y = fix_y(y_raw)
                if 0 <= x < CANVAS_SIZE and 0 <= y < CANVAS_SIZE and is_valid_color(color):
                    canvas.putpixel((x, y), ImageColor.getrgb(color))
                    success += 1
            except: continue
    
    if success > 0:
        asyncio.create_task(backup_to_channel())
        await message.answer(f"✅ Успешно нанесено пикселей: {success}")
    else:
        await message.answer("❌ Ошибка! Пример: `/add red 500 500` (можно списком)")

@dp.message(Command("line"))
async def cmd_line(message: types.Message):
    """Отрисовка линии"""
    try:
        p = message.text.split()
        color, x1, y1, x2, y2 = p[1], int(p[2]), int(p[3]), int(p[4]), int(p[5])
        if not is_valid_color(color): return await message.answer("❌ Цвет не валиден.")

        async with canvas_lock:
            draw = ImageDraw.Draw(canvas)
            draw.line([x1, fix_y(y1), x2, fix_y(y2)], fill=ImageColor.getrgb(color), width=1)
        
        asyncio.create_task(backup_to_channel())
        await send_canvas_photo(message, f"📏 Линия ({color}) готова.")
    except:
        await message.answer("Используй: `/line color x1 y1 x2 y2`")

@dp.message(Command("circle"))
async def cmd_circle(message: types.Message):
    """Отрисовка круга из v3.7"""
    try:
        p = message.text.split()
        color, x, y, r = p[1], int(p[2]), int(p[3]), int(p[4])
        if not is_valid_color(color): return await message.answer("❌ Цвет не валиден.")
        
        yp = fix_y(y)
        async with canvas_lock:
            draw = ImageDraw.Draw(canvas)
            draw.ellipse([x-r, yp-r, x+r, yp+r], outline=ImageColor.getrgb(color))
            
        asyncio.create_task(backup_to_channel())
        await send_canvas_photo(message, f"⭕ Окружность ({color}) отрисована.")
    except:
        await message.answer("Используй: `/circle color x y radius`")

@dp.message(Command("fill"))
async def cmd_fill(message: types.Message):
    """Заливка области"""
    try:
        p = message.text.split()
        color, x1, y1, x2, y2 = p[1], int(p[2]), int(p[3]), int(p[4]), int(p[5])
        
        xmin, xmax = sorted([x1, x2])
        ymin, ymax = sorted([fix_y(y1), fix_y(y2)])

        async with canvas_lock:
            draw = ImageDraw.Draw(canvas)
            draw.rectangle([xmin, ymin, xmax, ymax], fill=ImageColor.getrgb(color))
        
        asyncio.create_task(backup_to_channel())
        await send_canvas_photo(message, f"✅ Область залита цветом {color}.")
    except:
        await message.answer("Используй: `/fill color x1 y1 x2 y2`")

@dp.message(Command("point"))
async def cmd_point(message: types.Message):
    """Узнать цвет точки"""
    try:
        _, x, y_raw = message.text.split()
        x, yp = int(x), fix_y(y_raw)
        color_rgb = canvas.getpixel((x, yp))
        await message.answer(f"📍 Цвет в ({x}, {y_raw}): `rgb{color_rgb}`", parse_mode="Markdown")
    except:
        await message.answer("Используй: `/point x y`")

@dp.message(Command("zoom"))
async def cmd_zoom(message: types.Message):
    """Увеличение сектора"""
    try:
        _, x_in, y_in = message.text.split()
        x, yp = int(x_in), fix_y(y_in)
        
        # Обрезаем 100x100 и увеличиваем до 500x500
        box = (max(0, x-50), max(0, yp-50), min(1024, x+50), min(1024, yp+50))
        zoomed = canvas.crop(box).resize((500, 500), resample=Image.NEAREST)
        
        with io.BytesIO() as out:
            zoomed.save(out, format="PNG")
            out.seek(0)
            await message.answer_photo(
                photo=BufferedInputFile(out.read(), filename="zoom.png"), 
                caption=f"🔍 Сектор {x_in}:{y_in}"
            )
    except:
        await message.answer("Используй: `/zoom x y`")

@dp.message(Command("view"))
async def cmd_view(message: types.Message):
    """Показать весь холст"""
    await send_canvas_photo(message, f"🖼 **UnionPB v3.8 Lux**\nEngine by `{DEV_NAME}`")

# --- СЕРВЕР ---

async def main():
    logging.basicConfig(level=logging.INFO)
    
    # HTTP-сервер для Render
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="UnionPB Lux Status: Online"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    # Загрузка бэкапа и запуск
    await load_last_canvas()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Остановка бота...")