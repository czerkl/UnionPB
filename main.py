import asyncio
import html
import io
import logging
import os
import sys
import time
from datetime import datetime, timezone

from aiogram import BaseMiddleware, Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.filters.chat_member_updated import (
    IS_NOT_MEMBER,
    MEMBER,
    ChatMemberUpdatedFilter,
)
from aiogram.types import BufferedInputFile, ChatMemberUpdated
from aiohttp import web
from dotenv import load_dotenv
from PIL import Image, ImageColor, ImageDraw

# Загружаем переменные из .env
load_dotenv()

# --- КОНФИГУРАЦИЯ ---
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = os.getenv("CHANNEL_ID")
PORT = int(os.getenv("PORT", 10000))
DEV_NAME = "Mildred"

if not TOKEN or not CHANNEL_ID:
    logging.critical("ОШИБКА: Проверь BOT_TOKEN и CHANNEL_ID в .env!")
    sys.exit(1)

bot = Bot(token=TOKEN)
dp = Dispatcher()

CANVAS_SIZE = 248
IMAGE_STAMP_SIZE = 32
canvas = Image.new("RGB", (CANVAS_SIZE, CANVAS_SIZE), color="white")
canvas_lock = asyncio.Lock()

# Создаем обратный маппинг цветов (RGB -> Name) для команды /point
RGB_TO_NAME = {ImageColor.getrgb(name): name for name in ImageColor.colormap}

# Компактные пиксельные иконки ('.' — прозрачный фон)
ICONS: dict[str, tuple[dict[str, str], list[str]]] = {
    "smile": (
        {"Y": "yellow", "B": "black", "R": "red"},
        [
            "..YYYYYY..",
            ".YYYYYYYY.",
            "YY.YY..YY.",
            "YYYYYYYYYY",
            "YY.YYYY.YY",
            "YY..YY..YY",
            "YY.RRRR.YY",
            "YY..RR..YY",
            ".YYYYYYYY.",
            "..YYYYYY..",
        ],
    ),
    "heart": (
        {"R": "red", "W": "white", "D": "darkred"},
        [
            ".RRR..RRR.",
            "RWRRR.DRRR",
            "RRRRRRRRRR",
            "RRRRRRRRDR",
            ".RRRRRRDR.",
            "..RRRRDR..",
            "...RRDR...",
            "....DR....",
        ],
    ),
    "star": (
        {"Y": "yellow", "O": "orange"},
        [
            "....YY....",
            "....YY....",
            "..YYYYYY..",
            "YYYYYYYYYY",
            ".YYYYYYYY.",
            "..YYYYYY..",
            "..YY..YY..",
            ".YY....YY.",
            "OO......OO",
        ],
    ),
    "check": (
        {"G": "limegreen", "D": "darkgreen"},
        [
            "........GG",
            ".......GGD",
            "......GGD.",
            ".....GGD..",
            "GG..GGD...",
            "DGGGGD....",
            ".DGGD.....",
            "..DD......",
        ],
    ),
    "cross": (
        {"R": "crimson", "D": "darkred"},
        [
            "RR......RR",
            "DRR....RRD",
            ".DRR..RRD.",
            "..DRRRRD..",
            "...DRRD...",
            "..DRRRRD..",
            ".DRR..RRD.",
            "DRR....RRD",
            "RR......RR",
        ],
    ),
    "arrow_up": (
        {"C": "cyan", "B": "deepskyblue"},
        [
            "....CC....",
            "...CCCC...",
            "..CCBBCC..",
            ".CC.BB.CC.",
            "....BB....",
            "....BB....",
            "....BB....",
            "....BB....",
        ],
    ),
    "arrow_down": (
        {"C": "cyan", "B": "deepskyblue"},
        [
            "....BB....",
            "....BB....",
            "....BB....",
            "....BB....",
            ".CC.BB.CC.",
            "..CCBBCC..",
            "...CCCC...",
            "....CC....",
        ],
    ),
}

COMMANDS_LIST = (
    "🛠 <b>Инструментарий UnionPB:</b>\n"
    "• <code>/add цвет x y</code> — поставить точку (0-247)\n"
    "• <code>/line цвет x1 y1 x2 y2</code> — провести линию\n"
    "• <code>/circle цвет x y r</code> — нарисовать круг\n"
    "• <code>/fill цвет x1 y1 x2 y2</code> — залить прямоугольник\n"
    "• <code>/image x y</code> — вставить фото 32x32 (реплай или подпись к фото)\n"
    "• <code>/icon имя x y</code> — поставить иконку\n"
    "• <code>/iconlist</code> — список доступных иконок\n"
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
        if not event.from_user:
            return await handler(event, data)
        uid = event.from_user.id
        if (
            uid in self.last_time
            and time.time() - self.last_time[uid] < self.limit
        ):
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
    except Exception:
        return False


def build_canvas_png_bytes(img: Image.Image) -> bytes:
    """Сериализует переданный Image в PNG bytes в памяти и сразу освобождает буфер."""
    buf = io.BytesIO()
    try:
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()
    finally:
        buf.close()


async def send_canvas_photo(message, caption):
    """Отправка холста с тегом пользователя (HTML)"""
    async with canvas_lock:
        png_bytes = build_canvas_png_bytes(canvas)
    photo = BufferedInputFile(png_bytes, filename="canvas.png")
    safe_name = html.escape(message.from_user.full_name)
    user_tag = f'<a href="tg://user?id={message.from_user.id}">{safe_name}</a>'
    full_caption = f"{user_tag}, {caption}"
    await message.answer_photo(
        photo=photo, caption=full_caption, parse_mode="HTML"
    )
    del png_bytes, photo


async def backup_to_channel(user_full_name, action_text):
    """Профессиональный лог и бэкап в приватный канал на английском"""
    try:
        async with canvas_lock:
            png_bytes = build_canvas_png_bytes(canvas)

        file = BufferedInputFile(png_bytes, filename="matrix.png")
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        safe_user = html.escape(user_full_name)
        safe_action = html.escape(action_text)
        caption = (
            "<b>UnionPB Audit Log</b>\n"
            f"<b>User:</b> {safe_user}\n"
            f"<b>Timestamp:</b> {ts}\n"
            f"<b>Action:</b> <code>{safe_action}</code>\n"
            f"<b>Canvas:</b> {CANVAS_SIZE}x{CANVAS_SIZE}"
        )
        await bot.send_document(
            CHANNEL_ID,
            file,
            caption=caption,
            parse_mode="HTML",
            disable_notification=True,
        )
        del png_bytes, file
    except Exception as e:
        logging.error(f"Ошибка бэкапа: {e}")


async def load_last_canvas():
    global canvas
    try:
        if hasattr(bot, "get_chat_history"):
            async for msg in bot.get_chat_history(CHANNEL_ID, limit=20):
                if msg.document and msg.document.file_name == "matrix.png":
                    file_info = await bot.get_file(msg.document.file_id)
                    buf = io.BytesIO()
                    try:
                        await bot.download_file(file_info.file_path, destination=buf)
                        buf.seek(0)
                        with Image.open(buf) as loaded:
                            restored = loaded.convert("RGB")
                        async with canvas_lock:
                            old_canvas = canvas
                            canvas = restored
                            del old_canvas
                        logging.info("Холст успешно восстановлен из облака.")
                    finally:
                        buf.close()
                    return
    except Exception as e:
        logging.error(f"Ошибка восстановления: {e}")


def _extract_target_photo(message: types.Message) -> types.PhotoSize | None:
    """Берёт фото из самого сообщения или из сообщения, на которое сделан reply."""
    if message.photo:
        return message.photo[-1]
    if message.reply_to_message and message.reply_to_message.photo:
        return message.reply_to_message.photo[-1]
    return None


# --- ОБРАБОТЧИКИ ---


@dp.my_chat_member(
    ChatMemberUpdatedFilter(member_status_changed=IS_NOT_MEMBER >> MEMBER)
)
async def on_joined(event: ChatMemberUpdated):
    """Приветствие при добавлении в группу (HTML)"""
    welcome = (
        f"💎 <b>UnionPB v3.9 Online</b>\n\n"
        f"Привет! Я — распределенный графический движок.\n"
        f"Рисуйте на общем холсте 248x248 прямо в этом чате!\n"
        f"Просто тегните меня или используйте команды.\n\n"
        f"{COMMANDS_LIST}"
    )
    await bot.send_message(event.chat.id, welcome, parse_mode="HTML")


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    welcome = (
        f"💎 <b>UnionPB v3.9</b>\nКоординаты (0,0) — <b>снизу слева</b> (0-247).\n\n"
    )
    await message.answer(welcome + COMMANDS_LIST, parse_mode="HTML")


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    await message.answer(COMMANDS_LIST, parse_mode="HTML")


@dp.message(Command("iconlist"))
async def cmd_iconlist(message: types.Message):
    """Список доступных иконок"""
    names = ", ".join(f"<code>{name}</code>" for name in sorted(ICONS.keys()))
    await message.answer(
        f"🎨 <b>Доступные иконки:</b>\n{names}\n\n"
        f"Пример: <code>/icon smile 124 124</code>",
        parse_mode="HTML",
    )


@dp.message(Command("icon"))
async def cmd_icon(message: types.Message):
    """Рисует пиксельную иконку с центром в (x, y) пользовательских координат."""
    try:
        parts = (message.text or "").split()
        icon_name = parts[1].lower()
        x_center = int(parts[2])
        y_center = int(parts[3])

        if icon_name not in ICONS:
            return await message.answer(
                "❌ Неизвестная иконка. Используй <code>/iconlist</code>.",
                parse_mode="HTML",
            )

        palette, rows = ICONS[icon_name]
        h = len(rows)
        w = len(rows[0]) if h else 0
        # Переводим центр в верхний-левый угол изображения в координатах PIL
        top_left_x = x_center - (w // 2)
        top_left_y = fix_y(y_center) - (h // 2)

        drawn = 0
        async with canvas_lock:
            for r_idx, row in enumerate(rows):
                py = top_left_y + r_idx
                if not (0 <= py < CANVAS_SIZE):
                    continue
                for c_idx, ch in enumerate(row):
                    if ch == "." or ch not in palette:
                        continue
                    px = top_left_x + c_idx
                    if 0 <= px < CANVAS_SIZE:
                        canvas.putpixel((px, py), ImageColor.getrgb(palette[ch]))
                        drawn += 1

        if drawn == 0:
            return await message.answer(
                "❌ Иконка вышла за пределы холста (0-247).",
                parse_mode="HTML",
            )

        asyncio.create_task(
            backup_to_channel(
                message.from_user.full_name,
                f"icon {icon_name} {x_center} {y_center}",
            )
        )
        await send_canvas_photo(
            message, f"✨ Иконка <code>{icon_name}</code> размещена в ({x_center}, {y_center})."
        )
    except Exception:
        await message.answer(
            "Используй: <code>/icon имя x y</code> (например, <code>/icon smile 124 124</code>)",
            parse_mode="HTML",
        )


@dp.message(Command("image"))
async def cmd_image(message: types.Message):
    """Вставляет фото 32x32 в координаты (x, y) без удержания лишних буферов в RAM."""
    raw_text = message.text or message.caption or ""
    parts = raw_text.split()
    if len(parts) < 3:
        return await message.answer(
            "Используй: <code>/image x y</code> (ответь на фото или отправь фото с подписью <code>/image x y</code>)",
            parse_mode="HTML",
        )

    try:
        x_center = int(parts[1])
        y_center = int(parts[2])
    except ValueError:
        return await message.answer(
            "❌ Координаты должны быть целыми числами: <code>/image x y</code>",
            parse_mode="HTML",
        )

    photo_obj = _extract_target_photo(message)
    if not photo_obj:
        return await message.answer(
            "❌ Прикрепи фото с подписью <code>/image x y</code> или ответь командой на сообщение с фото.",
            parse_mode="HTML",
        )

    buf = io.BytesIO()
    resized = None
    try:
        file_info = await bot.get_file(photo_obj.file_id)
        await bot.download_file(file_info.file_path, destination=buf)
        buf.seek(0)

        with Image.open(buf) as src_img:
            rgb_img = src_img.convert("RGB")
            resized = rgb_img.resize(
                (IMAGE_STAMP_SIZE, IMAGE_STAMP_SIZE),
                resample=Image.Resampling.NEAREST,
            )
            rgb_img.close()

        top_left_x = x_center - (IMAGE_STAMP_SIZE // 2)
        top_left_y = fix_y(y_center) - (IMAGE_STAMP_SIZE // 2)

        async with canvas_lock:
            for py_local in range(IMAGE_STAMP_SIZE):
                dest_y = top_left_y + py_local
                if not (0 <= dest_y < CANVAS_SIZE):
                    continue
                for px_local in range(IMAGE_STAMP_SIZE):
                    dest_x = top_left_x + px_local
                    if 0 <= dest_x < CANVAS_SIZE:
                        canvas.putpixel(
                            (dest_x, dest_y), resized.getpixel((px_local, py_local))
                        )

        asyncio.create_task(
            backup_to_channel(
                message.from_user.full_name,
                f"image_32x32 at ({x_center}, {y_center})",
            )
        )
        await send_canvas_photo(
            message,
            f"🖼 Фото (32x32) нанесено с центром в ({x_center}, {y_center}).",
        )
    except Exception as e:
        logging.error(f"Ошибка обработки /image: {e}")
        await message.answer(
            "❌ Не удалось обработать изображение. Попробуй другое фото.",
            parse_mode="HTML",
        )
    finally:
        if resized is not None:
            resized.close()
            del resized
        buf.close()


@dp.message(Command("add"))
async def cmd_add(message: types.Message):
    lines = message.text.split("\n")
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

            if len(parts) != 3:
                continue
            try:
                color, x, y_raw = (
                    parts[0].lower(),
                    int(parts[1]),
                    int(parts[2]),
                )
                y = fix_y(y_raw)
                if (
                    0 <= x < CANVAS_SIZE
                    and 0 <= y < CANVAS_SIZE
                    and is_valid_color(color)
                ):
                    canvas.putpixel((x, y), ImageColor.getrgb(color))
                    success += 1
            except Exception:
                continue

    if success > 0:
        clean_action = " ".join(action_log)
        asyncio.create_task(
            backup_to_channel(message.from_user.full_name, clean_action)
        )
        await send_canvas_photo(message, f"✅ Успешно нанесено пикселей: {success}")
    else:
        await message.answer(
            "❌ Ошибка! Используй формат:\n"
            "<code>red 50 50</code>\n"
            "(можно списком через перенос строки, координаты от 0 до 247)",
            parse_mode="HTML",
        )


@dp.message(Command("line"))
async def cmd_line(message: types.Message):
    try:
        p = message.text.split()
        color, x1, y1, x2, y2 = (
            p[1].lower(),
            int(p[2]),
            int(p[3]),
            int(p[4]),
            int(p[5]),
        )
        if not is_valid_color(color):
            return await message.answer("❌ Цвет не валиден.", parse_mode="HTML")

        async with canvas_lock:
            draw = ImageDraw.Draw(canvas)
            draw.line(
                [x1, fix_y(y1), x2, fix_y(y2)],
                fill=ImageColor.getrgb(color),
                width=1,
            )

        asyncio.create_task(
            backup_to_channel(message.from_user.full_name, " ".join(p[1:]))
        )
        await send_canvas_photo(message, f"📏 Линия ({color}) готова.")
    except Exception:
        await message.answer(
            "Используй: <code>/line color x1 y1 x2 y2</code>", parse_mode="HTML"
        )


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
            draw.ellipse(
                [x - r, yp - r, x + r, yp + r], outline=ImageColor.getrgb(color)
            )

        asyncio.create_task(
            backup_to_channel(message.from_user.full_name, " ".join(p[1:]))
        )
        await send_canvas_photo(message, f"⭕ Окружность ({color}) отрисована.")
    except Exception:
        await message.answer(
            "Используй: <code>/circle color x y radius</code>", parse_mode="HTML"
        )


@dp.message(Command("fill"))
async def cmd_fill(message: types.Message):
    try:
        p = message.text.split()
        color, x1, y1, x2, y2 = (
            p[1].lower(),
            int(p[2]),
            int(p[3]),
            int(p[4]),
            int(p[5]),
        )

        xmin, xmax = sorted([x1, x2])
        ymin, ymax = sorted([fix_y(y1), fix_y(y2)])

        async with canvas_lock:
            draw = ImageDraw.Draw(canvas)
            draw.rectangle(
                [xmin, ymin, xmax, ymax], fill=ImageColor.getrgb(color)
            )

        asyncio.create_task(
            backup_to_channel(message.from_user.full_name, " ".join(p[1:]))
        )
        await send_canvas_photo(message, f"✅ Область залита цветом {color}.")
    except Exception:
        await message.answer(
            "Используй: <code>/fill color x1 y1 x2 y2</code>", parse_mode="HTML"
        )


@dp.message(Command("point"))
async def cmd_point(message: types.Message):
    try:
        parts = message.text.split()
        x, y_raw = int(parts[1]), int(parts[2])
        yp = fix_y(y_raw)

        async with canvas_lock:
            rgb = canvas.getpixel((x, yp))
        color_name = RGB_TO_NAME.get(rgb, f"rgb{rgb}")

        safe_name = html.escape(message.from_user.full_name)
        user_tag = f'<a href="tg://user?id={message.from_user.id}">{safe_name}</a>'
        await message.answer(
            f"📍 {user_tag}, цвет в ({x}, {y_raw}): <code>{color_name}</code>",
            parse_mode="HTML",
        )
    except Exception:
        await message.answer("Используй: <code>/point x y</code>", parse_mode="HTML")


@dp.message(Command("zoom"))
async def cmd_zoom(message: types.Message):
    try:
        parts = message.text.split()
        x_in, y_in = int(parts[1]), int(parts[2])
        yp = fix_y(y_in)

        box = (
            max(0, x_in - 50),
            max(0, yp - 50),
            min(CANVAS_SIZE, x_in + 50),
            min(CANVAS_SIZE, yp + 50),
        )
        async with canvas_lock:
            cropped = canvas.crop(box)
        zoomed = cropped.resize((500, 500), resample=Image.NEAREST)
        cropped.close()
        png_bytes = build_canvas_png_bytes(zoomed)
        zoomed.close()

        safe_name = html.escape(message.from_user.full_name)
        user_tag = f'<a href="tg://user?id={message.from_user.id}">{safe_name}</a>'
        await message.answer_photo(
            photo=BufferedInputFile(png_bytes, filename="zoom.png"),
            caption=f"🔍 {user_tag}, сектор {x_in}:{y_in}",
            parse_mode="HTML",
        )
        del png_bytes
    except Exception:
        await message.answer("Используй: <code>/zoom x y</code>", parse_mode="HTML")


@dp.message(Command("view"))
async def cmd_view(message: types.Message):
    await send_canvas_photo(message, "текущее состояние полотна.")


# --- СЕРВЕР ---

WEB_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>UnionPB Alive</title>
  <style>
    body {
      margin: 0;
      min-height: 100vh;
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      background: #0e1117;
      color: #e6edf3;
      font-family: system-ui, -apple-system, sans-serif;
      gap: 16px;
      padding: 20px;
      box-sizing: border-box;
    }
    h1 {
      margin: 0;
      font-size: 28px;
      letter-spacing: 0.5px;
    }
    .status {
      color: #3fb950;
      font-size: 14px;
    }
    img {
      width: min(496px, 90vw);
      height: auto;
      image-rendering: pixelated;
      border: 2px solid #30363d;
      border-radius: 8px;
      background: #ffffff;
    }
  </style>
</head>
<body>
  <h1>UnionPB Alive</h1>
  <div class="status">● Engine Online • Live Canvas (248×248)</div>
  <img src="/canvas.png" alt="UnionPB Latest Canvas" />
</body>
</html>
"""


async def handle_index(request: web.Request) -> web.Response:
    return web.Response(text=WEB_PAGE_HTML, content_type="text/html")


async def handle_canvas_png(request: web.Request) -> web.Response:
    async with canvas_lock:
        png_bytes = build_canvas_png_bytes(canvas)
    return web.Response(
        body=png_bytes,
        content_type="image/png",
        headers={"Cache-Control": "no-store, must-revalidate"},
    )


async def main():
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    app.router.add_get("/", handle_index)
    app.router.add_get("/canvas.png", handle_canvas_png)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    await load_last_canvas()
    await dp.start_polling(bot)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logging.info("Остановка бота...")
