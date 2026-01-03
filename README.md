# Telegram YouTube Upload Bot

A production-ready Telegram bot that allows users to upload videos directly to their YouTube channel.

## Features

- OAuth 2.0 authentication for YouTube
- Step-by-step video metadata collection
- Secure token storage with encryption
- Resumable video uploads
- Thumbnail setting
- Error handling and logging
- Rate limiting and cleanup

## Prerequisites

- Python 3.8+
- Google Cloud Project with YouTube Data API v3 enabled
- Telegram Bot Token

## Setup

1. **Clone or download the code.**

2. **Install dependencies:**
   ```
   pip install -r requirements.txt
   ```

3. **Set up Google Cloud:**
   - Go to [Google Cloud Console](https://console.cloud.google.com/)
   - Create a new project or select existing
   - Enable YouTube Data API v3
   - Create OAuth 2.0 credentials
   - Download `client_secrets.json` and place in the project root

4. **Set OAuth redirect URI:**
   - In Google Cloud Console, under OAuth 2.0 credentials, add authorized redirect URIs:
     - For local: `http://localhost:8080/oauth2callback`
     - For production: `https://yourdomain.com/oauth2callback`

5. **Configure environment variables:**
    - Copy `.env` and fill in:
      - `TELEGRAM_TOKEN`: Your Telegram bot token from @BotFather
      - `ENCRYPTION_KEY`: Generate with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
      - `MONGODB_URI`: MongoDB connection string (e.g., `mongodb://localhost:27017/youtube_bot`)
      - `LOG_CHANNEL_ID`: Telegram channel ID for logging (e.g., `-1001234567890`)

5. **Run the bot:**
   ```
   python main.py
   ```

## Usage

1. Start the bot with `/start`
2. Authorize YouTube access
3. Use `/upload` to upload a video
4. Follow the prompts to provide title, description, thumbnail, privacy, and tags

## Deployment

### Local Testing
- Run `python main.py`
- OAuth will use local server on port 8080

### Heroku
1. Create a Heroku app
2. Set environment variables in Heroku dashboard:
   - `TELEGRAM_TOKEN`
   - `ENCRYPTION_KEY`
   - `REDIRECT_URI` (e.g., `https://your-app-name.herokuapp.com/oauth2callback`)
3. Deploy the code (Procfile and runtime.txt are included)
4. In Google Cloud Console, add the Heroku URL as authorized redirect URI
5. Ensure the app has worker dyno running

### Render
1. Create a new Web Service on Render
2. Connect your repository
3. Set environment variables:
   - `TELEGRAM_TOKEN`
   - `ENCRYPTION_KEY`
   - `REDIRECT_URI` (e.g., `https://your-app.onrender.com/oauth2callback`)
4. Set build command: `pip install -r requirements.txt`
5. Set start command: `python main.py`
6. In Google Cloud Console, add the Render URL as authorized redirect URI

### Replit
1. Fork this repl
2. Set environment variables in Replit Secrets:
   - `TELEGRAM_TOKEN`
   - `ENCRYPTION_KEY`
   - `REDIRECT_URI` (e.g., `https://your-repl-name.replit.dev/oauth2callback`)
3. Run the repl
4. In Google Cloud Console, add the Replit URL as authorized redirect URI

### Koyeb
1. Create a new service on Koyeb
2. Connect your repository
3. Set environment variables:
   - `TELEGRAM_TOKEN`
   - `ENCRYPTION_KEY`
   - `REDIRECT_URI` (e.g., `https://your-app.koyeb.app/oauth2callback`)
4. Koyeb will use the Procfile automatically
5. In Google Cloud Console, add the Koyeb URL as authorized redirect URI

## Security Notes

- Never commit `.env` or `client_secrets.json` to version control
- Use strong encryption keys
- Implement user authorization for private bots
- Comply with YouTube TOS and GDPR
- Monitor API usage to avoid quota limits

## Troubleshooting

- Check logs for errors
- Ensure all dependencies are installed
- Verify API credentials and scopes
- For OAuth issues, clear stored tokens and re-authorize

## Contributing

Feel free to submit issues and pull requests.