import os
import threading
from flask import Flask, request, jsonify, abort

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier
import openai

# ─── Конфигурация ──────────────────────────────────────────────────────────────
openai.api_key = os.environ["OPENAI_API_KEY"]                   # обязательно
SLACK_BOT_TOKEN      = os.environ["SLACK_BOT_TOKEN"]            # Bot-User-OAuth
SLACK_SIGNING_SECRET = os.environ.get("SLACK_SIGNING_SECRET")   # Signing Secret

app            = Flask(__name__)
slack_client   = WebClient(token=SLACK_BOT_TOKEN)
sign_verifier  = SignatureVerifier(signing_secret=SLACK_SIGNING_SECRET)

# узнаём ID нашего бота, чтобы позже игнорировать свои же сообщения
BOT_ID = slack_client.auth_test()["user_id"]


# ─── Вспомогательная функция общения с OpenAI ──────────────────────────────────
def ask_gpt(user_text: str) -> str:
    """Обращается к GPT-4o и возвращает ответ."""
    response = openai.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": (
                    "Ты корпоративный ассистент компании BEM/JENCO. "
                    "Отвечай дружелюбно, кратко и по делу."
                ),
            },
            {"role": "user", "content": user_text},
        ],
        max_tokens=500,
        temperature=0.5,
    )
    return response.choices[0].message.content.strip()


# ─── Маршруты ──────────────────────────────────────────────────────────────────
@app.route("/", methods=["GET", "HEAD"])
def root():
    """Health-check для Render (возвращает 200)."""
    return "OK", 200


@app.route("/slack/commands", methods=["POST"])
def slash_commands():
    """Обрабатывает slash-команду  /gpt  (или любую другую, которую вы настроили)."""
    # Slack шлёт application/x-www-form-urlencoded → request.form
    if not sign_verifier.is_valid_request(request.get_data(), request.headers):
        abort(403)

    text       = request.form.get("text", "").strip() or "Пустой запрос."
    channel_id = request.form["channel_id"]
    user_id    = request.form["user_id"]

    # Быстрый ответ Slack'у, чтобы не истекал таймаут
    # (Slack требует ответить <3 сек.)
    def _async_work():
        answer = ask_gpt(text)
        try:
            slack_client.chat_postMessage(
                channel=channel_id,
                text=f"<@{user_id}> {answer}",
            )
        except SlackApiError as e:
            slack_client.chat_postMessage(
                channel=channel_id,
                text=f"Ошибка GPT: {e.response['error']}",
            )

    threading.Thread(target=_async_work, daemon=True).start()
    return jsonify(response_type="ephemeral", text="💬 Ответ отправлен в канал."), 200


@app.route("/slack/events", methods=["POST"])
def slack_events():
    """Endpoint для Events API."""
    # Slack шлёт JSON → request.get_json()
    if not sign_verifier.is_valid_request(request.get_data(), request.headers):
        abort(403)

    data = request.get_json()

    # Шаг 1 — Challenge verification при включении Events API
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data["challenge"]})

    # Шаг 2 — Обработка событий
    if data.get("type") == "event_callback":
        event = data["event"]

        # Игнорируем все сообщения от ботов (в том числе от себя)
        if event.get("subtype") == "bot_message" or event.get("user") == BOT_ID:
            return "OK", 200

        # Будем отвечать только на @упоминания, чтобы не захлестнуть канал
        if event.get("type") == "app_mention":
            user_id    = event["user"]
            channel_id = event["channel"]
            text       = event.get("text", "")

            def _async_mention():
                answer = ask_gpt(text)
                try:
                    slack_client.chat_postMessage(
                        channel=channel_id,
                        text=f"<@{user_id}> {answer}",
                    )
                except SlackApiError as e:
                    slack_client.chat_postMessage(
                        channel=channel_id,
                        text=f"Ошибка GPT: {e.response['error']}",
                    )

            threading.Thread(target=_async_mention, daemon=True).start()

    # Всегда отвечаем 200 OK, чтобы Slack не повторял событие
    return "OK", 200


# ─── Запуск приложения (важно для Render) ──────────────────────────────────────
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
