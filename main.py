from __future__ import annotations
import os, logging, threading
from typing import Any, List

import openai
from flask import Flask, request, jsonify, abort
from slack_sdk import WebClient
from slack_sdk.signature import SignatureVerifier
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

# ─── env ────────────────────────────────────────────────────────────────────
load_dotenv()
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY")
SLACK_BOT_TOKEN      = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")           # optional

for k, v in {"OPENAI_API_KEY":OPENAI_API_KEY,
             "SLACK_BOT_TOKEN":SLACK_BOT_TOKEN}.items():
    if not v: raise RuntimeError(f"Missing {k}")

openai.api_key = OPENAI_API_KEY
slack_client   = WebClient(token=SLACK_BOT_TOKEN)
sign_verifier  = (SignatureVerifier(SLACK_SIGNING_SECRET)
                  if SLACK_SIGNING_SECRET else None)

# ─── flask ──────────────────────────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.get("/")
def health():                                              # Render / k8s probe
    return {"status":"ok","service":"JENCO GPT Slack Bot"}, 200

# ─── utils ──────────────────────────────────────────────────────────────────
MAX_MSG = 4000

def split_msg(text: str) -> List[str]:
    return [text[i:i+MAX_MSG] for i in range(0, len(text), MAX_MSG)]

def send_in_parts(channel: str, user: str, text: str) -> None:
    for chunk in split_msg(text):
        try:
            slack_client.chat_postMessage(channel=channel,
                                          text=f"<@{user}> {chunk}")
        except SlackApiError as e:
            logging.error("Slack post error: %s", e.response["error"])

# ─── main handler ───────────────────────────────────────────────────────────
@app.post("/slack/events")
def slack_events():                                         # one endpoint for
    # 1) Slack Retry-Num (дубли) ------------------------------------------------
    if request.headers.get("X-Slack-Retry-Num"):
        return "retry_ack", 200

    # 2) signature --------------------------------------------------------------
    if sign_verifier and not sign_verifier.is_valid_request(
            request.get_data(), request.headers):
        abort(400, "Invalid signature")

    form = request.form

    # 3) url_verification (challenge) -------------------------------------------
    if form.get("type") == "url_verification":
        return jsonify({"challenge": form.get("challenge")}), 200

    # 4) slash command payload --------------------------------------------------
    text      = form.get("text")
    channel   = form.get("channel_id")
    user      = form.get("user_id")
    resp_url  = form.get("response_url")          # на случай if needed

    if not all([text, channel, user]):
        logging.warning("empty payload")
        return "ignored", 200

    # 4.1 мгновенный ответ Slack-у (<3 с)
    #     • "ephemeral" — видно только автору
    #     • "in_channel" — видят все + Slack публикует сам текст команды
    first_reply = {
        "response_type": "ephemeral",
        "text":        "⏳ GPT думает… (обычно 3-8 с)",
    }
    threading.Thread(target=process_gpt,
                     args=(text, channel, user),
                     daemon=True).start()
    return jsonify(first_reply), 200


def process_gpt(prompt: str, channel: str, user: str) -> None:
    """Runs in background thread: asks GPT & posts answer."""
    try:
        resp: dict[str, Any] = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role":"system",
                 "content":"Ты корпоративный ассистент компании BEM/JENCO."},
                {"role":"user","content":prompt},
            ],
            max_tokens=800, temperature=0.4)
        answer = resp.choices[0].message.content.strip()
        send_in_parts(channel, user, answer)      # текст >4 000? → разобьём
    except Exception as e:
        logging.exception("GPT error")
        slack_client.chat_postMessage(
            channel=channel, text=f"<@{user}> ⚠️ GPT error: {e}")

# ─── local run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
