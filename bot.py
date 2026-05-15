"""
Telegram bot that returns engagement metrics for one or many tweet/X posts
in a single message. Powered by SocialData API.

Setup on Railway:
  1. Add env var: TELEGRAM_BOT_TOKEN = your BotFather token
  2. Add env var: SOCIALDATA_API_KEY = your SocialData key
  3. Start command: python3 bot.py
  4. requirements.txt: python-telegram-bot, httpx
"""

import os
import re
import asyncio
import httpx
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application, MessageHandler, CommandHandler, filters, ContextTypes
)

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
SOCIALDATA_KEY = os.environ.get("SOCIALDATA_API_KEY", "")

TWEET_RE = re.compile(r"(?:twitter\.com|x\.com)/[^/\s]+/status/(\d+)")

# Tune these as you like
MAX_LINKS_PER_MSG = 20      # hard cap so users can't spam-burn credits
CONCURRENCY = 8             # parallel SocialData requests
TG_MSG_LIMIT = 3900         # safe margin under Telegram's 4096 cap


async def fetch_tweet(client: httpx.AsyncClient, tweet_id: str) -> dict:
    url = f"https://api.socialdata.tools/twitter/tweets/{tweet_id}"
    headers = {
        "Authorization": f"Bearer {SOCIALDATA_KEY}",
        "Accept": "application/json",
    }
    try:
        r = await client.get(url, headers=headers, timeout=20)
    except httpx.RequestError as e:
        return {"id": tweet_id, "error": f"network error: {e.__class__.__name__}"}

    if r.status_code == 200:
        try:
            data = r.json()
            data["id"] = tweet_id
            return data
        except Exception:
            return {"id": tweet_id, "error": "bad JSON from SocialData"}
    if r.status_code == 404:
        return {"id": tweet_id, "error": "not found (deleted/private)"}
    if r.status_code == 402:
        return {"id": tweet_id, "error": "out of SocialData credits"}
    if r.status_code in (401, 403):
        return {"id": tweet_id, "error": "invalid SocialData key"}
    return {"id": tweet_id, "error": f"HTTP {r.status_code}"}


async def fetch_many(tweet_ids):
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient() as client:
        async def bounded(tid):
            async with sem:
                return await fetch_tweet(client, tid)
        return await asyncio.gather(*(bounded(t) for t in tweet_ids))


def fmt(n):
    if n is None:
        return "—"
    try:
        return f"{int(n):,}"
    except (ValueError, TypeError):
        return str(n)


def render(data: dict) -> str:
    tweet_id = data.get("id", "?")
    if data.get("error"):
        return f"⚠️ {tweet_id}: {data['error']}"

    author = data.get("user", {}).get("screen_name", "?")
    likes = data.get("favorite_count")
    rts = data.get("retweet_count")
    replies = data.get("reply_count")
    quotes = data.get("quote_count")
    views = data.get("views_count") or data.get("view_count")
    bookmarks = data.get("bookmark_count")

    return (
        f"📊 @{author}  ·  https://x.com/{author}/status/{tweet_id}\n"
        f"👁 {fmt(views)}  ❤️ {fmt(likes)}  🔁 {fmt(rts)}  "
        f"💬 {fmt(replies)}  💭 {fmt(quotes)}  🔖 {fmt(bookmarks)}"
    )


def chunk_messages(blocks):
    out, buf = [], ""
    for b in blocks:
        candidate = (buf + "\n\n" + b) if buf else b
        if len(candidate) > TG_MSG_LIMIT:
            if buf:
                out.append(buf)
            buf = b
        else:
            buf = candidate
    if buf:
        out.append(buf)
    return out


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    ids = list(dict.fromkeys(TWEET_RE.findall(text)))  # dedupe, keep order

    if not ids:
        await update.message.reply_text(
            "Send me one or more tweet/X links and I'll return their stats."
        )
        return

    if len(ids) > MAX_LINKS_PER_MSG:
        await update.message.reply_text(
            f"You sent {len(ids)} links — limit is {MAX_LINKS_PER_MSG} per message. "
            f"Processing the first {MAX_LINKS_PER_MSG}."
        )
        ids = ids[:MAX_LINKS_PER_MSG]

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id, action=ChatAction.TYPING
    )

    results = await fetch_many(ids)
    blocks = [render(d) for d in results]

    header = f"📦 {len(ids)} link{'s' if len(ids) != 1 else ''} processed\n" + ("─" * 24)
    blocks.insert(0, header)

    for msg in chunk_messages(blocks):
        await update.message.reply_text(msg, disable_web_page_preview=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me one or many tweet/X links in a single message "
        f"(up to {MAX_LINKS_PER_MSG}) and I'll return their stats."
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
