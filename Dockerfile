# Более стабильная база с доступным wkhtmltopdf
FROM python:3.13-slim-bookworm

WORKDIR /app

# Системные зависимости
RUN apt-get update && apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    libgomp1 \
 && rm -rf /var/lib/apt/lists/*

# Python-зависимости
COPY requirements.txt /app/requirements.txt
COPY .env /app/.env
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# Код приложения
COPY ./app /app

# Указываем путь (в bookworm это /usr/bin/wkhtmltopdf)
ENV WKHTMLTOPDF_PATH=/usr/bin/wkhtmltopdf

CMD ["python", "main.py"]
