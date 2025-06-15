from flask import Flask, request, jsonify
import os
import openai
from slack_sdk import WebClient
from threading import Thread

app = Flask(__name__)

# Load environment variables
openai.api_key = os.environ.get("OPENAI_API_KEY")
slack_token = os.environ.get("SLACK_BOT_TOKEN")
client = WebClient(token=slack_token)

@app.route("/slack/events", methods=["POST"])
def slack_events():
    try:
        # Slack slash commands are sent as form-urlencoded
        text = request.form.get("text")
        channel_id = request.form.get("channel_id")
        user_id = request.form.get("user_id")

        print(f"✅ Received Slack request: text='{text}', channel='{channel_id}', user='{user_id}'")

        # Run GPT logic in a separate thread to avoid timeouts
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
                print(f"🤖 GPT response: {answer}")
                client.chat_postMessage(channel=channel_id, text=f"<@{user_id}> {answer}")

            except Exception as e:
                print(f"❌ Error from OpenAI: {e}")
                client.chat_postMessage(channel=channel_id, text=f"<@{user_id}> GPT error: {str(e)}")

        Thread(target=handle_gpt).start()

        return "", 200

    except Exception as e:
        print(f"❌ Request failed: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/", methods=["GET"])
def healthcheck():
    return "JENCO GPT bot is running!", 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
