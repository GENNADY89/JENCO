import os
from flask import Flask, request, make_response
from slack_sdk.signature import SignatureVerifier
from slack_sdk.web import WebClient
import openai
from dotenv import load_dotenv

load_dotenv()  # берём переменные из .env, если запускаетесь локально

# --- обязательные переменные окружения ---
SLACK_BOT_TOKEN      = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY")

missing = [n for n, v in [
    ("SLACK_BOT_TOKEN", SLACK_BOT_TOKEN),
    ("SLACK_SIGNING_SECRET", SLACK_SIGNING_SECRET),
    ("OPENAI_API_KEY", OPENAI_API_KEY)
] if not v]
if missing:
    raise RuntimeError(f"Missing env vars: {', '.join(missing)}")

# --- инициализация клиентов ---
app            = Flask(__name__)
client         = WebClient(token=SLACK_BOT_TOKEN)
sign_verifier  = SignatureVerifier(SLACK_SIGNING_SECRET)
openai.api_key = OPENAI_API_KEY


@app.route("/", methods=["GET"])
def healthcheck():
    return "OK", 200


@app.route("/slack/events", methods=["POST"])
def slack_events():
    # проверяем подпись
    if not sign_verifier.is_valid_request(request.get_data(), request.headers):
        return make_response("invalid request", 403)

    payload = request.get_json()

    # hand-shake Slack'а при добавлении URL
    if payload.get("type") == "url_verification":
        return make_response(payload.get("challenge"), 200)

    # реальные события
    event = payload.get("event", {})
    if event.get("type") == "app_mention":
        user_text = event.get("text", "")
        bot_id    = payload["authorizations"][0]["user_id"]
        cleaned   = user_text.replace(f"<@{bot_id}>", "").strip()

        answer = ask_chatgpt(cleaned)
        client.chat_postMessage(channel=event["channel"], text=answer)

    return "", 200


def ask_chatgpt(prompt):
    resp = openai.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=250
    )
    return resp.choices[0].message.content.strip()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
