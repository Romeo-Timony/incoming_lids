import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot
from aiogram.types import Update

logger = logging.getLogger(__name__)

OPERATOR_CHAT_FILE = Path(os.environ.get("OPERATOR_CHAT_FILE", ".operator_chat_id"))


class OperatorChatRegistry:
    """Stores where @massagebot2_bot should deliver completed applications."""

    def __init__(self, initial_chat_id: int | None = None) -> None:
        self._chat_id = initial_chat_id or self._load_from_disk()

    @property
    def chat_id(self) -> int | None:
        return self._chat_id

    def set_chat_id(self, chat_id: int) -> None:
        self._chat_id = chat_id
        OPERATOR_CHAT_FILE.write_text(str(chat_id), encoding="utf-8")
        logger.info("Operator chat registered: %s", chat_id)

    @staticmethod
    def _load_from_disk() -> int | None:
        if not OPERATOR_CHAT_FILE.exists():
            return None
        raw = OPERATOR_CHAT_FILE.read_text(encoding="utf-8").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            logger.warning("Invalid operator chat id in %s", OPERATOR_CHAT_FILE)
            return None


class OperatorInboxListener:
    """Listens to the operator bot so an admin can register via /start."""

    def __init__(self, bot: Bot, registry: OperatorChatRegistry) -> None:
        self._bot = bot
        self._registry = registry
        self._offset: int | None = None
        self._task: asyncio.Task | None = None
        self._stopped = asyncio.Event()

    def start(self) -> None:
        if self._task is None:
            self._stopped.clear()
            self._task = asyncio.create_task(self._run(), name="operator-inbox-listener")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        logger.info(
            "Operator inbox listener started. Write /start to the operator bot to receive applications."
        )
        while not self._stopped.is_set():
            try:
                updates = await self._bot.get_updates(
                    offset=self._offset,
                    timeout=25,
                    allowed_updates=["message"],
                )
                for update in updates:
                    self._offset = update.update_id + 1
                    await self._handle_update(update)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Operator inbox listener failed; retrying")
                await asyncio.sleep(3)

    async def _handle_update(self, update: Update) -> None:
        message = update.message
        if message is None or message.from_user is None:
            return

        text = (message.text or "").strip().lower()
        chat_id = message.chat.id
        self._registry.set_chat_id(chat_id)

        if text.startswith("/start"):
            await self._bot.send_message(
                chat_id,
                "Готово. Сюда будут приходить заполненные анкеты клиентов на массаж.",
            )
        else:
            await self._bot.send_message(
                chat_id,
                "Этот бот принимает готовые заявки. Напишите /start, чтобы закрепить чат для уведомлений.",
            )
