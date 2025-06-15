import os
import time
import logging
from collections import deque

from flask import Flask, request, jsonify
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from openai import OpenAI

# ────── Настройка ──────────────────────────────────────────────────────────────
load_dotenv()

SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
OPENAI_API_KEY  = os.getenv("OPENAI_API_KEY")

openai_client  = OpenAI(api_key=OPENAI_API_KEY)
slack_client   = WebClient(token=SLACK_BOT_TOKEN)

logging.basicConfig(level=logging.INFO, format="%(asctime)s ▶ %(levelname)s ▶ %(message)s")

# Запоминаем последние 100 ID событий, чтобы не обрабатывать дубликаты
recent_event_ids: deque[str] = deque(maxlen=100)

app = Flask(__name__)

# ────── Health-check ──────────────────────────────────────────────────────────
@app.get("/")
def health():
    return "JENCO-GPT bot is running", 200

# ────── Главный эндпоинт Slack ────────────────────────────────────────────────
@app.post("/slack/events")
def slack_events():
    # Slack slash-command присылает form-urlencoded, а Events API — JSON
    if request.content_type == "application/x-www-form-urlencoded":
        return handle_slash_command(request.form)

    data = request.get_json(silent=True) or {}
    logging.debug(f"Incoming JSON: {data}")

    # 1. Проверка URL (challenge)
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # 2. Сами события
    if data.get("type") == "event_callback":
        event_id = data.get("event_id")
        if event_id in recent_event_ids:
            return "", 200  # уже обработали
        recent_event_ids.append(event_id)

        event = data.get("event", {})

        # Интересуют только упоминания бота пользователем
        if event.get("type") == "app_mention" and not event.get("bot_id"):
            handle_app_mention(event)

    return "", 200

# ────── Обработка /gpt … ──────────────────────────────────────────────────────
def handle_slash_command(form):
    user_id   = form.get("user_id")
    channel   = form.get("channel_id")
    text      = form.get("text", "").strip()

    if not text:
        return jsonify(
            response_type="ephemeral",
            text="⚠️ Нужно написать вопрос после `/gpt`."
        )

    answer = ask_openai(text)

    try:
        slack_client.chat_postMessage(channel=channel, text=answer)
    except SlackApiError as e:
        logging.error(f"Slack error on slash command: {e.response['error']}")

    # Мгновенный response Slack’у, чтобы не ждать 3 сек
    return jsonify(response_type="in_channel", text="💬 Ответ отправлен в канал.")

# ────── Обработка @bot … ──────────────────────────────────────────────────────
def handle_app_mention(event: dict):
    channel = event.get("channel")
    user_id = event.get("user")
    raw    = event.get("text", "")
    # Убираем упоминание <@BOTID>
    prompt = raw.split(">", 1)[-1].strip()

    answer = ask_openai(prompt)

    message = f"<@{user_id}> {answer}"
    try:
        slack_client.chat_postMessage(channel=channel, text=message)
    except SlackApiError as e:
        logging.error(f"Slack error on mention: {e.response['error']}")

# ────── Вызов OpenAI ──────────────────────────────────────────────────────────
def ask_openai(prompt: str) -> str:
    try:
        response = openai_client.chat.completions.create(
            model="gpt-4o-mini",          # можно заменить на gpt-4 или gpt-3.5
            messages=[
                {"role": "system", "content": "Ты корпоративный ассистент компании BEM/JENCO."},
                {"role": "user",    "content": prompt}
            ],
            max_tokens=500,
            temperature=0.5,
            timeout=30    # секунд
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logging.error(f"OpenAI error: {e}")
        return "⚠️ Произошла ошибка при обращении к GPT."

# ────── Запуск (нужно для Render) ─────────────────────────────────────────────
if __name__ == "__main__":
    # Render сам назначит переменную PORT, но мы фиксируем 10000, чтобы логи совпадали
    app.run(host="0.0.0.0", port=10000)
