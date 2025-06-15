from flask import Flask, request, jsonify
import os
import openai
from slack_sdk import WebClient
from threading import Thread

# Инициализация Flask-приложения
app = Flask(__name__)

# Загрузка переменных окружения
openai.api_key = os.environ.get("OPENAI_API_KEY")
slack_token = os.environ.get("SLACK_BOT_TOKEN")
client = WebClient(token=slack_token)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.get_json()

    # Обработка подтверждения URL от Slack
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    event = data.get("event", {})
    user_id = event.get("user")
    channel = event.get("channel")
    text = event.get("text", "")

    # Игнорируем события от ботов (включая самого себя)
    if "bot_id" in event or user_id is None:
        return "Ignored bot message", 200

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

# Запуск Flask-сервера на внешнем порту (обязательно для Render)
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
