
from flask import Flask, request
import os
import openai
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from threading import Thread

app = Flask(__name__)

openai.api_key = os.environ.get("OPENAI_API_KEY")
slack_token = os.environ.get("SLACK_BOT_TOKEN")
client = WebClient(token=slack_token)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.get_json()
    print("==== Slack Command Received ====")
    print(data)

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
            print("==== GPT Response ====")
            print(answer)
            try:
                client.chat_postMessage(channel=channel, text=f"<@{user_id}> {answer}")
            except SlackApiError as slack_err:
                print(f"Slack API Error: {slack_err.response['error']}")
        except Exception as e:
            print(f"OpenAI Error: {str(e)}")
            try:
                client.chat_postMessage(channel=channel, text=f"<@{user_id}> ❌ Ошибка GPT: {str(e)}")
            except SlackApiError as slack_err:
                print(f"Slack API Error (fallback): {slack_err.response['error']}")

    Thread(target=handle_gpt).start()
    return "OK", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
