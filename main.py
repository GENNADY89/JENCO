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

    # Handle Slack URL verification
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # Handle event callback
    if "event" in data:
        event_data = data["event"]
        text = event_data.get("text")
        channel = event_data.get("channel")
        user_id = event_data.get("user")

        if text and channel and user_id:
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
                except SlackApiError as e:
                    print(f"Slack API error: {e.response['error']}")
                except Exception as e:
                    print(f"OpenAI error: {str(e)}")

            Thread(target=handle_gpt).start()

    return "OK", 200

@app.route("/", methods=["GET"])
def index():
    return "JENCO-GPT is running."

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
