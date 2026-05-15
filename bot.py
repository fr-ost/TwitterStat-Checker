"""
Telegram bot that returns full engagement metrics for any tweet/X post
using the SocialData API (https://socialdata.tools).

Setup on Railway:
  1. Add env var: TELEGRAM_BOT_TOKEN = your BotFather token
  2. Add env var: SOCIALDATA_API_KEY = your SocialData key
  3. Start command: python3 bot.py
  4. requirements.txt should contain: python-telegram-bot, httpx
"""

import os
import re
import httpx
from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler, filters, ContextTypes
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SOCIALDATA_KEY = os.environ.get("SOCIALDATA_API_KEY", "")

TWEET_RE = re.compile(r"(?:twitter\.com|x\.com)/[^/\s]+/status/(\d+)")


async def fetch_tweet(tweet_id: str):
    url = f"https://api.socialdata.tools/twitter/tweets/{tweet_id}"
    headers = {
        "Authorization": f"Bearer {SOCIALDATA_KEY}",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.get(url, headers=headers)
        if r.status_code == 404:
            return {"error": "Tweet not found (deleted or private)."}
        if r.status_code == 402:
            return {"error": "SocialData credits exhausted. Top up your account."}
        if r.status_code == 401 or r.status_code == 403:
            return {"error": "SocialData API key invalid."}
        if r.status_code != 200:
            return {"error": f"SocialData returned HTTP {r.status_code}."}
        try:
            return r.json()
        except Exception:
            return {"error": "Couldn't parse SocialData response."}


def fmt(n):
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    match = TWEET_RE.search(text)
    if not match:
        await update.message.reply_text(
            "Send me a tweet/X link, e.g.\nhttps://x.com/user/status/123..."
        )
        return

    tweet_id = match.group(1)
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action="typing"
    )

    data = await fetch_tweet(tweet_id)
    if data.get("error"):
        await update.message.reply_text(f"⚠️ {data['error']}")
        return

    author = data.get("user", {}).get("screen_name", "?")
    likes = data.get("favorite_count")
    rts = data.get("retweet_count")
    replies = data.get("reply_count")
    quotes = data.get("quote_count")
    views = data.get("views_count") or data.get("view_count")
    bookmarks = data.get("bookmark_count")

    msg = (
        f"📊 @{author}\n"
        f"https://x.com/{author}/status/{tweet_id}\n\n"
        f"👁  Impressions: {fmt(views)}\n"
        f"❤️  Likes:        {fmt(likes)}\n"
        f"🔁  Retweets:     {fmt(rts)}\n"
        f"💬  Replies:      {fmt(replies)}\n"
        f"💭  Quotes:       {fmt(quotes)}\n"
        f"🔖  Bookmarks:    {fmt(bookmarks)}"
    )
    await update.message.reply_text(msg, disable_web_page_preview=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me any tweet/X link and I'll return its full stats."
    )


def main():
    if not BOT_TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN env var not set.")
    if not SOCIALDATA_KEY:
        raise RuntimeError("SOCIALDATA_API_KEY env var not set.")

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
