import os
import re
import json
import datetime
import logging
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, CallbackContext
from telegram.helpers import escape_markdown

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")
DATA_FILE = "messages.json"

if not TELEGRAM_TOKEN:
    raise ValueError("BOT_TOKEN не знайдено! Перевірте змінні середовища.")
if not GENAI_API_KEY:
    raise ValueError("GEMINI_API_KEY не знайдено! Перевірте змінні середовища.")

genai.configure(api_key=GENAI_API_KEY)

# Регулярний вираз для пошуку посилань (http або https)
URL_PATTERN = re.compile(r'https?://\S+')

def remove_links(text: str) -> str:
    """
    Видаляє всі посилання (URL) з рядка.
    """
    return URL_PATTERN.sub('', text)

def load_messages():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError:
            logging.error("Помилка читання JSON. Починаємо з порожнього файлу.")
    return {}

def save_messages():
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(user_messages, file, ensure_ascii=False, indent=4)

user_messages = load_messages()

async def handle_message(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.message.chat_id)
    text = update.message.text
    # Видаляємо посилання з тексту, щоб вони не потрапляли в підсумок
    cleaned_text = remove_links(text).strip()

    bot_id = (await context.bot.get_me()).id
    if update.message.from_user.id == bot_id:
        return

    if chat_id not in user_messages:
        user_messages[chat_id] = []
    user_messages[chat_id].append(cleaned_text)
    save_messages()
    logging.info(f"Новe повідомлення від {chat_id}: {cleaned_text}")

async def send_summary(context: CallbackContext) -> None:
    now = datetime.datetime.now()
    # Надсилання підсумку о 20:00
    if now.hour == 20:
        if not any(user_messages.values()):
            logging.info("Немає повідомлень для підсумку.")
            return
        for chat_id, messages in user_messages.items():
            if messages:
                try:
                    # Збираємо всі повідомлення в один рядок
                    message_texts = "\n".join(messages)
                    model = genai.GenerativeModel("gemini-2.0-flash")
                    response = model.generate_content(
                        f"Проаналізуй ці повідомлення:\n{message_texts}\n"
                        "Визнач основні теми, які обговорювалися, і створи короткий список тем. "
                        "Видай лише список тем у маркованому форматі без додаткового тексту."
                    )
                    summary = response.text if response.text else "Немає зібраних тем за сьогодні."
                    if summary.strip() == "" or summary == "Немає зібраних тем за сьогодні.":
                        logging.info(f"Немає тем для відправки в чат {chat_id}.")
                        continue
                    safe_summary = escape_markdown(summary, version=2)
                    await context.bot.send_message(
                        chat_id,
                        f"📝 *Ось що сьогодні обговорювали:*\n{safe_summary}",
                        parse_mode="MarkdownV2"
                    )
                    logging.info(f"Список тем відправлено в чат {chat_id}.")
                except Exception as e:
                    logging.error(f"Помилка генерації тем для {chat_id}: {e}")
                user_messages[chat_id] = []
                save_messages()

async def test_summary(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.message.chat_id)
    if chat_id not in user_messages or not user_messages[chat_id]:
        await update.message.reply_text("Немає повідомлень для підсумку.")
        return
    try:
        messages = user_messages[chat_id]
        message_texts = "\n".join(messages)
        model = genai.GenerativeModel("gemini-2.0-flash")
        response = model.generate_content(
            f"Проаналізуй ці повідомлення:\n{message_texts}\n"
            "Визнач основні теми, які обговорювалися, і створи короткий список тем. "
            "Видай лише список тем у маркованому форматі без додаткового тексту."
        )
        summary = response.text if response.text else "Немає зібраних тем за сьогодні."
        if summary.strip() == "" or summary == "Немає зібраних тем за сьогодні.":
            await update.message.reply_text("Немає тем для відправки.")
            return
        safe_summary = escape_markdown(summary, version=2)
        await context.bot.send_message(
            chat_id,
            f"📝 *Ось що сьогодні обговорювали:*\n{safe_summary}",
            parse_mode="MarkdownV2"
        )
        user_messages[chat_id] = []
        save_messages()
        logging.info(f"Список тем відправлено в чат {chat_id} за запитом /test_summary.")
    except Exception as e:
        logging.error(f"Помилка генерації тем для {chat_id} при тестуванні: {e}")
        await update.message.reply_text("Сталася помилка при генерації підсумку.")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CommandHandler("test_summary", test_summary))
    job_queue = app.job_queue
    # Запускаємо send_summary кожні 60 секунд, перевірка часу всередині
    job_queue.run_repeating(send_summary, interval=60, first=0)
    logging.info("Бот запущено...")
    app.run_polling()

if __name__ == "__main__":
    main()
