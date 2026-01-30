import logging

from aiogram.types import Message
from sqlalchemy import select

from config import (
    async_session,
)
from database import User


# ADMIN_USER_ID = ...
# bot = ...
# async_session = ...
# User = ...

def strip_broadcast(text: str) -> str:
    # Удаляем только первое вхождение /broadcast и чистим пробелы
    return text.replace("/broadcast", "", 1).strip()

async def broadcast_send_same_content(message: Message, cleaned_text: str):
    from main import bot
    async with async_session() as session:
        result = await session.execute(
            select(User.user_id)
            # .where(User.has_subscription == False)
        )
        users = result.scalars().all()

    for user_id in users:
        try:
            # 1) Если это фото
            if message.photo:
                file_id = message.photo[-1].file_id
                await bot.send_photo(user_id, file_id, caption=cleaned_text or None)

            # 2) Если видео
            elif message.video:
                await bot.send_video(user_id, message.video.file_id, caption=cleaned_text or None)

            # 3) Если просто текст
            elif message.text:
                if not cleaned_text:
                    # если админ отправил только "/broadcast" без текста
                    continue
                await bot.send_message(user_id, cleaned_text)

            # 4) На будущее — можно расширять: document/animation/audio/voice и т.д.
            else:
                # если прилетело что-то неподдерживаемое
                logging.warning("Неподдерживаемый тип для broadcast")
        except Exception as e:
            logging.error(f"Не удалось отправить {user_id}: {e}")
