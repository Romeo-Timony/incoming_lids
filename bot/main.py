import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties

from bot.handlers import router
from core import get_settings, setup_logging
from services import SupportWorkflowService
from services.assistant import OpenAISupportAssistant
from services.storage import InMemorySessionRepository
from services.telegram import OperatorNotifier
from services.telegram.operator_inbox import OperatorChatRegistry, OperatorInboxListener

logger = logging.getLogger(__name__)


async def run_bot() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    client_bot = Bot(token=settings.telegram_bot_token, default=DefaultBotProperties())
    operator_bot = Bot(token=settings.operator_bot_token, default=DefaultBotProperties())

    registry = OperatorChatRegistry(initial_chat_id=settings.operator_chat_id)
    inbox_listener = OperatorInboxListener(operator_bot, registry)

    session_repository = InMemorySessionRepository()
    assistant = OpenAISupportAssistant(settings)
    notifier = OperatorNotifier(operator_bot, settings, registry)
    workflow = SupportWorkflowService(assistant=assistant, notifier=notifier)

    dp = Dispatcher()
    dp.include_router(router)
    dp["session_repository"] = session_repository
    dp["workflow"] = workflow

    if registry.chat_id:
        logger.info("Operator chat already set: %s", registry.chat_id)
    else:
        logger.warning(
            "Operator chat is not set yet. Open @massagebot2_bot and send /start."
        )

    logger.info("Starting massage booking survey bot (@massagebot1_bot)")
    inbox_listener.start()
    try:
        await dp.start_polling(client_bot)
    finally:
        await inbox_listener.stop()
        await workflow.close()
        await client_bot.session.close()
        await operator_bot.session.close()
