from __future__ import annotations

"""JENCO GPT Slack bot — single‑file Flask service.
• GET /              – health‑check for Render/K8s
• POST /slack/events – Slash‑command endpoint (`/gpt …`).
   – Validates Slack signature (optional)
   – Handles url_verification
   – Sends immediate “thinking…” reply visible to channel
   – Off‑loads OpenAI request to background thread
   – Streams long answers (>4 000 chars) to Slack thread in chunks
   – Supports UTF‑8‑aware slicing (Slack counts bytes, not code‑points)

Env vars (mandatory):  OPENAI_API_KEY, SLACK_BOT_TOKEN
Optional:              SLACK_SIGNING_SECRET
"""

import logging
import os
import threading
from typing import Any, List

import openai
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier

# ─── env ──────────────────────────────────────────────────────────────
load_dotenv()
OPENAI_API_KEY       = os.getenv("OPENAI_API_KEY")
SLACK_BOT_TOKEN      = os.getenv("SLACK_BOT_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")  # optional

for k, v in {"OPENAI_API_KEY": OPENAI_API_KEY, "SLACK_BOT_TOKEN": SLACK_BOT_TOKEN}.items():
    if not v:
        raise RuntimeError(f"Missing {k}")

openai.api_key = OPENAI_API_KEY
slack_client   = WebClient(token=SLACK_BOT_TOKEN)
sign_verifier  = SignatureVerifier(SLACK_SIGNING_SECRET) if SLACK_SIGNING_SECRET else None

# ─── flask ────────────────────────────────────────────────────────────
app = Flask(__name__)
logging.basicConfig(level=logging.INFO)

@app.get("/")
def health() -> tuple[dict[str, str], int]:
    """Render health‑probe"""
    return {"status": "ok", "service": "JENCO GPT Slack Bot"}, 200

# ─── helpers ──────────────────────────────────────────────────────────
MAX_MSG = 4000  # Slack text limit in *bytes*


def split_utf8(text: str, limit: int = MAX_MSG) -> List[str]:
    """Smart splitter: keeps line breaks; counts UTF‑8 bytes, not code‑points."""
    out, buf, size = [], [], 0
    for line in text.splitlines(keepends=True):
        ln = len(line.encode())
        if size + ln > limit:
            out.append("".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += ln
    if buf:
        out.append("".join(buf))
    return out or [""]


def post_chunks(channel: str, user: str, text: str, thread_ts: str | None = None) -> None:
    """Send long message as threaded sequence ≤4 000 bytes each."""
    ts = thread_ts
    for i, chunk in enumerate(split_utf8(text)):
        try:
            resp = slack_client.chat_postMessage(
                channel=channel,
                text=(f"<@{user}> {chunk}" if i == 0 and not ts else chunk),
                thread_ts=ts,
            )
            if i == 0:  # remember ts of the first posted message
                ts = resp["ts"]
        except SlackApiError as e:
            logging.error("Slack post error: %s", e.response.get("error", e))
            break


# ─── main handler ────────────────────────────────────────────────────
@app.post("/slack/events")
def slack_events():
    # 1) Slack retry‑protection -------------------------------------------------
    if request.headers.get("X-Slack-Retry-Num"):
        return "retry_ack", 200

    # 2) Validate signature (if secret set) -----------------------------------
    if sign_verifier and not sign_verifier.is_valid_request(request.get_data(), request.headers):
        abort(400, "Invalid signature")

    form = request.form

    # 3) url_verification challenge -------------------------------------------
    if form.get("type") == "url_verification":
        return jsonify({"challenge": form.get("challenge", "")}), 200

    # 4) Slash‑command payload -------------------------------------------------
    text     = form.get("text")
    channel  = form.get("channel_id")
    user     = form.get("user_id")

    if not all([text, channel, user]):
        logging.warning("⚠️ empty payload")
        return "ignored", 200

    # 4‑a) Immediate  (<3 s) visible reply so everyone sees the question
    first_reply = {
        "response_type": "in_channel",  # show in channel & publish user text
        "text": f":hourglass_flowing_sand: <@{user}> спросил:\n`{text}`\n\nGPT думает…",
    }

    # 4‑b) Launch GPT processing in background thread
    threading.Thread(target=process_gpt, args=(text, channel, user), daemon=True).start()
    return jsonify(first_reply), 200


def process_gpt(prompt: str, channel: str, user: str) -> None:
    """Ask OpenAI, then stream answer to Slack."""
    try:
        resp: Any = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Ты корпоративный ассистент компании BEM/JENCO."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=800,
            temperature=0.4,
        )
        answer = resp.choices[0].message.content.strip()
        post_chunks(channel, user, answer)
    except Exception as e:
        logging.exception("GPT error")
        slack_client.chat_postMessage(channel=channel, text=f"<@{user}> ⚠️ GPT error: {e}")


# ─── local run (dev) ─────────────────────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))
