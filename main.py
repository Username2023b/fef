# bot.py
import os
import requests
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# === Поддержка .env для локальной разработки (опционально) ===
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # На хостинге не требуется

# === Безопасное чтение настроек из переменных окружения ===
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
BITRIX_URL = os.getenv("BITRIX_URL")

if not TELEGRAM_TOKEN:
    raise ValueError("Ошибка: не задана переменная окружения TELEGRAM_TOKEN")
if not BITRIX_URL:
    raise ValueError("Ошибка: не задана переменная окружения BITRIX_URL")

IBLOCK_ID = 17

# Кэш для разделов (уменьшает количество запросов к API)
root_sections_cache = None
subsections_cache = {}

# === Вспомогательные функции ===
def get_root_sections():
    global root_sections_cache
    if root_sections_cache is None:
        r = requests.post(
            f"{BITRIX_URL}/rest/1/catalog.section.list.json",
            data={
                "filter[iblockId]": IBLOCK_ID,
                "filter[active]": "Y",
                "filter[iblockSectionId]": "",
                "select[]": ["id", "name"]
            },
            timeout=10
        )
        root_sections_cache = r.json().get("result", {}).get("sections", [])
    return root_sections_cache

def get_subsections(parent_id):
    if parent_id not in subsections_cache:
        r = requests.post(
            f"{BITRIX_URL}/rest/1/catalog.section.list.json",
            data={
                "filter[iblockId]": IBLOCK_ID,
                "filter[active]": "Y",
                "filter[iblockSectionId]": parent_id,
                "select[]": ["id", "name"]
            },
            timeout=10
        )
        subsections_cache[parent_id] = r.json().get("result", {}).get("sections", [])
    return subsections_cache[parent_id]

def get_products_in_tree(root_id):
    """Выгружает все активные/доступные товары из ветки (корень + подкатегории)"""
    all_items = []
    start = 0
    limit = 100
    while True:
        r = requests.post(
            f"{BITRIX_URL}/rest/1/catalog.product.list.json",
            data={
                "filter[iblockId]": IBLOCK_ID,
                "filter[active]": "Y",
                "filter[available]": "Y",
                "limit": limit,
                "start": start,
                "select[]": ["id", "name", "iblockSection"]
            },
            timeout=15
        )
        data = r.json()
        items = data.get("result", {}).get("products", [])
        if not items:
            break
        
        # Получаем все ID подкатегорий
        sub_ids = [s["id"] for s in get_subsections(root_id)]
        all_valid_ids = [root_id] + sub_ids

        # Фильтруем товары локально
        for item in items:
            sections = item.get("iblockSection") or []
            if any(sid in sections for sid in all_valid_ids):
                all_items.append({"id": item["id"], "name": item["name"]})
        
        if len(items) < limit or len(all_items) >= 50:
            break
        start += limit
    return all_items[:50]

# === Обработчики Telegram ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    sections = get_root_sections()
    if not sections:
        await update.message.reply_text("Категории временно недоступны.")
        return

    keyboard = []
    row = []
    for i, sec in enumerate(sections):
        row.append(InlineKeyboardButton(sec["name"], callback_data=f"root_{sec['id']}"))
        if (i + 1) % 2 == 0:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Выберите категорию:", reply_markup=reply_markup)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    if data.startswith("root_"):
        root_id = int(data.split("_")[1])
        subsections = get_subsections(root_id)
        products = get_products_in_tree(root_id)
        
        # Формируем сообщение с товарами
        if not products:
            text = "В этой категории нет доступных товаров."
        else:
            text = f"Товары ({len(products)}):\n\n"
            for p in products[:10]:
                text += f"• {p['name']}\n"
            if len(products) > 10:
                text += f"\n... и ещё {len(products)-10} товаров"
        
        # Кнопки подкатегорий
        keyboard = [[InlineKeyboardButton("Все", callback_data=f"sub_{root_id}_all")]]
        if subsections:
            for sub in subsections:
                keyboard.append([InlineKeyboardButton(sub["name"], callback_data=f"sub_{root_id}_{sub['id']}")])
        
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text=text, reply_markup=reply_markup)

# === Запуск бота ===
def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_polling()

if __name__ == "__main__":
    main()
