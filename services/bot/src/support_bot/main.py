"""Запуск бота: uv run python -m support_bot.main"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import SimpleEventIsolation
from aiogram.types import BotCommand

from support_bot import db, outbox, texts
from support_bot.config import BotSettings
from support_bot.handlers import client, operator, reply

# Команды для кнопки «Меню» в Telegram
COMMANDS = [
    BotCommand(command="start", description=texts.COMMAND_START),
    BotCommand(command="help", description=texts.COMMAND_HELP),
    BotCommand(command="status", description=texts.COMMAND_STATUS),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # aiogram пишет строку на каждое событие – оставляем предупреждения и ошибки
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    settings = BotSettings()

    pool = None
    if settings.database_url is None:
        logging.warning("DATABASE_URL не задан – вопросы клиентов не сохраняются")
    else:
        pool = await db.open_pool(settings.database_url.get_secret_value())

    dispatcher = Dispatcher(settings=settings, pool=pool, events_isolation=SimpleEventIsolation())
    dispatcher.include_router(reply.router)
    dispatcher.include_router(client.router)
    dispatcher.include_router(operator.router)

    try:
        # async with сам закроет соединение с Telegram при остановке
        async with Bot(token=settings.bot_token.get_secret_value()) as bot:
            await bot.set_my_commands(COMMANDS)
            stop = asyncio.Event()
            # Обрабатываем очередь параллельно с приемом сообщений Telegram
            delivery = asyncio.create_task(outbox.run(bot, pool, settings, stop)) if pool is not None else None
            try:
                # Оставляем сессию Telegram открытой, пока очередь завершает начатую отправку
                await dispatcher.start_polling(bot, close_bot_session=False)
            finally:
                # Сигнал останавливает цикл после текущей задачи, await дожидается его выхода
                stop.set()
                if delivery is not None:
                    await delivery
    finally:
        # аккуратное закрытие с бд, в тч ctrl + c
        if pool is not None:
            await pool.close()


if __name__ == "__main__":
    asyncio.run(main())
