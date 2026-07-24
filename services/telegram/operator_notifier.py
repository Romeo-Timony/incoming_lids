from aiogram import Bot

from core import Settings, SupportSession
from services.telegram.operator_inbox import OperatorChatRegistry


class OperatorNotifier:
    def __init__(
        self,
        bot: Bot,
        settings: Settings,
        registry: OperatorChatRegistry,
    ) -> None:
        self._bot = bot
        self._settings = settings
        self._registry = registry

    async def send_ticket(self, session: SupportSession) -> None:
        chat_id = self._registry.chat_id
        if chat_id is None:
            raise RuntimeError(
                "Operator chat is not registered. Open @massagebot2_bot and send /start."
            )

        ticket = session.ticket
        lines = [
            "=== НОВАЯ ЗАЯВКА НА МАССАЖ ===",
            "",
            f"Имя: {ticket.name}",
            f"Контакт: {ticket.contact}",
            "",
            "Жалоба на здоровье:",
            f"{ticket.health_complaint}",
            "",
            f"Где болит: {ticket.pain_location}",
            f"Сила боли: {ticket.pain_intensity}",
            f"Как давно беспокоит: {ticket.pain_duration}",
            f"Желаемое время записи: {ticket.preferred_time}",
            "",
            f"Telegram user id: {session.user_id}",
            f"Telegram username: @{session.telegram_username}" if session.telegram_username else "Telegram username: -",
            "",
            "=== КОНЕЦ ===",
        ]
        await self._bot.send_message(chat_id, "\n".join(lines))
