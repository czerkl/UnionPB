import asyncio
import io
import logging
import os
import sys
import time
from datetime import datetime

from aiogram import Bot, Dispatcher, types, BaseMiddleware, F
from aiogram.filters import Command, CommandObject
from aiogram.types import BufferedInputFile, ChatMemberUpdated
from aiogram.filters.chat_member_updated import ChatMemberUpdatedFilter, IS_NOT_MEMBER, MEMBER
from PIL import Image, ImageColor, ImageDraw
from aiohttp import web
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PORT = int(os.getenv("PORT", 10000))
DEV_NAME = "Czerkl"

if not TOKEN or not CHANNEL_ID:
    logging.critical("ОШИБКА: Проверь BOT_TOKEN и CHANNEL_ID в .env!")
    sys.exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()

CANVAS_SIZE = 1024
canvas = Image.new('RGB', (CANVAS_SIZE, CANVAS_SIZE), color='white')
canvas_lock = asyncio.Lock()

# Создаем обратный маппинг цветов (RGB -> Name) для команды /point
RGB_TO_NAME = {ImageColor.getrgb(name): name for name in ImageColor.colormap}

COMMANDS_LIST = (
    "🛠 <b>Инструментарий UnionPB:</b>\n"
    "• <code>/add цвет x y</code> — поставить точку\n"
    "• <code>/line цвет x1 y1 x2 y2</code> — провести линию\n"
    "• <code>/circle цвет x y r</code> — нарисовать круг\n"
    "• <code>/fill цвет x1 y1 x2 y2</code> — залить прямоугольник\n"
    "• <code>/point x y</code> — узнать цвет в координатах\n"
    "• <code>/zoom x y</code> — увеличить сектор 50x50\n"
    "• <code>/view</code> — показать весь холст"
)

# --- ЗАЩИТА ОТ СПАМА ---
class ThrottlingMiddleware(BaseMiddleware):
    def __init__(self, limit=0.6):
        self.last_time = {}
        self.limit = limit
        super().__init__()

    async def __call__(self, handler, event, data):
        if not event.from_user: return await handler(event, data)
        uid = event.from_user.id
        if uid in self.last_time and time.time() - self.last_time[uid] < self.limit:
            return 
        self.last_time[uid] = time.time()
        return await handler(event, data)

dp.message.middleware(ThrottlingMiddleware())

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def fix_y(y_user):
    return CANVAS_SIZE - 1 - int(y_user)

def is_valid_color(color):
    try:
        ImageColor.getrgb(color.lower())
        return True
    except:
        return False

async def send_canvas_photo(message, caption):
    """Отправка холста с тегом пользователя (HTML)"""
    async with canvas_lock:
        with io.BytesIO() as out:
            canvas.save(out, format="PNG")
            out.seek(0)
            photo = BufferedInputFile(out.read(), filename="canvas.png")
            # Тег пользователя через HTML
            user_tag = f'<a href="tg://user?id={message.from_user.id}">{message.from_user.full_name}</a>'
            full_caption = f"{user_tag}, {caption}"
            await message.answer_photo(photo=photo, caption=full_caption, parse_mode="HTML")

async def backup_to_channel(user_full_name, action_text):
    """Улучшенный бэкап"""
    try:
        async with canvas_lock:
            with io.BytesIO() as out:
                canvas.save(out, format="PNG")
                out.seek(0)
                file = BufferedInputFile(out.read(), filename="matrix.png")
                time_str = datetime.now().strftime('%M:%H')
                caption = (
                    f"Backup\n"
                    f"Юзер: {user_full_name}\n"
                    f"Data: {time_str}\n"
                    f"Что внес юзер: {action_text}"
                )
                await bot.send_document(CHANNEL_ID, file, caption=caption, disable_notification=True)
    except Exception as e:
        logging.error(f"Ошибка бэкапа: {e}")

async def load_last_canvas():
    global canvas
    try:
        async for msg in bot.get_chat_history(CHANNEL_ID, limit=20):
            if msg.document and msg.document.file_name == "matrix.png":
                file_info = await bot.get_file(msg.document.file_id)
                content = await bot.download_file(file_info.file_path)
                async with canvas_lock:
                    canvas = Image.open(content).convert('RGB')
                logging.info("Холст успешно восстановлен из облака.")
                return
    except Exception as e:
        logging.error(f"Ошибка восстановления: {e}")

# --- ОБРАБОТЧИКИ ---

@dp.my_chat_member(ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> MEMBER))
async def on_joined(event: ChatMemberUpdated):
    """Приветствие при добавлении в группу (HTML)"""
    welcome = (
        f"💎 <b>UnionPB v3.9 Custom Online</b>\n\n"
        f"Привет! Я — распределенный графический движок.\n"
        f"Рисуйте на общем холсте 1024x1024 прямо в этом чате!\n"
        f"Просто тегните меня или используйте команды.\n\n"
        f"{COMMANDS_LIST}"
    )
    await bot.send_message(event.chat.id, welcome, parse_mode="HTML")

@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome = f"💎 <b>UnionPB v3.9 Custom</b>\nКоординаты (0,0) — <b>снизу слева</b>.\n\n"
    await message.answer(welcome + COMMANDS_LIST, parse_mode="HTML")

@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    lines = message.text.split('\n')
    success = 0
    action_log = []
    
    async with canvas_lock:
        for i, line in enumerate(lines):
            parts = line.split()
            if i == 0: 
                parts = parts[1:]
                action_log = parts
            else:
                action_log.append(f"| {line}")

            if len(parts) != 3: continue
            try:
                color, x, y_raw = parts[0].lower(), int(parts[1]), int(parts[2])
                y = fix_y(y_raw)
                if 0 <= x < CANVAS_SIZE and 0 <= y < CANVAS_SIZE and is_valid_color(color):
                    canvas.putpixel((x, y), ImageColor.getrgb(color))
                    success += 1
            except: continue
    
    if success > 0:
        clean_action = " ".join(action_log)
        asyncio.create_task(backup_to_channel(message.from_user.full_name, clean_action))
        await send_canvas_photo(message, f"✅ Успешно нанесено пикселей: {success}")
    else:
        await message.answer(
            "❌ Ошибка! Используй формат:\n"
            "<code>red 500 500</code>\n"
            "(можно списком через перенос строки)", 
            parse_mode="HTML"
        )

@dp.message(Command("line"))
async def cmd_line(message: types.Message):
    try:
        p = message.text.split()
        color, x1, y1, x2, y2 = p[1].lower(), int(p[2]), int(p[3]), int(p[4]), int(p[5])
        if not is_valid_color(color): 
            return await message.answer("❌ Цвет не валиден.", parse_mode="HTML")

        async with canvas_lock:
            draw = ImageDraw.Draw(canvas)
            draw.line([x1, fix_y(y1), x2, fix_y(y2)], fill=ImageColor.getrgb(color), width=1)
        
        asyncio.create_task(backup_to_channel(message.from_user.full_name, " ".join(p[1:])))
        await send_canvas_photo(message, f"📏 Линия ({color}) готова.")
    except:
        await message.answer("Используй: <code>/line color x1 y1 x2 y2</code>", parse_mode="HTML")

@dp.message(Command("circle"))
async def cmd_circle(message: types.Message):
    try:
        p = message.text.split()
        color, x, y, r = p[1].lower(), int(p[2]), int(p[3]), int(p[4])
        if not is_valid_color(color): 
            return await message.answer("❌ Цвет не валиден.", parse_mode="HTML")
        
        yp = fix_y(y)
        async with canvas_lock:
            draw = ImageDraw.Draw(canvas)
            draw.ellipse([x-r, yp-r, x+r, yp+r], outline=ImageColor.getrgb(color))
            
        asyncio.create_task(backup_to_channel(message.from_user.full_name, " ".join(p[1:])))
        await send_canvas_photo(message, f"⭕ Окружность ({color}) отрисована.")
    except:
        await message.answer("Используй: <code>/circle color x y radius</code>", parse_mode="HTML")

@dp.message(Command("fill"))
async def cmd_fill(message: types.Message):
    try:
        p = message.text.split()
        color, x1, y1, x2, y2 = p[1].lower(), int(p[2]), int(p[3]), int(p[4]), int(p[5])
        
        xmin, xmax = sorted([x1, x2])
        ymin, ymax = sorted([fix_y(y1), fix_y(y2)])

        async with canvas_lock:
            draw = ImageDraw.Draw(canvas)
            draw.rectangle([xmin, ymin, xmax, ymax], fill=ImageColor.getrgb(color))
        
        asyncio.create_task(backup_to_channel(message.from_user.full_name, " ".join(p[1:])))
        await send_canvas_photo(message, f"✅ Область залита цветом {color}.")
    except:
        await message.answer("Используй: <code>/fill color x1 y1 x2 y2</code>", parse_mode="HTML")

@dp.message(Command("point"))
async def cmd_point(message: types.Message):
    try:
        parts = message.text.split()
        x, y_raw = int(parts[1]), int(parts[2])
        yp = fix_y(y_raw)
        
        rgb = canvas.getpixel((x, yp))
        color_name = RGB_TO_NAME.get(rgb, f"rgb{rgb}")
        
        user_tag = f'<a href="tg://user?id={message.from_user.id}">{message.from_user.full_name}</a>'
        await message.answer(f"📍 {user_tag}, цвет в ({x}, {y_raw}): <code>{color_name}</code>", parse_mode="HTML")
    except:
        await message.answer("Используй: <code>/point x y</code>", parse_mode="HTML")

@dp.message(Command("zoom"))
async def cmd_zoom(message: types.Message):
    try:
        parts = message.text.split()
        x_in, y_in = int(parts[1]), int(parts[2])
        yp = fix_y(y_in)
        
        box = (max(0, x_in-50), max(0, yp-50), min(1024, x_in+50), min(1024, yp+50))
        zoomed = canvas.crop(box).resize((500, 500), resample=Image.NEAREST)
        
        with io.BytesIO() as out:
            zoomed.save(out, format="PNG")
            out.seek(0)
            user_tag = f'<a href="tg://user?id={message.from_user.id}">{message.from_user.full_name}</a>'
            await message.answer_photo(
                photo=BufferedInputFile(out.read(), filename="zoom.png"), 
                caption=f"🔍 {user_tag}, сектор {x_in}:{y_in}",
                parse_mode="HTML"
            )
    except:
        await message.answer("Используй: <code>/zoom x y</code>", parse_mode="HTML")

@dp.message(Command("view"))
async def cmd_view(message: types.Message):
    await send_canvas_photo(message, "текущее состояние полотна.")

# --- СЕРВЕР ---

async def main():
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    app.router.add_get("/", lambda r: web.Response(text="UnionPB Lux Status: Online"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, '0.0.0.0', PORT).start()

    await load_last_canvas()
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Остановка бота...")
