import os
import subprocess
import logging
import requests
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
ASSEMBLYAI_KEY = os.environ.get("ASSEMBLYAI_KEY")

# Simple state management per user
user_state = {}  # user_id -> current state string
user_data = {}   # user_id -> data dict

def to_srt_time(ms):
    s = ms / 1000
    h, r = divmod(s, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02},{int(ms%1000):03}"

def to_srt_time_sec(seconds):
    h, r = divmod(seconds, 3600)
    m, s = divmod(r, 60)
    return f"{int(h):02}:{int(m):02}:{int(s):02},{int((seconds%1)*1000):03}"

def translate_text(text, target):
    sys_msg = "You are a professional translator. Translate to Kurdish Sorani. Only return translated text." if target == "kurdish" else "You are a professional translator. Translate to English. Only return translated text."
    try:
        r = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"},
            json={"model": "llama-3.3-70b-versatile", "messages": [{"role": "system", "content": sys_msg}, {"role": "user", "content": text}], "temperature": 0.3, "max_tokens": 500},
            timeout=30
        )
        if r.status_code == 200:
            return r.json()["choices"][0]["message"]["content"].strip()
        return text
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text

def assemblyai_diarize(audio_path, num_speakers):
    headers = {"Authorization": ASSEMBLYAI_KEY, "Content-Type": "application/json"}
    with open(audio_path, "rb") as f:
        up = requests.post("https://api.assemblyai.com/v2/upload", headers={"Authorization": ASSEMBLYAI_KEY}, data=f, timeout=180)
    if up.status_code != 200:
        raise Exception(f"Upload failed: {up.text}")
    audio_url = up.json()["upload_url"]
    sub = requests.post("https://api.assemblyai.com/v2/transcript", headers=headers,
        json={"audio_url": audio_url, "speaker_labels": True, "speakers_expected": num_speakers, "speech_models": ["universal-3-pro", "universal-2"], "punctuate": True, "format_text": True}, timeout=30)
    if sub.status_code != 200:
        raise Exception(f"Submit failed: {sub.text}")
    job = sub.json()
    if "id" not in job:
        raise Exception(f"No ID: {job}")
    tid = job["id"]
    for _ in range(120):
        time.sleep(5)
        res = requests.get(f"https://api.assemblyai.com/v2/transcript/{tid}", headers={"Authorization": ASSEMBLYAI_KEY}, timeout=30).json()
        logger.info(f"AssemblyAI: {res.get('status')}")
        if res["status"] == "completed":
            utts = res.get("utterances", [])
            if not utts:
                raise Exception("No utterances")
            return utts
        elif res["status"] == "error":
            raise Exception(f"Error: {res.get('error')}")
    raise Exception("Timeout")

async def extract_audio(video_path, audio_path):
    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-ar", "16000", "-ac", "1", "-b:a", "64k", audio_path], capture_output=True)
    return os.path.exists(audio_path)

async def download_media(update, path):
    msg = update.message
    if msg.text and msg.text.startswith("http"):
        r = subprocess.run(["yt-dlp", "-o", path, "--no-playlist", msg.text.strip()], capture_output=True, timeout=600)
        if r.returncode != 0:
            r2 = subprocess.run(["wget", "-O", path, msg.text.strip()], capture_output=True, timeout=600)
            return r2.returncode == 0
        return True
    elif msg.video or msg.document or msg.audio or msg.voice:
        f = msg.video or msg.document or msg.audio or msg.voice
        size = getattr(f, "file_size", 0) or 0
        if size > 50 * 1024 * 1024:
            return "too_big"
        tg = await f.get_file()
        await tg.download_to_drive(path)
        return True
    return False

def get_main_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 SRT کوردی لە ڤیدیۆ", callback_data="make_srt_kurdish")],
        [InlineKeyboardButton("🌍 SRT ئینگلیزی لە ڤیدیۆ", callback_data="make_srt_english")],
        [InlineKeyboardButton("🎤 دەنگی کەسێک دەربێنە", callback_data="speaker_extract")],
        [InlineKeyboardButton("📝 فایلی SRT وەرگێرە بۆ کوردی", callback_data="translate_srt_kurdish")],
        [InlineKeyboardButton("🔤 فایلی SRT وەرگێرە بۆ ئینگلیزی", callback_data="translate_srt_english")],
        [InlineKeyboardButton("🔥 SRT بخەرە ناو ڤیدیۆ", callback_data="burn_srt")],
    ])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    user_state[uid] = "choosing"
    user_data[uid] = {}
    await update.message.reply_text("سڵاو! 👋\n\nکام کارت دەوێت بکەیت؟", reply_markup=get_main_keyboard())

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    uid = query.from_user.id
    d = query.data

    if d == "make_srt_kurdish":
        user_state[uid] = "waiting_video_srt"
        user_data[uid] = {"mode": "make_srt_kurdish"}
        await query.edit_message_text("باشە! 🎬\n\nلینکی ڤیدیۆ یان ئۆدیۆکەت بنێرە\nیان فایلەکە ڕاستەوخۆ بنێرە 📁")

    elif d == "make_srt_english":
        user_state[uid] = "waiting_video_srt"
        user_data[uid] = {"mode": "make_srt_english"}
        await query.edit_message_text("باشە! 🌍\n\nلینکی ڤیدیۆ یان ئۆدیۆکەت بنێرە\nیان فایلەکە ڕاستەوخۆ بنێرە 📁")

    elif d == "speaker_extract":
        user_state[uid] = "waiting_video_speaker"
        user_data[uid] = {"mode": "speaker_extract"}
        await query.edit_message_text("باشە! 🎤\n\nلینکی ڤیدیۆ یان ئۆدیۆکەت بنێرە\nیان فایلەکە ڕاستەوخۆ بنێرە 📁")

    elif d == "translate_srt_kurdish":
        user_state[uid] = "waiting_srt_translate"
        user_data[uid] = {"mode": "translate_srt_kurdish"}
        await query.edit_message_text("باشە! 📝\n\nفایلی SRT بنێرە بۆ وەرگێڕانی کوردی 📄")

    elif d == "translate_srt_english":
        user_state[uid] = "waiting_srt_translate"
        user_data[uid] = {"mode": "translate_srt_english"}
        await query.edit_message_text("باشە! 🔤\n\nفایلی SRT بنێرە بۆ وەرگێڕانی ئینگلیزی 📄")

    elif d == "burn_srt":
        user_state[uid] = "waiting_video_burn"
        user_data[uid] = {"mode": "burn_srt"}
        await query.edit_message_text("باشە! 🔥\n\nلینکی ڤیدیۆکەت بنێرە\nیان فایلەکە ڕاستەوخۆ بنێرە 📁")

    elif d.startswith("sp_"):
        parts = d.split("_")
        speaker = parts[1]
        owner_id = int(parts[2])
        utterances = user_data.get(owner_id, {}).get("utterances", [])
        if not utterances:
            await query.edit_message_text("کێشەیەک هەبوو — /start بنووسە")
            return
        await query.edit_message_text(f"دەنگی {speaker} دەردەهێنم... ⏳")
        try:
            sp_utts = [u for u in utterances if u["speaker"] == speaker]
            srt = ""
            for i, u in enumerate(sp_utts, 1):
                srt += f"{i}\n{to_srt_time(u['start'])} --> {to_srt_time(u['end'])}\n{u['text'].strip()}\n\n"
            path = f"/tmp/{owner_id}/speaker_{speaker}.srt"
            with open(path, "w", encoding="utf-8") as f:
                f.write(srt)
            dur = (sp_utts[-1]["end"] - sp_utts[0]["start"]) / 1000 / 60
            await query.message.reply_text("ئامادەیە! 🎉")
            with open(path, "rb") as f:
                await query.message.reply_document(document=f, filename=f"speaker_{speaker}.srt",
                    caption=f"🎤 دەنگی {speaker}\n✅ {len(sp_utts)} رستە\n⏱ نزیکەی {int(dur)} خولەک")
            os.remove(path)
        except Exception as e:
            logger.error(f"Speaker extract: {e}")
            await query.message.reply_text("کێشەیەک هەبوو")

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    uid = update.message.from_user.id
    state = user_state.get(uid, "")

    if state == "waiting_video_srt":
        await handle_video_for_srt(update, uid)
    elif state == "waiting_video_speaker":
        await handle_video_for_speaker(update, uid)
    elif state == "waiting_speaker_number":
        await handle_speaker_number(update, uid)
    elif state == "waiting_srt_translate":
        await handle_srt_translate(update, uid)
    elif state == "waiting_video_burn":
        await handle_video_for_burn(update, uid)
    elif state == "waiting_srt_burn":
        await handle_srt_burn(update, uid)
    else:
        await update.message.reply_text("/start بنووسە بۆ دەستپێکردن")

async def handle_video_for_srt(update, uid):
    os.makedirs(f"/tmp/{uid}", exist_ok=True)
    path = f"/tmp/{uid}/input_video"
    mode = user_data[uid]["mode"]

    await update.message.reply_text("وەرگرتم... ⏳")
    dl = await download_media(update, path)
    if dl == "too_big":
        await update.message.reply_text("فایلەکەت زۆر گەورەیە\nتکایە لینک بنێرە")
        return
    if not dl:
        await update.message.reply_text("تکایە فایل یان لینک بنێرە 📁")
        return

    await update.message.reply_text("دەنگ دەردەهێنم... ⏳")
    audio = f"/tmp/{uid}/audio.mp3"
    if not await extract_audio(path, audio):
        await update.message.reply_text("کێشەیەک هەبوو لە دەرهێنانی دەنگدا")
        return

    await update.message.reply_text("Whisper AI گوێ دەگرێت... ⏳")
    try:
        with open(audio, "rb") as f:
            r = requests.post("https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
                files={"file": ("audio.mp3", f, "audio/mpeg")},
                data={"model": "whisper-large-v3", "response_format": "verbose_json", "timestamp_granularities[]": "segment"},
                timeout=120)
        if r.status_code != 200:
            await update.message.reply_text("کێشەیەک هەبوو لە Whisper")
            return
        data = r.json()
        segments = data.get("segments", [])
        lang = data.get("language", "نازانرێت")
        if not segments:
            await update.message.reply_text("هیچ دەنگێک نەدۆزرایەوە")
            return

        target = "kurdish" if mode == "make_srt_kurdish" else "english"
        label = "کوردی سورانی" if target == "kurdish" else "ئینگلیزی"
        await update.message.reply_text(f"زمانی دۆزرایەوە: {lang}\nوەردەگێرم بۆ {label}... ⏳")

        srt = ""
        for i, seg in enumerate(segments, 1):
            translated = translate_text(seg["text"].strip(), target)
            srt += f"{i}\n{to_srt_time_sec(seg['start'])} --> {to_srt_time_sec(seg['end'])}\n{translated}\n\n"

        fname = f"{target}_subtitles.srt"
        out = f"/tmp/{uid}/{fname}"
        with open(out, "w", encoding="utf-8") as f:
            f.write(srt)
        await update.message.reply_text("ئامادەیە! 🎉")
        with open(out, "rb") as f:
            await update.message.reply_document(document=f, filename=fname,
                caption=f"✅ {len(segments)} رستە\nزمانی ئەسڵی: {lang}\nوەرگێڕاوە بۆ: {label}")
        for p in [path, audio, out]:
            try:
                if os.path.exists(p): os.remove(p)
            except: pass
    except Exception as e:
        logger.error(f"SRT error: {e}")
        await update.message.reply_text("کێشەیەک هەبوو")
    user_state[uid] = "done"

async def handle_video_for_speaker(update, uid):
    os.makedirs(f"/tmp/{uid}", exist_ok=True)
    path = f"/tmp/{uid}/input_video"
    await update.message.reply_text("وەرگرتم... ⏳")
    dl = await download_media(update, path)
    if dl == "too_big":
        await update.message.reply_text("فایلەکەت زۆر گەورەیە\nتکایە لینک بنێرە")
        return
    if not dl:
        await update.message.reply_text("تکایە فایل یان لینک بنێرە 📁")
        return
    user_data[uid]["video"] = path
    user_state[uid] = "waiting_speaker_number"
    await update.message.reply_text("چەند دەنگ لە ڤیدیۆکەدا قسە دەکەن؟\nنووسە ژمارە (وەک: 2، 3، 4)")

async def handle_speaker_number(update, uid):
    try:
        n = int(update.message.text.strip())
        if n < 1 or n > 10:
            await update.message.reply_text("تکایە ژمارەیەک لە 1-10 بنووسە")
            return
    except:
        await update.message.reply_text("تکایە ژمارەیەک بنووسە")
        return

    video = user_data[uid]["video"]
    await update.message.reply_text(f"باشە! {n} دەنگ\nدەنگ دەردەهێنم... ⏳")
    audio = f"/tmp/{uid}/audio_sp.mp3"
    if not await extract_audio(video, audio):
        await update.message.reply_text("کێشەیەک هەبوو")
        return
    await update.message.reply_text("AssemblyAI دەنگەکان جیا دەکاتەوە... ⏳")
    try:
        utts = assemblyai_diarize(audio, n)
        user_data[uid]["utterances"] = utts
        speakers = sorted(set(u["speaker"] for u in utts))
        keyboard = []
        for sp in speakers:
            sp_u = [u for u in utts if u["speaker"] == sp]
            words = sum(len(u["text"].split()) for u in sp_u)
            keyboard.append([InlineKeyboardButton(f"🎤 دەنگی {sp} ({len(sp_u)} رستە، {words} وشە)", callback_data=f"sp_{sp}_{uid}")])
        await update.message.reply_text(f"✅ {len(speakers)} دەنگ دۆزرایەوە!\nکام دەنگت دەوێت؟", reply_markup=InlineKeyboardMarkup(keyboard))
        for p in [video, audio]:
            try:
                if os.path.exists(p): os.remove(p)
            except: pass
    except Exception as e:
        logger.error(f"Diarization error: {e}")
        await update.message.reply_text(f"کێشەیەک هەبوو: {str(e)[:100]}")
    user_state[uid] = "done"

async def handle_srt_translate(update, uid):
    mode = user_data[uid]["mode"]
    if not update.message.document or not (update.message.document.file_name or "").endswith(".srt"):
        await update.message.reply_text("تکایە فایلێکی SRT بنێرە 📄")
        return
    await update.message.reply_text("وەرگرتم... وەردەگێرم ⏳")
    os.makedirs(f"/tmp/{uid}", exist_ok=True)
    srt_path = f"/tmp/{uid}/input.srt"
    tg = await update.message.document.get_file()
    await tg.download_to_drive(srt_path)
    try:
        with open(srt_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        target = "kurdish" if mode == "translate_srt_kurdish" else "english"
        label = "کوردی سورانی" if target == "kurdish" else "ئینگلیزی"
        out_lines = []
        i = 0
        count = 0
        while i < len(lines):
            line = lines[i]
            if line.strip().isdigit():
                out_lines.append(line)
                i += 1
                if i < len(lines) and "-->" in lines[i]:
                    out_lines.append(lines[i])
                    i += 1
                    text_lines = []
                    while i < len(lines) and lines[i].strip():
                        text_lines.append(lines[i].strip())
                        i += 1
                    if text_lines:
                        translated = translate_text(" ".join(text_lines), target)
                        out_lines.append(translated + "\n")
                        count += 1
                    out_lines.append("\n")
            else:
                out_lines.append(line)
                i += 1
        fname = f"{target}_translated.srt"
        out = f"/tmp/{uid}/{fname}"
        with open(out, "w", encoding="utf-8") as f:
            f.writelines(out_lines)
        await update.message.reply_text("ئامادەیە! 🎉")
        with open(out, "rb") as f:
            await update.message.reply_document(document=f, filename=fname,
                caption=f"✅ {count} رستە وەرگێڕدرا\nوەرگێڕاوە بۆ: {label}")
        for p in [srt_path, out]:
            try:
                if os.path.exists(p): os.remove(p)
            except: pass
    except Exception as e:
        logger.error(f"SRT translate: {e}")
        await update.message.reply_text("کێشەیەک هەبوو")
    user_state[uid] = "done"

async def handle_video_for_burn(update, uid):
    os.makedirs(f"/tmp/{uid}", exist_ok=True)
    path = f"/tmp/{uid}/video.mp4"
    await update.message.reply_text("وەرگرتم... ⏳")
    dl = await download_media(update, path)
    if dl == "too_big":
        await update.message.reply_text("فایلەکەت زۆر گەورەیە\nتکایە لینک بنێرە")
        return
    if not dl:
        await update.message.reply_text("تکایە فایل یان لینک بنێرە 📁")
        return
    user_data[uid]["video"] = path
    user_state[uid] = "waiting_srt_burn"
    await update.message.reply_text("ڤیدیۆکەت ئامادەیە ✅\nئێستا فایلی SRT بنێرە 📄")

async def handle_srt_burn(update, uid):
    if not update.message.document or not (update.message.document.file_name or "").endswith(".srt"):
        await update.message.reply_text("تکایە فایلێکی SRT بنێرە 📄")
        return
    await update.message.reply_text("کاردەکەم... ⏳")
    os.makedirs(f"/tmp/{uid}", exist_ok=True)
    srt_path = f"/tmp/{uid}/subtitle.srt"
    tg = await update.message.document.get_file()
    await tg.download_to_drive(srt_path)
    video = user_data[uid]["video"]
    out = f"/tmp/{uid}/output.mp4"
    ass = f"/tmp/{uid}/subtitle.ass"
    subprocess.run(["ffmpeg", "-y", "-i", srt_path, ass], capture_output=True)
    if os.path.exists(ass):
        with open(ass, "r", encoding="utf-8") as f:
            c = f.read()
        c = c.replace("Style: Default,Arial", "Style: Default,NRT Reg").replace("Fontname: Arial", "Fontname: NRT Reg")
        with open(ass, "w", encoding="utf-8") as f:
            f.write(c)
    try:
        r = subprocess.run(["ffmpeg", "-y", "-i", video, "-vf", f"scale=640:360,ass={ass}:fontsdir=/app", "-preset", "ultrafast", "-crf", "35", "-c:a", "copy", out],
            capture_output=True, text=True, timeout=600)
        if r.returncode == 0 and os.path.exists(out):
            await update.message.reply_text("ئامادەیە! 🎉")
            with open(out, "rb") as f:
                await update.message.reply_document(document=f, filename="output_kurdish.mp4", caption="ساب‌تایتڵی کوردی هاردکۆد کراوە ✅")
        else:
            logger.error(f"FFmpeg: {r.stderr[-300:]}")
            await update.message.reply_text("کێشەیەک هەبوو")
    except subprocess.TimeoutExpired:
        await update.message.reply_text("ڤیدیۆکەت زۆر درێژە")
    except Exception as e:
        logger.error(f"Burn error: {e}")
        await update.message.reply_text("کێشەیەک هەبوو")
    for p in [video, srt_path, ass, out]:
        try:
            if os.path.exists(p): os.remove(p)
        except: pass
    user_state[uid] = "done"

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
