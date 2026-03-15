import os
import subprocess
import logging
import requests
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
    ConversationHandler,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ASSEMBLYAI_KEY = os.environ.get("ASSEMBLYAI_KEY")

WAITING_CHOICE = 1
WAITING_VIDEO_FOR_SRT = 2
WAITING_VIDEO_FOR_BURN = 3
WAITING_SRT = 4
WAITING_VIDEO_FOR_SPEAKER = 5
WAITING_SPEAKER_NUMBER = 6
WAITING_SRT_FOR_TRANSLATE = 7

user_data = {}

# ---------------- Utility Functions ---------------- #

def to_srt_time(ms):
    seconds = ms / 1000
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms_part = int(ms % 1000)
    return f"{h:02}:{m:02}:{s:02},{ms_part:03}"

def to_srt_time_sec(seconds):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"

def translate_text(text, target_lang):
    if target_lang == "kurdish":
        system_msg = "You are a professional translator. Translate the following text to Kurdish Sorani. Only return the translated text, nothing else."
    else:
        system_msg = "You are a professional translator. Translate the following text to English. Only return the translated text, nothing else."
    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": system_msg},
                    {"role": "user", "content": text}
                ],
                "temperature": 0.3,
                "max_tokens": 5000
            },
            timeout=60
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"].strip()
        return text
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text

async def download_media(update, path):
    msg = update.message
    if msg.text and msg.text.startswith("http"):
        result = subprocess.run(["yt-dlp", "-o", path + ".mp4", "--no-playlist", msg.text.strip()], capture_output=True, timeout=600)
        if result.returncode != 0:
            result2 = subprocess.run(["wget", "-O", path, msg.text.strip()], capture_output=True, timeout=600)
            return result2.returncode == 0
        return True
    elif msg.video or msg.document or msg.audio or msg.voice:
        file_obj = msg.video or msg.document or msg.audio or msg.voice
        size = getattr(file_obj, "file_size", 0) or 0
        if size > 50 * 1024 * 1024:
            return "too_big"
        tg_file = await file_obj.get_file()
        await tg_file.download_to_drive(path)
        return True
    return False

async def extract_audio(video_path, audio_path):
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", video_path, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k", audio_path],
        capture_output=True
    )
    return os.path.exists(audio_path)

# ---------------- AssemblyAI Speaker ---------------- #

def assemblyai_transcribe_with_speakers(audio_path, num_speakers):
    headers = {"Authorization": ASSEMBLYAI_KEY, "Content-Type": "application/json"}
    with open(audio_path, "rb") as f:
        upload_resp = requests.post(
            "https://api.assemblyai.com/v2/upload",
            headers=headers,
            data=f,
            timeout=180
        )
    if upload_resp.status_code != 200:
        raise Exception(f"Upload failed: {upload_resp.text}")
    audio_url = upload_resp.json()["upload_url"]

    payload = {
        "audio_url": audio_url,
        "speaker_labels": True,
        "speakers_expected": num_speakers,
        "speech_models": ["universal-3-pro", "universal-2"],
        "punctuate": True,
        "format_text": True
    }

    submit_resp = requests.post(
        "https://api.assemblyai.com/v2/transcript",
        headers=headers,
        json=payload,
        timeout=30
    )
    if submit_resp.status_code != 200:
        raise Exception(f"Submit failed: {submit_resp.text}")

    transcript_id = submit_resp.json().get("id")
    if not transcript_id:
        raise Exception(f"No transcript ID returned")

    waited = 0
    while waited < 600:
        time.sleep(5)
        waited += 5
        poll_resp = requests.get(
            f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
            headers=headers,
            timeout=30
        )
        result = poll_resp.json()
        status = result.get("status")
        logger.info(f"AssemblyAI status: {status} ({waited}s)")
        if status == "completed":
            utterances = result.get("utterances", [])
            if not utterances:
                raise Exception("No utterances returned")
            return utterances
        elif status == "error":
            raise Exception(f"Transcription error: {result.get('error')}")
    raise Exception("Timeout waiting for transcription")

# ---------------- Telegram Handlers ---------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎬 SRT کوردی دروست بکە", callback_data="make_srt_kurdish")],
        [InlineKeyboardButton("🌍 SRT وەرگێران بۆ ئینگلیزی", callback_data="make_srt_english")],
        [InlineKeyboardButton("🎤 دەنگی کەسێک دەربێنە", callback_data="speaker_extract")],
        [InlineKeyboardButton("📝 فایلی SRT وەرگێرە بۆ کوردی", callback_data="translate_srt_kurdish")],
        [InlineKeyboardButton("🔤 فایلی SRT وەرگێرە بۆ ئینگلیزی", callback_data="translate_srt_english")],
        [InlineKeyboardButton("🔥 SRT بخەرە ناو ڤیدیۆ", callback_data="burn_srt")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("سڵاو! 👋\n\nکام کارت دەوێت بکەیت؟", reply_markup=reply_markup)
    return WAITING_CHOICE

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    if query.data == "make_srt_kurdish":
        user_data[uid] = {"mode": "make_srt_kurdish"}
        await query.edit_message_text("باشە! 🎬\n\nلینکی ڤیدیۆ یان فایلەکەت بنێرە 📁")
        return WAITING_VIDEO_FOR_SRT
    elif query.data == "make_srt_english":
        user_data[uid] = {"mode": "make_srt_english"}
        await query.edit_message_text("باشە! 🌍\n\nلینکی ڤیدیۆ یان فایلەکەت بنێرە 📁")
        return WAITING_VIDEO_FOR_SRT
    elif query.data == "speaker_extract":
        user_data[uid] = {"mode": "speaker_extract"}
        await query.edit_message_text("باشە! 🎤\n\nلینکی ڤیدیۆ یان فایلەکەت بنێرە 📁")
        return WAITING_VIDEO_FOR_SPEAKER
    elif query.data == "burn_srt":
        user_data[uid] = {"mode": "burn_srt"}
        await query.edit_message_text("باشە! 🔥\n\nلینکی ڤیدیۆکەت بنێرە 📁")
        return WAITING_VIDEO_FOR_BURN
    elif query.data == "translate_srt_kurdish":
        user_data[uid] = {"mode": "translate_srt_kurdish"}
        await query.edit_message_text("تکایە فایلی SRT بنێرە بۆ وەرگێڕان بۆ کوردی 📄")
        return WAITING_SRT_FOR_TRANSLATE
    elif query.data == "translate_srt_english":
        user_data[uid] = {"mode": "translate_srt_english"}
        await query.edit_message_text("تکایە فایلی SRT بنێرە بۆ وەرگێڕان بۆ ئینگلیزی 📄")
        return WAITING_SRT_FOR_TRANSLATE

# ---------------- SRT / Translation ---------------- #

async def receive_video_for_srt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    os.makedirs(f"/tmp/{user_id}", exist_ok=True)
    video_path = f"/tmp/{user_id}/input_video.mp4"
    mode = user_data.get(user_id, {}).get("mode", "make_srt_kurdish")

    await update.message.reply_text("وەرگرتم... ⏳")
    dl = await download_media(update, video_path)
    if dl == "too_big":
        await update.message.reply_text("فایلەکەت زۆر گەورەیە\nتکایە لینک بنێرە")
        return WAITING_VIDEO_FOR_SRT
    if not dl:
        await update.message.reply_text("تکایە فایل یان لینک بنێرە 📁")
        return WAITING_VIDEO_FOR_SRT

    audio_path = f"/tmp/{user_id}/audio.mp3"
    await update.message.reply_text("دەنگەکە دەردەهێنم... ⏳")
    if not await extract_audio(video_path, audio_path):
        await update.message.reply_text("کێشەیەک هەبوو لە دەرهێنانی دەنگدا")
        return WAITING_VIDEO_FOR_SRT

    await update.message.reply_text("Whisper AI گوێ دەگرێت... ⏳")
    try:
        with open(audio_path, "rb") as f:
            response = requests.post(
                "https://api.groq.com/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.mp3", f, "audio/mpeg")},
                data={"model": "whisper-large-v3", "response_format": "verbose_json", "timestamp_granularities[]": "segment"},
                timeout=180
            )
        if response.status_code != 200:
            await update.message.reply_text("کێشەیەک هەبوو لە Whisper")
            return WAITING_VIDEO_FOR_SRT

        data = response.json()
        segments = data.get("segments", [])
        detected_lang = data.get("language", "نازانرێت")
        if not segments:
            await update.message.reply_text("هیچ دەنگێک نەدۆزرایەوە")
            return WAITING_VIDEO_FOR_SRT

        target = "kurdish" if mode == "make_srt_kurdish" else "english"
        fname = "kurdish_subtitles.srt" if target == "kurdish" else "english_subtitles.srt"
        caption_end = "وەرگێڕاوە بۆ کوردی سورانی" if target == "kurdish" else "وەرگێڕاوە بۆ ئینگلیزی"

        # Batch translation
        joined_texts = "\n".join([seg["text"].strip() for seg in segments])
        translated_all = translate_text(joined_texts, target)
        translated_segments = translated_all.split("\n")
        srt_content = ""
        for i, seg in enumerate(segments):
            text = translated_segments[i] if i < len(translated_segments) else seg["text"].strip()
            srt_content += f"{i+1}\n{to_srt_time_sec(seg['start'])} --> {to_srt_time_sec(seg['end'])}\n{text}\n\n"

        srt_path = f"/tmp/{user_id}/{fname}"
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        await update.message.reply_text("ئامادەیە! 🎉")
        with open(srt_path, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=fname,
                caption=f"✅ {len(segments)} رستە\nزمانی ئەسڵی: {detected_lang}\n{caption_end}"
            )
    except Exception as e:
        logger.error(f"SRT error: {e}")
        await update.message.reply_text("کێشەیەک هەبوو")

    # cleanup
    for p in [video_path, audio_path, srt_path]:
        try: os.remove(p)
        except: pass
    user_data.pop(user_id, None)
    return ConversationHandler.END

# ---------------- Main ---------------- #

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("هەڵوەشایەوە\n/start بنووسە بۆ دەستپێکردنەوە")
    return ConversationHandler.END

def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN not set")

    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_CHOICE: [CallbackQueryHandler(button_handler)],
            WAITING_VIDEO_FOR_SRT: [MessageHandler(filters.ALL, receive_video_for_srt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True,
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
