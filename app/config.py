from PIL.WebPImagePlugin import SUPPORTED
from dotenv import load_dotenv
import os
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

# Загрузка переменных окружения
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
PAYMENTS_TOKEN = os.getenv("PAYMENTS_TOKEN")
SUPPORTED_EXTENSIONS = ["pdf", "txt", "docx", "pptx", "html", "doc"]

# Подключение к PostgreSQL
DATABASE_URL = f"postgresql+asyncpg://{os.getenv('POSTGRES_USER')}:{os.getenv('POSTGRES_PASSWORD')}@db/{os.getenv('POSTGRES_DB')}"
engine = create_async_engine(DATABASE_URL, echo=False)
async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

# ID администратора для уведомлений об ошибках
ADMIN_USER_ID = 316028838
SUBSCRIPTION_PRICE = 1000
SUBSCRIPTION_DURATION = 7
FREE_MESSAGES_LIMIT = 5
