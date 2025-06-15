import os
from flask import Flask, request, jsonify
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv
from openai import OpenAI
import logging

# Load environment variables
load_dotenv()
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize clients
slack_client = WebClient(token=SLACK_BOT_TOKEN)
openai_client = OpenAI(api_key=OPENAI_API_KEY)

app = Flask(__name__)

@app.route("/", methods=["GET"])
def index():
    return "Slack GPT bot is running."

@app.route("/slack/events", methods=["POST"])
def slack_events():
    data = request.get_json()

    # Handle Slack URL verification
    if data.get("type") == "url_verification":
        return jsonify({"challenge": data.get("challenge")})

    # Handle Slack event callbacks
    if data.get("type") == "event_callback":
        event = data.get("event", {})
        if event.get("type") == "app_mention" and "bot_id" not in event:
            user = event.get("user")
            text = event.get("text")
            channel = event.get("channel")

            logging.info(f"Message from {user}: {text}")

            # Remove bot mention from text
            prompt = text.split(">", 1)[-1].strip()

            # Get completion from OpenAI
            try:
                response = openai_client.chat.completions.create(
                    model="gpt-4",
                    messages=[
                        {"role": "system", "content": "You are a helpful assistant."},
                        {"role": "user", "content": prompt}
                    ],
                    max_tokens=500
                )
                reply = response.choices[0].message.content.strip()

                # Send reply back to Slack
                slack_client.chat_postMessage(channel=channel, text=reply)
            except SlackApiError as e:
                logging.error(f"Slack API error: {e.response['error']}")
            except Exception as e:
                logging.error(f"OpenAI error: {e}")

    return "", 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
