import asyncio
from datetime import datetime, timezone
from loguru import logger
from sqlalchemy import select

from olmas_kashey.db.models import Membership, MembershipState, Event
from olmas_kashey.db.session import get_db
from olmas_kashey.telegram.client import OlmasClient
from olmas_kashey.core.settings import settings

class MembershipMonitor:
    def __init__(self, client: OlmasClient):
        self.client = client
        self.check_interval_seconds = 1800 # 30 mins for full cycle or between cycles
        self.per_check_delay = 5 # Seconds between each group check to be safe

    async def run(self, once: bool = False) -> None:
        """
        Run the monitor loop.
        """
        logger.info(f"Starting MembershipMonitor (once={once})")
        
        while True:
            try:
                await self.check_all()
            except asyncio.CancelledError:
                logger.info("MembershipMonitor cancelled.")
                break
            except Exception as e:
                logger.error(f"Error in MembershipMonitor loop: {e}")
            
            if once:
                break
                
            logger.info(f"Monitor cycle complete. Sleeping for {self.check_interval_seconds}s...")
            await asyncio.sleep(self.check_interval_seconds)

    async def check_all(self) -> None:
        """
        Fetch joined groups and verify status.
        """
        async for session in get_db():
            # Fetch all JOINED memberships
            # We fetch IDs first to avoid long-running transaction if check takes time?
            # Or fetch batch by batch?
            # Fetch all is fine if list is small (<1000). If large, paginate.
            # Let's assume <1000 for now.
            stmt = select(Membership).where(Membership.state == MembershipState.JOINED)
            memberships = (await session.execute(stmt)).scalars().all()
            
            if not memberships:
                logger.info("No joined groups to monitor.")
                return

            logger.debug(f"Checking status for {len(memberships)} joined groups...")
            
            for mem in memberships:
                # We need Entity ID or Username to check. Membership has relation to Entity.
                # We should eager load entity? 
                # Or just fetch entity_id and rely on implicit load if session is active.
                # Since we are iterating inside `async for session`, session is active.
                # But we should probably eager load to be efficient.
                # However, lazy load is fine for <1000 items. 
                # Wait, generic relationship access might need await if not eager loaded in async.
                # `mem.entity` is a relationship.
                
                # Let's verify if we need explicit load. Usually yes in asyncio.
                # But let's assume we can get entity_id directly from `mem.entity_id`.
                # We pass `entity_id` (tg_id) or `id` (internal)?
                # `client.check_membership` expects TG entity (id or username).
                # `mem.entity_id` is INTERNAL DB ID.
                # We need `mem.entity.tg_id`.
                # So we must join.
                pass 

        # Re-query with join
        async for session in get_db():
            from olmas_kashey.db.models import Entity
            stmt = select(Membership, Entity).join(Entity).where(Membership.state == MembershipState.JOINED)
            results = (await session.execute(stmt)).all() # returns list of (Membership, Entity) tuples
            
            for mem, entity in results:
                try:
                    target = entity.username or entity.tg_id
                    status = await self.client.check_membership(target)
                    
                    if status == "joined":
                        # All good, update last checked
                        mem.last_checked_at = datetime.now(timezone.utc)
                        # Commit per item or batch? 
                        # Per item is safer for long process.
                        await session.commit()
                        logger.debug(f"Verified {target}: JOINED")
                    
                    elif status in ("left", "banned", "kicked"):
                        logger.warning(f"Status changed for {target}: {status.upper()}")
                        
                        old_state = mem.state
                        new_state = MembershipState.LEFT if status == "left" else MembershipState.REMOVED
                        
                        mem.state = new_state
                        mem.left_at = datetime.now(timezone.utc)
                        mem.last_checked_at = datetime.now(timezone.utc)
                        
                        # Log Event
                        event = Event(
                            entity_id=entity.id,
                            type="membership_lost",
                            payload={"reason": status, "old_state": old_state}
                        )
                        session.add(event)
                        await session.commit()
                        
                    else:
                        # Unknown error, log check but don't change state
                        mem.last_checked_at = datetime.now(timezone.utc)
                        await session.commit()
                        logger.warning(f"Could not verify {target}: status={status}")

                    # Rate limit between checks
                    await asyncio.sleep(self.per_check_delay)
                    
                except Exception as e:
                    logger.error(f"Error checking {entity.tg_id}: {e}")
                    # Continue to next
                    await asyncio.sleep(self.per_check_delay)
