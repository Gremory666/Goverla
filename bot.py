import os
import json
import datetime
import logging
import google.generativeai as genai
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext

# Налаштування логування
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Завантаження змінних середовища
TELEGRAM_TOKEN = os.getenv("BOT_TOKEN")
GENAI_API_KEY = os.getenv("GEMINI_API_KEY")

# Файл для збереження повідомлень
DATA_FILE = "messages.json"

# Перевірка токенів
if not TELEGRAM_TOKEN:
    raise ValueError("❌ TELEGRAM_TOKEN не знайдено! Перевірте змінні середовища.")
if not GENAI_API_KEY:
    raise ValueError("❌ GENAI_API_KEY не знайдено! Перевірте змінні середовища.")

# Налаштування Gemini API
genai.configure(api_key=GENAI_API_KEY)

# Функція для завантаження історії повідомлень
def load_messages():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError:
            logging.error("❌ Помилка читання JSON. Починаємо з порожнього файлу.")
    return {}

# Функція для збереження історії повідомлень
def save_messages():
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(user_messages, file, ensure_ascii=False, indent=4)

# Завантаження повідомлень
user_messages = load_messages()

# Команда /start
async def start(update: Update, context: CallbackContext) -> None:
    await update.message.reply_text("✅ Бот запущено! Я збиратиму повідомлення і о 21:00 надсилатиму список тем, про які йшлося в чаті.")

# Обробка повідомлень
async def handle_message(update: Update, context: CallbackContext) -> None:
    chat_id = str(update.message.chat_id)  # ID як рядок для JSON
    text = update.message.text

    # Отримання ID бота, щоб він не записував власні повідомлення
    bot_id = (await context.bot.get_me()).id
    if update.message.from_user.id == bot_id:
        return  # Бот не зберігає свої повідомлення

    if chat_id not in user_messages:
        user_messages[chat_id] = []

    user_messages[chat_id].append(text)
    save_messages()  # Збереження у файл після кожного повідомлення 

    logging.info(f"📩 Нове повідомлення від {chat_id}: {text}")

# Генерація списку тем через Gemini API
async def send_summary(context: CallbackContext) -> None:
    now = datetime.datetime.now()
    if now.hour == 13:
        for chat_id, messages in user_messages.items():
            if messages:
                try:
                    # Формування запиту до Gemini
                    model = genai.GenerativeModel("gemini-2.0-flash")
                    response = model.generate_content(
                        f"Проаналізуй ці повідомлення:\n{messages}\n"
                        "Визнач основні теми, які обговорювалися, і створи динамічний та емоційний список! "
                        "Додай трохи гумору, емоцій або коментарів, щоб зробити його цікавішим. "
                        "Приклад:\n🔥 Гаряче обговорення про штучний інтелект!\n🤔 Чи справді каву можна вважати корисною? "
                        "Видай лише список тем у маркованому форматі без зайвого тексту."
                    )
                    summary = response.text if response.text else "Немає зібраних тем за сьогодні."

                    # Відправка підсумку
                    await context.bot.send_message(chat_id, f"📝 *Ось що сьогодні обговорювали:*\n{summary}", parse_mode="Markdown")
                    logging.info(f"✅ Список тем відправлено в чат {chat_id}")
                except Exception as e:
                    logging.error(f"❌ Помилка генерації тем для {chat_id}: {e}")

                # Очищення історії після відправки
                user_messages[chat_id] = []
                save_messages()  # Очищений JSON після надсилання списку тем

# Головна функція
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    # Обробники
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Щоденне завдання о 21:00
    job_queue = app.job_queue
    job_queue.run_repeating(send_summary, interval=60, first=0)

    # Запуск бота
    logging.info("🚀 Бот запущено...")
    app.run_polling()

if __name__ == "__main__":
    main()
