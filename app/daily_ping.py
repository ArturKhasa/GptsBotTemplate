import asyncio
import logging
import random
from datetime import datetime, timedelta

from openai import OpenAI
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from sqlalchemy import select

from config import TELEGRAM_BOT_TOKEN, OPENAI_API_KEY, async_session, FREE_MESSAGES_LIMIT, ADMIN_USER_ID
from database import User, init_db

PING_WINDOW_START_HOUR = 12
PING_WINDOW_END_HOUR = 18

FALLBACK_PING_TEXT = (
    "Здравствуйте! Это ваш Консультант.\n\n"
    "Мы скучаем: у вас все еще есть бесплатный запрос, но вы им не воспользовались 😔\n"
    "Если вопрос по налогам, бухгалтерии или праву уже назрел, просто напишите его в чат."
)

openai_client = OpenAI(api_key=OPENAI_API_KEY)


def _generate_ping_text_sync() -> str:
    prompt = (
        "Сгенерируй короткий, вежливый и немного жалобный текст для Telegram-сообщения. "
        "Цель: мягко напомнить пользователю, что у него остался бесплатный запрос в боте по бухгалтерии/налогам/праву. "
        "Требования: 2-3 предложения, на русском, без хэштегов, без markdown-разметки, без кавычек вокруг текста, до 280 символов."
    )
    response = openai_client.responses.create(
        model="gpt-5-mini",
        input=prompt,
    )
    text = (response.output_text or "").strip()
    return text if text else FALLBACK_PING_TEXT


async def generate_ping_text() -> str:
    try:
        return await asyncio.to_thread(_generate_ping_text_sync)
    except Exception as exc:
        logging.warning("Не удалось сгенерировать PING_TEXT через OpenAI, использую fallback: %s", exc)
        return FALLBACK_PING_TEXT


def add_sad_emojis(text: str) -> str:
    return f"{text.rstrip()} 😔 🙏"


async def ping_users_without_subscription() -> tuple[int, int]:
    sent = 0
    failed = 0
    ping_text = add_sad_emojis(await generate_ping_text())

    session = AiohttpSession(timeout=60)
    bot = Bot(
        token=TELEGRAM_BOT_TOKEN,
        default=DefaultBotProperties(parse_mode="HTML"),
        session=session,
    )

    try:
        async with async_session() as db_session:
            result = await db_session.execute(
                select(User.user_id).where(
                    User.has_subscription.is_(False),
                    User.free_messages > 0,
                    User.subscription_type.is_(None),
                )
            )
            user_ids = result.scalars().all()

        for user_id in user_ids:
            try:
                await bot.send_message(user_id, ping_text)
                sent += 1
            except Exception as exc:
                failed += 1
                logging.warning("Не удалось отправить daily ping пользователю %s: %s", user_id, exc)

        report_text = (
            f"Daily ping завершен. Отправлено: {sent}. Ошибок: {failed}. "
            f"Время: {datetime.utcnow().isoformat()}Z"
        )
        logging.info(report_text)

        for admin_id in ADMIN_USER_ID:
            try:
                await bot.send_message(admin_id, report_text)
            except Exception as exc:
                logging.warning("Не удалось отправить отчет админу %s: %s", admin_id, exc)

        return sent, failed
    finally:
        await bot.session.close()


def get_random_ping_time_for_day(day: datetime) -> datetime:
    window_start = day.replace(
        hour=PING_WINDOW_START_HOUR, minute=0, second=0, microsecond=0
    )
    window_duration_seconds = (PING_WINDOW_END_HOUR - PING_WINDOW_START_HOUR) * 60 * 60
    random_offset = random.randint(0, window_duration_seconds - 1)
    return window_start + timedelta(seconds=random_offset)


async def run_daily_ping_loop():
    await init_db()
    now = datetime.now()
    next_run = get_random_ping_time_for_day(now)
    if next_run <= now:
        next_run = get_random_ping_time_for_day(now + timedelta(days=1))

    while True:
        now = datetime.now()
        sleep_seconds = max(0, int((next_run - now).total_seconds()))
        logging.info("Следующий daily ping запланирован на %s", next_run.isoformat())
        await asyncio.sleep(sleep_seconds)

        try:
            await ping_users_without_subscription()
        except Exception as exc:
            logging.exception("Критическая ошибка daily ping: %s", exc)
        finally:
            next_run = get_random_ping_time_for_day(next_run + timedelta(days=1))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_daily_ping_loop())
