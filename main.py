from flask import Flask, request
import os
import openai
from slack_sdk import WebClient
from threading import Thread

app = Flask(__name__)

openai.api_key = os.environ.get("OPENAI_API_KEY")
slack_token = os.environ.get("SLACK_BOT_TOKEN")
client = WebClient(token=slack_token)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.form
    text = data.get("text")
    channel = data.get("channel_id")
    user_id = data.get("user_id")

    def handle_gpt():
        try:
            response = openai.ChatCompletion.create(
                model="gpt-4o",
                messages=[
                    {"role": "system", "content": "Ты корпоративный ассистент компании BEM/JENCO."},
                    {"role": "user", "content": text}
                ],
                max_tokens=500,
                temperature=0.5
            )
            answer = response["choices"][0]["message"]["content"]
            client.chat_postMessage(channel=channel, text=f"<@{user_id}> {answer}")
        except Exception as e:
            client.chat_postMessage(channel=channel, text=f"Ошибка GPT: {str(e)}")

    Thread(target=handle_gpt).start()
    return "OK", 200
