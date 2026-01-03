import os
import logging
import sqlite3
import tempfile
import asyncio
import subprocess
from pathlib import Path
from cryptography.fernet import Fernet
from pymongo import MongoClient

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, ConversationHandler, CallbackQueryHandler, filters, ContextTypes

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

from flask import Flask, request, redirect
import threading

from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Constants
TELEGRAM_TOKEN = '8286971022:AAHbj2_RUkaGl1exXYM0mgFFKrfqbmWT_1A'
YOUTUBE_CLIENT_SECRETS_FILE = 'client_secrets.json'
DATABASE_FILE = 'tokens.db'
ENCRYPTION_KEY = 'gyYr7u7upZkOfoS5kugD4l0uYSj9Z1Qc_mA_UNhrn2Y='  # Generate a key using Fernet.generate_key()
REDIRECT_URI = os.getenv('REDIRECT_URI', 'http://localhost:8080/oauth2callback')
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/youtube_bot')
LOG_CHANNEL_ID = os.getenv('LOG_CHANNEL_ID')

# Animation URLs
UPLOAD_ANIMATION_URL = 'https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExaHdvajU3ajZlc3ZhdmhqOWU4am0zYXJ6YzE1Z244eGJsM3d3emNuYSZlcD12MV9naWZzX3NlYXJjaCZjdD1n/b7d8ZzxqGw4Gpt0qfY/giphy.gif'  # Example loading animation
WAITING_ANIMATION_URL = 'https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbDF1MGNmMnlnczg5cXU0NnU0bmdhY21pdWZkdzNwYXZ0ODhtcXNreCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/jleNxE9BsJVO8/giphy.gif'  # Example waiting animation
PROCESSING_ANIMATION_URL = 'https://media.giphy.com/media/v1.Y2lkPTc5MGI3NjExbDF1MGNmMnlnczg5cXU0NnU0bmdhY21pdWZkdzNwYXZ0ODhtcXNreCZlcD12MV9naWZzX3NlYXJjaCZjdD1n/qb1eHxhUHLdsc/giphy.gif'  # Example processing animation

# YouTube API scopes
SCOPES = ['https://www.googleapis.com/auth/youtube.upload']

# Conversation states
WAITING_FOR_VIDEO, WAITING_FOR_TITLE, WAITING_FOR_DESCRIPTION, WAITING_FOR_THUMBNAIL, WAITING_FOR_PRIVACY, WAITING_FOR_TAGS = range(6)

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Database setup
mongo_client = MongoClient(MONGODB_URI)
db = mongo_client.youtube_bot
tokens_collection = db.tokens

def init_db():
    # MongoDB doesn't need init like SQLite
    pass

def encrypt_token(token):
    f = Fernet(ENCRYPTION_KEY)
    return f.encrypt(token.encode()).decode()

def decrypt_token(encrypted_token):
    f = Fernet(ENCRYPTION_KEY)
    return f.decrypt(encrypted_token.encode()).decode()

def store_token(user_id, token):
    encrypted = encrypt_token(token)
    tokens_collection.update_one(
        {'user_id': user_id},
        {'$set': {'encrypted_token': encrypted}},
        upsert=True
    )

def get_token(user_id):
    doc = tokens_collection.find_one({'user_id': user_id})
    if doc:
        return decrypt_token(doc['encrypted_token'])
    return None

# Log to channel
async def log_to_channel(message):
    if LOG_CHANNEL_ID:
        try:
            await application.bot.send_message(chat_id=LOG_CHANNEL_ID, text=message)
        except Exception as e:
            logger.error(f'Failed to log to channel: {e}')

# OAuth flow
def get_credentials(user_id):
    creds = None
    token = get_token(user_id)
    if token:
        creds = Credentials.from_authorized_user_info(eval(token), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = Flow.from_client_secrets_file(YOUTUBE_CLIENT_SECRETS_FILE, SCOPES, redirect_uri=REDIRECT_URI)
            auth_url, _ = flow.authorization_url(prompt='consent')
            print(f"Please go to this URL to authorize: {auth_url}")
            # For production, this would be sent to user
            creds = None  # Will be set by callback
        store_token(user_id, creds.to_json())
    return creds

# Flask app for production OAuth
app = Flask(__name__)
auth_codes = {}

@app.route('/oauth2callback')
def oauth2callback():
    code = request.args.get('code')
    state = request.args.get('state')
    if state and code:
        user_id = int(state)
        flow = Flow.from_client_secrets_file(YOUTUBE_CLIENT_SECRETS_FILE, SCOPES, redirect_uri=REDIRECT_URI, state=state)
        flow.fetch_token(code=code)
        creds = flow.credentials
        store_token(user_id, creds.to_json())
    return 'Authorization successful! You can now use the bot. Close this window.'

def run_flask():
    app.run(port=8080, debug=False)

# Telegram handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    keyboard = [[InlineKeyboardButton("🔑 Authorize YouTube", callback_data='authorize')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('👋 Welcome! Click to authorize YouTube access.', reply_markup=reply_markup)

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if get_token(user_id):
        await update.message.reply_text('✅ You are authorized. You can use /upload.')
    else:
        await update.message.reply_text('❌ You are not authorized. Use /start to authorize.')

async def authorize_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    flow = Flow.from_client_secrets_file(YOUTUBE_CLIENT_SECRETS_FILE, SCOPES, redirect_uri=REDIRECT_URI)
    auth_url, _ = flow.authorization_url(prompt='consent', state=str(user_id))
    await query.edit_message_text(f'🔗 Please authorize: {auth_url}\n✅ After authorization, send /upload to start uploading.')

async def upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action='typing')
    if not get_token(user_id):
        await update.message.reply_text('❌ Please authorize YouTube first with /start.')
        return ConversationHandler.END
    await update.message.reply_text('📹 Please send the video file.')
    context.user_data['user_id'] = user_id
    return WAITING_FOR_VIDEO

async def receive_video(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    video = update.message.video or update.message.document
    if not video:
        await update.message.reply_text('❌ Please send a video file.')
        return WAITING_FOR_VIDEO
    file_size_gb = video.file_size / (1024 ** 3) if video.file_size else 0
    if file_size_gb > 1.5:
        await update.message.reply_text('❌ File size exceeds 1.5GB limit.')
        return WAITING_FOR_VIDEO
    # Send processing animation
    await update.message.reply_animation(PROCESSING_ANIMATION_URL, caption='🔄 Processing video...')
    file = await context.bot.get_file(video.file_id)
    temp_dir = Path(tempfile.mkdtemp())
    video_path = temp_dir / 'video.mp4'
    try:
        await file.download_to_drive(video_path)
        context.user_data['video_path'] = str(video_path)
        context.user_data['temp_dir'] = str(temp_dir)
        context.user_data['file_size'] = video.file_size / (1024 * 1024) if video.file_size else 0  # MB
    except Exception as e:
        logger.error(f'Failed to download video: {e}')
        await update.message.reply_text('❌ Failed to download video. Please try sending a smaller file or try again.')
        return WAITING_FOR_VIDEO
    await log_to_channel(f"📹 Video received from user {update.effective_user.id}, size: {file_size_gb:.2f} GB")
    await update.message.reply_text('✅ Video received. ✏️ Please enter the title:')
    return WAITING_FOR_TITLE

async def receive_title(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['title'] = update.message.text
    await update.message.reply_text('📝 Please enter the description:')
    return WAITING_FOR_DESCRIPTION

async def receive_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['description'] = update.message.text
    await update.message.reply_text('🖼️ Please send the thumbnail image:')
    return WAITING_FOR_THUMBNAIL

async def receive_thumbnail(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    photo = update.message.photo[-1] if update.message.photo else None
    if not photo:
        await update.message.reply_text('❌ Please send an image for thumbnail.')
        return WAITING_FOR_THUMBNAIL
    file = await context.bot.get_file(photo.file_id)
    thumbnail_path = Path(context.user_data['temp_dir']) / 'thumbnail.jpg'
    try:
        await file.download_to_drive(thumbnail_path)
        context.user_data['thumbnail_path'] = str(thumbnail_path)
    except Exception as e:
        logger.error(f'Failed to download thumbnail: {e}')
        await update.message.reply_text('❌ Failed to download thumbnail. Please try sending a smaller image or try again.')
        return WAITING_FOR_THUMBNAIL
    keyboard = [['public'], ['private']]
    reply_markup = InlineKeyboardMarkup([[InlineKeyboardButton(text, callback_data=text) for text in row] for row in keyboard])
    await update.message.reply_text('🔒 Choose privacy setting:', reply_markup=reply_markup)
    return WAITING_FOR_PRIVACY

async def receive_privacy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['privacy'] = query.data
    await query.edit_message_text('🏷️ Please enter tags (comma-separated):')
    return WAITING_FOR_TAGS

async def receive_tags(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    tags = [tag.strip() for tag in update.message.text.split(',')]
    context.user_data['tags'] = tags
    # Send progress message
    progress_message = await update.message.reply_text("🪢 Uploading To Youtube\n┃\n┣[░░░░░░░░░░] » \n┣• PERCENTAGE ➜ 0.00%\n┣• TIME LEFT ➜ Calculating...\n┖• ESTIMATED ➜ Calculating...")
    success = await upload_to_youtube(context.user_data, progress_message)
    if success:
        await progress_message.edit_text("🪢 Uploading To Youtube\n┃\n┣[██████████] » \n┣• PERCENTAGE ➜ 100.00%\n┣• TIME LEFT ➜ 0m, 0s\n┖• ESTIMATED ➜ Done")
    else:
        await progress_message.edit_text("❌ Upload failed. Please try again.")
    # Cleanup
    temp_dir = Path(context.user_data['temp_dir'])
    for file in temp_dir.iterdir():
        file.unlink()
    temp_dir.rmdir()
    return ConversationHandler.END

def create_progress_bar(percentage):
    filled = int(percentage / 10)
    bar = '█' * filled + '░' * (10 - filled)
    return f"[{bar}]"

async def upload_to_youtube(data, progress_message):
    user_id = data['user_id']
    await log_to_channel(f"🚀 Starting upload for user {user_id}, title: {data['title']}")
    creds = get_credentials(user_id)
    youtube = build('youtube', 'v3', credentials=creds)
    body = {
        'snippet': {
            'title': data['title'],
            'description': data['description'],
            'tags': data['tags'],
            'categoryId': '22'  # People & Blogs
        },
        'status': {
            'privacyStatus': data['privacy']
        }
    }
    file_size_mb = data.get('file_size', 0)
    media = MediaFileUpload(data['video_path'], chunksize=1024*1024, resumable=True)  # 1MB chunks
    try:
        request = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
        response = None
        while response is None:
            status, response = await asyncio.to_thread(request.next_chunk)
            if status:
                progress = status.progress()
                percentage = progress * 100
                progress_bar = create_progress_bar(percentage)
                time_left = "Estimating..."  # Hard to calculate accurately
                estimated = f"{file_size_mb:.2f} MB"
                text = f"🪢 Uploading To Youtube\n┃\n┣{progress_bar} » \n┣• PERCENTAGE ➜ {percentage:.2f}%\n┣• TIME LEFT ➜ {time_left}\n┖• ESTIMATED ➜ {estimated}"
                await progress_message.edit_text(text)
        video_id = response['id']
        # Set thumbnail (optional, may fail if channel not verified)
        try:
            youtube.thumbnails().set(videoId=video_id, media_body=MediaFileUpload(data['thumbnail_path'])).execute()
        except HttpError as e:
            logger.warning(f'Failed to set thumbnail: {e}. Video uploaded without custom thumbnail.')
        await log_to_channel(f"✅ Upload successful for user {user_id}, video ID: {video_id}")
        return True
    except HttpError as e:
        logger.error(f'YouTube API error: {e}')
        await log_to_channel(f"❌ Upload failed for user {user_id}: {e}")
        return False

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text('❌ Upload cancelled.')
    return ConversationHandler.END

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text('🔄 Restarting bot...')
    # Start new process
    subprocess.Popen(['python', 'main.py'])
    # Kill current process
    os._exit(0)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("DEVELOPER", url="https://t.me/SHIVAM_DUBBER")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('💰 Contact the developer for premium features or support:', reply_markup=reply_markup)

def main():
    init_db()
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('upload', upload)],
        states={
            WAITING_FOR_VIDEO: [MessageHandler(filters.VIDEO | filters.Document.ALL, receive_video)],
            WAITING_FOR_TITLE: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_title)],
            WAITING_FOR_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_description)],
            WAITING_FOR_THUMBNAIL: [MessageHandler(filters.PHOTO, receive_thumbnail)],
            WAITING_FOR_PRIVACY: [CallbackQueryHandler(receive_privacy)],
            WAITING_FOR_TAGS: [MessageHandler(filters.TEXT & ~filters.COMMAND, receive_tags)],
        },
        fallbacks=[CommandHandler('cancel', cancel)],
    )

    application.add_handler(CommandHandler('start', start))
    application.add_handler(CommandHandler('status', status))
    application.add_handler(CommandHandler('restart', restart))
    application.add_handler(CommandHandler('buy', buy))
    application.add_handler(CallbackQueryHandler(authorize_callback, pattern='authorize'))
    application.add_handler(conv_handler)

    # Start Flask in a thread for production
    threading.Thread(target=run_flask, daemon=True).start()

    application.run_polling()

if __name__ == '__main__':
    main()