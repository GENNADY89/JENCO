# pip install slack_bolt slack_sdk openai python-dotenv requests
import os, logging, threading, requests
from typing import Any, List
import openai
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.signature import SignatureVerifier
from dotenv import load_dotenv

# ─── env ────────────────────────────────────────────────────────────────────
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")
SLACK_SIGNING_SECRET = os.getenv("SLACK_SIGNING_SECRET")  # optional

for k, v in {"OPENAI_API_KEY": OPENAI_API_KEY,
             "SLACK_BOT_TOKEN": SLACK_BOT_TOKEN}.items():
    if not v:
        raise RuntimeError(f"Missing {k}")

openai.api_key = OPENAI_API_KEY
slack_client = WebClient(token=SLACK_BOT_TOKEN)
sign_verifier = SignatureVerifier(SLACK_SIGNING_SECRET) if SLACK_SIGNING_SECRET else None

app = App(token=SLACK_BOT_TOKEN)  # Slack Bolt app
sclient = WebClient(token=SLACK_BOT_TOKEN)

MAX_MSG = 4_000  # hard Slack limit for plain-text message

# ─── utils ──────────────────────────────────────────────────────────────────
def looks_like_table(txt: str) -> bool:
    """Проверка, похож ли текст на таблицу."""
    return '|' in txt and '\n' in txt

def wrap_code_block(txt: str) -> str:
    """Оборачиваем текст в тройные кавычки (код-блок)."""
    if txt.startswith("```") and txt.rstrip().endswith("```"):
        return txt
    return f"```\n{txt}\n```"

def split_msg(txt: str) -> List[str]:
    """Режем текст на части, если он слишком длинный."""
    if len(txt) <= MAX_MSG:
        return [txt]
    
    chunks: List[str] = []
    while txt:
        part = txt[:MAX_MSG]
        txt = txt[MAX_MSG:]
        part = wrap_code_block(part) if part.strip() else part
        chunks.append(part)
    return chunks

def send_in_parts(channel: str, user: str, text: str) -> None:
    """Отправка длинного сообщения несколькими частями."""
    for chunk in split_msg(text):
        try:
            slack_client.chat_postMessage(channel=channel,
                                          text=f"<@{user}> {chunk}")
        except SlackApiError as e:
            logging.error("Slack post error: %s", e.response["error"])

# ─── main handler ───────────────────────────────────────────────────────────
@app.event("message")
def handle_files(event, say):
    """Обработка сообщений в Slack, включая файлы."""
    if event.get("subtype") == "file_share":
        # 1️⃣ Ловим файлы и скачиваем их
        sf = event["files"][0]
        file_id = sf["id"]
        
        # 2️⃣ Мета-данные файла
        meta = sclient.files_info(file=file_id)["file"]
        url = meta["url_private_download"]
        headers = {"Authorization": f"Bearer {SLACK_BOT_TOKEN}"}
        data = requests.get(url, headers=headers).content
        with open("/tmp/tmp_upload", "wb") as f:
            f.write(data)
        
        # 3️⃣ Загружаем файл в OpenAI
        upload = openai.files.create(
            file=open("/tmp/tmp_upload", "rb"),
            purpose="assistants"
        )
        oa_file_id = upload.id

        # 4️⃣ Создание ассистента
        assistant = openai.beta.assistants.create(
            name="SlackStrategyBot",
            model="gpt-4o-mini",          # o-3 / полный GPT-4o
            tools=[{"type": "retrieval"}]  # Retrieval включён
        )

        # 5️⃣ Создаём диалоговый поток
        thread = openai.beta.threads.create()
        run = openai.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=assistant.id,
            additional_instructions=(
                "Проанализируй файл и выдай ключевые инсайты "
                "для бизнес-модели проекта."
            ),
            tools=[{"type": "retrieval"}],
            file_ids=[oa_file_id]
        )

        # 6️⃣ Уведомление в Slack
        say(f"🤖 GPT анализирует файл… (run id: {run.id})")

# ─── обработчик для сообщений (slash-команды) ───────────────────────────────
@app.post("/slack/events")
def slack_events():
    """Основной обработчик Slash команд и сообщений."""
    # 1. Slack ретраи
    if request.headers.get("X-Slack-Retry-Num"):
        return "retry_ack", 200

    # 2. подпись
    if sign_verifier and not sign_verifier.is_valid_request(
            request.get_data(), request.headers):
        abort(400, "Invalid signature")

    form = request.form

    # 3. url_verification
    if form.get("type") == "url_verification":
        return jsonify({"challenge": form.get("challenge")}), 200

    # 4. slash-command payload
    text = form.get("text")
    channel = form.get("channel_id")
    user = form.get("user_id")

    if not all([text, channel, user]):
        logging.warning("empty payload")
        return "ignored", 200

    # мгновенный ответ Slack-у (<3 с)
    first_reply = {
        "response_type": "in_channel",
        "text": f":hourglass_flowing_sand: <@{user}> спросил:\n`{text}`\n\nGPT думает…",
    }
    threading.Thread(target=process_gpt,
                     args=(text, channel, user),
                     daemon=True).start()
    return jsonify(first_reply), 200

def process_gpt(prompt: str, channel: str, user: str) -> None:
    """Запрос к GPT и публикация ответа."""
    try:
        resp = openai.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system",
                 "content": "Ты корпоративный ассистент компании BEM/JENCO."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=800,
            temperature=0.4,
        )
        answer = resp.choices[0].message.content.strip()

        # если это таблица — оборачиваем в код-блок
        if looks_like_table(answer):
            answer = wrap_code_block(answer)

        send_in_parts(channel, user, answer)

    except Exception as e:
        logging.exception("GPT error")
        slack_client.chat_postMessage(
            channel=channel, text=f"<@{user}> ⚠️ GPT error: {e}")

# ─── local run ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    SocketModeHandler(app, SLACK_APP_TOKEN).start()
