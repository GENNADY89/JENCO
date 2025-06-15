from flask import Flask, request, jsonify
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

    # 🔁 Handle Slack's URL verification challenge
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # 🔁 Handle actual Slack events
    if "event" in data:
        event = data["event"]

        if event.get("type") == "app_mention" or event.get("type") == "message":
            text = event.get("text")
            channel = event.get("channel")
            user = event.get("user")

            if text and channel and user:
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
                        client.chat_postMessage(channel=channel, text=f"<@{user}> {answer}")
                    except SlackApiError as e:
                        print("Slack API Error:", e.response["error"])
                    except Exception as e:
                        client.chat_postMessage(channel=channel, text=f"Ошибка GPT: {str(e)}")

                Thread(target=handle_gpt).start()

    return "OK", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))
