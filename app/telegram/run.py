"""
Telegram Bot Long-Polling Runner for KrishiVaani — Phase 8.3.

Entry point:
    python -m app.telegram.run

Runs python-telegram-bot in asynchronous long-polling mode (no webhook, no public tunnel required).
Requires TELEGRAM_BOT_TOKEN configured in environment / settings.
"""

import sys
import logging
from telegram.ext import Application, CommandHandler, MessageHandler, filters

from app.core.config import settings
from app.telegram.handlers import TelegramHandler

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger("app.telegram")


def build_telegram_application(token: str, handler: TelegramHandler | None = None) -> Application:
    """Build and configure the Telegram Application instance."""
    bot_handler = handler or TelegramHandler()
    application = Application.builder().token(token).build()

    # Register handlers
    application.add_handler(CommandHandler("start", bot_handler.handle_start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot_handler.handle_text))
    application.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, bot_handler.handle_voice))
    application.add_error_handler(bot_handler.handle_error)

    return application


def main() -> None:
    """Entry point for python -m app.telegram.run."""
    token = getattr(settings, "telegram_bot_token", None)
    if not token or not str(token).strip():
        print(
            "Error: TELEGRAM_BOT_TOKEN is not configured in settings or environment.\n"
            "Please configure TELEGRAM_BOT_TOKEN in your environment or .env file to run the Telegram bot.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Ensure database and persistent tables are initialized on startup
    try:
        from app.db.database import ensure_database_initialized, init_db
        ensure_database_initialized()
        init_db()
        logger.info("Database and schema verified successfully.")
    except Exception as db_err:
        logger.warning("Database startup initialization check notice: %s", db_err)

    logger.info("Starting KrishiVaani Telegram bot polling...")
    app = build_telegram_application(token)
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

