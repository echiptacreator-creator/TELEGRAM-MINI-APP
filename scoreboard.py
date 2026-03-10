import logging
import re
from dataclasses import dataclass
from typing import Optional

import aiosqlite
from aiogram import Bot

SCOREBOARD_DB_PATH = "scoreboard.db"


@dataclass
class ScoreboardState:
    channel_id: int
    main_message_id: Optional[int]
    scoreboard_message_id: Optional[int]
    home_team: str
    away_team: str
    all_main_text: str


@dataclass
class ParsedMatchInfo:
    status: str  # ready, live, halftime, finished
    current_minute: str
    home_score: int
    away_score: int
    goals: list[dict]
    yellow_count: int
    red_count: int
    last_event: str


async def init_scoreboard_db():
    async with aiosqlite.connect(SCOREBOARD_DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS scoreboard_state (
                channel_id INTEGER PRIMARY KEY,
                main_message_id INTEGER,
                scoreboard_message_id INTEGER,
                home_team TEXT NOT NULL DEFAULT 'Uy jamoa',
                away_team TEXT NOT NULL DEFAULT 'Mehmon jamoa',
                all_main_text TEXT NOT NULL DEFAULT ''
            )
            """
        )

        try:
            await db.execute(
                "ALTER TABLE scoreboard_state ADD COLUMN all_main_text TEXT NOT NULL DEFAULT ''"
            )
        except:
            pass

        await db.commit()


async def get_scoreboard_state(channel_id: int) -> ScoreboardState:
    async with aiosqlite.connect(SCOREBOARD_DB_PATH) as db:
        async with db.execute(
            """
            SELECT channel_id, main_message_id, scoreboard_message_id,
                   home_team, away_team, all_main_text
            FROM scoreboard_state
            WHERE channel_id = ?
            """,
            (channel_id,),
        ) as cur:
            row = await cur.fetchone()

        if row:
            return ScoreboardState(*row)

        state = ScoreboardState(
            channel_id=channel_id,
            main_message_id=None,
            scoreboard_message_id=None,
            home_team="Uy jamoa",
            away_team="Mehmon jamoa",
            all_main_text="",
        )

        await db.execute(
            """
            INSERT INTO scoreboard_state (
                channel_id, main_message_id, scoreboard_message_id,
                home_team, away_team, all_main_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                state.channel_id,
                state.main_message_id,
                state.scoreboard_message_id,
                state.home_team,
                state.away_team,
                state.all_main_text,
            ),
        )
        await db.commit()
        return state


async def save_scoreboard_state(state: ScoreboardState):
    async with aiosqlite.connect(SCOREBOARD_DB_PATH) as db:
        await db.execute(
            """
            UPDATE scoreboard_state
            SET main_message_id = ?, scoreboard_message_id = ?, home_team = ?, away_team = ?, all_main_text = ?
            WHERE channel_id = ?
            """,
            (
                state.main_message_id,
                state.scoreboard_message_id,
                state.home_team,
                state.away_team,
                state.all_main_text,
                state.channel_id,
            ),
        )
        await db.commit()


def strip_html(text: str) -> str:
    return re.sub(r"<[^>]+>", "", text or "")


def escape_html(text: str) -> str:
    return (
        (text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


MINUTE_RE = re.compile(r"^(\d+(?:\+\d+)?)'\s*(.*)$")


def split_lines(main_text: str) -> list[str]:
    plain = strip_html(main_text)
    return [line.strip() for line in plain.splitlines() if line.strip()]


def detect_status(lines: list[str]) -> tuple[str, str]:
    status = "ready"
    current_minute = ""

    for line in lines:
        low = line.casefold()

        minute_match = MINUTE_RE.match(line)
        if minute_match:
            current_minute = minute_match.group(1) + "'"

        if "uchrashuv boshlandi" in low:
            status = "live"
        if "birinchi bo‘lim yakunlandi" in low or "birinchi bo'lim yakunlandi" in low:
            status = "halftime"
        if "ikkinchi bo‘lim boshlandi" in low or "ikkinchi bo'lim boshlandi" in low:
            status = "live"
        if "uchrashuv yakunlandi" in low or "o‘yin yakunlandi" in low or "o'yin yakunlandi" in low:
            status = "finished"

    return status, current_minute


def detect_goal_team_and_scorer(
    content: str,
    home_team: str,
    away_team: str,
) -> tuple[Optional[str], str]:
    low = content.casefold()
    home_low = home_team.casefold()
    away_low = away_team.casefold()

    team = None
    scorer = ""

    if home_low and home_low in low:
        team = "home"
        scorer = re.sub(re.escape(home_team), "", content, flags=re.IGNORECASE).strip(" -—:|")
    elif away_low and away_low in low:
        team = "away"
        scorer = re.sub(re.escape(away_team), "", content, flags=re.IGNORECASE).strip(" -—:|")

    if not scorer:
        scorer = content

    scorer = re.sub(r"^(⚽|🔥|🥅|🎯)\s*", "", scorer).strip()
    scorer = re.sub(r"^(go+ol+|gol|goal)\b[! ]*", "", scorer, flags=re.IGNORECASE).strip(" -—:|")

    return team, scorer


def parse_main_post(main_text: str, home_team: str, away_team: str) -> ParsedMatchInfo:
    lines = split_lines(main_text)
    status, current_minute = detect_status(lines)

    home_score = 0
    away_score = 0
    goals: list[dict] = []
    yellow_count = 0
    red_count = 0
    last_event = ""

    seen_event_lines = set()

    for line in lines:
        minute_match = MINUTE_RE.match(line)
        if not minute_match:
            continue

        minute = minute_match.group(1) + "'"
        content = minute_match.group(2).strip()
        low = content.casefold()

        # Bir xil event qatori qayta tushsa, ikkinchi marta hisoblamaymiz
        event_key = f"{minute}|{content}"
        if event_key in seen_event_lines:
            continue
        seen_event_lines.add(event_key)

        if content:
            last_event = f"{minute} {content}"

        is_goal = any(word in low for word in ["goool", "gooool", "gooooool", "gol", "goal", "gool"])
        is_disallowed = "bekor qilindi" in low or "avtogol bekor" in low

        if is_goal and not is_disallowed:
            team, scorer = detect_goal_team_and_scorer(content, home_team, away_team)
            if team == "home":
                home_score += 1
                goals.append({
                    "minute": minute,
                    "team_name": home_team,
                    "scorer": scorer or home_team,
                })
            elif team == "away":
                away_score += 1
                goals.append({
                    "minute": minute,
                    "team_name": away_team,
                    "scorer": scorer or away_team,
                })

        if "ogohlantirildi" in low or "sariq kartochka" in low or "sariq oldi" in low:
            yellow_count += 1

        if "chetlatildi" in low or "qizil kartochka" in low or "qizil oldi" in low:
            red_count += 1

    return ParsedMatchInfo(
        status=status,
        current_minute=current_minute,
        home_score=home_score,
        away_score=away_score,
        goals=goals,
        yellow_count=yellow_count,
        red_count=red_count,
        last_event=last_event,
    )

def render_scoreboard(state: ScoreboardState, parsed: ParsedMatchInfo) -> str:
    if parsed.status == "finished":
        status_line = "🏁 <b>YAKUNLANDI</b>"
    elif parsed.status == "halftime":
        status_line = "⏸ <b>TANAFFUS</b>"
    elif parsed.status == "live":
        if parsed.current_minute:
            status_line = f"🔴 <b>LIVE</b> | {escape_html(parsed.current_minute)}"
        else:
            status_line = "🔴 <b>LIVE</b>"
    else:
        status_line = "🕒 <b>TAYYOR</b>"

    header = (
        f"📊 <b>{escape_html(state.home_team.upper())} {parsed.home_score} — "
        f"{parsed.away_score} {escape_html(state.away_team.upper())}</b>\n"
        f"{status_line}"
    )

    goals_block = "⚽ <b>Gollar:</b>\nYo‘q"
    if parsed.goals:
        goal_lines = []
        for goal in parsed.goals[-6:]:
            scorer = goal['scorer'] or goal['team_name']
            goal_lines.append(
                f"{escape_html(goal['minute'])} {escape_html(scorer)} "
                f"({escape_html(goal['team_name'])})"
            )
        goals_block = "⚽ <b>Gollar:</b>\n" + "\n".join(goal_lines)

    cards_block = f"🟨 {parsed.yellow_count} | 🟥 {parsed.red_count}"

    parts = [header, "", goals_block, "", cards_block]

    return "\n".join(parts)[:4096]


async def scoreboard_register_main_post(
    bot: Bot,
    channel_id: int,
    main_message_id: int,
):
    state = await get_scoreboard_state(channel_id)
    state.main_message_id = main_message_id
    await save_scoreboard_state(state)

    if state.scoreboard_message_id:
        return

    placeholder = (
        f"📊 <b>{escape_html(state.home_team.upper())} 0 — 0 {escape_html(state.away_team.upper())}</b>\n"
        "🕒 <b>TAYYOR</b>"
    )

    try:
        sent = await bot.send_message(chat_id=channel_id, text=placeholder)
        state.scoreboard_message_id = sent.message_id
        await save_scoreboard_state(state)
    except Exception as e:
        logging.exception("scoreboard register xatolik: %s", e)


async def scoreboard_set_teams(
    bot: Bot,
    channel_id: int,
    home_team: str,
    away_team: str,
    main_text: Optional[str] = None,
):
    state = await get_scoreboard_state(channel_id)
    state.home_team = home_team.strip()
    state.away_team = away_team.strip()
    await save_scoreboard_state(state)

    if main_text is not None:
        await scoreboard_sync_from_main_post(
            bot=bot,
            channel_id=channel_id,
            main_text=main_text,
            replace_current=False,
        )


async def scoreboard_sync_from_main_post(
    bot: Bot,
    channel_id: int,
    main_text: str,
    replace_current: bool = False,
):
    state = await get_scoreboard_state(channel_id)

    # Agar scoreboard post bo'lmasa yaratamiz
    if not state.scoreboard_message_id:
        await scoreboard_register_main_post(
            bot=bot,
            channel_id=channel_id,
            main_message_id=state.main_message_id or 0,
        )
        state = await get_scoreboard_state(channel_id)

    clean_main_text = (main_text or "").strip()

    if replace_current:
        # Qo'lda edit bo'lganda yoki current live post to'liq almashtirilganda ishlatiladi
        state.all_main_text = clean_main_text
    else:
        # Yangi live postlar matnini umumiy tarixga qo'shib boramiz
        if clean_main_text:
            if state.all_main_text.strip():
                if clean_main_text not in state.all_main_text:
                    state.all_main_text += "\n\n" + clean_main_text
            else:
                state.all_main_text = clean_main_text

    await save_scoreboard_state(state)

    parsed = parse_main_post(state.all_main_text, state.home_team, state.away_team)
    scoreboard_text = render_scoreboard(state, parsed)

    try:
        await bot.edit_message_text(
            chat_id=channel_id,
            message_id=state.scoreboard_message_id,
            text=scoreboard_text,
        )
    except Exception as e:
        logging.exception("scoreboard edit xatolik, qayta yaratamiz: %s", e)
        try:
            sent = await bot.send_message(chat_id=channel_id, text=scoreboard_text)
            state.scoreboard_message_id = sent.message_id
            await save_scoreboard_state(state)
        except Exception as e2:
            logging.exception("scoreboard qayta yaratishda xatolik: %s", e2)

async def scoreboard_reset_match(
    bot: Bot,
    channel_id: int,
    main_message_id: int,
):
    state = await get_scoreboard_state(channel_id)
    state.main_message_id = main_message_id
    state.all_main_text = ""
    await save_scoreboard_state(state)

    await scoreboard_register_main_post(
        bot=bot,
        channel_id=channel_id,
        main_message_id=main_message_id,

    )

async def scoreboard_recreate_post(
    bot: Bot,
    channel_id: int,
):
    state = await get_scoreboard_state(channel_id)

    parsed = parse_main_post(state.all_main_text, state.home_team, state.away_team)
    scoreboard_text = render_scoreboard(state, parsed)

    # Eski scoreboard postni o‘chirishga harakat qilamiz
    if state.scoreboard_message_id:
        try:
            await bot.delete_message(
                chat_id=channel_id,
                message_id=state.scoreboard_message_id,
            )
        except Exception:
            pass

    # Yangisini yuboramiz
    try:
        sent = await bot.send_message(
            chat_id=channel_id,
            text=scoreboard_text,
        )
        state.scoreboard_message_id = sent.message_id
        await save_scoreboard_state(state)
    except Exception as e:
        logging.exception("scoreboard recreate xatolik: %s", e)





