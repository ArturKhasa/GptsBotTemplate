from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import BigInteger,Column, Integer, String, DateTime, Text, func, Index, Boolean
from config import engine
from migrate_once import ensure_subscription_type_pg
from sqlalchemy import select, func
from datetime import datetime, timedelta
from config import (
    async_session,
    DAILY_LIMIT
)

# Базовый класс
class Base(DeclarativeBase):
    pass

# Модель пользователя
class User(Base):
    __tablename__ = "users"

    user_id = Column(BigInteger, primary_key=True)
    full_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    free_messages = Column(Integer, default=10)  # Количество бесплатных сообщений
    has_subscription = Column(Boolean, default=False)  # Флаг подписки
    subscription_expiry = Column(DateTime, nullable=True)  # Дата окончания подписки
    utm = Column(String, nullable=True) # Метки
    subscription_type = Column(String, nullable=True)


# Модель хранения истории запросов
class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(BigInteger, nullable=False)
    user_message = Column(Text, nullable=False)
    bot_response = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())

    # Альтернативный способ создания индекса (если нужно явное название)
    __table_args__ = (
        Index("idx_user_id", "user_id"),
    )

async def is_user_have_sub(user_id: int) -> bool:
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalars().first()
            if not user:
                return False

            # подписка
            if user.has_subscription:
                if user.subscription_expiry and user.subscription_expiry <= now_utc:
                    user.has_subscription = False
                    await session.commit()
                    return False
                return True

            # бесплатные
            if user.free_messages > 0:
                user.free_messages -= 1
                await session.commit()
                return True

            return False


async def is_user_have_limit(user_id: int) -> bool:
    now_utc = datetime.utcnow()
    start_of_day_utc = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    next_day_utc = start_of_day_utc + timedelta(days=1)
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalars().first()
            if not user:
                return False
            # ✅ суточный лимит для всех (в т.ч. подписчиков)
            cnt_q = await session.execute(
                select(func.count(ChatHistory.id)).where(
                    ChatHistory.user_id == user_id,
                    ChatHistory.timestamp >= start_of_day_utc,
                    ChatHistory.timestamp < next_day_utc,
                )
            )
            used_today = cnt_q.scalar_one()
            if used_today >= DAILY_LIMIT:
                return False

# Создание таблиц
async def init_db():
    await ensure_subscription_type_pg(engine)
    async with engine.begin() as conn:

        await conn.run_sync(Base.metadata.create_all)