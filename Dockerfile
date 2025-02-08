# Базовый образ для Python 3.13 (замените на актуальный, если версия изменится)
FROM python:3.13-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Устанавливаем системные зависимости (например, libgomp для faiss)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Копируем и устанавливаем зависимости Python
COPY requirements.txt /app/requirements.txt
COPY .env /app/.env
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Копируем код приложения
COPY ./app /app

# Открываем порт приложения
#EXPOSE 5555

# Запуск приложения
CMD ["python", "main.py"]