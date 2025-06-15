# main.py
# ────────────────────────────────────────────────────────────────────────────
"""
JENCO GPT Slack-Bot
──────────────────
Минимальное Flask-приложение, которое:
  • проверяет /health (GET /) — важен для Render/K8s-проб;
  • обрабатывает входящие события Slack (POST /slack/events);
  • пересылает текстовые сообщения в OpenAI (gpt-4o, gpt-4o-mini и т.д.);
  • отправляет ответ обратно в канал.
Лёгкая запись логов + опциональная верификация подписи Slack.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from typing import Any

import openai
from flask import Flask, abort, request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier
from dotenv import load_dotenv

# ─── Загружаем .env (локально) ───────────────────────────────────────────────
load_dotenv(override=False)

# ─── Обязательные переменные окружения ───────────────────────────────────────
OPENAI_API_KEY        = os.getenv("OPENAI_API_KEY")
SLACK_BOT_TOKEN       = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET  = os.getenv("SLACK_SIGNING_SECRET")  # можно None

REQUIRED_ENV_VARS = {
    "OPENAI_API_KEY": OPENAI_API_KEY,
    "SLACK_BOT_TOKEN": SLACK_BOT_TOKEN,
}
missing = [k for k, v in REQUIRED_ENV_VARS.items() if not v]
if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

# ─── Инициализация внешних SDK ───────────────────────────────────────────────
openai.api_key = OPENAI_API_KEY
slack_client   = WebClient(token=SLACK_BOT_TOKEN)
sign_verifier  = SignatureVerifier(SLACK_SIGNING_SECRET) if SLACK_SIGNING_SECRET else None

# ─── Flask-приложение ────────────────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

# Health-check (Render / Kubernetes etc.)
@app.get("/")
def health() -> tuple[dict[str, str], int]:
    return {"status": "ok", "service": "JENCO GPT Slack Bot"}, 200


@app.post("/slack/events")
def slack_events() -> tuple[str, int]:
    """
    Базовый обработчик slash-команд и сообщений (event_subscriptions → 'messages').
    Slack шлёт форму application/x-www-form-urlencoded.
    """
    # Защита от бесконечных ретраев Slack (Retry-Num header)
    if request.headers.get("X-Slack-Retry-Num"):
        return "retry_ack", 200

    # Валидация подписи Slack (если задан секрет)
    if sign_verifier and not sign_verifier.is_valid_request(
        request.get_data(), request.headers
    ):
        logging.warning("⚠️  Invalid Slack signature")
        abort(400, description="Invalid signature")

    form = request.form

    # Команда /slash → challenge / event callback (url_verification)
    if form.get("type") == "url_verification":
        return form.get("challenge", ""), 200

    # Текст и метаданные
    text: str | None     = form.get("text")
    channel_id: str | None = form.get("channel_id")
    user_id: str | None    = form.get("user_id")

    if not (text and channel_id and user_id):
        logging.warning("⚠️  Ignored empty payload")
        return "ignored", 200

    def ask_gpt(message: str, channel: str, user: str) -> None:
        """Запуск в отдельном потоке, чтобы не блокировать Slack."""
        try:
            response: dict[str, Any] = openai.chat.completions.create(
                model="gpt-4o-mini",  # можно заменить на gpt-4o
                messages=[
                    {
                        "role": "system",
                        "content": "Ты корпоративный ассистент компании BEM/JENCO.",
                    },
                    {"role": "user", "content": message},
                ],
                max_tokens=500,
                temperature=0.4,
            )
            answer: str = response.choices[0].message.content.strip()
            slack_client.chat_postMessage(channel=channel, text=f"<@{user}> {answer}")
        except SlackApiError as e:
            logging.error("Slack API error: %s", e)
        except Exception as e:
            logging.exception("GPT error: %s", e)
            slack_client.chat_postMessage(
                channel=channel, text=f"<@{user}> GPT Error: {e}"
            )

    threading.Thread(target=ask_gpt, args=(text, channel_id, user_id), daemon=True).start()
    return "OK", 200


# ─── Запуск локально / gunicorn ──────────────────────────────────────────────
if __name__ == "__main__":
    # PORT приходит от Render, Railway, Heroku и др.
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
