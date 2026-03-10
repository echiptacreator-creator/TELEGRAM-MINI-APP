import asyncio
import logging
import os
import aiosqlite
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from formatter import add_match_event_emoji
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ChatType
from aiogram.filters import Command
from scoreboard import (
    init_scoreboard_db,
    scoreboard_register_main_post,
    scoreboard_sync_from_main_post,
    scoreboard_set_teams,
    scoreboard_reset_match,
)
from aiogram.types import (
    Message,
    CallbackQuery,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
)
from dotenv import load_dotenv
from scoreboard import (
    init_scoreboard_db,
    scoreboard_register_main_post,
    scoreboard_sync_from_main_post,
    scoreboard_set_teams,
    scoreboard_reset_match,
    scoreboard_recreate_post,
)

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN topilmadi. .env faylni tekshiring.")

logging.basicConfig(level=logging.INFO)

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher()

DB_PATH = "match_bot.db"
DELETE_DELAY_SECONDS = 30


@dataclass
class MatchState:
    self.stream_url: str | None = None
    channel_id: int
    started: int
    main_message_id: Optional[int]
    main_text: str
    period: str  # not_started, first_half, halftime, second_half, finished
    first_half_start_ts: Optional[int]
    second_half_start_ts: Optional[int]
    first_half_extra: int
    second_half_extra: int
    minute_offset: int
    freeze_minute: Optional[str]
    first_half_extra_asked: int
    second_half_extra_asked: int

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS matches (
                channel_id INTEGER PRIMARY KEY,
                started INTEGER NOT NULL DEFAULT 0,
                main_message_id INTEGER,
                main_text TEXT NOT NULL DEFAULT '',
                period TEXT NOT NULL DEFAULT 'not_started',
                first_half_start_ts INTEGER,
                second_half_start_ts INTEGER,
                first_half_extra INTEGER NOT NULL DEFAULT 0,
                second_half_extra INTEGER NOT NULL DEFAULT 0,
                minute_offset INTEGER NOT NULL DEFAULT 0,
                freeze_minute TEXT,
                first_half_extra_asked INTEGER NOT NULL DEFAULT 0,
                second_half_extra_asked INTEGER NOT NULL DEFAULT 0
            )
            """
        )

        try:
            await db.execute(
                "ALTER TABLE matches ADD COLUMN first_half_extra_asked INTEGER NOT NULL DEFAULT 0"
            )
        except:
            pass

        try:
            await db.execute(
                "ALTER TABLE matches ADD COLUMN second_half_extra_asked INTEGER NOT NULL DEFAULT 0"
            )
        except:
            pass

        await db.commit()


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_main_keyboard(state):
    if not state.stream_url:
        return None

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📺 Jonli efir",
                    url=state.stream_url
                )
            ]
        ]
    )

async def get_state(channel_id: int) -> MatchState:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT channel_id, started, main_message_id, main_text, period, "
            "first_half_start_ts, second_half_start_ts, first_half_extra, "
            "second_half_extra, minute_offset, freeze_minute, "
            "first_half_extra_asked, second_half_extra_asked "
            "FROM matches WHERE channel_id = ?",
            (channel_id,),
        ) as cur:
            row = await cur.fetchone()

        if not row:
            await db.execute(
                """
                INSERT OR IGNORE INTO matches (
                    channel_id, started, main_message_id, main_text, period,
                    first_half_start_ts, second_half_start_ts,
                    first_half_extra, second_half_extra, minute_offset, freeze_minute,
                    first_half_extra_asked, second_half_extra_asked
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    channel_id,
                    0,
                    None,
                    "",
                    "not_started",
                    None,
                    None,
                    0,
                    0,
                    0,
                    None,
                    0,
                    0,
                ),
            )
            await db.commit()

            async with db.execute(
                "SELECT channel_id, started, main_message_id, main_text, period, "
                "first_half_start_ts, second_half_start_ts, first_half_extra, "
                "second_half_extra, minute_offset, freeze_minute, "
                "first_half_extra_asked, second_half_extra_asked "
                "FROM matches WHERE channel_id = ?",
                (channel_id,),
            ) as cur:
                row = await cur.fetchone()

        return MatchState(*row)

async def save_state(state: MatchState):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE matches SET
                started = ?,
                main_message_id = ?,
                main_text = ?,
                period = ?,
                first_half_start_ts = ?,
                second_half_start_ts = ?,
                first_half_extra = ?,
                second_half_extra = ?,
                minute_offset = ?,
                freeze_minute = ?,
                first_half_extra_asked = ?,
                second_half_extra_asked = ?
            WHERE channel_id = ?
            """,
            (
                state.started,
                state.main_message_id,
                state.main_text,
                state.period,
                state.first_half_start_ts,
                state.second_half_start_ts,
                state.first_half_extra,
                state.second_half_extra,
                state.minute_offset,
                state.freeze_minute,
                state.first_half_extra_asked,
                state.second_half_extra_asked,
                state.channel_id,
            ),
        )
        await db.commit()

def now_ts() -> int:
    return int(datetime.now().timestamp())


def minute_label(state: MatchState) -> str:
    if state.period == "first_half" and state.first_half_start_ts:
        elapsed_min = max(0, int((now_ts() - state.first_half_start_ts) // 60))
        current = elapsed_min + 1

        if current <= 45:
            return f"{current}'"

        extra_now = current - 45
        if state.first_half_extra > 0 and extra_now > state.first_half_extra:
            extra_now = state.first_half_extra

        return f"45+{extra_now}'"

    if state.period == "second_half" and state.second_half_start_ts:
        elapsed_min = max(0, int((now_ts() - state.second_half_start_ts) // 60))
        current = 46 + elapsed_min

        if current <= 90:
            return f"{current}'"

        extra_now = current - 90
        if state.second_half_extra > 0 and extra_now > state.second_half_extra:
            extra_now = state.second_half_extra

        return f"90+{extra_now}'"

    if state.freeze_minute:
        return state.freeze_minute

    return "0'"

def escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def extra_time_keyboard(half: int) -> InlineKeyboardMarkup:
    buttons = []
    row = []
    for i in range(0, 11):
        row.append(
            InlineKeyboardButton(
                text=f"+{i}",
                callback_data=f"extra:{half}:{i}",
            )
        )
        if len(row) == 4:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(inline_keyboard=buttons)


async def update_main_post(state: MatchState):
    if not state.main_message_id:
        return

    try:
        await bot.edit_message_text(
            chat_id=state.channel_id,
            message_id=state.main_message_id,
            text=state.main_text[:4096],
            reply_markup=get_main_keyboard(state)
        )

        await scoreboard_sync_from_main_post(
            bot=bot,
            channel_id=state.channel_id,
            main_text=state.main_text,
            replace_current=False,
        )

    except Exception as e:
        logging.exception("update_main_post xatolik: %s", e)
        raise

async def create_new_live_post(channel_id: int, title: str = "📍 <b>Live davom etmoqda</b>") -> int:
    sent = await bot.send_message(chat_id=channel_id, text=title)
    return sent.message_id

async def append_event(state: MatchState, text: str, with_minute: bool = True):
    try:
        formatted_text = add_match_event_emoji(text.strip())
        print("KELGAN TEXT:", text)
        print("FORMATDAN KEYIN:", formatted_text)

        clean_text = escape_html(formatted_text)

        if with_minute:
            label = minute_label(state)
            line = f"{label} {clean_text}"
        else:
            line = clean_text

        if state.main_text.strip():
            state.main_text += f"\n\n{line}"
        else:
            state.main_text = line

        await save_state(state)
        await update_main_post(state)

    except Exception as e:
        logging.exception("append_event xatolik: %s", e)
        raise

async def maybe_ask_extra_time(state: MatchState):
    if state.period == "first_half" and state.first_half_start_ts and not state.first_half_extra_asked:
        elapsed_min = max(0, int((now_ts() - state.first_half_start_ts) // 60))
        current = elapsed_min + 1

        if current >= 44:
            state.first_half_extra_asked = 1
            await save_state(state)
            try:
                await bot.send_message(
                    OWNER_ID,
                    "1-bo‘lim 44-daqiqaga kirdi. Birinchi bo‘limga qancha vaqt qo‘shiladi?",
                    reply_markup=extra_time_keyboard(1),
                )
            except Exception:
                pass

    if state.period == "second_half" and state.second_half_start_ts and not state.second_half_extra_asked:
        elapsed_min = max(0, int((now_ts() - state.second_half_start_ts) // 60))
        current = 46 + elapsed_min

        if current >= 89:
            state.second_half_extra_asked = 1
            await save_state(state)
            try:
                await bot.send_message(
                    OWNER_ID,
                    "2-bo‘lim 89-daqiqaga kirdi. Ikkinchi bo‘limga qancha vaqt qo‘shiladi?",
                    reply_markup=extra_time_keyboard(2),
                )
            except Exception:
                pass

async def delayed_delete_and_merge(message: Message, state: MatchState):
    await asyncio.sleep(DELETE_DELAY_SECONDS)

    fresh_state = await get_state(message.chat.id)
    await maybe_ask_extra_time(fresh_state)

    if fresh_state.main_message_id == message.message_id:
        return

    if not message.text:
        return

    text = message.text.strip()
    lower = text.lower()

    skip_phrases = {
        "uchrashuv boshlandi",
        "birinchi bo'lim yakunlandi",
        "ikkinchi bo'lim boshlandi",
        "uchrashuv yakunlandi",
    }
    if lower in skip_phrases:
        return

    try:
        await message.delete()
    except Exception:
        pass

    await append_event(fresh_state, text, with_minute=True)


@dp.message(Command("start"))
async def cmd_start(message: Message):
    if message.from_user and message.from_user.id == OWNER_ID:
        await message.answer(
            "Bot tayyor.\n\n"
            "Kanalga admin qilib qo‘sh.\n"
            "Kanaldagi postlar bilan ishlaydi.\n\n"
            "Ishlatish:\n"
            "1) Kanalga <b>Uchrashuv boshlandi</b> yoz\n"
            "2) Keyin oddiy live xabarlarni tashlab bor\n"
            "3) <b>Birinchi bo‘lim yakunlandi</b>\n"
            "4) <b>Ikkinchi bo‘lim boshlandi</b>\n"
            "5) <b>Uchrashuv yakunlandi</b>"
        )


@dp.channel_post(F.text)
async def handle_channel_posts(message: Message):
    if message.chat.type != ChatType.CHANNEL:
        return

    state = await get_state(message.chat.id)
    text = message.text.strip()
    lower = text.casefold()

    # 1) MATCH START
    if lower.startswith("uchrashuv boshlandi"):
        state.started = 1
        state.period = "first_half"
        state.first_half_start_ts = now_ts()
        state.second_half_start_ts = None
        state.first_half_extra = 0
        state.second_half_extra = 0
        state.minute_offset = 0
        state.freeze_minute = "1'"
        state.main_message_id = message.message_id
        state.main_text = "⚽ <b>Uchrashuv boshlandi</b>"
        state.first_half_extra_asked = 0
        state.second_half_extra_asked = 0

        await save_state(state)

        await scoreboard_reset_match(
            bot=bot,
            channel_id=message.chat.id,
            main_message_id=message.message_id,
        )

        await update_main_post(state)

        parts = [p.strip() for p in text.split("|")]
        if len(parts) >= 3 and parts[1] and parts[2]:
            await scoreboard_set_teams(
                bot=bot,
                channel_id=message.chat.id,
                home_team=parts[1],
                away_team=parts[2],
                main_text=state.main_text,
            )

        try:
            await bot.send_message(
                OWNER_ID,
                f"Kanal {message.chat.title} uchun o‘yin boshlandi."
            )
        except Exception:
            pass
        return

    if not state.started or not state.main_message_id:
        return

    await maybe_ask_extra_time(state)

    if lower == "birinchi bo‘lim yakunlandi" or lower == "birinchi bo'lim yakunlandi":
        state.period = "halftime"
        state.freeze_minute = "45'"
        state.main_text += "\n\n⏸ <b>Birinchi bo‘lim yakunlandi</b>"
        await save_state(state)
        await update_main_post(state)
        return

    if lower == "ikkinchi bo‘lim boshlandi" or lower == "ikkinchi bo'lim boshlandi":
        state.period = "second_half"
        state.second_half_start_ts = now_ts()
        state.minute_offset = 45
        state.freeze_minute = "46'"

        # 2-bo'lim uchun yangi live post ochamiz
        new_message_id = await create_new_live_post(
            message.chat.id,
            "▶️ <b>Ikkinchi bo‘lim boshlandi</b>"
        )

        state.main_message_id = new_message_id
        state.main_text = "▶️ <b>Ikkinchi bo‘lim boshlandi</b>"

        await save_state(state)
        await update_main_post(state)
        return

    if lower == "uchrashuv yakunlandi":
        state.period = "finished"
        state.freeze_minute = "90'"
        state.main_text += "\n\n🏁 <b>Uchrashuv yakunlandi</b>"
        await save_state(state)
        await update_main_post(state)
        return

    asyncio.create_task(delayed_delete_and_merge(message, state))

@dp.edited_channel_post(F.text)
async def handle_edited_channel_posts(message: Message):
    if message.chat.type != ChatType.CHANNEL:
        return

    state = await get_state(message.chat.id)

    if not state.started or not state.main_message_id:
        return

    if message.message_id != state.main_message_id:
        return

    edited_text = message.html_text or message.text or ""
    if not edited_text.strip():
        return

    state.main_text = edited_text
    await save_state(state)

    try:
        await scoreboard_sync_from_main_post(
            bot=bot,
            channel_id=message.chat.id,
            main_text=state.main_text,
            replace_current=True,
        )
    except Exception as e:
        logging.exception("edited_channel_post scoreboard sync xatolik: %s", e)

@dp.channel_post(F.photo | F.video | F.animation | F.document)
async def handle_media_posts(message: Message):
    if message.chat.type != ChatType.CHANNEL:
        return

    state = await get_state(message.chat.id)

    # Match hali boshlanmagan bo'lsa, media bilan ishlamaymiz
    if not state.started or not state.main_message_id:
        return

    # Uchrashuv tugagan bo'lsa yangi live post ochmaymiz
    if state.period == "finished":
        return

    # Qaysi bo'limdaligiga qarab sarlavha
    if state.period == "second_half":
        title = "📍 <b>2-bo‘lim live davom etmoqda</b>"
    elif state.period == "halftime":
        title = "📍 <b>Tanaffusdan keyin live davom etadi</b>"
    else:
        title = "📍 <b>Live davom etmoqda</b>"

    # Yangi live post ochamiz
    new_message_id = await create_new_live_post(message.chat.id, title)

    # Endi keyingi sharhlar shu postga tushadi
    state.main_message_id = new_message_id
    state.main_text = title
    await save_state(state)

    # Scoreboard ham yangi post sifatida qayta pastga tushsin
    try:
        await scoreboard_recreate_post(
            bot=bot,
            channel_id=state.channel_id,
        )
    except Exception as e:
        logging.exception("media paytida scoreboard recreate xatolik: %s", e)

@dp.callback_query(F.data.startswith("extra:"))
async def handle_extra_time(callback: CallbackQuery):
    if not callback.from_user or callback.from_user.id != OWNER_ID:
        await callback.answer("Bu tugma faqat admin uchun.", show_alert=True)
        return

    _, half_str, value_str = callback.data.split(":")
    half = int(half_str)
    value = int(value_str)

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT channel_id FROM matches WHERE started = 1 ORDER BY channel_id DESC"
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await callback.answer("Aktiv o‘yin topilmadi.", show_alert=True)
        return

    channel_id = rows[-1][0]
    state = await get_state(channel_id)

    if half == 1:
        state.first_half_extra = value
        announce = f"⏱ <b>Birinchi bo‘limga {value} daqiqa vaqt qo‘shib berildi</b>"

        if state.main_text.strip():
            state.main_text += f"\n\n{announce}"
        else:
            state.main_text = announce

        await save_state(state)
        await update_main_post(state)

        await callback.message.edit_text(f"1-bo‘lim uchun +{value} daqiqa saqlandi.")
        await callback.answer("Saqlandi")
        return

    if half == 2:
        state.second_half_extra = value
        announce = f"⏱ <b>Ikkinchi bo‘limga {value} daqiqa vaqt qo‘shib berildi</b>"

        if state.main_text.strip():
            state.main_text += f"\n\n{announce}"
        else:
            state.main_text = announce

        await save_state(state)
        await update_main_post(state)

        await callback.message.edit_text(f"2-bo‘lim uchun +{value} daqiqa saqlandi.")
        await callback.answer("Saqlandi")
        return

    await callback.answer("Xatolik", show_alert=True)

async def background_extra_time_watcher():
    while True:
        try:
            async with aiosqlite.connect(DB_PATH) as db:
                async with db.execute(
                    "SELECT channel_id FROM matches WHERE started = 1"
                ) as cur:
                    rows = await cur.fetchall()

            for row in rows:
                channel_id = row[0]
                state = await get_state(channel_id)
                await maybe_ask_extra_time(state)

        except Exception as e:
            logging.exception("background watcher error: %s", e)

        await asyncio.sleep(15)

@dp.message(Command("status"))
async def cmd_status(message: Message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return

    text_lines = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT channel_id, started, period, main_message_id FROM matches"
        ) as cur:
            rows = await cur.fetchall()

    if not rows:
        await message.answer("Hali hech qanaqa o‘yin yo‘q.")
        return

    for channel_id, started, period, main_message_id in rows:
        text_lines.append(
            f"channel_id={channel_id}\nstarted={started}\nperiod={period}\nmain_message_id={main_message_id}\n"
        )

    await message.answer("\n".join(text_lines))


@dp.message(Command("teams"))
async def cmd_teams(message: Message):
    if not message.from_user or message.from_user.id != OWNER_ID:
        return

    payload = message.text.replace("/teams", "", 1).strip()
    if "|" not in payload:
        await message.answer("Format: /teams Neftchi | Andijon")
        return

    home, away = [x.strip() for x in payload.split("|", 1)]

    state = None
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT channel_id FROM matches WHERE started = 1 ORDER BY channel_id DESC"
        ) as cur:
            row = await cur.fetchone()

    if not row:
        await message.answer("Aktiv o‘yin topilmadi.")
        return

    channel_id = row[0]
    match_state = await get_state(channel_id)

    await scoreboard_set_teams(
        bot=bot,
        channel_id=channel_id,
        home_team=home,
        away_team=away,
        main_text=match_state.main_text,
    )

    await message.answer(f"Jamoalar saqlandi: {home} vs {away}")

@dp.message(Command("stream"))
async def set_stream(message: Message):

    if message.from_user.id != OWNER_ID:
        return

    url = message.text.split(maxsplit=1)[1]

    for state in match_states.values():
        if state.started:
            state.stream_url = url

            await update_main_post(state)

            await message.answer("✅ Jonli efir link qo‘shildi")
            return

async def main():
    await init_db()
    await init_scoreboard_db()
    asyncio.create_task(background_extra_time_watcher())
    await dp.start_polling(bot)


if __name__ == "__main__":

    asyncio.run(main())




