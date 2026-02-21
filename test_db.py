import asyncio
from olmas_kashey.db.models import Entity
from olmas_kashey.db.session import get_db
from sqlalchemy import select

async def main():
    async for session in get_db():
        res = await session.execute(select(Entity))
        entities = res.scalars().all()
        print(f"Total entities in DB: {len(entities)}")
        
if __name__ == "__main__":
    asyncio.run(main())
