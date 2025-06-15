import os, json, logging
from flask import Flask, request, make_response, jsonify
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
from openai import OpenAI

# -----------------------------------------------------------------------------
# 0.  Переменные окружения (НУЖНЫ В Рендере!)
#     - SLACK_BOT_TOKEN        — Bot User OAuth Token «xoxb-…»
#     - SLACK_SIGNING_SECRET   — Signing Secret
#     - OPENAI_API_KEY         — ключ OpenAI
# -----------------------------------------------------------------------------
SLACK_BOT_TOKEN      = os.environ["SLACK_BOT_TOKEN"]
SLACK_SIGNING_SECRET = os.environ["SLACK_SIGNING_SECRET"]
OPENAI_API_KEY       = os.environ["OPENAI_API_KEY"]

# -----------------------------------------------------------------------------
app            = Flask(__name__)
log            = logging.getLogger(__name__)
slack_client   = WebClient(token=SLACK_BOT_TOKEN)
sign_verifier  = SignatureVerifier(SLACK_SIGNING_SECRET)
openai_client  = OpenAI(api_key=OPENAI_API_KEY)
# -----------------------------------------------------------------------------

@app.route("/", methods=["GET"])
def health():
    """Render пингует корень — вернём 200, чтобы не было 404."""
    return "OK", 200

# ------------------------------------------------------------------  SLACK EVENTS
@app.route("/slack/events", methods=["POST"])
def slack_events():
    if not sign_verifier.is_valid_request(request.get_data(), request.headers):
        return "invalid signature", 403

    payload = request.get_json(force=True)

    # 1) challenge — верификация URL
    if payload.get("type") == "url_verification":
        return jsonify({"challenge": payload["challenge"]})

    # 2) обычное событие
    event = payload.get("event", {})
    # игнорируем собственные сообщения, чтобы не спамить
    if event.get("bot_id"):
        return "", 200

    # пример: реакция на @mention
    if event.get("type") == "app_mention":
        user   = event["user"]
        text   = event.get("text", "")
        thread = event.get("ts")

        answer = chat_gpt(text)
        slack_client.chat_postMessage(
            channel=event["channel"],
            text=answer,
            thread_ts=thread,
        )

    return "", 200

# --------------------------------------------------------------  SLASH-КОМАНДА /gpt
@app.route("/slack/command", methods=["POST"])
def slash_command():
    if not sign_verifier.is_valid_request(request.get_data(), request.headers):
        return "invalid signature", 403

    text      = request.form.get("text", "")
    channel   = request.form["channel_id"]
    response_url = request.form["response_url"]

    # сразу ACK, иначе «dispatch_failed»
    initial = {"response_type": "ephemeral", "text": "⏳ Думаю…"}
    # важно: вернуть JSON
    ack = make_response(json.dumps(initial), 200)
    ack.headers["Content-Type"] = "application/json"

    # основной ответ — асинхронно
    try:
        answer = chat_gpt(text or "Hello!")
        slack_client.chat_postMessage(channel=channel, text=answer)
    except Exception as e:
        log.exception("OpenAI error")
        slack_client.chat_postMessage(channel=channel, text=f"⚠️ Ошибка: {e}")

    return ack

# -------------------------------------------------------------  GPT-помощник
def chat_gpt(prompt: str) -> str:
    """Простой вызов OpenAI Chat Completions."""
    resp = openai_client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "system", "content": "You are a helpful assistant"},
                  {"role": "user",   "content": prompt}],
        temperature=0.7,
    )
    return resp.choices[0].message.content.strip()

# ----------------------------------------------------------------------------- MAIN
if __name__ == "__main__":
    # Render слушает любой порт; Flask по умолчанию 5000 → зададим 10000, как в логах
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
