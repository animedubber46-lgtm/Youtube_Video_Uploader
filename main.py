import os
import json
import logging
import asyncio
import tempfile
import threading
import subprocess
from pathlib import Path

from cryptography.fernet import Fernet
from pymongo import MongoClient

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from flask import Flask, request

# ===================== ENV VARIABLES ===================== #

TELEGRAM_TOKEN = os.getenv("7677701935:AAG7ZrNWg-waRiVYCl9M_kPBDXCEmQJADGo")
CLIENT_ID = os.environ["56955446636-cbn2rau39rdh530h9i5jnbl2iip4fsd2.apps.googleusercontent.com"]
CLIENT_SECRET = os.environ["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"]
REDIRECT_URI = os.environ["https://youtubeuploader-ca9825a36bd8.herokuapp.com/oauth2callback"]
ENCRYPTION_KEY = os.environ["OiDu-9M4g7-lSkrIe1Okg_4raHFaLP-a08mmYkwe0Wc="].encode()
MONGODB_URI = os.environ["mongodb+srv://sakshamranjan7:8wBCaYilCTlgdNV3@cluster0.h184m7m.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"]
LOG_CHANNEL_ID = int(os.getenv("LOG_CHANNEL_ID", "-1002783627126"))

# ===================== CONSTANTS ===================== #

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

UPLOAD_ANIMATION_URL = "https://media.giphy.com/media/qb1eHxhUHLdsc/giphy.gif"
WAITING_ANIMATION_URL = "https://media.giphy.com/media/jleNxE9BsJVO8/giphy.gif"
PROCESSING_ANIMATION_URL = "https://media.giphy.com/media/b7d8ZzxqGw4Gpt0qfY/giphy.gif"

WAITING_FOR_VIDEO, WAITING_FOR_TITLE, WAITING_FOR_DESCRIPTION, WAITING_FOR_THUMBNAIL, WAITING_FOR_PRIVACY, WAITING_FOR_TAGS = range(6)

# ===================== GLOBALS ===================== #

application = None
app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

mongo = MongoClient(MONGODB_URI)
db = mongo.youtube_bot
tokens_collection = db.tokens

fernet = Fernet(ENCRYPTION_KEY)

# ===================== TOKEN HELPERS ===================== #

def encrypt_token(data: str) -> str:
    return fernet.encrypt(data.encode()).decode()

def decrypt_token(data: str) -> str:
    return fernet.decrypt(data.encode()).decode()

def store_token(user_id: int, creds: Credentials):
    tokens_collection.update_one(
        {"user_id": user_id},
        {"$set": {"token": encrypt_token(creds.to_json())}},
        upsert=True
    )

def get_token(user_id: int):
    doc = tokens_collection.find_one({"user_id": user_id})
    if not doc:
        return None
    return Credentials.from_authorized_user_info(
        json.loads(decrypt_token(doc["token"])),
        SCOPES
    )

# ===================== OAUTH ===================== #

def oauth_flow(state=None):
    return Flow.from_client_config(
        {
            "web": {
                "client_id": CLIENT_ID,
                "client_secret": CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token"
            }
        },
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI,
        state=state
    )

@app.route("/oauth2callback")
def oauth2callback():
    code = request.args.get("code")
    state = request.args.get("state")

    if not code or not state:
        return "Invalid OAuth request"

    flow = oauth_flow(state)
    flow.fetch_token(code=code)

    store_token(int(state), flow.credentials)
    return "✅ Authorization successful! You can return to Telegram."

def run_flask():
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 8080)))

# ===================== TELEGRAM ===================== #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("🔑 Authorize YouTube", callback_data="authorize")]]
    await update.message.reply_text(
        "👋 Welcome!\nAuthorize YouTube to upload videos.",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

async def authorize_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    flow = oauth_flow(str(user_id))
    url, _ = flow.authorization_url(prompt="consent", access_type="offline")

    await query.edit_message_text(f"🔗 Click to authorize:\n{url}")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if get_token(update.effective_user.id):
        await update.message.reply_text("✅ You are authorized.")
    else:
        await update.message.reply_text("❌ Not authorized. Use /start.")

async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not get_token(update.effective_user.id):
        await update.message.reply_text("❌ Please authorize first.")
        return ConversationHandler.END

    await update.message.reply_text("📹 Send the video file.")
    context.user_data["user_id"] = update.effective_user.id
    return WAITING_FOR_VIDEO

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    video = update.message.video or update.message.document
    if not video:
        return WAITING_FOR_VIDEO

    await update.message.reply_animation(PROCESSING_ANIMATION_URL)

    file = await video.get_file()
    temp_dir = Path(tempfile.mkdtemp())
    video_path = temp_dir / "video.mp4"
    await file.download_to_drive(video_path)

    context.user_data.update({
        "video_path": str(video_path),
        "temp_dir": str(temp_dir)
    })

    await update.message.reply_text("✏️ Enter title:")
    return WAITING_FOR_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["title"] = update.message.text
    await update.message.reply_text("📝 Enter description:")
    return WAITING_FOR_DESCRIPTION

async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text
    await update.message.reply_text("🏷 Enter tags (comma separated):")
    return WAITING_FOR_TAGS

async def receive_tags(update: Update, context: ContextTypes.DEFAULT_TYPE):
    data = context.user_data
    creds = get_token(data["user_id"])

    youtube = build("youtube", "v3", credentials=creds)

    body = {
        "snippet": {
            "title": data["title"],
            "description": data["description"],
            "tags": update.message.text.split(","),
            "categoryId": "22"
        },
        "status": {"privacyStatus": "public"}
    }

    media = MediaFileUpload(data["video_path"], resumable=True)

    try:
        youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media
        ).execute()
        await update.message.reply_text("✅ Upload successful!")
    except HttpError as e:
        await update.message.reply_text(f"❌ Upload failed: {e}")

    return ConversationHandler.END

# ===================== MAIN ===================== #

def main():
    global application

    threading.Thread(target=run_flask, daemon=True).start()

    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("upload", upload)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.ALL, receive_video)],
            WAITING_FOR_TITLE: [MessageHandler(filters.TEXT, receive_title)],
            WAITING_FOR_DESCRIPTION: [MessageHandler(filters.TEXT, receive_description)],
            WAITING_FOR_TAGS: [MessageHandler(filters.TEXT, receive_tags)],
        },
        fallbacks=[]
    )

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("status", status))
    application.add_handler(CallbackQueryHandler(authorize_callback, pattern="authorize"))
    application.add_handler(conv)

    application.run_polling()

if __name__ == "__main__":
    main()

