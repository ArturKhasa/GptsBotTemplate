from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import Column, Integer, String, DateTime, Text, func, Index, Boolean
from config import engine

# Базовый класс
class Base(DeclarativeBase):
    pass

# Модель пользователя
class User(Base):
    __tablename__ = "users"

    user_id = Column(Integer, primary_key=True)
    full_name = Column(String, nullable=True)
    username = Column(String, nullable=True)
    free_messages = Column(Integer, default=10)  # Количество бесплатных сообщений
    has_subscription = Column(Boolean, default=False)  # Флаг подписки
    subscription_expiry = Column(DateTime, nullable=True)  # Дата окончания подписки


# Модель хранения истории запросов
class ChatHistory(Base):
    __tablename__ = "chat_history"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False)
    user_message = Column(Text, nullable=False)
    bot_response = Column(Text, nullable=False)
    timestamp = Column(DateTime, server_default=func.now())

    # Альтернативный способ создания индекса (если нужно явное название)
    __table_args__ = (
        Index("idx_user_id", "user_id"),
    )

# Создание таблиц
async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)