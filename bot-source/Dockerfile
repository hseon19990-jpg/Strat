FROM python:3.11-slim

WORKDIR /app

COPY bot_repo/telegram-bot/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bot_repo/telegram-bot/ .

CMD ["python", "bot.py"]