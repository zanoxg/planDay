import sqlite3
import logging
from datetime import datetime, time, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    ConversationHandler,
    MessageHandler,
    filters,
    ContextTypes
)

# Настройка логгирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Константы состояний
DATE, TASK, EDIT, DELETE, NEW_TEXT, VIEW_DATE = range(6)


# Подключение к базе данных
def init_db():
    try:
        conn = sqlite3.connect('planner.db')
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                task TEXT,
                completed INTEGER DEFAULT 0
            )
        ''')
        conn.commit()
        conn.close()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Error initializing database: {e}")


init_db()


# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        user = update.message.from_user

        # Улучшенная проверка доступности job_queue
        if hasattr(context, 'job_queue') and context.job_queue is not None:
            # Проверяем наличие существующей задачи
            job_exists = any(job.name == str(user.id) for job in context.job_queue.jobs())

            if not job_exists:
                context.job_queue.run_daily(
                    send_daily_reminder,
                    time(hour=7, minute=0, second=0, tzinfo=None),
                    context=user.id,
                    name=str(user.id)
                )
                logger.info(f"Added daily reminder for user {user.id}")
        else:
            logger.warning("Job queue is not available - reminders disabled")

        await update.message.reply_text(
            "📅 Привет! Я твой умный планировщик задач.\n\n"
            "Доступные команды:\n"
            "/add - Добавить задачу\n"
            "/list - Показать задачи\n"
            "/edit - Редактировать задачу\n"
            "/delete - Удалить задачу\n"
            "/done - Отметить выполненной\n"
            "\nЯ буду присылать тебе ежедневные напоминания в 7:00 утра!"
        )
    except Exception as e:
        logger.error(f"Error in start command: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка. Попробуйте позже.")


# Отправка ежедневного напоминания
async def send_daily_reminder(context: ContextTypes.DEFAULT_TYPE):
    try:
        user_id = context.job.context
        today = datetime.now().strftime("%Y-%m-%d")

        conn = sqlite3.connect('planner.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT task FROM tasks WHERE user_id = ? AND date = ? AND completed = 0",
            (user_id, today)
        )
        tasks = cursor.fetchall()
        conn.close()

        if tasks:
            tasks_text = "\n".join([f"• {task[0]}" for task in tasks])
            await context.bot.send_message(
                chat_id=user_id,
                text=f"🌞 Доброе утро! Вот твои задачи на сегодня:\n\n{tasks_text}"
            )
        else:
            await context.bot.send_message(
                chat_id=user_id,
                text="🌞 Доброе утро! На сегодня задач нет, отличный день для отдыха!"
            )
    except Exception as e:
        logger.error(f"Error sending daily reminder: {e}")


# Добавление задачи
async def add_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.message.reply_text("📅 Введите дату в формате ГГГГ-ММ-ДД:")
        return DATE
    except Exception as e:
        logger.error(f"Error in add_task: {e}")
        return ConversationHandler.END


async def get_date(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        date_str = update.message.text
        datetime.strptime(date_str, "%Y-%m-%d")
        context.user_data['date'] = date_str
        await update.message.reply_text("✏️ Введите описание задачи:")
        return TASK
    except ValueError:
        await update.message.reply_text("❌ Неверный формат даты! Попробуйте снова (ГГГГ-ММ-ДД):")
        return DATE
    except Exception as e:
        logger.error(f"Error in get_date: {e}")
        return ConversationHandler.END


async def get_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        task_text = update.message.text
        user_id = update.message.from_user.id
        date = context.user_data['date']

        conn = sqlite3.connect('planner.db')
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO tasks (user_id, date, task) VALUES (?, ?, ?)",
            (user_id, date, task_text)
        )
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ Задача добавлена на {date}!")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in get_task: {e}")
        await update.message.reply_text("❌ Ошибка при добавлении задачи.")
        return ConversationHandler.END


# Просмотр задач с инлайн-клавиатурой
async def list_tasks(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        args = context.args
        if args and len(args) > 0:
            date = args[0]
        else:
            date = datetime.now().strftime("%Y-%m-%d")

        user_id = update.message.from_user.id

        conn = sqlite3.connect('planner.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, task, completed FROM tasks WHERE user_id = ? AND date = ?",
            (user_id, date)
        )
        tasks = cursor.fetchall()
        conn.close()

        if not tasks:
            await update.message.reply_text(f"🤷‍♂️ На {date} задач нет!")
            return

        keyboard = []
        response = f"📝 Задачи на {date}:\n\n"

        for task_id, task_text, completed in tasks:
            status = "✅" if completed else "🟩"
            response += f"{task_id}. [{status}] {task_text}\n"

            # Создаем кнопки для каждой задачи
            keyboard.append([
                InlineKeyboardButton(f"{task_id}. {task_text[:15]}...", callback_data=f"view_{task_id}")
            ])

        # Кнопки управления
        prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        next_date = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        keyboard.append([
            InlineKeyboardButton("◀️ Пред. день", callback_data=f"prev_{prev_date}"),
            InlineKeyboardButton("▶️ След. день", callback_data=f"next_{next_date}")
        ])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(response, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in list_tasks: {e}")
        await update.message.reply_text("⚠️ Произошла ошибка при получении задач.")


# Обработка инлайн-кнопок
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    try:
        query = update.callback_query
        await query.answer()
        data = query.data
        user_id = query.from_user.id

        # Просмотр задачи
        if data.startswith("view_"):
            task_id = data.split("_")[1]

            conn = sqlite3.connect('planner.db')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT date, task, completed FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id)
            )
            task = cursor.fetchone()
            conn.close()

            if task:
                date, task_text, completed = task
                status = "✅ Выполнена" if completed else "🟩 В процессе"

                keyboard = [
                    [InlineKeyboardButton("✅ Выполнить", callback_data=f"done_{task_id}")],
                    [InlineKeyboardButton("✏️ Редактировать", callback_data=f"edit_{task_id}")],
                    [InlineKeyboardButton("❌ Удалить", callback_data=f"delete_{task_id}")],
                    [InlineKeyboardButton("🔙 Назад к задачам", callback_data=f"back_{date}")]
                ]

                reply_markup = InlineKeyboardMarkup(keyboard)
                await query.edit_message_text(
                    text=f"📝 Задача #{task_id}\n\n"
                         f"🗓 Дата: {date}\n"
                         f"📌 Описание: {task_text}\n"
                         f"🔰 Статус: {status}",
                    reply_markup=reply_markup
                )

        # Отметка выполнения
        elif data.startswith("done_"):
            task_id = data.split("_")[1]

            conn = sqlite3.connect('planner.db')
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE tasks SET completed = 1 WHERE id = ? AND user_id = ?",
                (task_id, user_id)
            )
            conn.commit()
            conn.close()

            await query.edit_message_text(f"✅ Задача #{task_id} отмечена выполненной!")

        # Начало редактирования
        elif data.startswith("edit_"):
            task_id = data.split("_")[1]
            context.user_data['edit_id'] = task_id
            await query.edit_message_text(f"✏️ Введите новый текст для задачи #{task_id}:")
            return NEW_TEXT

        # Удаление задачи
        elif data.startswith("delete_"):
            task_id = data.split("_")[1]

            conn = sqlite3.connect('planner.db')
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM tasks WHERE id = ? AND user_id = ?",
                (task_id, user_id)
            )
            conn.commit()
            conn.close()

            await query.edit_message_text(f"❌ Задача #{task_id} удалена!")

        # Навигация по дням
        elif data.startswith("prev_") or data.startswith("next_"):
            new_date = data.split("_")[1]

            conn = sqlite3.connect('planner.db')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, task, completed FROM tasks WHERE user_id = ? AND date = ?",
                (user_id, new_date)
            )
            tasks = cursor.fetchall()
            conn.close()

            if not tasks:
                await query.edit_message_text(f"🤷‍♂️ На {new_date} задач нет!")
                return

            keyboard = []
            response = f"📝 Задачи на {new_date}:\n\n"

            for task_id, task_text, completed in tasks:
                status = "✅" if completed else "🟩"
                response += f"{task_id}. [{status}] {task_text}\n"

                keyboard.append([
                    InlineKeyboardButton(f"{task_id}. {task_text[:15]}...", callback_data=f"view_{task_id}")
                ])

            prev_date = (datetime.strptime(new_date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            next_date = (datetime.strptime(new_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

            keyboard.append([
                InlineKeyboardButton("◀️ Пред. день", callback_data=f"prev_{prev_date}"),
                InlineKeyboardButton("▶️ След. день", callback_data=f"next_{next_date}")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(response, reply_markup=reply_markup)

        # Возврат к списку задач
        elif data.startswith("back_"):
            date = data.split("_")[1]

            conn = sqlite3.connect('planner.db')
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, task, completed FROM tasks WHERE user_id = ? AND date = ?",
                (user_id, date)
            )
            tasks = cursor.fetchall()
            conn.close()

            keyboard = []
            response = f"📝 Задачи на {date}:\n\n"

            for task_id, task_text, completed in tasks:
                status = "✅" if completed else "🟩"
                response += f"{task_id}. [{status}] {task_text}\n"

                keyboard.append([
                    InlineKeyboardButton(f"{task_id}. {task_text[:15]}...", callback_data=f"view_{task_id}")
                ])

            prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
            next_date = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

            keyboard.append([
                InlineKeyboardButton("◀️ Пред. день", callback_data=f"prev_{prev_date}"),
                InlineKeyboardButton("▶️ След. день", callback_data=f"next_{next_date}")
            ])

            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.edit_message_text(response, reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error in button_handler: {e}")
        try:
            await query.edit_message_text("⚠️ Произошла ошибка при обработке запроса.")
        except:
            pass


# Редактирование задачи
async def edit_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.message.reply_text("✏️ Введите ID задачи для редактирования:")
        return EDIT
    except Exception as e:
        logger.error(f"Error in edit_task: {e}")
        return ConversationHandler.END


async def get_edit_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        task_id = int(update.message.text)
        context.user_data['edit_id'] = task_id
        await update.message.reply_text("📝 Введите новый текст задачи:")
        return NEW_TEXT
    except ValueError:
        await update.message.reply_text("❌ Неверный ID! Введите число:")
        return EDIT
    except Exception as e:
        logger.error(f"Error in get_edit_id: {e}")
        return ConversationHandler.END


async def get_new_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        new_text = update.message.text
        task_id = context.user_data['edit_id']
        user_id = update.message.from_user.id

        conn = sqlite3.connect('planner.db')
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE tasks SET task = ? WHERE id = ? AND user_id = ?",
            (new_text, task_id, user_id)
        )
        conn.commit()

        # Получаем дату для возврата
        cursor.execute(
            "SELECT date FROM tasks WHERE id = ?",
            (task_id,)
        )
        task_date = cursor.fetchone()[0]
        conn.close()

        await update.message.reply_text("✅ Задача обновлена!")

        # Показываем обновленный список
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📝 Задачи на {task_date}:",
            reply_markup=get_tasks_keyboard(user_id, task_date)
        )

        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in get_new_text: {e}")
        await update.message.reply_text("❌ Ошибка при обновлении задачи.")
        return ConversationHandler.END


# Удаление задачи
async def delete_task(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.message.reply_text("❌ Введите ID задачи для удаления:")
        return DELETE
    except Exception as e:
        logger.error(f"Error in delete_task: {e}")
        return ConversationHandler.END


async def confirm_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        task_id = int(update.message.text)
        user_id = update.message.from_user.id

        conn = sqlite3.connect('planner.db')
        cursor = conn.cursor()

        # Получаем дату перед удалением
        cursor.execute(
            "SELECT date FROM tasks WHERE id = ?",
            (task_id,)
        )
        task_date = cursor.fetchone()[0]

        cursor.execute(
            "DELETE FROM tasks WHERE id = ? AND user_id = ?",
            (task_id, user_id)
        )
        conn.commit()
        conn.close()

        await update.message.reply_text(f"✅ Задача {task_id} удалена!")

        # Показываем обновленный список
        await context.bot.send_message(
            chat_id=user_id,
            text=f"📝 Задачи на {task_date}:",
            reply_markup=get_tasks_keyboard(user_id, task_date)
        )

        return ConversationHandler.END
    except (ValueError, TypeError):
        await update.message.reply_text("❌ Неверный ID! Введите число:")
        return DELETE
    except Exception as e:
        logger.error(f"Error in confirm_delete: {e}")
        await update.message.reply_text("❌ Ошибка при удалении задачи.")
        return ConversationHandler.END


# Генератор клавиатуры для задач
def get_tasks_keyboard(user_id: int, date: str) -> InlineKeyboardMarkup:
    try:
        conn = sqlite3.connect('planner.db')
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, task, completed FROM tasks WHERE user_id = ? AND date = ?",
            (user_id, date)
        )
        tasks = cursor.fetchall()
        conn.close()

        keyboard = []
        for task_id, task_text, completed in tasks:
            keyboard.append([
                InlineKeyboardButton(f"{task_id}. {task_text[:15]}...", callback_data=f"view_{task_id}")
            ])

        prev_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        next_date = (datetime.strptime(date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")

        keyboard.append([
            InlineKeyboardButton("◀️ Пред. день", callback_data=f"prev_{prev_date}"),
            InlineKeyboardButton("▶️ След. день", callback_data=f"next_{next_date}")
        ])

        return InlineKeyboardMarkup(keyboard)
    except Exception as e:
        logger.error(f"Error in get_tasks_keyboard: {e}")
        return InlineKeyboardMarkup([])


# Отмена операций
async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        await update.message.reply_text("❌ Операция отменена")
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Error in cancel: {e}")
        return ConversationHandler.END


def main() -> None:
    try:
        logger.info("Starting bot...")
        # Создаем приложение с помощью ApplicationBuilder
        application = ApplicationBuilder() \
            .token("7969788951:AAHBlSslGj2vecmP8n7Apz-bC8nNmyfgZQU") \
            .build()

        # Обработчики команд
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("list", list_tasks))

        # Обработчик инлайн-кнопок
        application.add_handler(CallbackQueryHandler(button_handler))

        # Диалог добавления задачи
        add_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('add', add_task)],
            states={
                DATE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_date)],
                TASK: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_task)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        application.add_handler(add_conv_handler)

        # Диалог редактирования
        edit_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('edit', edit_task)],
            states={
                EDIT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_edit_id)],
                NEW_TEXT: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_text)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        application.add_handler(edit_conv_handler)

        # Диалог удаления
        del_conv_handler = ConversationHandler(
            entry_points=[CommandHandler('delete', delete_task)],
            states={
                DELETE: [MessageHandler(filters.TEXT & ~filters.COMMAND, confirm_delete)]
            },
            fallbacks=[CommandHandler('cancel', cancel)]
        )
        application.add_handler(del_conv_handler)

        # Запуск бота
        logger.info("Bot is running...")
        application.run_polling()
    except Exception as e:
        logger.critical(f"Critical error in main: {e}")


if __name__ == '__main__':
    main()