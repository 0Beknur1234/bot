import os
import json
from datetime import datetime
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    filters, ContextTypes, ConversationHandler, CallbackQueryHandler
)
import gspread
from google.oauth2.service_account import Credentials

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
SPREADSHEET_ID = os.environ.get("SPREADSHEET_ID")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

# --- ШАГИ ДИАЛОГА ---
CATEGORY, PHOTO, DESCRIPTION, CONTACT = range(4)

CATEGORIES = ["🔍 Найдено", "❓ Потерялось", "🆘 Требуется помощь", "🏠 Ищет новое место"]

def get_sheet():
    creds_json = os.environ.get("GOOGLE_CREDENTIALS")
    creds_dict = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1
    return sheet

# --- СТАРТ ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["➕ Создать карточку", "📋 Список карточек"]]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    await update.message.reply_text(
        "👋 Привет! Я помогу создать карточку объекта или найти нужную информацию.\n\n"
        "Выбери действие:",
        reply_markup=markup
    )

# --- СОЗДАНИЕ КАРТОЧКИ ---
async def new_card(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[cat] for cat in CATEGORIES]
    markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True, one_time_keyboard=True)
    await update.message.reply_text("📁 Выбери категорию:", reply_markup=markup)
    return CATEGORY

async def get_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.text not in CATEGORIES:
        await update.message.reply_text("Пожалуйста, выбери категорию из списка.")
        return CATEGORY
    context.user_data["category"] = update.message.text
    await update.message.reply_text(
        "📸 Отправь фото (или напиши 'пропустить'):",
        reply_markup=ReplyKeyboardRemove()
    )
    return PHOTO

async def get_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.photo:
        context.user_data["photo"] = update.message.photo[-1].file_id
    else:
        context.user_data["photo"] = ""
    await update.message.reply_text("📝 Опиши ситуацию:")
    return DESCRIPTION

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["description"] = update.message.text
    await update.message.reply_text("📞 Укажи контактные данные:")
    return CONTACT

async def get_contact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["contact"] = update.message.text
    data = context.user_data
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    username = update.message.from_user.username or update.message.from_user.first_name

    try:
        sheet = get_sheet()
        sheet.append_row([
            now,
            data["category"],
            data["description"],
            data["contact"],
            data.get("photo", ""),
            username
        ])
        await update.message.reply_text(
            f"✅ Карточка создана!\n\n"
            f"📁 Категория: {data['category']}\n"
            f"📝 Описание: {data['description']}\n"
            f"📞 Контакт: {data['contact']}\n\n"
            f"Карточка отправлена на проверку.",
            reply_markup=ReplyKeyboardMarkup([["➕ Создать карточку", "📋 Список карточек"]], resize_keyboard=True)
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка при сохранении: {e}")

    context.user_data.clear()
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.clear()
    await update.message.reply_text(
        "❌ Отменено.",
        reply_markup=ReplyKeyboardMarkup([["➕ Создать карточку", "📋 Список карточек"]], resize_keyboard=True)
    )
    return ConversationHandler.END

# --- СПИСОК КАРТОЧЕК ---
async def list_cards(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sheet = get_sheet()
        rows = sheet.get_all_values()[1:]  # пропускаем заголовок

        if not rows:
            await update.message.reply_text("📭 Карточек пока нет.")
            return

        # Кнопки фильтра по категории
        keyboard = [
            [InlineKeyboardButton(cat, callback_data=f"filter:{cat}")]
            for cat in CATEGORIES
        ]
        keyboard.append([InlineKeyboardButton("📋 Все", callback_data="filter:all")])
        markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Выбери категорию для фильтра:", reply_markup=markup)

    except Exception as e:
        await update.message.reply_text(f"❌ Ошибка: {e}")

async def filter_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category = query.data.replace("filter:", "")

    try:
        sheet = get_sheet()
        rows = sheet.get_all_values()[1:]

        if category != "all":
            rows = [r for r in rows if r[1] == category]

        if not rows:
            await query.edit_message_text("📭 Карточек по этой категории нет.")
            return

        last_10 = rows[-10:]
        text = f"📋 Последние карточки ({category if category != 'all' else 'все'}):\n\n"
        for i, row in enumerate(reversed(last_10), 1):
            text += (
                f"{i}. {row[1]}\n"
                f"📅 {row[0]}\n"
                f"📝 {row[2]}\n"
                f"📞 {row[3]}\n\n"
            )
        await query.edit_message_text(text)

    except Exception as e:
        await query.edit_message_text(f"❌ Ошибка: {e}")

# --- ЗАПУСК ---
def main():
    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[
            MessageHandler(filters.Regex("^➕ Создать карточку$"), new_card),
            CommandHandler("new", new_card)
        ],
        states={
            CATEGORY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_category)],
            PHOTO: [
                MessageHandler(filters.PHOTO, get_photo),
                MessageHandler(filters.Regex("^пропустить$"), get_photo),
                MessageHandler(filters.TEXT, get_photo),
            ],
            DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
            CONTACT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_contact)],
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex("^📋 Список карточек$"), list_cards))
    app.add_handler(CallbackQueryHandler(filter_callback, pattern="^filter:"))

    print("Бот запущен...")
    app.run_polling()

if __name__ == "__main__":
    main()
