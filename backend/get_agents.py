import asyncio
from app.database import async_session
from sqlalchemy import select
from app.models.agent import Agent


async def main():
    async with async_session() as db:
        r = await db.execute(select(Agent.id, Agent.name))
        for row in r.fetchall():
            print(f"{row[0]} | {row[1]}")


asyncio.run(main())
