"""
Telegram bot that returns public engagement metrics for a tweet/X post.

No Twitter API key needed — uses cdn.syndication.twimg.com (the same
endpoint that powers tweet embeds on third-party sites).

Setup:
  1. pip install python-telegram-bot httpx
  2. Get a bot token from @BotFather on Telegram
  3. Paste it into BOT_TOKEN below
  4. python twitter_stats_bot.py
"""

import re
import math
import httpx
from telegram import Update
from telegram.ext import (
    Application, MessageHandler, CommandHandler, filters, ContextTypes
)

BOT_TOKEN = "8814820902:AAGZ2deTEqUvR_w7AhRzapy8Zb6uTz838JA"

TWEET_RE = re.compile(r"(?:twitter\.com|x\.com)/[^/\s]+/status/(\d+)")
BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _to_base36(n: float) -> str:
    """Mimics JS Number.prototype.toString(36) for floats."""
    if n == 0:
        return "0"
    int_part = int(n)
    frac = n - int_part

    if int_part == 0:
        int_str = "0"
    else:
        int_str = ""
        x = int_part
        while x > 0:
            int_str = BASE36[x % 36] + int_str
            x //= 36

    frac_str = ""
    if frac > 0:
        frac_str = "."
        for _ in range(12):
            frac *= 36
            d = int(frac)
            frac_str += BASE36[d]
            frac -= d
            if frac == 0:
                break
    return int_str + frac_str


def make_token(tweet_id: str) -> str:
    """Token algorithm Twitter uses for the public syndication endpoint."""
    n = int(tweet_id) / 1e15 * math.pi
    return re.sub(r"[0.]", "", _to_base36(n))


async def fetch_tweet(tweet_id: str):
    token = make_token(tweet_id)
    url = (
        f"https://cdn.syndication.twimg.com/tweet-result"
        f"?id={tweet_id}&token={token}&lang=en"
    )
    headers = {"User-Agent": "Mozilla/5.0"}
    async with httpx.AsyncClient(timeout=15, headers=headers) as client:
        r = await client.get(url)
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except Exception:
            return None


def extract_views(data: dict):
    """Views/impressions live in a few possible spots depending on the tweet."""
    for key in ("view_count_str", "view_count"):
        if key in data and data[key]:
            return data[key]
    views = data.get("views")
    if isinstance(views, dict):
        return views.get("count") or views.get("state")
    return None


def fmt(n):
    if n is None:
        return "not exposed"
    if isinstance(n, str) and n.isdigit():
        n = int(n)
    if isinstance(n, int):
        return f"{n:,}"
    return str(n)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text or ""
    match = TWEET_RE.search(text)
    if not match:
        await update.message.reply_text(
            "Send me a link to a tweet, e.g.\nhttps://x.com/user/status/123..."
        )
        return

    tweet_id = match.group(1)
    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action="typing")

    data = await fetch_tweet(tweet_id)
    if not data:
        await update.message.reply_text(
            "Couldn't fetch that tweet. It may be private, deleted, "
            "age-restricted, or the endpoint blocked the request."
        )
        return

    author = data.get("user", {}).get("screen_name", "?")
    likes = data.get("favorite_count")
    replies = data.get("conversation_count")
    rts = data.get("retweet_count") or data.get("quote_count")
    views = extract_views(data)

    msg = (
        f"📊 Stats for @{author}\n"
        f"https://x.com/{author}/status/{tweet_id}\n\n"
        f"👁  Impressions: {fmt(views)}\n"
        f"❤️  Likes:        {fmt(likes)}\n"
        f"🔁  Retweets:     {fmt(rts)}\n"
        f"💬  Replies:      {fmt(replies)}"
    )
    await update.message.reply_text(msg, disable_web_page_preview=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! Send me any tweet/X link and I'll return its public stats."
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    print("Bot running. Press Ctrl+C to stop.")
    app.run_polling()


if __name__ == "__main__":
    main()
