import os
import subprocess
import logging
import requests
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes, ConversationHandler

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

user_data = {}

def to_srt_time(seconds):
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
                "max_tokens": 500
            },
            timeout=30
        )
        if response.status_code == 200:
            translated = response.json()["choices"][0]["message"]["content"].strip()
            logger.info(f"Translated ({target_lang}): {text[:40]} -> {translated[:40]}")
            return translated
        else:
            logger.error(f"Translation error: {response.status_code} {response.text}")
            return text
    except Exception as e:
        logger.error(f"Translation exception: {e}")
        return text

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("🎬 SRT کوردی دروست بکە", callback_data="make_srt_kurdish")],
        [InlineKeyboardButton("🌍 SRT وەرگێران بۆ ئینگلیزی", callback_data="make_srt_english")],
        [InlineKeyboardButton("🎤 دەنگی کەسێک دەربێنە", callback_data="speaker_extract")],
        [InlineKeyboardButton("🔥 SRT بخەرە ناو ڤیدیۆ", callback_data="burn_srt")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "سڵاو! 👋\n\nکام کارت دەوێت بکەیت؟",
        reply_markup=reply_markup
    )
    return WAITING_CHOICE

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "make_srt_kurdish":
        user_data[query.from_user.id] = {"mode": "make_srt_kurdish"}
        await query.edit_message_text("باشە! 🎬\n\nلینکی ڤیدیۆ یان ئۆدیۆکەت بنێرە\n(Google Drive, YouTube, هەر لینکێک)\n\nیان فایلەکە ڕاستەوخۆ بنێرە 📁")
        return WAITING_VIDEO_FOR_SRT

    elif query.data == "make_srt_english":
        user_data[query.from_user.id] = {"mode": "make_srt_english"}
        await query.edit_message_text("باشە! 🌍\n\nلینکی ڤیدیۆ یان ئۆدیۆکەت بنێرە\n(Google Drive, YouTube, هەر لینکێک)\n\nیان فایلەکە ڕاستەوخۆ بنێرە 📁")
        return WAITING_VIDEO_FOR_SRT

    elif query.data == "speaker_extract":
        user_data[query.from_user.id] = {"mode": "speaker_extract"}
        await query.edit_message_text("باشە! 🎤\n\nلینکی ڤیدیۆ یان ئۆدیۆکەت بنێرە\n(Google Drive, YouTube, هەر لینکێک)\n\nیان فایلەکە ڕاستەوخۆ بنێرە 📁")
        return WAITING_VIDEO_FOR_SPEAKER

    elif query.data == "burn_srt":
        user_data[query.from_user.id] = {"mode": "burn_srt"}
        await query.edit_message_text("باشە! 🔥\n\nلینکی ڤیدیۆکەت بنێرە\n(Google Drive, YouTube, هەر لینکێک)\n\nیان فایلەکە ڕاستەوخۆ بنێرە 📁")
        return WAITING_VIDEO_FOR_BURN

async def download_file(url, path):
    try:
        result = subprocess.run(["yt-dlp", "-o", path, "--no-playlist", url], capture_output=True, timeout=600)
        if result.returncode == 0:
            return True
        result2 = subprocess.run(["wget", "-O", path, url], capture_output=True, timeout=600)
        return result2.returncode == 0
    except:
        return False

async def receive_video_for_speaker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    os.makedirs(f"/tmp/{user_id}", exist_ok=True)
    video_path = f"/tmp/{user_id}/input_video"

    if update.message.text and update.message.text.startswith("http"):
        url = update.message.text.strip()
        await update.message.reply_text("دابەزێنم... ⏳")
        success = await download_file(url, video_path)
        if not success:
            await update.message.reply_text("نەمتوانی دابەزێنم ❌")
            return WAITING_VIDEO_FOR_SPEAKER
    elif update.message.video or update.message.document or update.message.audio or update.message.voice:
        file = update.message.video or update.message.document or update.message.audio or update.message.voice
        await update.message.reply_text("وەرگرتم ⏳")
        tg_file = await file.get_file()
        await tg_file.download_to_drive(video_path)
    else:
        await update.message.reply_text("تکایە فایل یان لینک بنێرە 📁")
        return WAITING_VIDEO_FOR_SPEAKER

    user_data[user_id]["video"] = video_path
    await update.message.reply_text("چەند دەنگ لە ڤیدیۆکەدا قسە دەکەن؟\nنووسە: 2، 3، 4...")
    return WAITING_SPEAKER_NUMBER

async def receive_speaker_number(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    try:
        num_speakers = int(update.message.text.strip())
        if num_speakers < 1 or num_speakers > 10:
            await update.message.reply_text("تکایە ژمارەیەک لە نێوان 1-10 بنووسە")
            return WAITING_SPEAKER_NUMBER
    except:
        await update.message.reply_text("تکایە ژمارەیەک بنووسە (وەک: 2، 3، 4)")
        return WAITING_SPEAKER_NUMBER

    video_path = user_data[user_id]["video"]
    await update.message.reply_text(f"باشە! {num_speakers} دەنگ — دەنگەکە دەردەهێنم... ⏳")

    # Extract audio
    audio_path = f"/tmp/{user_id}/audio.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        audio_path
    ], capture_output=True)

    if not os.path.exists(audio_path):
        await update.message.reply_text("کێشەیەک هەبوو ❌")
        return ConversationHandler.END

    await update.message.reply_text("AssemblyAI دەنگەکان جیا دەکاتەوە... ⏳\nئەمە چەند خولەک کات دەبرێت")

    try:
        # Upload audio to AssemblyAI
        with open(audio_path, "rb") as f:
            upload_response = requests.post(
                "https://api.assemblyai.com/v2/upload",
                headers={"authorization": ASSEMBLYAI_KEY},
                data=f,
                timeout=120
            )

        if upload_response.status_code != 200:
            await update.message.reply_text("کێشەیەک هەبوو لە بارکردندا ❌")
            return ConversationHandler.END

        audio_url = upload_response.json()["upload_url"]

        # Submit transcription with diarization
        transcript_response = requests.post(
            "https://api.assemblyai.com/v2/transcript",
            headers={"authorization": ASSEMBLYAI_KEY, "content-type": "application/json"},
            json={
                "audio_url": audio_url,
                "speaker_labels": True,
                "speakers_expected": num_speakers
            },
            timeout=30
        )

        transcript_id = transcript_response.json()["id"]

        # Poll for result
        while True:
            time.sleep(5)
            result_response = requests.get(
                f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
                headers={"authorization": ASSEMBLYAI_KEY},
                timeout=30
            )
            result = result_response.json()

            if result["status"] == "completed":
                break
            elif result["status"] == "error":
                await update.message.reply_text("کێشەیەک هەبوو ❌")
                return ConversationHandler.END

        # Get unique speakers
        utterances = result.get("utterances", [])
        speakers = list(set([u["speaker"] for u in utterances]))
        speakers.sort()

        # Create keyboard for speaker selection
        keyboard = []
        for sp in speakers:
            keyboard.append([InlineKeyboardButton(f"🎤 دەنگی {sp}", callback_data=f"sp_{transcript_id}_{sp}_{user_id}")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            f"✅ {len(speakers)} دەنگ دۆزرایەوە!\nکام دەنگت دەوێت دەربهێنیت؟",
            reply_markup=reply_markup
        )

    except Exception as e:
        logger.error(f"AssemblyAI error: {e}")
        await update.message.reply_text("کێشەیەک هەبوو ❌")

    return ConversationHandler.END

async def speaker_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split("_")
    transcript_id = parts[1]
    speaker = parts[2]
    user_id = int(parts[3])

    await query.edit_message_text(f"دەنگی {speaker} دەردەهێنم... ⏳")

    try:
        result_response = requests.get(
            f"https://api.assemblyai.com/v2/transcript/{transcript_id}",
            headers={"authorization": ASSEMBLYAI_KEY},
            timeout=30
        )
        result = result_response.json()
        utterances = result.get("utterances", [])

        # Filter by speaker
        speaker_utterances = [u for u in utterances if u["speaker"] == speaker]

        # Create SRT
        srt_content = ""
        for i, utt in enumerate(speaker_utterances, 1):
            start = utt["start"] / 1000
            end = utt["end"] / 1000
            text = utt["text"]
            srt_content += f"{i}\n{to_srt_time(start)} --> {to_srt_time(end)}\n{text}\n\n"

        srt_path = f"/tmp/{user_id}/speaker_{speaker}.srt"
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        await query.message.reply_text("ئامادەیە! 🎉")
        with open(srt_path, "rb") as f:
            await query.message.reply_document(
                document=f,
                filename=f"speaker_{speaker}.srt",
                caption=f"✅ دەنگی {speaker}\n{len(speaker_utterances)} رستە"
            )

        if os.path.exists(srt_path):
            os.remove(srt_path)

    except Exception as e:
        logger.error(f"Speaker extract error: {e}")
        await query.message.reply_text("کێشەیەک هەبوو ❌")

async def receive_video_for_srt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    os.makedirs(f"/tmp/{user_id}", exist_ok=True)
    video_path = f"/tmp/{user_id}/input_video"
    mode = user_data.get(user_id, {}).get("mode", "make_srt_kurdish")

    if update.message.text and update.message.text.startswith("http"):
        url = update.message.text.strip()
        await update.message.reply_text("دابەزێنم... ⏳")
        success = await download_file(url, video_path)
        if not success:
            await update.message.reply_text("نەمتوانی دابەزێنم ❌")
            return WAITING_VIDEO_FOR_SRT
    elif update.message.video or update.message.document or update.message.audio or update.message.voice:
        file = update.message.video or update.message.document or update.message.audio or update.message.voice
        await update.message.reply_text("وەرگرتم ⏳")
        tg_file = await file.get_file()
        await tg_file.download_to_drive(video_path)
    else:
        await update.message.reply_text("تکایە فایل یان لینک بنێرە 📁")
        return WAITING_VIDEO_FOR_SRT

    await update.message.reply_text("دەنگەکە دەردەهێنم... ⏳")

    audio_path = f"/tmp/{user_id}/audio.mp3"
    subprocess.run([
        "ffmpeg", "-y", "-i", video_path,
        "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k",
        audio_path
    ], capture_output=True)

    if not os.path.exists(audio_path):
        await update.message.reply_text("کێشەیەک هەبوو ❌")
        return WAITING_VIDEO_FOR_SRT

    await update.message.reply_text("Whisper گوێ دەگرێت... ⏳")

    try:
        with open(audio_path, "rb") as f:
            response = requests.post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.mp3", f, "audio/mpeg")},
                data={
                    "model": "whisper-large-v3",
                    "response_format": "verbose_json",
                    "timestamp_granularities[]": "segment"
                },
                timeout=120
            )

        if response.status_code != 200:
            await update.message.reply_text("کێشەیەک هەبوو ❌")
            return WAITING_VIDEO_FOR_SRT

        data = response.json()
        segments = data.get("segments", [])
        detected_lang = data.get("language", "نازانرێت")

        if not segments:
            await update.message.reply_text("هیچ دەنگێک نەدۆزرایەوە ❌")
            return WAITING_VIDEO_FOR_SRT

        if mode == "make_srt_kurdish":
            target = "kurdish"
            await update.message.reply_text(f"زمانی دۆزرایەوە: {detected_lang}\nوەردەگێرم بۆ کوردی سورانی... ⏳")
            fname = "kurdish_subtitles.srt"
            caption_end = "وەرگێڕاوە بۆ: کوردی سورانی"
        else:
            target = "english"
            await update.message.reply_text(f"زمانی دۆزرایەوە: {detected_lang}\nوەردەگێرم بۆ ئینگلیزی... ⏳")
            fname = "english_subtitles.srt"
            caption_end = "وەرگێڕاوە بۆ: ئینگلیزی"

        srt_content = ""
        for i, seg in enumerate(segments, 1):
            start = seg["start"]
            end = seg["end"]
            original_text = seg["text"].strip()
            translated_text = translate_text(original_text, target)
            srt_content += f"{i}\n{to_srt_time(start)} --> {to_srt_time(end)}\n{translated_text}\n\n"

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
        logger.error(f"Error: {e}")
        await update.message.reply_text("کێشەیەک هەبوو ❌")

    for p in [video_path, audio_path]:
        try:
            if os.path.exists(p):
                os.remove(p)
        except:
            pass

    return ConversationHandler.END

async def receive_video_for_burn(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    os.makedirs(f"/tmp/{user_id}", exist_ok=True)
    video_path = f"/tmp/{user_id}/video.mp4"

    if update.message.text and update.message.text.startswith("http"):
        url = update.message.text.strip()
        await update.message.reply_text("دابەزێنم... ⏳")
        success = await download_file(url, video_path)
        if not success:
            await update.message.reply_text("نەمتوانی دابەزێنم ❌")
            return WAITING_VIDEO_FOR_BURN
        await update.message.reply_text("ڤیدیۆکەت ئامادەیە ✅\nئێستا فایلی SRT بنێرە 📄")
    elif update.message.video or (update.message.document and 'video' in (update.message.document.mime_type or '')):
        file = update.message.video or update.message.document
        await update.message.reply_text("وەرگرتم ✅\nئێستا فایلی SRT بنێرە 📄")
        tg_file = await file.get_file()
        await tg_file.download_to_drive(video_path)
    else:
        await update.message.reply_text("تکایە فایل یان لینک بنێرە 📁")
        return WAITING_VIDEO_FOR_BURN

    user_data[user_id]["video"] = video_path
    return WAITING_SRT

async def receive_srt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if not update.message.document or not (update.message.document.file_name or "").endswith(".srt"):
        await update.message.reply_text("تکایە فایلێکی SRT بنێرە 📄")
        return WAITING_SRT

    await update.message.reply_text("کاردەکەم... ⏳")

    srt_file = await update.message.document.get_file()
    srt_path = f"/tmp/{user_id}/subtitle.srt"
    await srt_file.download_to_drive(srt_path)

    video_path = user_data[user_id]["video"]
    output_path = f"/tmp/{user_id}/output.mp4"
    ass_path = f"/tmp/{user_id}/subtitle.ass"

    subprocess.run(["ffmpeg", "-y", "-i", srt_path, ass_path], capture_output=True)

    if os.path.exists(ass_path):
        with open(ass_path, 'r', encoding='utf-8') as f:
            ass_content = f.read()
        ass_content = ass_content.replace('Style: Default,Arial', 'Style: Default,NRT Reg')
        ass_content = ass_content.replace('Fontname: Arial', 'Fontname: NRT Reg')
        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(ass_content)

    cmd = [
        "ffmpeg", "-y", "-i", video_path,
        "-vf", f"scale=640:360,ass={ass_path}:fontsdir=/app",
        "-preset", "ultrafast", "-crf", "35",
        "-c:a", "copy", output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if result.returncode == 0 and os.path.exists(output_path):
            await update.message.reply_text("ئامادەیە! 🎉")
            with open(output_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="output_kurdish.mp4",
                    caption="ساب‌تایتڵی کوردی هاردکۆد کراوە ✅"
                )
        else:
            logger.error(f"FFmpeg error: {result.stderr}")
            await update.message.reply_text("کێشەیەک هەبوو ❌")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("ڤیدیۆکەت زۆر درێژە ❌")
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("کێشەیەک هەبوو ❌")

    for p in [video_path, srt_path, ass_path, output_path]:
        try:
            if os.path.exists(p):
                os.remove(p)
        except:
            pass

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("هەڵوەشایەوە ❌\n/start بنووسە بۆ دەستپێکردنەوە")
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            WAITING_CHOICE: [CallbackQueryHandler(button_handler, pattern="^(make_srt_kurdish|make_srt_english|speaker_extract|burn_srt)$")],
            WAITING_VIDEO_FOR_SRT: [MessageHandler(filters.ALL, receive_video_for_srt)],
            WAITING_VIDEO_FOR_BURN: [MessageHandler(filters.ALL, receive_video_for_burn)],
            WAITING_VIDEO_FOR_SPEAKER: [MessageHandler(filters.ALL, receive_video_for_speaker)],
            WAITING_SPEAKER_NUMBER: [MessageHandler(filters.TEXT, receive_speaker_number)],
            WAITING_SRT: [MessageHandler(filters.Document.ALL, receive_srt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(speaker_callback, pattern="^sp_"))
    app.run_polling()

if __name__ == "__main__":
    main()
