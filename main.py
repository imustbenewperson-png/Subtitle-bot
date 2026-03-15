import os
import subprocess
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, ConversationHandler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TOKEN = os.environ.get("BOT_TOKEN")

WAITING_VIDEO = 1
WAITING_SRT = 2

user_data = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "سڵاو! 👋\n\n"
        "ئەم بۆتە ساب‌تایتڵی کوردی دەخاتە ناو ڤیدیۆکەت.\n\n"
        "پێش هەموو شتێک لینکی ڤیدیۆکەت بنێرە 🎬\n"
        "(Google Drive, Telegram, هەر لینکێک)"
    )
    return WAITING_VIDEO

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    os.makedirs(f"/tmp/{user_id}", exist_ok=True)
    video_path = f"/tmp/{user_id}/video.mp4"

    # Check if it's a URL
    if update.message.text and (update.message.text.startswith("http://") or update.message.text.startswith("https://")):
        url = update.message.text.strip()
        await update.message.reply_text("لینکەکەت وەرگرتم ✅\nدابەزێنم... چاوەڕێ بکە ⏳")
        try:
            result = subprocess.run(["wget", "-O", video_path, url], capture_output=True, timeout=600)
            if result.returncode != 0:
                await update.message.reply_text("نەمتوانی ڤیدیۆکە دابەزێنم ❌\nلینکەکە دووبارە تاقی بکەرەوە")
                return WAITING_VIDEO
        except Exception:
            await update.message.reply_text("کێشەیەک هەبوو لە دابەزاندنەکەدا ❌")
            return WAITING_VIDEO
        await update.message.reply_text("ڤیدیۆکەت ئامادەیە ✅\nئێستا فایلی SRT بنێرە 📄")

    # Direct video or document upload
    elif update.message.video:
        file = update.message.video
        await update.message.reply_text("ڤیدیۆکەت وەرگرتم ✅\nئێستا فایلی SRT بنێرە 📄")
        video_file = await file.get_file()
        await video_file.download_to_drive(video_path)

    elif update.message.document and update.message.document.mime_type and 'video' in update.message.document.mime_type:
        file = update.message.document
        await update.message.reply_text("ڤیدیۆکەت وەرگرتم ✅\nئێستا فایلی SRT بنێرە 📄")
        video_file = await file.get_file()
        await video_file.download_to_drive(video_path)

    else:
        await update.message.reply_text("تکایە لینکی ڤیدیۆ یان فایلی ڤیدیۆ بنێرە 🎬")
        return WAITING_VIDEO

    user_data[user_id] = {"video": video_path}
    return WAITING_SRT

async def receive_srt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    if not update.message.document:
        await update.message.reply_text("تکایە فایلی SRT بنێرە 📄")
        return WAITING_SRT

    filename = update.message.document.file_name or ""
    if not filename.endswith(".srt"):
        await update.message.reply_text("تکایە فایلێکی SRT بنێرە 📄")
        return WAITING_SRT

    await update.message.reply_text("فایلەکەت وەرگرتم ✅\nکاردەکەم... چەند خولەک چاوەڕێ بکە ⏳")

    srt_file = await update.message.document.get_file()
    srt_path = f"/tmp/{user_id}/subtitle.srt"
    await srt_file.download_to_drive(srt_path)

    video_path = user_data[user_id]["video"]
    output_path = f"/tmp/{user_id}/output.mp4"
    ass_path = f"/tmp/{user_id}/subtitle.ass"

    # Convert SRT to ASS
    convert_cmd = ["ffmpeg", "-y", "-i", srt_path, ass_path]
    subprocess.run(convert_cmd, capture_output=True)

    # Modify ASS to use Kurdish font
    if os.path.exists(ass_path):
        with open(ass_path, 'r', encoding='utf-8') as f:
            ass_content = f.read()
        ass_content = ass_content.replace('Style: Default,Arial', 'Style: Default,NRT Reg')
        ass_content = ass_content.replace('Fontname: Arial', 'Fontname: NRT Reg')
        with open(ass_path, 'w', encoding='utf-8') as f:
            f.write(ass_content)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path,
        "-vf", f"ass={ass_path}:fontsdir=/app",
        "-c:a", "copy",
        output_path
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

        if result.returncode == 0 and os.path.exists(output_path):
            await update.message.reply_text("ئامادەیە! دەینێرم بۆت 🎉")
            with open(output_path, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename="output_kurdish.mp4",
                    caption="ساب‌تایتڵی کوردی هاردکۆد کراوە ✅"
                )
        else:
            logger.error(f"FFmpeg error: {result.stderr}")
            await update.message.reply_text("کێشەیەک هەبوو، دووبارە تاقی بکەرەوە ❌")

    except subprocess.TimeoutExpired:
        await update.message.reply_text("ڤیدیۆکەت زۆر درێژە ❌")
    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text("کێشەیەک هەبوو ❌")

    # Cleanup
    try:
        os.remove(video_path)
        os.remove(srt_path)
        if os.path.exists(ass_path):
            os.remove(ass_path)
        if os.path.exists(output_path):
            os.remove(output_path)
    except:
        pass

    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("هەڵوەشایەوە. /start بنووسە بۆ دەستپێکردنەوە")
    return ConversationHandler.END

def main():
    app = Application.builder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.TEXT | filters.VIDEO | filters.Document.ALL, receive_video)
        ],
        states={
            WAITING_VIDEO: [MessageHandler(filters.TEXT | filters.VIDEO | filters.Document.ALL, receive_video)],
            WAITING_SRT: [MessageHandler(filters.Document.ALL, receive_srt)],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conv_handler)
    app.run_polling()

if __name__ == "__main__":
    main()
