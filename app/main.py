from openai import OpenAI
import logging
import re
import asyncio
import csv
import io
import subs
from invoice import generate_invoice, get_company_info
from datetime import datetime, timedelta
from promting import inicial_start_promt
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, Message, InlineKeyboardMarkup, InlineKeyboardButton, LabeledPrice, PreCheckoutQuery, FSInputFile, BufferedInputFile
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ChatType, ChatAction
from config import (
    OPENAI_API_KEY,
    TELEGRAM_BOT_TOKEN,
    async_session,
    ADMIN_USER_ID,
    FREE_MESSAGES_LIMIT,
    PAYMENTS_TOKEN,
    SUBSCRIPTION_DURATION,
    SUPPORTED_EXTENSIONS
)
from database import init_db, ChatHistory, User, is_user_have_sub, is_user_have_limit
from sqlalchemy.future import select
from sqlalchemy import text
from sender import strip_broadcast, broadcast_send_same_content
# Создаем кнопки
button1 = KeyboardButton(text="📌 О нас")
button2 = KeyboardButton(text="📞 Связаться с нами")
button3 = KeyboardButton(text="📚 Полезные материалы")
button4 = KeyboardButton(text="📖 Инструкция")
button5 = KeyboardButton(text="⭐ Купить подписку")

# Создаем клавиатуру
keyboard = ReplyKeyboardMarkup(
    keyboard=[[button5], [button1], [button2], [button3], [button4]],  # Кнопки передаются списком списков
    resize_keyboard=True  # Уменьшаем размер клавиатуры
)
client = OpenAI(api_key=OPENAI_API_KEY)
# Инициализация бота с учетом новых изменений в aiogram 3.7+
session = AiohttpSession(timeout=180)
bot = Bot(token=TELEGRAM_BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"), session=session)
dp = Dispatcher()

# Логирование
logging.basicConfig(level=logging.INFO)

async def send_long_message(message: Message, text: str, chunk_size: int = 4000):
    for i in range(0, len(text), chunk_size):
        chunk = text[i:i+chunk_size]
        await message.answer(chunk, parse_mode="HTML")

async def upload_and_analyze_file(file_paths: list[str], user_query: str | None):
    if not user_query:
        user_query = "Проанализируй файл и пришли результаты анализа"

    # 1) Создаём vector store и загружаем туда файлы (у вас это уже есть)
    vector_store = client.vector_stores.create()

    file_streams = []
    try:
        file_streams = [open(path, "rb") for path in file_paths]

        client.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vector_store.id,
            files=file_streams,
        )

        # 2) ВОТ ЗДЕСЬ "ВСТАВЛЯЕТСЯ" интернет-поиск:
        #    вместо assistant/thread/run делаем один вызов Responses API
        resp = client.responses.create(
            model="gpt-5",
            tools=[
                {"type": "web_search"},
                {"type": "file_search", "vector_store_ids": [vector_store.id]},
            ],
            # если хотите принудительно искать в интернете — раскомментируйте:
            # tool_choice={"type": "web_search"},
            input=user_query,
        )

        return resp.output_text
    finally:
        # закрываем файлы
        for fs in file_streams:
            try:
                fs.close()
            except Exception:
                pass
        # чистим vector store
        try:
            client.vector_stores.delete(vector_store_id=vector_store.id)
        except Exception:
            pass

# Функция запроса к ChatGPT
async def chatgpt_response(prompt: str, from_user) -> str:
    try:
        sys_prompt = inicial_start_promt()
        # Загружаем историю диалога пользователя
        # result = await async_session().execute(
        #     select(ChatHistory)
        #     .where(ChatHistory.user_id == from_user.id)
        #     .order_by(ChatHistory.timestamp.asc(), ChatHistory.id.asc())
        # )
        # history_rows = result.scalars().all()

        # Формируем messages для ChatGPT
        messages = [{"role": "system", "content": sys_prompt}]
        # for row in history_rows:
        #     messages.append({"role": "user", "content": row.user_message})
        #     messages.append({"role": "assistant", "content": row.bot_response})

        # Добавляем новое сообщение
        messages.append({"role": "user", "content": prompt})
        user = await get_or_create_user(from_user)

        if user.subscription_type == 'pro':
            model = "gpt-5"
        else:
            model = "gpt-5-mini"

        # Отправляем запрос в модель
        # response = client.chat.completions.create(
        #     model=model,
        #     messages=messages,
        # )

        response = client.responses.create(
            model=model,
            tools=[{"type": "web_search"}],
            input=messages
        )

        return response.output_text
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
        await bot.send_message(ADMIN_USER_ID[0], f"⚠️ Ошибка в боте:\n<pre>{error_message}</pre>")
    except Exception as e:
        logging.error(f"Не удалось отправить сообщение администратору: {e}")


# Функция проверки или регистрации пользователя
async def get_or_create_user(tg_user, utm = None) -> User:
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.user_id == tg_user.id))
            user = result.scalars().first()

            if not user:
                user = User(user_id=tg_user.id,full_name=tg_user.first_name, username=tg_user.username, free_messages=FREE_MESSAGES_LIMIT, has_subscription=False, utm=utm)
                session.add(user)
                await session.commit()

            return user


# Кнопка "Купить подписку"
async def get_subscription_button():
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"Разовый запрос — {subs.get_subscription_info('buy_one_time').price}₽", callback_data="buy_one_time")],
        [InlineKeyboardButton(text=f"LITE — {subs.get_subscription_info('buy_subscription_lite').price} ₽/мес: ответы на любые вопросы, урезанные расшифровки", callback_data="buy_subscription_lite")],
        [InlineKeyboardButton(text=f"PRO — {subs.get_subscription_info('buy_subscription_pro').price} ₽/мес: развернутые ответы, поиск в интернете, поиск по файлам", callback_data="buy_subscription_pro")]
    ])
    return keyboard

# Функция покупки подписки
async def buy_subscription(user_id: int, subscription_type: str) -> User:
    async with async_session() as session:
        async with session.begin():
            result = await session.execute(select(User).where(User.user_id == user_id))
            user = result.scalars().first()

            if user:
                if subscription_type == 'one-time':
                    user.has_subscription = False
                    user.free_messages = 1
                else:
                    user.has_subscription = True
                    user.subscription_expiry = datetime.utcnow() + timedelta(days=SUBSCRIPTION_DURATION)

                user.subscription_type = subscription_type
                await session.commit()
    return user

# Обработчик команды /start
@dp.message(Command("start"))
async def cmd_start(message: Message):
    args = message.text.split(" ", 1)  # Разбиваем текст команды
    utm = args[1] if len(args) > 1 else None  # Извлекаем UTM-метку
    await get_or_create_user(message.from_user, utm)
    await message.answer(f"Здравствуйте, {message.from_user.full_name}! Я — ваш виртуальный Консультант.👋\n\n"
                         f"Здесь вы можете получить помощь по вопросам в области права, налогообложения и бухгалтерского учета. В любой момент вы можете задать мне {FREE_MESSAGES_LIMIT} вопроса, совершенно бесплатно 🤟\n\n"
                         f"Если вы готовы начать, просто напишите, что вам нужно или прикрепите файл для анализа", reply_markup=keyboard)

# 📌 О нас
@dp.message(lambda message: message.text == "📌 О нас")
async def about_bot(message: types.Message):
    text = (
        "🤖 Вот перечень того, что может Консультант:\n\n"
        "✅ Отвечает на вопросы по налогам и отчетности\n"
        "✅ Анализирует загруженные файлы\n"
        "✅ Помогает сдавать отчетность в срок\n"
        "✅ Уведомляет о важных изменениях\n\n"
        "📅 Подключите подписку для полного доступа\n"
        "Если вы хотите сгенерировать счет на оплату для юр.лиц\nИспользуй команду /invoice"
    )
    await message.answer(text)

# 📞 Связаться с нами
@dp.message(lambda message: message.text == "📞 Связаться с нами")
async def contact_support(message: types.Message):
    await message.answer("Вы всегда можете связаться через поддержку: @MARINA_HMA")

# ⭐ Купить подписку
@dp.message(lambda message: message.text == "⭐ Купить подписку")
async def contact_support(message: types.Message):
    keyboard = await get_subscription_button()
    await message.answer(
        "⭐ Нажмите на кнопку ниже, чтобы продолжить. Либо сгенерируйте счет для оплаты через юр.лицо с помощью команды /invoice.\n\nЧтобы ознакомиться со всеми видами подписки для юр.лиц, напишите @MARINA_HMA",
        reply_markup=keyboard)


# 📖 Инструкция (пример запроса)
@dp.message(lambda message: message.text == "📖 Инструкция")
async def send_instruction(message: types.Message):
    instruction_text = (
        "📌 *Пример запроса:*\n\n"
        "💬 _Как рассчитать налог на прибыль для ИП в 2025 году?_\n\n"
        "Вы можете задать любые вопросы связанные с бухгалтерией, правом и налогообложением"
    )
    await message.answer(instruction_text, parse_mode="MarkdownV2")

# 📚 Полезные материалы (отправка PDF)
@dp.message(lambda message: message.text == "📚 Полезные материалы")
async def send_pdf(message: types.Message):
    await bot.send_document(message.chat.id, FSInputFile("promt.pdf"), caption="📎 Вот полезные материалы, которые позволят более качественно формировать запрос в ИИ")

# Команда для рассылки (только админ)
@dp.message(
    (F.text.contains("/broadcast")) | (F.caption.contains("/broadcast"))
)
async def broadcast_from_forwarded(message: Message):
    if message.from_user.id not in ADMIN_USER_ID:
        return
    raw_text = message.text or message.caption or ""
    cleaned = strip_broadcast(raw_text)

    await message.answer("✅ Рассылка запущена!")
    await broadcast_send_same_content(message, cleaned)
    await message.answer("✅ Рассылка завершена!")

@dp.message(Command("damp"))
async def dump_chat_history(message: Message):
    if message.from_user.id not in ADMIN_USER_ID:
        await message.answer("⛔ Команда доступна только администратору.")
        return

    query = text(
        """
        select *
        from chat_history
        left join public.users u on chat_history.user_id = u.user_id
        order by timestamp desc
        """
    )

    try:
        async with async_session() as session:
            result = await session.execute(query)
            rows = result.mappings().all()

        if not rows:
            await message.answer("Выгрузка пустая: в таблице chat_history нет данных.")
            return

        headers = list(rows[0].keys())
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(rows)

        csv_bytes = output.getvalue().encode("utf-8")
        filename = f"chat_history_dump_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.csv"
        document = BufferedInputFile(csv_bytes, filename=filename)
        await message.answer_document(document, caption=f"✅ Выгрузка готова. Записей: {len(rows)}")
    except Exception as e:
        logging.error(f"Ошибка выгрузки /damp: {e}")
        await notify_admin(f"Ошибка выгрузки /damp: {e}")
        await message.answer("❌ Не удалось выполнить выгрузку.")

@dp.message(Command("invoice"))
async def send_invoice(message: types.Message):
    args = message.text.split()
    if len(args) != 2:
        await message.answer('Пожалуйста, укажите ИНН компании после команды /invoice. Например "/invoice 1655163150" ')
        return

    inn = args[1]
    company_info = await get_company_info(inn)

    if not company_info:
        await message.answer("❌ Компания не найдена. Проверьте ИНН и попробуйте снова.")
        return

    await message.answer("📄 Генерация счета...")
    pdf_path = await generate_invoice(company_info, message.from_user.id)
    pdf_file = FSInputFile(pdf_path)
    await message.answer_document(pdf_file, caption="✅ Ваш счет готов! При оплате, в назначении платежа необходимо указать номер счета и дату")

# Обработчик нажатия на кнопку "Купить подписку"
@dp.callback_query(lambda c: c.data in (
        "buy_subscription_lite",
        "buy_subscription_pro",
        "buy_one_time"
    ))
async def process_subscription(callback_query: types.CallbackQuery):
    subscription = subs.get_subscription_info(callback_query.data)

    user_id = callback_query.from_user.id
    # Определяем описание и payload
    if callback_query.data == "buy_one_time":
        title = "Разовый доступ к боту"
        description = subscription.description
    else:
        title = "Подписка на бота"
        description = f"{subscription.description} на {SUBSCRIPTION_DURATION} дней"

    await bot.send_invoice(user_id,
                           title=title,
                           description=description,
                           provider_token=PAYMENTS_TOKEN,
                           currency="rub",
                           photo_url="https://storage.yandexcloud.net/tgmaps/konsultant.png",
                           photo_width=2048,
                           photo_height=2048,
                           # photo_size=416,
                           is_flexible=False,
                           prices=[LabeledPrice(label=title, amount=subscription.price * 100)],
                           start_parameter="one-month-subscription",
                           payload=subscription.payload)
    await bot.send_message(
        user_id,
        "<i>Оплачивая подписку, вы принимаете условия оферты.</i>\n"
        "<i><a href=\"https://konsultantgpt.ru/oferta.pdf\">Публичная оферта</a> · "
        "<a href=\"https://konsultantgpt.ru/politica.pdf\">Политика ПДн</a></i>"
    )

# Обработка PreCheckoutQuery
@dp.pre_checkout_query()
async def pre_checkout_query_handler(pre_checkout_query: PreCheckoutQuery):
    await bot.answer_pre_checkout_query(pre_checkout_query.id, ok=True)

# Обработка успешного платежа
@dp.message(F.successful_payment)
async def successful_payment(message: types.Message):
    payment_info = message.successful_payment

    user = await buy_subscription(message.chat.id, payment_info.invoice_payload)
    await bot.send_message(message.chat.id,
                           f"🥳Спасибо за покупку! Подписка {user.subscription_type} готова к использованию")

# 🔹 2. Принимаем файлы
@dp.message(lambda message: message.document)
async def handle_document(message: Message):
    document = message.document
    user_id = message.from_user.id
    user_text = message.caption

    file_id = document.file_id
    file_info = await bot.get_file(file_id)
    file_extension = document.file_name.split(".")[-1]

    if not await is_user_have_sub(user_id):
        keyboard = await get_subscription_button()
        await message.answer("❌ Ваш лимит бесплатных сообщений исчерпан. Купите подписку, чтобы продолжить. Либо сгенерируйте счет для оплаты через юр.лицо с помощью команды /invoice. Если вас интересует подписка на более длительный срок, напишите @MARINA_HMA",
                             reply_markup=keyboard)
        return

    if not await is_user_have_limit(user_id):
        await message.answer("Ой! Похоже, на сегодня лимит «искр вдохновения» исчерпан. ✨ \nЧтобы сервис работал стабильно для всех, сейчас действует ограничение: 5 запросов в день. \nВаша порция на сегодня подошла к концу, но не грустите — счетчик обновится уже завтра, и мы снова будем на связи!Буду очень ждать вас завтра, чтобы продолжить наше общение. Спасибо, что вы с нами! 🙌")
        return

    async with async_session() as session:
        result = await session.execute(select(User).where(User.user_id == user_id))
        user = result.scalars().first()
    if user and user.subscription_type == "lite":
        keyboard = await get_subscription_button()
        await message.answer(
            "📎 Анализ файлов недоступен на тарифе LITE. Перейдите на PRO, чтобы использовать поиск по файлам.",
            reply_markup=keyboard
        )
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

    await send_long_message(message, htmlText)

# Обработчик сообщений
@dp.message()
async def handle_message(message: Message):
    user_id = message.from_user.id
    user_text = message.text
    if message.new_chat_members:
        await bot.send_message(message.chat.id, "Спасибо, что добавили меня в группу! 🎉 Чтобы каждый пользователь мог работать со мной в чате, он должен написать мне в личных сообщениях /start, если до этого не писал. Так же не забудьте подключить груповую подписку!")
        return
    if message.left_chat_member:
        return
    if message.chat.type in [ChatType.GROUP, ChatType.SUPERGROUP]:
        if not await is_user_have_sub(user_id):
            keyboard = await get_subscription_button()
            await message.answer(
                "❌ Ваш лимит бесплатных сообщений исчерпан. Купите подписку, чтобы продолжить. Либо сгенерируйте счет для оплаты через юр.лицо с помощью команды /invoice. Если вас интересует подписка на более длительный срок, напишите @MARINA_HMA",
                reply_markup=keyboard)
            return

        if not await is_user_have_limit(user_id):
            await message.answer(
                "Ой! Похоже, на сегодня лимит «искр вдохновения» исчерпан. ✨ \nЧтобы сервис работал стабильно для всех, сейчас действует ограничение: 5 запросов в день. \nВаша порция на сегодня подошла к концу, но не грустите — счетчик обновится уже завтра, и мы снова будем на связи!Буду очень ждать вас завтра, чтобы продолжить наше общение. Спасибо, что вы с нами! 🙌")
            return
    if not user_text:
        return
    if not await is_user_have_sub(user_id):
        keyboard = await get_subscription_button()
        await message.answer("❌ Ваш лимит бесплатных сообщений исчерпан. Купите подписку, чтобы продолжить. Либо сгенерируйте счет для оплаты через юр.лицо с помощью команды /invoice. Если вас интересует подписка на более длительный срок, напишите @MARINA_HMA",
                             reply_markup=keyboard)
        return

    if not await is_user_have_limit(user_id):
        await message.answer("Ой! Похоже, на сегодня лимит «искр вдохновения» исчерпан. ✨ \nЧтобы сервис работал стабильно для всех, сейчас действует ограничение: 5 запросов в день. \nВаша порция на сегодня подошла к концу, но не грустите — счетчик обновится уже завтра, и мы снова будем на связи!Буду очень ждать вас завтра, чтобы продолжить наше общение. Спасибо, что вы с нами! 🙌")
        return

    # Отправляем эффект "печатает..."
    await message.answer("⏳ Ответ может занять некоторое время…")
    await bot.send_chat_action(chat_id=message.chat.id, action=ChatAction.TYPING)

    response_text = await chatgpt_response(user_text, message.from_user)

    htmlText = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', response_text)
    htmlText = re.sub(r'\[(.*?)\]\((.*?)\)', r'<a href="\2">\1</a>', htmlText)
    htmlText = htmlText.replace("?utm_source=openai", "")
    # Сохраняем в базу данных
    await send_long_message(message, htmlText)
    await save_message(user_id, user_text, response_text)

    # await message.answer(htmlText, parse_mode="HTML")


# Функция запуска бота
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
