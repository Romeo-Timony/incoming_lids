from core import SupportTicket


def format_collected_ticket(ticket: SupportTicket) -> str:
    lines = [
        f"Имя: {ticket.name or '-'}",
        f"Контакт: {ticket.contact or '-'}",
        f"Жалоба на здоровье: {ticket.health_complaint or '-'}",
        f"Где болит: {ticket.pain_location or '-'}",
        f"Сила боли: {ticket.pain_intensity or '-'}",
        f"Как давно беспокоит: {ticket.pain_duration or '-'}",
        f"Желаемое время записи: {ticket.preferred_time or '-'}",
    ]
    return "\n".join(lines)
