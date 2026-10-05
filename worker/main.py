import os

import psycopg
from dotenv import load_dotenv

load_dotenv()
DATABASE_URL = os.getenv("DATABASE_URL")


def get_connection():
    return psycopg.connect(DATABASE_URL)


def get_new_ticket():
    with get_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute("""
                SELECT id, chat_id, status
                FROM public.tickets
                WHERE status = 'new'
                ORDER BY created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            """)

            ticket = cursor.fetchone()

            if ticket is None:
                return None

            cursor.execute("""
                UPDATE public.tickets
                SET
                    status = 'processing',
                    locked_at = NOW(),
                    attempts = attempts + 1
                WHERE id = %s
            """, (ticket[0],))

            return ticket


def main():
    ticket = get_new_ticket()

    if ticket is None:
        print("Новых обращений нет")
        return

    print(f"Взяли обращение в обработку: {ticket}")


if __name__ == "__main__":
    main()