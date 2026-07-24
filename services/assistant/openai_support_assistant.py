import asyncio
import json
import logging
import re

import httpx

from core import AssistantTurn, Settings, SupportTicket
from core.schemas import DialogueMessage
from services.assistant.prompts import ASSISTANT_RESPONSE_SCHEMA, SUPPORT_ASSISTANT_PROMPT

logger = logging.getLogger(__name__)

RETRYABLE_STATUS_CODES = {408, 409, 429, 500, 502, 503, 504}


class OpenAISupportAssistant:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.openai_base_url,
            timeout=httpx.Timeout(45.0, connect=12.0),
            headers={
                "Authorization": f"Bearer {settings.openai_api_key}",
                "Content-Type": "application/json",
            },
        )

    async def generate_turn(
        self,
        current_ticket: SupportTicket,
        user_message: str,
        is_new_session: bool,
        conversation_history: list[DialogueMessage],
        last_assistant_message: str | None,
        telegram_first_name: str | None,
    ) -> AssistantTurn:
        payload = {
            "model": self._settings.openai_model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": SUPPORT_ASSISTANT_PROMPT},
                {
                    "role": "user",
                    "content": self._build_user_prompt(
                        current_ticket=current_ticket,
                        user_message=user_message,
                        is_new_session=is_new_session,
                        conversation_history=conversation_history,
                        last_assistant_message=last_assistant_message,
                        telegram_first_name=telegram_first_name,
                    ),
                },
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": ASSISTANT_RESPONSE_SCHEMA,
            },
        }

        try:
            response = await self._post_with_retries(payload)
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return AssistantTurn.model_validate(json.loads(content))
        except Exception:
            logger.exception("Falling back to local massage booking turn generation")
            return self._build_fallback_turn(
                current_ticket=current_ticket,
                user_message=user_message,
                is_new_session=is_new_session,
                conversation_history=conversation_history,
                last_assistant_message=last_assistant_message,
                telegram_first_name=telegram_first_name,
            )

    async def close(self) -> None:
        await self._client.aclose()

    async def _post_with_retries(self, payload: dict) -> httpx.Response:
        last_error: Exception | None = None

        for attempt in range(1, 4):
            try:
                response = await self._client.post("/chat/completions", json=payload)
                if response.status_code in RETRYABLE_STATUS_CODES:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except httpx.HTTPStatusError as exc:
                last_error = exc
                status_code = exc.response.status_code
                if status_code not in RETRYABLE_STATUS_CODES or attempt == 3:
                    raise
            except httpx.RequestError as exc:
                last_error = exc
                if attempt == 3:
                    break

            await asyncio.sleep(0.75 * attempt)

        assert last_error is not None
        raise last_error

    @staticmethod
    def _build_user_prompt(
        current_ticket: SupportTicket,
        user_message: str,
        is_new_session: bool,
        conversation_history: list[DialogueMessage],
        last_assistant_message: str | None,
        telegram_first_name: str | None,
    ) -> str:
        ticket_json = json.dumps(current_ticket.model_dump(), ensure_ascii=False, indent=2)
        history_json = json.dumps(
            [message.model_dump() for message in conversation_history],
            ensure_ascii=False,
            indent=2,
        )
        first_name = telegram_first_name or "null"
        last_bot_message = last_assistant_message or "null"

        return (
            f"is_new_session: {str(is_new_session).lower()}\n"
            f"telegram_first_name: {first_name}\n"
            f"current_ticket:\n{ticket_json}\n\n"
            f"conversation_history:\n{history_json}\n\n"
            f"last_assistant_message:\n{last_bot_message}\n\n"
            f"latest_user_message:\n{user_message}"
        )

    def _build_fallback_turn(
        self,
        current_ticket: SupportTicket,
        user_message: str,
        is_new_session: bool,
        conversation_history: list[DialogueMessage],
        last_assistant_message: str | None,
        telegram_first_name: str | None,
    ) -> AssistantTurn:
        message = self._normalize_text(user_message)
        message_lower = message.lower()
        extracted = SupportTicket()
        requested_field = self._detect_requested_field(last_assistant_message)

        if self._is_repeat_question_request(message_lower):
            repeated_question = last_assistant_message or "Пока мы не дошли до следующего вопроса."
            return AssistantTurn(
                reply=f"Последний мой вопрос был таким: {repeated_question}",
                extracted_ticket=extracted,
                ready_to_submit=current_ticket.is_complete(),
            )

        if not current_ticket.name and self._looks_like_name(message):
            extracted.name = message

        if not current_ticket.contact:
            contact = self._extract_contact(message)
            if contact:
                extracted.contact = contact

        if requested_field == "name" and not extracted.name and self._looks_like_name(message):
            extracted.name = message
        elif requested_field == "contact" and not extracted.contact:
            extracted.contact = self._extract_contact(message) or message
        elif requested_field == "pain_intensity":
            extracted.pain_intensity = self._extract_pain_intensity(message_lower)
        elif requested_field == "pain_duration" and self._looks_like_time_answer(message_lower):
            extracted.pain_duration = message
        elif requested_field == "pain_location":
            extracted.pain_location = self._extract_pain_location(message) or message
        elif requested_field == "preferred_time":
            extracted.preferred_time = message
        elif requested_field == "health_complaint":
            extracted.health_complaint = self._extract_complaint(message, current_ticket)

        if (
            not extracted.health_complaint
            and not current_ticket.health_complaint
            and not self._looks_like_name(message)
            and not self._extract_contact(message)
        ):
            if self._looks_like_complaint(message_lower):
                extracted.health_complaint = self._extract_complaint(message, current_ticket)

        if not extracted.pain_location and not current_ticket.pain_location:
            extracted.pain_location = self._extract_pain_location(message)

        if not extracted.pain_intensity and not current_ticket.pain_intensity:
            extracted.pain_intensity = self._extract_pain_intensity(message_lower)

        if (
            not extracted.pain_duration
            and not current_ticket.pain_duration
            and self._looks_like_time_answer(message_lower)
        ):
            extracted.pain_duration = message

        if (
            not extracted.preferred_time
            and not current_ticket.preferred_time
            and self._looks_like_booking_time(message_lower)
        ):
            extracted.preferred_time = message

        merged_ticket = current_ticket.model_copy(deep=True)
        merged_ticket.merge(extracted)

        reply = self._build_fallback_reply(
            merged_ticket=merged_ticket,
            extracted=extracted,
            is_new_session=is_new_session,
            conversation_history=conversation_history,
            telegram_first_name=telegram_first_name,
        )

        return AssistantTurn(
            reply=reply,
            extracted_ticket=extracted,
            ready_to_submit=merged_ticket.is_complete(),
        )

    def _build_fallback_reply(
        self,
        merged_ticket: SupportTicket,
        extracted: SupportTicket,
        is_new_session: bool,
        conversation_history: list[DialogueMessage],
        telegram_first_name: str | None,
    ) -> str:
        if not conversation_history and is_new_session and not extracted.name and not merged_ticket.name:
            return "Здравствуйте! Я помогу оформить запись на массаж. Как вас зовут?"

        if not merged_ticket.name:
            return "Подскажите, как к вам обращаться?"

        if not merged_ticket.contact:
            return "Оставьте, пожалуйста, контакт для связи: телефон или Telegram."

        if not merged_ticket.health_complaint:
            name = merged_ticket.name or telegram_first_name
            prefix = f"{name}, " if name else ""
            return f"{prefix}кратко опишите жалобу на здоровье: что вас беспокоит?"

        if not merged_ticket.pain_location:
            return "Где именно болит или где ощущаете дискомфорт?"

        if not merged_ticket.pain_intensity:
            return "Насколько сильная боль: слабая, средняя или сильная?"

        if not merged_ticket.pain_duration:
            return "Как давно вас это беспокоит?"

        if not merged_ticket.preferred_time:
            return "На какое удобное для вас время хотите записаться?"

        return "Спасибо! Проверяю, всё ли собрано по анкете."

    @staticmethod
    def _normalize_text(value: str) -> str:
        return " ".join(value.split()).strip()

    @staticmethod
    def _is_repeat_question_request(message_lower: str) -> bool:
        triggers = [
            "какой был прошлый вопрос",
            "какой был предыдущий вопрос",
            "повтори вопрос",
            "повтори последний вопрос",
            "что ты спрашивал",
            "что вы спрашивали",
        ]
        return any(trigger in message_lower for trigger in triggers)

    @staticmethod
    def _detect_requested_field(last_assistant_message: str | None) -> str | None:
        if not last_assistant_message:
            return None

        message = last_assistant_message.lower()
        if any(phrase in message for phrase in ["как вас зовут", "как к вам обращаться", "полное имя"]):
            return "name"
        if any(phrase in message for phrase in ["контакт", "телефон для связи", "telegram"]):
            return "contact"
        if any(
            phrase in message
            for phrase in [
                "жалобу на здоровье",
                "что вас беспокоит",
                "что беспокоит",
                "опишите жалобу",
            ]
        ):
            return "health_complaint"
        if any(
            phrase in message
            for phrase in [
                "где именно болит",
                "где болит",
                "где ощущаете",
                "локализац",
            ]
        ):
            return "pain_location"
        if any(
            phrase in message
            for phrase in [
                "насколько сильная",
                "сила боли",
                "слабая, средняя",
                "интенсивност",
            ]
        ):
            return "pain_intensity"
        if any(
            phrase in message
            for phrase in [
                "как давно",
                "сколько уже",
                "когда началось",
            ]
        ):
            return "pain_duration"
        if any(
            phrase in message
            for phrase in [
                "на какое",
                "удобное для вас время",
                "записаться",
                "дата и время",
            ]
        ):
            return "preferred_time"
        return None

    @staticmethod
    def _looks_like_name(message: str) -> bool:
        lowered = message.lower()
        blockers = [
            "бол",
            "жалоб",
            "шея",
            "спин",
            "поясниц",
            "плеч",
            "мышц",
            "массаж",
            "запис",
            "срочно",
            "вчера",
            "сегодня",
            "слабая",
            "средняя",
            "сильная",
        ]
        if any(blocker in lowered for blocker in blockers):
            return False
        if any(char.isdigit() for char in message):
            return False
        words = [word for word in re.split(r"\s+", message) if word]
        return 1 <= len(words) <= 3

    @staticmethod
    def _extract_contact(message: str) -> str | None:
        if message.startswith("@") and len(message) > 1:
            return message

        compact = re.sub(r"[^\d+]", "", message)
        digits = re.sub(r"\D", "", compact)
        if len(digits) >= 10:
            return compact
        return None

    @staticmethod
    def _looks_like_time_answer(message_lower: str) -> bool:
        tokens = [
            "минут",
            "час",
            "день",
            "недел",
            "месяц",
            "год",
            "сегодня",
            "вчера",
            "только что",
            "утром",
            "вечером",
            "назад",
            "давно",
            "недавно",
        ]
        return any(token in message_lower for token in tokens)

    @staticmethod
    def _looks_like_booking_time(message_lower: str) -> bool:
        tokens = [
            "завтра",
            "послезавтра",
            "понедельник",
            "вторник",
            "сред",
            "четверг",
            "пятниц",
            "суббот",
            "воскресень",
            "утра",
            "утром",
            "днем",
            "днём",
            "вечером",
            "вечера",
            "час",
            ":",
            "запис",
        ]
        return any(token in message_lower for token in tokens) or bool(re.search(r"\d", message_lower))

    @staticmethod
    def _looks_like_complaint(message_lower: str) -> bool:
        tokens = [
            "бол",
            "жалоб",
            "беспоко",
            "напряж",
            "скован",
            "усталост",
            "дискомфорт",
            "тяну",
            "ноет",
            "зажим",
            "отек",
            "отёк",
            "головн",
        ]
        return any(token in message_lower for token in tokens)

    @staticmethod
    def _extract_pain_intensity(message_lower: str) -> str | None:
        if any(token in message_lower for token in ["сильн", "очень больно", "невыносим", "9", "10"]):
            return "сильная"
        if any(token in message_lower for token in ["слабая", "слаб", "чуть", "немного", "1", "2", "3"]):
            return "слабая"
        if any(token in message_lower for token in ["средн", "умерен", "4", "5", "6", "7"]):
            return "средняя"
        return None

    @staticmethod
    def _extract_pain_location(message: str) -> str | None:
        message_lower = message.lower()
        body_parts = {
            "шея": "шея",
            "шейн": "шея",
            "поясниц": "поясница",
            "спин": "спина",
            "плеч": "плечи",
            "лопатк": "лопатки",
            "голов": "голова",
            "ног": "ноги",
            "колен": "колени",
            "рук": "руки",
            "пояс": "поясница",
            "крестц": "крестцовая область",
            "грудн": "грудной отдел",
            "поясничн": "поясница",
        }
        for token, label in body_parts.items():
            if token in message_lower:
                return label
        return None

    def _extract_complaint(self, message: str, current_ticket: SupportTicket) -> str | None:
        cleaned = self._normalize_text(message)
        if not cleaned or self._looks_like_name(cleaned):
            return None

        existing = current_ticket.health_complaint
        if existing:
            existing_lower = existing.lower()
            if cleaned.lower() == existing_lower:
                return None
            if cleaned.lower() in existing_lower:
                return None
            if len(cleaned.split()) <= 4:
                return f"{existing.rstrip('.')} {cleaned}".strip()

        return cleaned
