import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from olmas_kashey.db.models import Base, Entity, SearchRun, Membership, Event, EntityKind, MembershipState
from datetime import datetime, timezone

# Use in-memory SQLite for testing
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

@pytest.fixture
async def db_session():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    SessionLocal = async_sessionmaker(engine, expire_on_commit=False)
    async with SessionLocal() as session:
        yield session
    
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.mark.asyncio
async def test_create_entity(db_session):
    entity = Entity(
        tg_id=123456789,
        username="test_channel",
        title="Test Channel",
        kind=EntityKind.CHANNEL
    )
    db_session.add(entity)
    await db_session.commit()

    result = await db_session.execute(select(Entity).where(Entity.tg_id == 123456789))
    fetched = result.scalar_one()
    assert fetched.username == "test_channel"
    assert fetched.kind == EntityKind.CHANNEL
    assert fetched.id is not None

@pytest.mark.asyncio
async def test_search_run(db_session):
    run = SearchRun(
        keyword="ielts",
        started_at=datetime.now(timezone.utc),
        success=True,
        results_count=10
    )
    db_session.add(run)
    await db_session.commit()
    
    assert run.id is not None
    assert run.success is True

@pytest.mark.asyncio
async def test_membership_association(db_session):
    entity = Entity(tg_id=999, kind=EntityKind.GROUP)
    db_session.add(entity)
    await db_session.commit()
    
    membership = Membership(
        entity_id=entity.id,
        state=MembershipState.JOINED,
        joined_at=datetime.now(timezone.utc)
    )
    db_session.add(membership)
    await db_session.commit()
    
    # Reload entity
    await db_session.refresh(entity, attribute_names=["memberships"])
    assert entity.memberships is not None
    assert entity.memberships.state == MembershipState.JOINED

@pytest.mark.asyncio
async def test_event_creation(db_session):
    entity = Entity(tg_id=888, kind=EntityKind.BOT)
    db_session.add(entity)
    await db_session.commit()
    
    event = Event(
        entity_id=entity.id,
        type="message_received",
        payload={"text": "hello"}
    )
    db_session.add(event)
    await db_session.commit()
    
    assert event.id is not None
    assert event.payload["text"] == "hello"
