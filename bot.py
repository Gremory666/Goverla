import os
import re
import json
import datetime
import logging
from collections import Counter
from zoneinfo import ZoneInfo

import google.generativeai as genai
from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    CallbackContext,
)

# Налаштування логування
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Отримання змінних середовища
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
DATA_FILE = "messages.json"

if not TELEGRAM_TOKEN:
    raise ValueError("BOT_TOKEN не знайдено! Перевірте змінні середовища.")
if not GENAI_API_KEY:
    raise ValueError("GEMINI_API_KEY не знайдено! Перевірте змінні середовища.")

# Конфігурація generative AI
genai.configure(api_key=GENAI_API_KEY)

# Глобальний словник для зберігання повідомлень за chat_id
user_messages = {}

# Шаблон для видалення URL
URL_PATTERN = re.compile(r'https?://\S+')

def remove_links(text: str) -> str:
    """Видаляє посилання з тексту."""
    return URL_PATTERN.sub('', text)

def is_spam(text: str, chat_id: str) -> bool:
    """Перевіряє, чи є повідомлення спамом."""
    allowed_short = {"так", "ні"}
    words = text.split()

    if chat_id in user_messages and user_messages[chat_id]:
        last_message = user_messages[chat_id][-1]["text"]
        if text == last_message:
            return True

    if len(words) < 2 and text.lower() not in allowed_short:
        if chat_id in user_messages and user_messages[chat_id]:
            prev_message = user_messages[chat_id][-1]["text"]
            if len(prev_message.split()) < 2:
                return True
    return False

# Список заборонених слів для цензурування
BAD_WORDS = {"матюк1", "матюк2", "матюк3"}

def censor_text(text: str) -> str:
    """Замінює заборонені слова на '***'."""
    words = text.split()
    return " ".join("***" if word.lower() in BAD_WORDS else word for word in words)

def extract_keywords(texts):
    """Витягує топ-5 найчастіших слів із списку повідомлень."""
    words = " ".join(texts).split()
    common_words = Counter(words).most_common(5)
    return [word for word, _ in common_words]

def load_messages():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                # Перетворюємо рядки назад у datetime після завантаження
                for chat_id, messages in data.items():
                    for msg in messages:
                        if "timestamp" in msg and isinstance(msg["timestamp"], str):
                            msg["timestamp"] = datetime.datetime.fromisoformat(msg["timestamp"])
                return data
        except Exception as e:
            logging.error(f"Помилка завантаження повідомлень: {e}")
    return {}

def save_messages():
    try:
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            # Перетворюємо datetime на рядок (ISO 8601) перед збереженням
            def datetime_serializer(obj):
                if isinstance(obj, datetime.datetime):
                    return obj.isoformat()
                raise TypeError("Type not serializable")

            json.dump(user_messages, f, ensure_ascii=False, indent=4, default=datetime_serializer)
    except Exception as e:
        logging.error(f"Помилка збереження повідомлень: {e}")

# Завантаження повідомлень під час запуску
user_messages = load_messages()

# Набір ключових слів для виявлення важливих повідомлень
important_keywords = {"важливо", "терміново", "допоможіть", "проблема"}


async def handle_message(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.message.chat.id)
    text = update.message.text
    text = remove_links(text)
    text = censor_text(text)
    text = text.strip()

    if update.message.from_user.id == (await context.bot.get_me()).id:
        return

    if is_spam(text, chat_id):
        logging.info(f"Ігнорується спам/флуд: {text}")
        return

    user_messages.setdefault(chat_id, []).append({"text": text, "timestamp": datetime.datetime.now()})
    save_messages()
    logging.info(f"Повідомлення збережено для чату {chat_id}: {text}")

async def show_stats(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.message.chat.id)
    if chat_id not in user_messages or not user_messages[chat_id]:
        await update.message.reply_text("Немає даних для статистики.")
        return
    messages = [msg["text"] for msg in user_messages[chat_id]]
    word_count = sum(len(msg.split()) for msg in messages)
    keywords = extract_keywords(messages)

    filtered_keywords = [word for word in keywords if not word.startswith('@')]
    keywords_str = ", ".join(filtered_keywords)

    stats_header = re.escape("📊 *Статистика чату:*")
    messages_line = re.escape(f"🔹 Повідомлень: {len(messages)}")
    words_line = re.escape(f"🔹 Слів: {word_count}")
    keywords_label = re.escape("🔹 Популярні слова:")

    message_text = f"{stats_header}\n{messages_line}\n{words_line}\n{keywords_label} {keywords_str}"
    logging.info(f"Текст перед відправкою: {message_text}")

    await update.message.reply_text(
        message_text,
        parse_mode="MarkdownV2"
    )

async def remind(update: Update, context: CallbackContext) -> None:
    try:
        args = context.args
        if len(args) < 2:
            await update.message.reply_text("Формат: /remind <хвилини> <текст>")
            return
        minutes = int(args[0])
        text = " ".join(args[1:])
        chat_id = update.message.chat.id
        user = update.message.from_user
        mention = f"[{re.escape(user.first_name)}](tg://user?id={user.id})"
        text = re.escape(text)
        context.job_queue.run_once(
            lambda ctx: ctx.bot.send_message(
                chat_id,
                f"🔔 {mention}, нагадування: {text}",
                parse_mode="MarkdownV2"
            ),
            when=minutes * 60
        )
        await update.message.reply_text(f"Нагадування встановлено на {minutes} хвилин.")
    except ValueError:
        await update.message.reply_text("Помилка! Використовуйте число для часу.")


async def send_summary(context: CallbackContext, clear_history: bool = True) -> None:
    """Надсилає резюме повідомлень.

    Args:
        context: Об'єкт CallbackContext.
        clear_history: Чи очищати історію повідомлень після надсилання (за замовчуванням True).
    """
    global user_messages

    for chat_id in list(user_messages.keys()):
        if not user_messages[chat_id]:
            continue

        messages = [msg["text"] for msg in user_messages[chat_id]]
        message_texts = "\n".join(messages)
        imp_msgs = [msg for msg in messages if any(kw in msg.lower() for kw in important_keywords)]

        prompt = (
            f"Ось повідомлення чату:\n{message_texts}\n\n"
            "Сформулюй коротке резюме того, що обговорювали, у 2-5 реченнях, "
            "а потім додай список основних тем у маркованому форматі."
        )
        try:
            model = genai.GenerativeModel("gemini-1.0-pro")
            response = model.generate_content(prompt)
            ai_summary = response.text if response.text else "Немає зібраних тем."
        except Exception as e:
            logging.error(f"Помилка генерації AI підсумку: {e}")
            ai_summary = "Помилка генерації підсумку через проблеми з AI."

        keywords = extract_keywords(messages)
        keywords_str = re.escape(", ".join(keywords))

        # Екрануємо ai_summary ПЕРЕД об'єднанням
        ai_summary = re.escape(ai_summary)

        summary_text = ai_summary + f"\n\n📌 Ключові слова: {keywords_str}"
        if imp_msgs:
          imp_msgs_str = "\n".join(imp_msgs)
          # Екрануємо imp_msgs_str ПЕРЕД додаванням
          imp_msgs_str = re.escape(imp_msgs_str)

          summary_text += f"\n\n🚨 Важливі повідомлення:\n{imp_msgs_str}"


        try:
            await context.bot.send_message(chat_id, summary_text, parse_mode="MarkdownV2")
            logging.info(f"Надіслано резюме в чат {chat_id}")
        except Exception as e:
            logging.error(f"Помилка під час відправлення повідомлення в чат {chat_id}: {e}")

        if clear_history:
            del user_messages[chat_id]
            save_messages()


async def summarize(update: Update, context: CallbackContext) -> None:
    """Обробник команди /summarize."""
    chat_id = str(update.message.chat.id)
    chat_admins = await context.bot.get_chat_administrators(chat_id)
    admin_ids = [admin.user.id for admin in chat_admins]

    if update.message.from_user.id not in admin_ids:
        await update.message.reply_text("Команда доступна лише для адміністраторів.")
        return

    if chat_id not in user_messages or not user_messages[chat_id]:
        await update.message.reply_text("Немає повідомлень для підсумку.")
        return

    # Викликаємо send_summary з clear_history=False
    await send_summary(context, clear_history=True)


def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("stats", show_stats))
    app.add_handler(CommandHandler("remind", remind))
    app.add_handler(CommandHandler("summarize", summarize))

    time = datetime.time(hour=21, minute=0, second=0, tzinfo=ZoneInfo("Europe/Kiev"))
    app.job_queue.run_daily(send_summary, time, days=(0, 1, 2, 3, 4, 5, 6))

    logging.info("Бот запущено...")
    app.run_polling()

if __name__ == "__main__":
    main()