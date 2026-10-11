"""Запуск бота: uv run python -m support_bot.main"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.types import BotCommand

from support_bot import texts
from support_bot.config import BotSettings
from support_bot.handlers import client

# Команды для кнопки «Меню» в Telegram
COMMANDS = [
    BotCommand(command="start", description=texts.COMMAND_START),
    BotCommand(command="help", description=texts.COMMAND_HELP),
]


async def main() -> None:
    logging.basicConfig(level=logging.INFO)
    # aiogram пишет строку на каждое событие — оставляем от него только ошибки
    logging.getLogger("aiogram.event").setLevel(logging.WARNING)
    settings = BotSettings()

    dispatcher = Dispatcher()
    dispatcher.include_router(client.router)

    # async with сам закроет соединение с Telegram при остановке
    async with Bot(token=settings.bot_token.get_secret_value()) as bot:
        await bot.set_my_commands(COMMANDS)
        await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
