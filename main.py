from flask import Flask, request, jsonify
import os
import openai
from slack_sdk import WebClient
from threading import Thread

app = Flask(__name__)

# API ключи из переменных окружения
openai.api_key = os.environ.get("OPENAI_API_KEY")
slack_token = os.environ.get("SLACK_BOT_TOKEN")
client = WebClient(token=slack_token)


@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.get_json()

    # 🔐 Обработка URL верификации от Slack
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # ⚙️ Обработка событий (например, упоминание в канале)
    if data.get("type") == "event_callback":
        event = data.get("event", {})
        text = event.get("text")
        channel = event.get("channel")
        user_id = event.get("user")

        if text and channel and user_id:
            # Вызов OpenAI в отдельном потоке
            def handle_gpt():
                try:
                    response = openai.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {"role": "system", "content": "Ты корпоративный ассистент компании BEM/JENCO."},
                            {"role": "user", "content": text}
                        ],
                        max_tokens=500,
                        temperature=0.5
                    )
                    answer = response.choices[0].message.content
                    client.chat_postMessage(channel=channel, text=f"<@{user_id}> {answer}")
                except Exception as e:
                    client.chat_postMessage(channel=channel, text=f"Ошибка GPT: {str(e)}")

            Thread(target=handle_gpt).start()

    return "OK", 200
