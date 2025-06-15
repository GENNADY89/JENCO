from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
import os
import openai
from threading import Thread

app = Flask(__name__)

# ENV
openai.api_key = os.environ.get("OPENAI_API_KEY")
slack_token = os.environ.get("SLACK_BOT_TOKEN")
client = WebClient(token=slack_token)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.json

    # Step 1: Slack URL verification
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # Step 2: Event callback
    if data.get("type") == "event_callback":
        event = data.get("event", {})
        text = event.get("text")
        channel = event.get("channel")
        user = event.get("user")

        if not text or not channel:
            return "Missing fields", 400

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
                client.chat_postMessage(channel=channel, text=f"<@{user}> {answer}")
            except Exception as e:
                client.chat_postMessage(channel=channel, text=f"Ошибка GPT: {str(e)}")

        Thread(target=handle_gpt).start()
        return "OK", 200

    return "Ignored", 200

# Required for Render deployment
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
