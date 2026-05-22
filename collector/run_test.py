import asyncio

from collector.telegram import TelegramCollector
from config.settings import get_settings


async def main() -> None:
    settings = get_settings()
    collector = TelegramCollector(settings)
    await collector.connect()
    result = await collector.collect_channel("@durov", days=3)
    print(result)
    await collector.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
