import os
import re
import logging
from datetime import datetime
import requests

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove
)
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler
)
from telegram.error import BadRequest

TELEGRAM_BOT_TOKEN = "7842784260:AAH5J22Uv8Wr7CNPMI_MCexJuYh6j3Q6Kjs"
SPOONACULAR_API_KEY = "fd458f7b70da4fde867ea1fa030e5147"

ASK_INGREDIENTS, ASK_CUISINE, ASK_MEAL_TYPE = range(3)

MAIN_MENU_KEYBOARD = [
    ["🔍 Поиск по ингредиентам"],
    ["🎲 Случайный рецепт", "🍲 Выбор кухни"],
    ["❓ Помощь"]
]
MAIN_MENU_MARKUP = ReplyKeyboardMarkup(
    MAIN_MENU_KEYBOARD, resize_keyboard=True, one_time_keyboard=False)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("apscheduler").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

LOG_DIR = "user_logs"
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)


def log_user_interaction(user_id: int, username: str, text: str, is_bot_message: bool = False):
    """логирование"""
    log_file_path = os.path.join(LOG_DIR, f"{user_id}.log")
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sender = "BOT" if is_bot_message else (
        username if username else f"User_{user_id}")
    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(f"{timestamp} [{sender}]: {text}\n")


def escape_markdown_v2(text: str) -> str:
    """экранирование markdown v2"""
    if not isinstance(text, str):
        text = str(text)
    escape_chars = r'_*[]()~`>#+=|{}.!\-'
    escape_chars += '\u2013\u2014\u2212'
    pattern = r'([{}])'.format(re.escape(escape_chars))
    return re.sub(pattern, r'\\\1', text)


def format_recipe_summary_markdown_v2(recipe_data):
    """форматирование информация о рецепте с markdown v2\n
    вовращает словарь: \n
    детали рецепта(text), url image, url source, id рецепта"""
    recipe_id = recipe_data.get("id", "N/A")
    title_raw = recipe_data.get("title", "Без названия")
    image_url = recipe_data.get("image")
    calories_info = next((n for n in recipe_data.get("nutrition", {}).get(
        "nutrients", []) if n["name"] == "Calories"), None)
    calories_raw = f"{round(calories_info['amount'])} ккал" if calories_info else "не указана"

    message_text = f"*{escape_markdown_v2(title_raw)}* \\(ID: {recipe_id}\\)\n"
    message_text += f"Калорийность: {escape_markdown_v2(calories_raw)}\n"
    if recipe_data.get("cuisines"):
        message_text += f"Кухни: {escape_markdown_v2(', '.join(recipe_data['cuisines']))}\n"
    if recipe_data.get("dishTypes"):
        message_text += f"Типы блюд: {escape_markdown_v2(', '.join(recipe_data['dishTypes']))}\n"
    return {
        "text": message_text,
        "image_url": image_url,
        "source_url": recipe_data.get("sourceUrl"),
        "id": recipe_id
    }


def format_recipe_details_plain_text(recipe_data):
    """форматирование подробной информации рецепта\n
    возвращает словарь: \n 
    детали рецепта(text), url image, url source, id рецепта"""
    title_raw = recipe_data.get("title", "Без названия")
    recipe_id = recipe_data.get("id", "N/A")
    ingredients_list_raw = recipe_data.get("extendedIngredients", [])
    instructions_raw = recipe_data.get(
        "instructions", "Инструкции отсутствуют.")
    source_url_raw = recipe_data.get("sourceUrl")

    message_text = f"Название: {title_raw} (ID: {recipe_id})\n\n"
    message_text += "Ингредиенты:\n"
    if ingredients_list_raw:
        for ing in ingredients_list_raw:
            message_text += f"- {ing.get('original', '')}\n"
    else:
        message_text += "Не указаны.\n"

    message_text += "\nИнструкции:\n"
    instructions_no_html = re.sub(
        '<[^<]+?>', '', instructions_raw) if instructions_raw else "Инструкции отсутствуют."
    message_text += f"{instructions_no_html}\n"

    return {"text": message_text, "image_url": recipe_data.get("image"), "source_url": source_url_raw, "id": recipe_id}


def search_recipes_complex(query=None, cuisine=None, meal_type=None, ingredients=None, number=5):
    """поиск рецепта по API \n
    запрашивает (необязательные): названия, кухня, тип блюда, ингредиенты, количество(5) \n
    возвращает: рецепты"""
    format_recipe_details_plain_text
    params = {"apiKey": SPOONACULAR_API_KEY, "number": number,
              "addRecipeInformation": True, "fillIngredients": True, "instructionsRequired": True}
    if query:
        params["query"] = query
    if cuisine:
        params["cuisine"] = cuisine
    if meal_type:
        params["type"] = meal_type
    if ingredients:
        params["includeIngredients"] = ingredients
    params = {k: v for k, v in params.items() if v is not None}
    try:
        response = requests.get(
            "https://api.spoonacular.com/recipes/complexSearch", params=params)
        response.raise_for_status()
        data = response.json()
        return [format_recipe_summary_markdown_v2(recipe) for recipe in data.get("results", [])]
    except Exception as e:
        logger.error(f"API Error (complexSearch): {e}", exc_info=True)
        return []


def get_random_recipes(tags=None, number=1):
    """один случайный рецепт \n
    возвращает: рецепт"""
    params = {"apiKey": SPOONACULAR_API_KEY, "number": number}
    if tags:
        params["tags"] = tags
    try:
        response = requests.get(
            "https://api.spoonacular.com/recipes/random", params=params)
        response.raise_for_status()
        data = response.json()
        return [format_recipe_summary_markdown_v2(recipe) for recipe in data.get("recipes", [])]
    except Exception as e:
        logger.error(
            f"API Error (random with tags: {tags}): {e}", exc_info=True)
        return []


def get_recipe_information_plain(recipe_id):
    """получение подробной информации рецепта \n
    получает: id рецепта \n
    возвращает: format_recipe_details_plain_text() """
    params = {"apiKey": SPOONACULAR_API_KEY, "includeNutrition": True}
    try:
        response = requests.get(
            f"https://api.spoonacular.com/recipes/{recipe_id}/information", params=params)
        response.raise_for_status()
        return format_recipe_details_plain_text(response.json())
    except Exception as e:
        logger.error(
            f"API Error (information for ID {recipe_id}): {e}", exc_info=True)
        return None


def get_recipe_nutrition_info_markdown_v2(recipe_id):
    """получает и возвращает пищевую ценность по id \n
    получает: id рецепта \n
    возвращает: информацию о пищевой ценности - к.б.ж.у."""
    params = {"apiKey": SPOONACULAR_API_KEY}
    try:
        response = requests.get(
            f"https://api.spoonacular.com/recipes/{recipe_id}/nutritionWidget.json", params=params)
        response.raise_for_status()
        data = response.json()
        nutrition_label_raw = f"Пищевая ценность для рецепта ID {recipe_id}"
        nutrition_info = f"*{escape_markdown_v2(nutrition_label_raw)}*\n"
        nutrition_info += f"Калории: {escape_markdown_v2(data.get('calories', 'N/A'))}\n"
        nutrition_info += f"Белки: {escape_markdown_v2(data.get('protein', 'N/A'))}\n"
        nutrition_info += f"Жиры: {escape_markdown_v2(data.get('fat', 'N/A'))}\n"
        nutrition_info += f"Углеводы: {escape_markdown_v2(data.get('carbs', 'N/A'))}\n"
        return nutrition_info
    except Exception as e:
        logger.error(
            f"API Error (nutritionWidget for ID {recipe_id}): {e}", exc_info=True)
        return escape_markdown_v2("Не удалось получить информацию о пищевой ценности.")


async def send_recipes_summary_response(update_or_query_message, context: ContextTypes.DEFAULT_TYPE, recipes: list):
    """обработчик результатов поиска пользователя"""
    if isinstance(update_or_query_message, Update):
        chat_id = update_or_query_message.effective_chat.id
        username = update_or_query_message.effective_user.username or update_or_query_message.effective_user.first_name
    else:
        chat_id = update_or_query_message.chat_id
        username = context.user_data.get('callback_username', 'UnknownUser')

    if not recipes:
        response_text = "К сожалению, по вашему запросу ничего не найдено."
        await context.bot.send_message(chat_id=chat_id, text=response_text)
        log_user_interaction(
            chat_id, username, response_text, is_bot_message=True)
        return

    for recipe_summary in recipes:
        message_text = recipe_summary['text']
        recipe_id = recipe_summary['id']
        buttons = []
        buttons.append(InlineKeyboardButton(
            "📖 Подробнее", callback_data=f"details_{recipe_id}"))
        buttons.append(InlineKeyboardButton(
            "📊 БЖУ", callback_data=f"nutrition_{recipe_id}"))
        if recipe_summary.get("source_url"):
            buttons.append(InlineKeyboardButton(
                "🔗 Источник API", url=recipe_summary["source_url"]))

        reply_markup = InlineKeyboardMarkup([buttons])

        log_text_for_bot = f"[PHOTO IF ANY] {message_text}" if recipe_summary['image_url'] else message_text

        if recipe_summary['image_url']:
            try:
                await context.bot.send_photo(
                    chat_id=chat_id, photo=recipe_summary['image_url'], caption=message_text,
                    reply_markup=reply_markup, parse_mode='MarkdownV2'
                )
            except Exception as e_photo:
                logger.error(
                    f"Error sending photo for recipe ID {recipe_id}: {e_photo}", exc_info=True)
                try:
                    await context.bot.send_message(
                        chat_id=chat_id, text=message_text, reply_markup=reply_markup, parse_mode='MarkdownV2'
                    )
                except Exception as e_text_fallback:
                    logger.error(
                        f"Error sending summary text fallback for recipe ID {recipe_id}: {e_text_fallback}", exc_info=True)
        else:
            await context.bot.send_message(
                chat_id=chat_id, text=message_text, reply_markup=reply_markup, parse_mode='MarkdownV2'
            )
        log_user_interaction(
            chat_id, username, log_text_for_bot, is_bot_message=True)


async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, message_text: str = None):
    """отправляет главное меню с опциональным сообщением"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name

    text_to_send = message_text if message_text else "Выберите действие:"
    escaped_text = escape_markdown_v2(text_to_send)

    await context.bot.send_message(chat_id=chat_id, text=escaped_text, reply_markup=MAIN_MENU_MARKUP, parse_mode='MarkdownV2')
    log_user_interaction(chat_id, username, text_to_send, is_bot_message=True)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/start"""
    user = update.effective_user
    chat_id = update.effective_chat.id
    username = user.username or user.first_name
    log_user_interaction(chat_id, username, update.message.text)

    mention_user_v2 = user.mention_markdown_v2()
    raw_text_part1 = f"Привет, "
    raw_text_part2_unescaped = (
        f". Я твой кулинарный помощник! Используй кнопки ниже или команды для навигации."
    )
    greeting_text = raw_text_part1 + mention_user_v2 + \
        escape_markdown_v2(raw_text_part2_unescaped)

    await context.bot.send_message(chat_id=chat_id, text=greeting_text, parse_mode='MarkdownV2')
    log_user_interaction(
        chat_id, username, f"Привет, {user.full_name}..." + raw_text_part2_unescaped, is_bot_message=True)
    await show_main_menu(update, context, "Главное меню:")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/help"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    log_user_interaction(chat_id, username, update.message.text)

    help_title_raw = "Справка по боту:"
    help_body_items_raw = [
        "🔍 *Поиск по ингредиентам* (`/findrecipe`): Начните пошаговый поиск, указав ингредиенты, кухню и тип блюда.",
        "🎲 *Случайный рецепт* (`/randomrecipe`): Получите случайный рецепт. Можно добавить название кухни после команды, например: `/randomrecipe italian`.",
        "🍲 *Выбор кухни* (`/cuisines`): Показывает список кухонь. Нажмите на кухню, чтобы получить случайный рецепт.",
        "📊 *Пищевая ценность*: После нахождения рецепта, под ним будет кнопка '📊 БЖУ' для просмотра пищевой ценности. Отдельной команды `/nutrition` больше нет, так как ID теперь не нужно вводить вручную.",
        "❓ *Помощь* (`/help`): Это сообщение.",
        " *Главное меню* (`/menu`): Показать кнопки главного меню.",
        "Отмена: В процессе пошагового поиска используйте команду `/cancel`."
    ]
    escaped_title = escape_markdown_v2(help_title_raw)
    escaped_body_lines = []
    for item in help_body_items_raw:
        parts = item.split('`')
        processed_parts = []
        for i, part in enumerate(parts):
            if i % 2 == 1:
                processed_parts.append(f"`{escape_markdown_v2(part)}`")
            else:  
                sub_parts = part.split('*')
                processed_sub_parts = []
                for j, sub_part in enumerate(sub_parts):
                    if j % 2 == 1:
                        processed_sub_parts.append(
                            f"*{escape_markdown_v2(sub_part)}*")
                    else:
                        processed_sub_parts.append(
                            escape_markdown_v2(sub_part))
                processed_parts.append("".join(processed_sub_parts))
        escaped_body_lines.append("".join(processed_parts))
    escaped_body = "\n".join(escaped_body_lines)

    final_help_text = f"*{escaped_title}*\n{escaped_body}"

    await update.message.reply_text(final_help_text, parse_mode='MarkdownV2', reply_markup=MAIN_MENU_MARKUP)
    log_user_interaction(
        chat_id, username, f"{help_title_raw}\n" + "\n".join(help_body_items_raw), is_bot_message=True)


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/menu"""
    await show_main_menu(update, context, "Главное меню:")


async def random_recipe_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/randomrecipe"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    log_user_interaction(chat_id, username, update.message.text)
    tags = None
    search_tags_msg_raw = "Ищу случайный рецепт..."
    if context.args:
        tags = " ".join(context.args)
        search_tags_msg_raw = f"Ищу случайный рецепт для кухни: {tags}..."

    await update.message.reply_text(escape_markdown_v2(search_tags_msg_raw), parse_mode='MarkdownV2')
    log_user_interaction(
        chat_id, username, search_tags_msg_raw, is_bot_message=True)
    recipes = get_random_recipes(tags=tags, number=1)
    await send_recipes_summary_response(update, context, recipes)


async def cuisines_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/cuisines"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    log_user_interaction(chat_id, username, update.message.text)

    popular_cuisines_list = ["Italian", "Mexican", "Chinese", "Indian", "Japanese",
                             "French", "Thai", "Russian", "Greek", "Spanish"]
    keyboard = []
    row = []
    for cuisine_name in popular_cuisines_list:
        row.append(InlineKeyboardButton(
            cuisine_name, callback_data=f"cuisine_{cuisine_name.lower()}"))
        if len(row) >= 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    msg_text = "Выберите кухню, чтобы увидеть случайный рецепт:"
    await update.message.reply_text(msg_text, reply_markup=reply_markup)
    log_user_interaction(chat_id, username, msg_text, is_bot_message=True)


async def find_recipe_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/findrecipe \n
    запрос ингредиентов и переход на запрос кухни"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    log_user_interaction(
        chat_id, username, update.message.text if update.message else "Button: Find Recipe")
    context.user_data['find_recipe'] = {}
    msg_text = "Введите ингредиенты через запятую (например: курица, рис, помидоры):"
    await context.bot.send_message(chat_id=chat_id, text=msg_text, reply_markup=ReplyKeyboardRemove())
    log_user_interaction(chat_id, username, msg_text, is_bot_message=True)
    return ASK_INGREDIENTS


async def received_ingredients(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """запрос кухни и переход на запрос тип блюда"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    user_input = update.message.text
    log_user_interaction(chat_id, username, user_input)
    context.user_data['find_recipe']['ingredients'] = user_input
    reply_keyboard = [['Пропустить']]
    msg_text = "Укажите кухню (например: italian, chinese) или 'Пропустить'."
    await update.message.reply_text(msg_text, reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
    log_user_interaction(chat_id, username, msg_text, is_bot_message=True)
    return ASK_CUISINE


async def received_cuisine(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """запрос типа блюда и переход к поиску"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    user_input = update.message.text
    log_user_interaction(chat_id, username, user_input)
    if user_input.lower() != 'пропустить':
        context.user_data['find_recipe']['cuisine'] = user_input
    else:
        context.user_data['find_recipe']['cuisine'] = None
    reply_keyboard = [['Пропустить']]
    msg_text = "Укажите тип блюда (например: main course, salad, dessert) или 'Пропустить'."
    await update.message.reply_text(msg_text, reply_markup=ReplyKeyboardMarkup(reply_keyboard, one_time_keyboard=True, resize_keyboard=True))
    log_user_interaction(chat_id, username, msg_text, is_bot_message=True)
    return ASK_MEAL_TYPE


async def received_meal_type_and_search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """переход к поиску на основе запросов"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    user_input = update.message.text
    log_user_interaction(chat_id, username, user_input)
    if user_input.lower() != 'пропустить':
        context.user_data['find_recipe']['meal_type'] = user_input
    else:
        context.user_data['find_recipe']['meal_type'] = None
    await perform_search(update, context)
    return ConversationHandler.END


async def perform_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """поиск по запросам"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    search_params = context.user_data.get('find_recipe', {})
    loading_msg = "Ищу рецепты по вашим критериям..."
    await context.bot.send_message(chat_id=chat_id, text=loading_msg, reply_markup=MAIN_MENU_MARKUP)
    log_user_interaction(chat_id, username, loading_msg, is_bot_message=True)
    recipes = search_recipes_complex(ingredients=search_params.get('ingredients'), cuisine=search_params.get(
        'cuisine'), meal_type=search_params.get('meal_type'), number=5)
    await send_recipes_summary_response(update, context, recipes)
    context.user_data.pop('find_recipe', None)


async def cancel_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """/cancel"""
    chat_id = update.effective_chat.id
    username = update.effective_user.username or update.effective_user.first_name
    log_user_interaction(chat_id, username, update.message.text)
    context.user_data.pop('find_recipe', None)
    msg_text = "Поиск отменен."
    await update.message.reply_text(msg_text, reply_markup=MAIN_MENU_MARKUP)
    log_user_interaction(chat_id, username, msg_text, is_bot_message=True)
    return ConversationHandler.END


async def recipe_details_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """обработчик кнопки подбробнее о рецепте"""
    query = update.callback_query
    chat_id = query.message.chat_id
    username = query.from_user.username or query.from_user.first_name
    context.user_data['callback_username'] = username

    try:
        await query.answer()
    except BadRequest as e:
        if "Query is too old" in str(e) or "query id is invalid" in str(e):
            logger.warning(f"Details cb (data: {query.data}) old/invalid: {e}")
            return
        logger.error(
            f"BadRequest on details cb (data: {query.data}): {e}", exc_info=True)
        return
    except Exception as e:
        logger.error(
            f"Error on query.answer() for details cb (data: {query.data}): {e}", exc_info=True)
        return

    log_user_interaction(chat_id, username, f"Callback: {query.data}")
    recipe_id_str = query.data.split('_')[1]

    loading_msg_raw = "Загружаю детали рецепта..."
    await context.bot.send_message(chat_id=chat_id, text=loading_msg_raw)
    log_user_interaction(
        chat_id, username, loading_msg_raw, is_bot_message=True)

    recipe_details_data = get_recipe_information_plain(recipe_id_str)

    if recipe_details_data:
        message_text_plain = recipe_details_data['text']
        image_url = recipe_details_data['image_url']
        source_url = recipe_details_data['source_url']
        buttons = []
        if source_url:
            buttons.append(InlineKeyboardButton(
                "🔗 Источник рецепта", url=source_url))
        reply_markup = InlineKeyboardMarkup([buttons]) if buttons else None

        log_msg_details = message_text_plain
        if image_url:
            try:
                await context.bot.send_photo(chat_id=chat_id, photo=image_url, caption=message_text_plain, reply_markup=reply_markup)
                log_msg_details = f"[PHOTO] {message_text_plain}"
            except Exception as e_photo:
                logger.error(
                    f"Error sending photo details ID {recipe_id_str}: {e_photo}", exc_info=True)
                try:
                    await context.bot.send_message(chat_id=chat_id, text=message_text_plain, reply_markup=reply_markup)
                except Exception as e_text:
                    logger.error(
                        f"Error sending text details fallback ID {recipe_id_str}: {e_text}", exc_info=True)
        else:
            try:
                await context.bot.send_message(chat_id=chat_id, text=message_text_plain, reply_markup=reply_markup)
            except Exception as e_text_no_img:
                logger.error(
                    f"Error sending text details (no img) ID {recipe_id_str}: {e_text_no_img}", exc_info=True)
        log_user_interaction(
            chat_id, username, log_msg_details, is_bot_message=True)
    else:
        err_msg_raw = "Не удалось загрузить детали рецепта."
        await context.bot.send_message(chat_id=chat_id, text=err_msg_raw)
        log_user_interaction(
            chat_id, username, err_msg_raw, is_bot_message=True)


async def cuisine_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """обработчик кнопки выбора кухни"""
    query = update.callback_query
    chat_id = query.message.chat_id
    username = query.from_user.username or query.from_user.first_name
    context.user_data['callback_username'] = username

    try:
        await query.answer()
    except BadRequest as e:
        if "Query is too old" in str(e) or "query id is invalid" in str(e):
            logger.warning(f"Cuisine cb (data: {query.data}) old/invalid: {e}")
            return
        logger.error(
            f"BadRequest on cuisine cb (data: {query.data}): {e}", exc_info=True)
        return
    except Exception as e:
        logger.error(
            f"Error on query.answer() for cuisine cb (data: {query.data}): {e}", exc_info=True)
        return

    cuisine_tag = query.data.split('_')[1]
    log_user_interaction(
        chat_id, username, f"Cuisine button pressed: {cuisine_tag}")

    search_msg_raw = f"Ищу случайный рецепт для кухни: {cuisine_tag.capitalize()}..."
    await context.bot.send_message(chat_id=chat_id, text=escape_markdown_v2(search_msg_raw), parse_mode='MarkdownV2')
    log_user_interaction(
        chat_id, username, search_msg_raw, is_bot_message=True)

    recipes = get_random_recipes(tags=cuisine_tag, number=1)
    await send_recipes_summary_response(query.message, context, recipes)


async def nutrition_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """обработчик к.б.ж.у."""
    query = update.callback_query
    chat_id = query.message.chat_id
    username = query.from_user.username or query.from_user.first_name
    context.user_data['callback_username'] = username

    try:
        await query.answer()
    except BadRequest as e:
        if "Query is too old" in str(e) or "query id is invalid" in str(e):
            logger.warning(
                f"Nutrition cb (data: {query.data}) old/invalid: {e}")
            return
        logger.error(
            f"BadRequest on nutrition cb (data: {query.data}): {e}", exc_info=True)
        return
    except Exception as e:
        logger.error(
            f"Error on query.answer() for nutrition cb (data: {query.data}): {e}", exc_info=True)
        return

    log_user_interaction(chat_id, username, f"Callback: {query.data}")
    recipe_id_str = query.data.split('_')[1]

    loading_msg_raw = f"Запрашиваю пищевую ценность для рецепта ID {recipe_id_str}..."
    await context.bot.send_message(chat_id=chat_id, text=escape_markdown_v2(loading_msg_raw), parse_mode='MarkdownV2')
    log_user_interaction(
        chat_id, username, loading_msg_raw, is_bot_message=True)

    nutrition_info_md = get_recipe_nutrition_info_markdown_v2(
        recipe_id_str)

    await context.bot.send_message(chat_id=chat_id, text=nutrition_info_md, parse_mode='MarkdownV2')
    log_user_interaction(chat_id, username, nutrition_info_md,
                         is_bot_message=True)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """обработчик ошибок"""
    logger.error(f"Exception while handling an update:",
                 exc_info=context.error)
    if update and hasattr(update, 'effective_chat') and update.effective_chat:
        chat_id = update.effective_chat.id
        error_message_raw = "Извините, произошла непредвиденная ошибка. Попробуйте позже."
        if isinstance(context.error, BadRequest) and "Can't parse entities" in str(context.error):
            error_message_raw = "Произошла ошибка при форматировании сообщения. Пожалуйста, попробуйте еще раз."
        try:
            await context.bot.send_message(chat_id=chat_id, text=error_message_raw)
            log_user_interaction(chat_id, "BOT_ERROR_HANDLER",
                                 error_message_raw, is_bot_message=True)
        except Exception as e_send_err:
            logger.error(
                f"Failed to send error message from global handler to {chat_id}: {e_send_err}", exc_info=True)



def main() -> None:
    """запуск"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
    application.add_error_handler(error_handler)

    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("randomrecipe", random_recipe_command_handler))
    application.add_handler(CommandHandler("cuisines", cuisines_command_handler))

    application.add_handler(MessageHandler(filters.Regex("^🎲 Случайный рецепт$"), random_recipe_command_handler))
    application.add_handler(MessageHandler(filters.Regex("^🍲 Выбор кухни$"), cuisines_command_handler))
    application.add_handler(MessageHandler(filters.Regex("^❓ Помощь$"), help_command))

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('findrecipe', find_recipe_start),
            MessageHandler(filters.Regex("^🔍 Поиск по ингредиентам$"), find_recipe_start)
        ],
        states={
            ASK_INGREDIENTS: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_ingredients)],
            ASK_CUISINE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_cuisine)],
            ASK_MEAL_TYPE: [MessageHandler(filters.TEXT & ~filters.COMMAND, received_meal_type_and_search)],
        },
        fallbacks=[CommandHandler('cancel', cancel_conversation)],
    )
    application.add_handler(conv_handler) 

    application.add_handler(CallbackQueryHandler(recipe_details_callback, pattern='^details_'))
    application.add_handler(CallbackQueryHandler(cuisine_button_callback, pattern='^cuisine_'))
    application.add_handler(CallbackQueryHandler(nutrition_callback, pattern='^nutrition_'))

    async def log_unhandled_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if update.message and update.message.text:
            all_menu_buttons = [item for sublist in MAIN_MENU_KEYBOARD for item in sublist]
            if update.message.text not in all_menu_buttons:
                chat_id = update.effective_chat.id
                username = update.effective_user.username or update.effective_user.first_name
                log_user_interaction(chat_id, username, f"Unhandled text: {update.message.text}") 

    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, log_unhandled_text), group=1)

    logger.info("Бот запущен и готов к работе!")
    application.run_polling()
    
if __name__ == '__main__':
    main()