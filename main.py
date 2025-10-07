#!/usr/bin/env python3
# main.py - TestBook AI Pro Bot (final)
# Features: AI chat, voice->text, image OCR->AI, quiz, translation, logs, Flask keepalive
# Security: BOT_TOKEN and OPENAI_API_KEY must be set as environment variables on Render.

import os
import json
import time
import random
import threading
import tempfile
import traceback
from io import BytesIO

from flask import Flask
from PIL import Image
import requests

import telebot
from telebot import types

# Optional libs (may raise if not installed)
try:
    import openai
except Exception:
    openai = None

try:
    from googletrans import Translator
except Exception:
    Translator = None

try:
    import pytesseract
except Exception:
    pytesseract = None

try:
    from pydub import AudioSegment
    import speech_recognition as sr
except Exception:
    AudioSegment = None
    sr = None

try:
    from gtts import gTTS
except Exception:
    gTTS = None

# -------------------------
# Config from environment
# -------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN not set in environment variables.")
if not OPENAI_API_KEY:
    print("Warning: OPENAI_API_KEY not set — AI features disabled (but bot can still run).")

if openai:
    openai.api_key = OPENAI_API_KEY

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

# -------------------------
# Simple persistent storage
# -------------------------
DATA_FILE = "userdata.json"
try:
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            USERDATA = json.load(f)
    else:
        USERDATA = {}
except Exception:
    USERDATA = {}

def save_data():
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(USERDATA, f, ensure_ascii=False, indent=2)

def ensure_user(uid):
    uid = str(uid)
    if uid not in USERDATA:
        USERDATA[uid] = {"notes": [], "scores": {}, "lang": "auto", "logs": []}
        save_data()

def log_user(uid, text):
    uid = str(uid)
    ensure_user(uid)
    USERDATA[uid]["logs"].append({"ts": int(time.time()), "text": text})
    # keep only last 200 entries
    USERDATA[uid]["logs"] = USERDATA[uid]["logs"][-200:]
    save_data()

# -------------------------
# Content: book + quiz bank
# -------------------------
BOOK = [
    {
        "id": "ch1",
        "title": "Adhyay 1: Parichay",
        "content": "Yeh pehla adhyay hai. Isme mool tatvon ka parichay diya gaya hai.",
        "quiz": [
            {
                "q": "Parichay adhyay ka uddeshya kya hai?",
                "opts": ["Samanya jankari", "Ganit", "Bhasha", "Itihas"],
                "a": 0
            }
        ]
    },
    {
        "id": "ch2",
        "title": "Adhyay 2: Mool Sankalpnaen",
        "content": "Doosra adhyay: kuch mool sankalpnaen aur udaharan.",
        "quiz": [
            {
                "q": "Concept A kis se sambandhit hai?",
                "opts": ["A", "B", "C", "D"],
                "a": 1
            }
        ]
    }
]
BOOK_MAP = {b["id"]: b for b in BOOK}

# Quiz question bank for daily/random quiz (extend as needed)
QUIZ_BANK = [
    {"q":"Bharat ka rashtriya phool kaun sa hai?","opts":["Rose","Lotus","Lily","Sunflower"],"a":1},
    {"q":"2+2*2 = ?","opts":["6","8","4","10"],"a":0},
    {"q":"Capital of India?","opts":["Mumbai","Kolkata","New Delhi","Chennai"],"a":2},
    {"q":"H2O is chemical for:","opts":["Salt","Water","Oxygen","Hydrogen"],"a":1},
    {"q":"5*6 = ?","opts":["30","25","35","40"],"a":0}
]

# -------------------------
# Helpers: keyboards
# -------------------------
def main_menu_kb():
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True)
    kb.row("📚 Chapters", "❓ Quiz")
    kb.row("🎙 Voice", "🖼 Image Solve")
    kb.row("🌐 Translate", "📜 My Logs")
    return kb

def chapters_inline_kb():
    kb = types.InlineKeyboardMarkup()
    for b in BOOK:
        kb.add(types.InlineKeyboardButton(b["title"], callback_data=f"read_{b['id']}"))
    return kb

def quiz_chapters_inline():
    kb = types.InlineKeyboardMarkup()
    for b in BOOK:
        kb.add(types.InlineKeyboardButton(b["title"], callback_data=f"quiz_{b['id']}"))
    return kb

def quiz_options_kb(base_id, qid, q):
    kb = types.InlineKeyboardMarkup()
    for i,opt in enumerate(q["opts"]):
        kb.add(types.InlineKeyboardButton(f"{chr(65+i)}. {opt}", callback_data=f"ans_{base_id}_{qid}_{i}"))
    return kb

# -------------------------
# OpenAI helper
# -------------------------
def openai_chat_reply(prompt, max_tokens=400):
    if not openai:
        return "AI not configured on server."
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"system","content":"You are TestBook Assistant."},{"role":"user","content":prompt}],
            max_tokens=max_tokens,
            temperature=0.7
        )
        return resp["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"AI error: {e}"

# -------------------------
# Speech helpers
# -------------------------
def convert_ogg_to_wav(ogg_bytes, out_path):
    if AudioSegment is None:
        raise RuntimeError("pydub not installed on server.")
    # read from bytes and export wav
    tmp = BytesIO(ogg_bytes)
    audio = AudioSegment.from_file(tmp, format="ogg")
    audio.export(out_path, format="wav")

def transcribe_audio_file(wav_path):
    if sr is None:
        raise RuntimeError("speech_recognition not available.")
    r = sr.Recognizer()
    with sr.AudioFile(wav_path) as source:
        audio = r.record(source)
    try:
        # try Google free recognizer (works often)
        return r.recognize_google(audio, language="hi-IN")
    except Exception:
        try:
            return r.recognize_google(audio, language="en-US")
        except Exception as e:
            raise RuntimeError(f"STT failed: {e}")

# -------------------------
# Image OCR helper
# -------------------------
def ocr_image_from_bytes(img_bytes):
    if pytesseract is None:
        raise RuntimeError("pytesseract not installed on server.")
    img = Image.open(BytesIO(img_bytes)).convert("RGB")
    text = pytesseract.image_to_string(img)
    return text.strip()

# -------------------------
# Bot handlers
# -------------------------
@bot.message_handler(commands=["start","help"])
def cmd_start(m):
    ensure_user(m.from_user.id)
    bot.send_message(m.chat.id, "👋 Namaste! Main TestBook Pro Bot hoon.\nChoose option:", reply_markup=main_menu_kb())

@bot.message_handler(commands=["chapters"])
def cmd_chapters(m):
    bot.send_message(m.chat.id, "📚 Chapters:", reply_markup=chapters_inline_kb())

@bot.message_handler(commands=["quiz"])
def cmd_quiz(m):
    bot.send_message(m.chat.id, "❓ Choose chapter quiz or /dailyquiz for random quiz", reply_markup=quiz_chapters_inline())

@bot.message_handler(commands=["dailyquiz"])
def cmd_dailyquiz(m):
    # send 5 random questions sequentially using ephemeral state
    uid = str(m.from_user.id)
    ensure_user(uid)
    questions = random.sample(QUIZ_BANK, min(5, len(QUIZ_BANK)))
    USERDATA[uid]["pending_quiz"] = {"questions": questions, "index":0, "score":0}
    save_data()
    send_next_quiz_question(m.chat.id, uid)

def send_next_quiz_question(chat_id, uid):
    state = USERDATA[uid].get("pending_quiz")
    if not state:
        bot.send_message(chat_id, "No quiz in progress.")
        return
    idx = state["index"]
    if idx >= len(state["questions"]):
        score = state["score"]
        total = len(state["questions"])
        bot.send_message(chat_id, f"🏁 Quiz finished. Score: {score}/{total}")
        USERDATA[uid].pop("pending_quiz", None)
        save_data()
        return
    q = state["questions"][idx]
    kb = types.InlineKeyboardMarkup()
    for i,opt in enumerate(q["opts"]):
        kb.add(types.InlineKeyboardButton(f"{chr(65+i)}. {opt}", callback_data=f"dailyans_{uid}_{idx}_{i}"))
    bot.send_message(chat_id, f"Q{idx+1}: {q['q']}", reply_markup=kb)

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    try:
        data = call.data
        # read chapter
        if data.startswith("read_"):
            ch_id = data.split("_",1)[1]
            ch = BOOK_MAP.get(ch_id)
            if not ch:
                bot.answer_callback_query(call.id, "Not found.")
                return
            lang = USERDATA.get(str(call.from_user.id), {}).get("lang","auto")
            content = ch["content"]
            bot.send_message(call.message.chat.id, f"*{ch['title']}*\n\n{content}", parse_mode="Markdown")
            bot.answer_callback_query(call.id)
            return

        # chapter quiz
        if data.startswith("quiz_"):
            ch_id = data.split("_",1)[1]
            ch = BOOK_MAP.get(ch_id)
            if not ch:
                bot.answer_callback_query(call.id, "Not found.")
                return
            q = ch["quiz"][0]
            kb = quiz_options_kb(ch_id, 0, q)
            bot.send_message(call.message.chat.id, f"❓ {q['q']}", reply_markup=kb)
            bot.answer_callback_query(call.id)
            return

        # answer to book quiz
        if data.startswith("ans_"):
            # ans_ch1_0_2
            parts = data.split("_")
            _, ch_id, q_idx, opt_idx = parts
            q_idx = int(q_idx); opt_idx = int(opt_idx)
            ch = BOOK_MAP.get(ch_id)
            quiz = ch["quiz"][q_idx]
            correct = (opt_idx == quiz["a"])
            uid = str(call.from_user.id)
            ensure_user(uid)
            USERDATA[uid]["scores"].setdefault(ch_id,[]).append(1 if correct else 0)
            save_data()
            bot.send_message(call.message.chat.id, "✅ Correct!" if correct else f"❌ Wrong. Ans: {quiz['opts'][quiz['a']]}")
            bot.answer_callback_query(call.id)
            return

        # daily quiz answer
        if data.startswith("dailyans_"):
            # dailyans_uid_idx_opt
            parts = data.split("_")
            _, uid_str, qidx_str, opt_str = parts
            uid = uid_str
            qidx = int(qidx_str); opt = int(opt_str)
            state = USERDATA.get(uid, {}).get("pending_quiz")
            if not state:
                bot.answer_callback_query(call.id, "Quiz not found.")
                return
            q = state["questions"][qidx]
            correct = (opt == q["a"])
            if correct:
                state["score"] = state.get("score",0) + 1
            state["index"] = state.get("index",0) + 1
            USERDATA[uid]["pending_quiz"] = state
            save_data()
            bot.answer_callback_query(call.id, "Answer recorded.")
            # send next question
            send_next_quiz_question(call.message.chat.id, uid)
            return

        bot.answer_callback_query(call.id, "Unknown action.")
    except Exception as e:
        try:
            bot.answer_callback_query(call.id, "Error occurred.")
        except:
            pass
        print("Callback error:", e)
        traceback.print_exc()

# -------------------------
# Message handlers: voice, image, text
# -------------------------
@bot.message_handler(content_types=['voice'])
def handle_voice(message):
    uid = message.from_user.id
    ensure_user(uid)
    try:
        file_info = bot.get_file(message.voice.file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        r = requests.get(file_url)
        ogg_bytes = r.content
        # convert to wav
        tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
        if AudioSegment is None:
            bot.reply_to(message, "Server missing audio conversion libs.")
            return
        convert_ogg_to_wav(ogg_bytes, tmp_wav.name)
        text = transcribe_audio_file(tmp_wav.name)
        log_user(uid, f"Voice: {text}")
        bot.send_message(message.chat.id, f"🎧 Transcribed: {text}")
        # pass to AI
        reply = openai_chat_reply(text)
        bot.send_message(message.chat.id, reply)
        log_user(uid, f"Bot: {reply}")
    except Exception as e:
        bot.reply_to(message, f"Voice error: {e}")
        traceback.print_exc()

@bot.message_handler(content_types=['photo'])
def handle_photo(message):
    uid = message.from_user.id
    ensure_user(uid)
    try:
        file_info = bot.get_file(message.photo[-1].file_id)
        file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_info.file_path}"
        r = requests.get(file_url)
        img_bytes = r.content
        if pytesseract is None:
            bot.send_message(message.chat.id, "OCR not available on server.")
            return
        extracted = ocr_image_from_bytes(img_bytes)
        if not extracted.strip():
            bot.send_message(message.chat.id, "Could not extract text from image.")
            return
        bot.send_message(message.chat.id, f"📝 Extracted text:\n{extracted}")
        log_user(uid, f"Photo text: {extracted}")
        # ask AI to solve / answer
        reply = openai_chat_reply(f"Solve or explain the following question:\n\n{extracted}")
        bot.send_message(message.chat.id, reply)
        log_user(uid, f"Bot: {reply}")
    except Exception as e:
        bot.reply_to(message, f"Image error: {e}")
        traceback.print_exc()

@bot.message_handler(content_types=['text'])
def handle_text(message):
    uid = message.from_user.id
    ensure_user(uid)
    txt = message.text.strip()
    log_user(uid, f"You: {txt}")

    # quick commands
    if txt.lower() in ("/start","start","help"):
        cmd_start(message); return

    if txt.lower().startswith("/addnote"):
        note = txt.partition(" ")[2].strip()
        if note:
            USERDATA[str(uid)]["notes"].append({"text":note,"ts":int(time.time())})
            save_data()
            bot.reply_to(message, "Note saved.")
        else:
            bot.reply_to(message, "Usage: /addnote your note")
        return

    if txt.lower() == "/mylugs" or txt.lower() == "/logs" or txt.lower() == "📜 my logs":
        logs = USERDATA[str(uid)].get("logs",[])
        out = "\n".join([f"- {l['text']}" for l in logs[-10:]]) or "No logs yet."
        bot.reply_to(message, f"🧾 Last logs:\n{out}")
        return

    # Translate helper (quick)
    if txt.lower().startswith("/translate") or message.text == "🌐 Translate":
        if Translator is None:
            bot.reply_to(message, "Translation not available on server.")
            return
        # user will send a next message to translate; simplified: translate current text
        try:
            trans = Translator()
            out = trans.translate(txt.partition(" ")[2] or txt, dest='en').text
            bot.reply_to(message, f"Translated:\n{out}")
        except Exception as e:
            bot.reply_to(message, f"Translate error: {e}")
        return

    # If user asks for quiz
    if txt.lower() == "/dailyquiz" or txt.lower() == "❓ quiz":
        cmd_dailyquiz(message); return

    # Default: pass to OpenAI
    reply = openai_chat_reply(txt)
    bot.send_message(message.chat.id, reply)
    log_user(uid, f"Bot: {reply}")

# -------------------------
# Keepalive Flask app for Render
# -------------------------
app = Flask("keepalive")
@app.route("/")
def index():
    return "TestBook Pro Bot is running."

def run_server():
    # pick port from env or default 10000
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_server, daemon=True).start()

# -------------------------
# Start polling
# -------------------------
if __name__ == "__main__":
    print("✅ TestBook Pro Bot starting...")
    try:
        bot.infinity_polling(timeout=60, long_polling_timeout = 60)
    except KeyboardInterrupt:
        print("Stopping...")
    except Exception as e:
        print("Runtime error:", e)
        traceback.print_exc()
