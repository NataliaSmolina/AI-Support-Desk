
import asyncio
import os

import psycopg
from dotenv import load_dotenv

from ai_clients.config import AISettings
from ai_clients.llm import LlmClassifier

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise RuntimeError("Не задана переменная DATABASE_URL")


def get_connection():
    return psycopg.connect(DATABASE_URL)


def get_new_ticket():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT
                    t.id,
                    t.chat_id,
                    m.text
                FROM public.tickets AS t
                JOIN LATERAL (
                    SELECT text
                    FROM public.messages
                    WHERE ticket_id = t.id
                      AND author = 'client'
                    ORDER BY created_at ASC
                    LIMIT 1
                ) AS m ON TRUE
                WHERE t.status = 'new'
                ORDER BY t.created_at ASC
                LIMIT 1
                FOR UPDATE OF t SKIP LOCKED
            """)

            ticket = cursor.fetchone()

            if ticket is None:
                return None

            ticket_id, chat_id, message_text = ticket

            cursor.execute("""
                UPDATE public.tickets
                SET
                    status = 'processing',
                    locked_at = NOW(),
                    attempts = attempts + 1
                WHERE id = %s
            """, (ticket_id,))

            return {
                "id": ticket_id,
                "chat_id": chat_id,
                "message": message_text,
            }


async def main():
    ticket = get_new_ticket()

    if ticket is None:
        print("Новых обращений с сообщениями клиентов нет")
        return

    print(f"Взяли обращение №{ticket['id']} в обработку")
    print(f"Telegram chat_id: {ticket['chat_id']}")
    print(f"Текст обращения: {ticket['message']}")

    settings = AISettings()
    classifier = LlmClassifier(
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        timeout_s=settings.request_timeout_s,
    )

    try:
        result = await classifier.classify(ticket["message"])

        print("\nРезультат классификации:")
        print(result.model_dump_json(indent=2))
    finally:
        await classifier.aclose()


if __name__ == "__main__":
    asyncio.run(main())
