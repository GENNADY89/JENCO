#!/usr/bin/env python3
"""JENCO‑GPT‑BOT main entry‑point.

• Слушает события Slack (`/slack/events`)  
• Обрабатывает slash‑команду `/gpt`  
• Делает запрос к OpenAI и отправляет ответ в тот же канал / тред.

Перед запуском ОБЯЗАТЕЛЬНЫ переменные окружения:
    SLACK_SIGNING_SECRET – из Your App → Basic Information → Signing Secret
    SLACK_BOT_TOKEN      – Bot OAuth Token (xoxb‑…)
    OPENAI_API_KEY       – ключ OpenAI

Render автоматически задаёт PORT, поэтому app.run() берёт его из env.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict

from flask import Flask, jsonify, make_response, request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier

# ---------------------------------------------------------------------------
#  Конфигурация и проверки окружения
# ---------------------------------------------------------------------------
REQUIRED_VARS = ("SLACK_SIGNING_SECRET", "SLACK_BOT_TOKEN", "OPENAI_API_KEY")
missing = [name for name in REQUIRED_VARS if not os.getenv(name)]
if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
SLACK_BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]

# ---------------------------------------------------------------------------
#  Логирование
# ---------------------------------------------------------------------------
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
#  Инициализация библиотек
# ---------------------------------------------------------------------------
app = Flask(__name__)
client = WebClient(token=SLACK_BOT_TOKEN)
sign_verifier = SignatureVerifier(SLACK_SIGNING_SECRET)

# ---------------------------------------------------------------------------
#  Вспомогательные функции
# ---------------------------------------------------------------------------

def chatgpt(prompt: str) -> str:
    """Отправляем запрос в OpenAI и возвращаем ответ."""
    import openai  # импортируем внутри функции, чтобы не тянуть при unit‑тестах

    openai.api_key = OPENAI_API_KEY
    try:
        resp = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.8,
            max_tokens=512,
        )
        return resp.choices[0].message.content.strip()
    except Exception as exc:  # pylint: disable=broad-except
        log.exception("OpenAI API error: %s", exc)
        return "⚠️ Sorry, I couldn't get a response from OpenAI."


def _post_message(channel: str, text: str, thread_ts: str | None = None) -> None:
    """Отправляем сообщение в Slack с базовой обработкой ошибок."""
    try:
        client.chat_postMessage(channel=channel, text=text, thread_ts=thread_ts)
    except SlackApiError as err:
        log.error("Slack API error: %s", err.response["error"])


# ---------------------------------------------------------------------------
#  HTTP‑маршруты
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])  # health‑check
def index():  # noqa: D401  (простая функция‑хэндлер)
    return "JENCO‑GPT‑BOT is alive ✔", 200


@app.route("/slack/events", methods=["POST"])
def slack_events():
    """Главный приёмник событий Slack Events API."""
    # 1) обработка повторных доставок от Slack
    if request.headers.get("X-Slack-Retry-Num"):
        return make_response("No need to retry", 200)

    # 2) проверка подписи
    if not sign_verifier.is_valid_request(request.get_data(), request.headers):
        log.warning("Invalid Slack signature → 403")
        return make_response("Invalid request", 403)

    payload: Dict[str, Any] = request.get_json(force=True, silent=True) or {}

    # 3) URL‑verification (первичная валидация эндпоинта)
    if payload.get("type") == "url_verification":
        return jsonify({"challenge": payload.get("challenge")})

    # 4) event_callback
    if payload.get("type") == "event_callback":
        handle_event(payload.get("event", {}))

    return "", 200


def handle_event(event: Dict[str, Any]):
    """Обработка отдельных ивентов."""
    etype = event.get("type")
    if etype == "app_mention":
        _on_app_mention(event)
    # Можно добавить другие события при необходимости (message.channels и т.д.)


def _on_app_mention(event: Dict[str, Any]):
    """Ответ на упоминание бота @JENCO‑GPT‑ASSISTANT …"""
    channel = event.get("channel")
    thread_ts = event.get("ts")

    raw_text: str = event.get("text", "")
    prompt = raw_text.split("<@", 1)[-1].split(">", 1)[-1].strip() or "Привет! Чем могу помочь?"

    answer = chatgpt(prompt)
    _post_message(channel, answer, thread_ts=thread_ts)


@app.route("/gpt", methods=["POST"])  # Slash‑command endpoint
def slash_gpt():  # noqa: D401
    # Проверяем подпись
    if not sign_verifier.is_valid_request(request.get_data(), request.headers):
        return make_response("Invalid request", 403)

    form = request.form
    channel_id = form.get("channel_id")
    prompt = form.get("text", "").strip() or "Привет! Чем могу помочь?"

    # Отвечаем сразу Slack'у ack, чтобы не словить timeout (3 сек)
    ack_body = {
        "response_type": "ephemeral",
        "text": "💭 Ответ отправляется в канал…"
    }

    # Async‑обработка (без Celery, просто fire‑and‑forget)
    from threading import Thread

    Thread(target=lambda: _post_message(channel_id, chatgpt(prompt))).start()

    return jsonify(ack_body)


# ---------------------------------------------------------------------------
#  Запуск локального сервера
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
