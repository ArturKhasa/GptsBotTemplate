from openai import OpenAI
import openai
import time
import logging
import re
import asyncio
from datetime import datetime, timedelta
from promting import inicial_start_promt
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, Document, PreCheckoutQuery
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatAction
from config import (
    OPENAI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    async_session,
    ADMIN_USER_ID,
    SUBSCRIPTION_PRICE,
    FREE_MESSAGES_LIMIT,
    PAYMENTS_TOKEN,
    SUBSCRIPTION_DURATION,
    SUPPORTED_EXTENSIONS
)
from database import init_db, ChatHistory, User
from sqlalchemy.future import select

client = OpenAI(api_key=OPENAI_API_KEY)
# Инициализация бота с учетом новых изменений в aiogram 3.7+
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Логирование
logging.basicConfig(level=logging.INFO)

async def upload_and_analyze_file(file_paths: [], user_query):
    if not user_query:
        user_query = "Проанализируй файл и пришли результаты анализа"

    assistant = client.beta.assistants.create(
        name="Эксперт в бухгалтерии",
        instructions=inicial_start_promt(),
        model="gpt-4o",
        tools=[{"type": "file_search"}],
    )

    vector_store = client.beta.vector_stores.create()
    file_streams = [open(path, "rb") for path in file_paths]
    file_batch = client.beta.vector_stores.file_batches.upload_and_poll(
        vector_store_id=vector_store.id, files=file_streams
    )
    thread = client.beta.threads.create(
        messages=[
            {
                "role": "user",
                "content": user_query
            }
        ]
    )

    assistant = client.beta.assistants.update(
        assistant_id=assistant.id,
        tool_resources={"file_search": {"vector_store_ids": [vector_store.id]}},
    )

    # Запускаем задачу
    run = openai.beta.threads.runs.create(
        thread_id=thread.id,
        assistant_id=assistant.id
    )
    run_id = run.id

    # Ожидаем завершения задачи
    while True:
        run_status = openai.beta.threads.runs.retrieve(thread_id=thread.id, run_id=run_id)
        if run_status.status == "completed":
            break
        time.sleep(2)

    # Получаем ответ
    messages = openai.beta.threads.messages.list(thread_id=thread.id)
    for msg in messages.data:
        if msg.role == "assistant":
            client.beta.vector_stores.delete(vector_store_id=vector_store.id)
            return msg.content[0].text.value

    return "Не удалось получить ответ от OpenAI."

# Функция запроса к ChatGPT
async def chatgpt_response(prompt: str) -> str:
    try:
        sys_prompt = inicial_start_promt()
        response = client.chat.completions.create(model="gpt-4o-mini",
        messages=[{"role": "system", "content": sys_prompt},
                  {"role": "user", "content": prompt}],
        temperature=0.2)
        return response.choices[0].message.content
    except Exception as e:
        logging.error(f"Ошибка OpenAI: {e}")
        await notify_admin(f"Ошибка OpenAI: {e}")
        return "Ошибка при обработке запроса."

# Функция сохранения истории запросов в PostgreSQL
async def save_message(user_id: int, user_message: str, bot_response: str):
    try:
        async with async_session() as session:
            async with session.begin():
                new_entry = ChatHistory(
                    user_id=user_id,
                    user_message=user_message,
                    bot_response=bot_response
                )
                session.add(new_entry)
    except Exception as e:
        logging.error(f"Ошибка сохранения в БД: {e}")
        await notify_admin(f"Ошибка БД: {e}")

# Функция для уведомления администратора в Telegram
async def notify_admin(error_message: str):
    try:
        await bot.send_message(ADMIN_USER_ID, f"⚠️ Ошибка в боте:\n<pre>{error_message}</pre>")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение администратору: {e}")


# Функция проверки или регистрации пользователя
async def get_or_create_user(tg_user, utm) -> User:
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.user_id == tg_user.id))
            user = result.scalars().first()

            if not user:
                user = User(user_id=tg_user.id,full_name=tg_user.first_name, username=tg_user.username, free_messages=FREE_MESSAGES_LIMIT, has_subscription=False, utm=utm)
                session.add(user)
                await session.commit()

            return user

# Функция рассылки сообщений всем пользователям
async def broadcast_message(text: str):
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(select(User.user_id))
            users = result.scalars().all()

            for user_id in users:
                try:
                    await bot.send_message(user_id, text)
                except Exception as e:
                    logging.error(f"Не удалось отправить сообщение {user_id}: {e}")

# Проверка на наличие подписки или сокращение лимита
async def can_user_send_message(user_id: int) -> bool:
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalars().first()

            if user and user.has_subscription:
                if user.subscription_expiry <= datetime.now():
                    user.has_subscription = False
                    await session.commit()
                    return False
                return True  # У подписчика нет ограничений

            if user and user.free_messages > 0:
                user.free_messages -= 1  # Уменьшаем лимит
                await session.commit()
                return True

            return False

# Кнопка "Купить подписку"
async def get_subscription_button():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Купить подписку ({SUBSCRIPTION_PRICE} руб на {SUBSCRIPTION_DURATION} дн.)", callback_data="buy_subscription")]
    ])
    return keyboard

# Функция покупки подписки
async def buy_subscription(user_id: int) -> User:
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalars().first()

            if user:
                user.has_subscription = True
                user.subscription_expiry = datetime.utcnow() + timedelta(days=SUBSCRIPTION_DURATION)
                # user.free_messages = FREE_MESSAGES_LIMIT
                await session.commit()
    return user

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    args = message.text.split(" ", 1)  # Разбиваем текст команды
    utm = args[1] if len(args) > 1 else None  # Извлекаем UTM-метку
    await get_or_create_user(message.from_user, utm)
    # await message.answer(f"👋 Привет, {message.from_user.full_name}! Я ваш помощник по бухгалтерии. Задавайте вопросы!")
    await message.answer(f"Привет, {message.from_user.full_name}! Я — твой виртуальный бухгалтер.👋\n\n"
                         f"Здесь ты можешь получить помощь по бухгалтерским вопросам, рассчитать налоги, узнать сроки сдачи отчётности или получить советы по ведению учёта. В любой момент ты можешь задать мне {FREE_MESSAGES_LIMIT} вопросов, совершенно бесплатно! 🤟\n\n"
                         f"Если ты готов начать, просто напиши, что тебе нужно или прикрепи файл для анализа!")

# Команда для рассылки (только админ)
@dp.message(Command("broadcast"))
async def cmd_broadcast(message: Message):
    if message.from_user.id != ADMIN_USER_ID:
        await message.answer("❌ У вас нет прав на отправку рассылки.")
        return

    text = message.text.replace("/broadcast", "").strip()
    if not text:
        await message.answer("❌ Пожалуйста, укажите текст рассылки.")
        return

    await message.answer(f"✅ Рассылка запущена!")
    await broadcast_message(text)
    await message.answer("✅ Рассылка завершена!")

# Обработчик нажатия на кнопку "Купить подписку"
@dp.callback_query(lambda c: c.data == "buy_subscription")
async def process_subscription(callback_query: types.CallbackQuery):
    user_id = callback_query.from_user.id
    await bot.send_invoice(user_id,
                           title="Подписка на бота",
                           description=f"БЕЗЛИМИТ на {SUBSCRIPTION_DURATION} дней",
                           provider_token=PAYMENTS_TOKEN,
                           currency="rub",
                           photo_url="https://storage.yandexcloud.net/tgmaps/buh.jpg",
                           photo_width=1024,
                           photo_height=1024,
                           # photo_size=416,
                           is_flexible=False,
                           prices=[LabeledPrice(label="Подписка на бота", amount=SUBSCRIPTION_PRICE * 100)],
                           start_parameter="one-month-subscription",
                           payload="test-invoice-payload")

# Обработка PreCheckoutQuery
@dp.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# Обработка успешного платежа
@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment_info = message.successful_payment
    logging.info(payment_info)
    user = await buy_subscription(message.chat.id)
    await bot.send_message(message.chat.id,
                           f"🥳Подписка продлена до {user.subscription_expiry.date()}")

# 🔹 2. Принимаем файлы
@dp.message(lambda message: message.document)
async def handle_document(message: Message):
    document = message.document
    user_id = message.from_user.id
    user_text = message.caption

    file_id = document.file_id
    file_info = await bot.get_file(file_id)
    file_extension = document.file_name.split(".")[-1]

    if not await can_user_send_message(user_id):
        keyboard = await get_subscription_button()
        await message.answer("❌ Ваш лимит бесплатных сообщений исчерпан. Купите подписку, чтобы продолжить.",
                             reply_markup=keyboard)
        return

    if file_extension not in SUPPORTED_EXTENSIONS:
        await message.answer(f"⚠️ Я поддерживаю файлы формата: {', .'.join(SUPPORTED_EXTENSIONS)}\nЕсли Ваш файл формата Excel, Вы можете прислать мне его в текстовом формате")
        return

    # Сохраняем файл локально
    await bot.download_file(file_info.file_path, document.file_name)

    await message.answer(f"📤 Анализируем файл {document.file_name}, пожалуйста подождите максимум 30 секунд...")

    # Отправляем эффект "печатает..."
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    response_text = await upload_and_analyze_file([document.file_name], user_text)
    # Сохраняем в базу данных
    await save_message(user_id, user_text if user_text else document.file_name, response_text)
    htmlText = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', response_text)

    await message.answer(f"📄 Результат анализа:\n\n{htmlText}", parse_mode="HTML")

# Обработчик сообщений
@dp.message()
async def handle_message(message: Message):
    user_id = message.from_user.id
    user_text = message.text
    if not await can_user_send_message(user_id):
        keyboard = await get_subscription_button()
        await message.answer("❌ Ваш лимит бесплатных сообщений исчерпан. Купите подписку, чтобы продолжить.", reply_markup=keyboard)
        return

    # Отправляем эффект "печатает..."
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    response_text = await chatgpt_response(user_text)
    # Сохраняем в базу данных
    await save_message(user_id, user_text, response_text)
    htmlText = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', response_text)
    await message.answer(htmlText, parse_mode="HTML")


# Функция запуска бота
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())