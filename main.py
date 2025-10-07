import os
import telebot
import openai
import time
import speech_recognition as sr
import requests
from telebot import types
from gtts import gTTS
from googletrans import Translator
from io import BytesIO
from PIL import Image
import pytesseract

# Environment Variables
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPEN_API_KEY = os.getenv("OPEN_API_KEY")

if not BOT_TOKEN or not OPEN_API_KEY:
    raise ValueError("❌ BOT_TOKEN or OPEN_API_KEY missing! Set them in Render dashboard.")

bot = telebot.TeleBot(BOT_TOKEN)
openai.api_key = OPEN_API_KEY
translator = Translator()

# 🧩 Main Menu
def main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.row("🧠 Chat", "🎙 Voice-to-Text", "🌐 Translate")
    markup.row("🖼 Image Solve", "📜 My Logs", "❌ Close")
    return markup

# 🏁 Start Command
@bot.message_handler(commands=['start'])
def start(message):
    bot.send_message(
        message.chat.id,
        "👋 Welcome to TestBook AI Bot (Pro Edition)!\nChoose an option below 👇",
        reply_markup=main_menu()
    )

# 📜 Store chat logs
user_logs = {}

def log_message(uid, text):
    if uid not in user_logs:
        user_logs[uid] = []
    user_logs[uid].append(text)

# 🌐 Translation
@bot.message_handler(func=lambda msg: msg.text == "🌐 Translate")
def translate_prompt(message):
    bot.send_message(message.chat.id, "Send text to translate (Hindi ↔ English supported).")

@bot.message_handler(func=lambda msg: msg.text in ["🧠 Chat", "🎙 Voice-to-Text", "🖼 Image Solve", "📜 My Logs", "❌ Close"])
def menu_handler(message):
    if message.text == "🧠 Chat":
        bot.send_message(message.chat.id, "🧠 Type your question.")
    elif message.text == "🎙 Voice-to-Text":
        bot.send_message(message.chat.id, "🎤 Send a voice message — I’ll convert & reply.")
    elif message.text == "🖼 Image Solve":
        bot.send_message(message.chat.id, "📷 Send an image of your question/problem.")
    elif message.text == "📜 My Logs":
        logs = "\n".join(user_logs.get(message.chat.id, ["No logs yet."]))
        bot.send_message(message.chat.id, f"🧾 Your Logs:\n{logs}")
    elif message.text == "❌ Close":
        bot.send_message(message.chat.id, "❌ Menu closed.", reply_markup=types.ReplyKeyboardRemove())

# 🎙 Voice message handler
@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    try:
        file_info = bot.get_file(message.voice.file_id)
        file = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}")
        with open("voice.ogg", "wb") as f:
            f.write(file.content)

        recognizer = sr.Recognizer()
        with sr.AudioFile("voice.ogg") as source:
            audio = recognizer.record(source)
        text = recognizer.recognize_google(audio, language="hi-IN")
        bot.send_message(message.chat.id, f"🎧 You said: {text}")

        log_message(message.chat.id, f"Voice: {text}")
        ai_reply(message, text)
    except Exception as e:
        bot.reply_to(message, f"⚠️ Voice error: {e}")

# 🖼 Image handler
@bot.message_handler(content_types=['photo'])
def handle_image(message):
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        img_data = requests.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}")
        img = Image.open(BytesIO(img_data.content))

        # Extract text from image
        extracted_text = pytesseract.image_to_string(img)
        bot.send_message(message.chat.id, f"📝 Extracted Text:\n{extracted_text}")

        ai_reply(message, extracted_text)
    except Exception as e:
        bot.reply_to(message, f"⚠️ Image error: {e}")

# 💬 AI Chat handler
@bot.message_handler(func=lambda msg: True, content_types=['text'])
def handle_text(message):
    user_text = message.text
    log_message(message.chat.id, f"You: {user_text}")

    # Translation shortcut
    if message.reply_to_message and "Translate" in message.reply_to_message.text:
        translated = translator.translate(user_text, dest="en").text
        bot.reply_to(message, f"🌐 Translated: {translated}")
        return

    ai_reply(message, user_text)

def ai_reply(message, user_text):
    # --- Keep the bot alive for Render ---
from flask import Flask
import threading

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running fine!"

def run_flask():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_flask).start()
    try:
        bot.send_chat_action(message.chat.id, 'typing')
        time.sleep(1)

        response = openai.ChatCompletion.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are TestBook Pro Assistant, smart and accurate."},
                {"role": "user", "content": user_text}
            ]
        )
        reply = response['choices'][0]['message']['content']

        bot.send_message(message.chat.id, reply)
        log_message(message.chat.id, f"Bot: {reply}")

    except Exception as e:
        bot.reply_to(message, f"⚠️ Error: {e}")

print("✅ TestBook Pro Bot Running...")
bot.polling(non_stop=True)
