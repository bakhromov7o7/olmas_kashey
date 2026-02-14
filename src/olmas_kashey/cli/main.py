import asyncio
import typer
from typing import List, Optional
from loguru import logger
import subprocess

from olmas_kashey.telegram.client import OlmasClient
# from olmas_kashey.services.manager import Manager # Legacy, removed
from olmas_kashey.services.group_discovery import GroupDiscoveryService
from olmas_kashey.services.query_plan import QueryPlanner
from olmas_kashey.services.membership_monitor import MembershipMonitor
from olmas_kashey.services.health_monitor import HealthMonitor
from olmas_kashey.core.signal_handler import SignalHandler
from olmas_kashey.core.settings import settings

app = typer.Typer(help="Olmas Kashey - Telegram User Automation")


@app.command()
def init_db() -> None:
    """
    Initialize the database using Alembic migrations.
    """
    logger.info("Initializing database...")
    try:
        # Running alembic upgrade head using subprocess
        subprocess.run(["alembic", "upgrade", "head"], check=True)
        logger.info("Database initialized successfully.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to initialize database: {e}")
        raise typer.Exit(code=1)


async def _scan(keywords: List[str], limit: int) -> None:
    # Manual scan without planner (or using planner but overriding keywords?)
    # The requirement says "run-discovery --limit N".
    # Implementation: Use GroupDiscoveryService but maybe we need ad-hoc keyword support?
    # GroupDiscoveryService uses QueryPlanner.
    # If we want to scan SPECIFIC keywords, we might need a different method or bypass planner.
    # But usually "scan" implies ad-hoc. 
    # Let's support ad-hoc in GroupDiscoveryService or just use client directly here?
    # Better: Add `process_keyword` to public API of service and use it.
    
    client = OlmasClient()
    planner = QueryPlanner()
    service = GroupDiscoveryService(client, planner)
    
    await client.start()
    try:
        for keyword in keywords:
            await service._process_keyword(keyword) # Calling internal method or should make public?
            # It is _process_keyword. I should probably rename to process_keyword if public.
            # For now I will access it.
    finally:
        await client.stop()


@app.command()
def run_discovery(
    limit: int = typer.Option(10, help="Number of keywords to process from the plan"),
) -> None:
    """
    Run the discovery pipeline for N keywords from the planner.
    """
    async def _run():
        from olmas_kashey.core.signal_handler import SignalHandler
        sig_handler = SignalHandler()
        sig_handler.install()

        client = OlmasClient()
        planner = QueryPlanner()
        service = GroupDiscoveryService(client, planner)
        
        await client.start()
        try:
            await service.run(iterations=limit, sig_handler=sig_handler)
        finally:
            await client.stop()

    asyncio.run(_run())


@app.command()
def start() -> None:
    """
    Start the automation daemon (monitor, discovery, health check).
    """
    try:
        asyncio.run(_monitor())
    except KeyboardInterrupt:
        typer.secho("\n🛑 Automation stopped by user.", fg=typer.colors.YELLOW)

async def _monitor() -> None:
    """
    Continuous automation engine.
    Orchestrates discovery, membership, and health monitoring.
    """
    from olmas_kashey.core.signal_handler import SignalHandler
    from olmas_kashey.services.health_monitor import HealthMonitor
    from olmas_kashey.services.membership import MembershipService
    from olmas_kashey.services.membership_monitor import MembershipMonitor
    from olmas_kashey.services.group_discovery import GroupDiscoveryService
    from olmas_kashey.services.query_plan import QueryPlanner
    from olmas_kashey.services.control_bot import ControlBotService
    
    # 1. Setup
    sig_handler = SignalHandler()
    sig_handler.install()

    # 0. Bot Setup (Initialized early to pass to Client)
    # We pass None as client initially, then set it once client is created
    bot_service = ControlBotService()
    bot_task = None
    if settings.telegram.bot_token:
        bot_task = asyncio.create_task(bot_service.start())

    client = OlmasClient(bot=bot_service)
    bot_service.client = client # Link them back
    
    planner = QueryPlanner()
    discovery_service = GroupDiscoveryService(client, planner, bot=bot_service)
    membership_service = MembershipService(client)
    membership_monitor = MembershipMonitor(client)
    health_monitor = HealthMonitor(client)
    
    typer.secho("🏗️  Olmas Kashey Automation Engine Starting...", fg=typer.colors.CYAN, bold=True)
    await client.start()
    
    try:
        iteration = 1
        while not sig_handler.check_shutdown:
            typer.secho(f"\n--- Cycle {iteration} ---", fg=typer.colors.BRIGHT_BLACK, bold=True)
            
            if bot_service: 
                await bot_service.wait_if_paused()

            # 2. Health Check
            typer.echo("🩺 Checking account health...")
            is_healthy = await health_monitor.check_health()
            if not is_healthy:
                typer.secho(f"⚠️  Account Restricted: {health_monitor.restriction_reason}", fg=typer.colors.RED, bold=True)
                typer.echo("⏸️  Automation paused for 1 hour...")
                if await sig_handler.sleep(3600):
                    break
                continue
            
            if bot_service: await bot_service.wait_if_paused()

            # 3. Membership Verification
            typer.echo("👀 Verifying status of joined groups...")
            await membership_monitor.check_all()

            if bot_service: await bot_service.wait_if_paused()

            # 4. Process Pending Joins
            typer.echo("👥 Processing pending joins from allowlist...")
            await membership_service.process_joins()

            # 5. Group Discovery
            if bot_service: await bot_service.wait_if_paused()
            typer.echo("🔍 Running discovery cycle...")
            await discovery_service.run(iterations=2, sig_handler=sig_handler)

            # 6. Global Cycle Delay
            iteration += 1
            cycle_delay = settings.service.scheduler_interval_minutes * 60
            typer.secho(f"🏁 Cycle complete. Sleeping {cycle_delay}s...", fg=typer.colors.BRIGHT_BLACK)
            
            # Wait for delay OR until resume if paused
            total_sleep = 0
            while total_sleep < cycle_delay and not sig_handler.check_shutdown:
                if bot_service:
                    await bot_service.wait_if_paused()
                
                sleep_chunk = min(10, cycle_delay - total_sleep)
                if await sig_handler.sleep(sleep_chunk):
                    break
                total_sleep += sleep_chunk
                
    except Exception as e:
        logger.exception("Engine failure")
        typer.secho(f"🔥 Engine Error: {e}", fg=typer.colors.RED, bold=True)
    finally:
        if bot_task:
            await bot_service.stop()
            bot_task.cancel()
        await client.stop()
        typer.echo("🔌 Disconnected.")
@app.command()


@app.command()
def plan(
    limit: int = typer.Option(10, help="Number of queries to preview"),
    seed: int = typer.Option(42, help="Random seed for keyword generation"),
) -> None:
    """
    Preview the next N queries that will be executed.
    """
    async def _preview():
        planner = QueryPlanner(seed=seed)
        logger.info(f"Previewing next {limit} queries with seed {seed}...")
        queries = await planner.preview(limit)
        for i, q in enumerate(queries, 1):
            typer.echo(f"{i}. {q}")

    asyncio.run(_preview())


@app.command()
def run_monitor(
    once: bool = typer.Option(False, "--once", help="Run a single pass and exit"),
) -> None:
    """
    Run the membership monitor to verify status of joined groups.
    """
    async def _run():
        client = OlmasClient()
        monitor = MembershipMonitor(client)
        
        await client.start()
        try:
            await monitor.run(once=once)
        finally:
            await client.stop()

    asyncio.run(_run())


@app.command("continuous-search")
def continuous_search(
    topic: str = typer.Option(..., "--topic", "-t", help="Topic or keyword to start searching"),
    delay: int = typer.Option(120, "--delay", "-d", help="Delay between search cycles in seconds"),
    no_ai: bool = typer.Option(False, "--no-ai", help="Disable AI keyword expansion, only search the topic itself")
) -> None:
    """
    Start a continuous search for a topic (AI-powered or direct).
    """
    async def _run():
        from olmas_kashey.services.ai_keyword_generator import AIKeywordGenerator
        from olmas_kashey.services.discovery_pipeline import DiscoveryPipeline
        from olmas_kashey.core.signal_handler import SignalHandler
        from datetime import datetime, timezone
        from olmas_kashey.db.session import get_db
        from olmas_kashey.db.models import Entity, Event, Membership, MembershipState
        
        sig_handler = SignalHandler()
        sig_handler.install()
        
        client = OlmasClient()
        ai_gen = AIKeywordGenerator()
        pipeline = DiscoveryPipeline(client)
        
        await client.start()
        
        total_groups_found = 0
        total_joined = 0
        keywords_used = set()
        
        try:
            typer.echo(f"🚀 {'Direct' if no_ai else 'AI-powered'} continuous search started!")
            typer.echo(f"📝 Topic: {topic}")
            typer.echo("⏹️  Press Ctrl+C to stop\n")
            
            while not sig_handler.check_shutdown:
                # 1. Prepare keywords starting with the topic itself
                batch = [topic]
                if not no_ai:
                    typer.echo("🤖 Generating related keywords with AI...")
                    data = await ai_gen.generate_keywords(topic=topic, count=10)
                    if data:
                        # Combine keywords and usernames
                        batch.extend(data.get("usernames", []))
                        batch.extend(data.get("keywords", []))
                
                # 2. Filter keywords
                if no_ai:
                    batch = [topic]
                else:
                    batch = [k for k in batch if k.lower() not in keywords_used]
                    for k in batch: keywords_used.add(k.lower())

                if not batch:
                    if no_ai:
                        # In no-ai mode, we just re-search the topic after the delay
                        batch = [topic]
                    else:
                        typer.echo("💤 No new related keywords from AI. Waiting for next cycle...")
                
                if batch:
                    for keyword in batch:
                        if sig_handler.check_shutdown:
                            break
                        
                        typer.echo(f"\n🔍 Processing: '{keyword}'")
                        
                        try:
                            # Use discovery pipeline instead of raw search
                            result = await pipeline.discover(keyword)
                            
                            if result["status"] == "not_found":
                                typer.echo(f"  ❌ No good candidates found for '{keyword}'")
                                continue
                            
                            best = result["best"]
                            typer.echo(f"  🎯 Found best match: {best['title']} (@{best['username'] or 'no-username'}) [Score: {best['score']}]")
                            
                            total_groups_found += 1
                            
                            # Auto-join if confidence is enough
                            if best["score"] >= 0.7:
                                async for session in get_db():
                                    # Check if already joined
                                    from sqlalchemy import select
                                    stmt = select(Entity).where(Entity.tg_id == int(best["chat_id"]))
                                    res = await session.execute(stmt)
                                    entity = res.scalar_one_or_none()
                                    
                                    # If entity exists, check membership
                                    if entity:
                                        stmt = select(Membership).where(Membership.entity_id == entity.id)
                                        res = await session.execute(stmt)
                                        mem = res.scalar_one_or_none()
                                        if mem and mem.state == MembershipState.JOINED:
                                            typer.echo(f"  ℹ️ Already joined: {best['title']}")
                                            continue
                                    
                                    # Try to join
                                    try:
                                        # Use random delay for safety
                                        import random
                                        from olmas_kashey.core.settings import settings
                                        wait_time = random.uniform(settings.discovery.join_delay_min, settings.discovery.join_delay_max)
                                        typer.echo(f"  ⏳ Waiting {wait_time:.1f}s (safety delay) before join...")
                                        if await sig_handler.sleep(wait_time):
                                            break
                                        
                                        typer.echo(f"  ➕ Attempting to join...")
                                        await client.join_channel(best["username"] or best["chat_id"])
                                        
                                        # Refresh/Create entity and membership records
                                        await pipeline._cache_entity(best["entity"])
                                        
                                        # Re-fetch internal ID
                                        stmt = select(Entity).where(Entity.tg_id == int(best["chat_id"]))
                                        res = await session.execute(stmt)
                                        entity = res.scalar_one()
                                        
                                        # Update membership
                                        stmt = select(Membership).where(Membership.entity_id == entity.id)
                                        res = await session.execute(stmt)
                                        mem = res.scalar_one()
                                        
                                        mem.state = MembershipState.JOINED
                                        mem.joined_at = datetime.now(timezone.utc)
                                        total_joined += 1
                                        
                                        typer.secho(f"  ✅ Successfully joined!", fg=typer.colors.GREEN)
                                        
                                        # Emit join event
                                        join_event = Event(
                                            entity_id=entity.id,
                                            type="robust_auto_joined",
                                            payload={"source_keyword": keyword, "score": best["score"]}
                                        )
                                        session.add(join_event)
                                        await session.commit()
                                        
                                    except Exception as join_err:
                                        typer.secho(f"  ❌ Join failed: {join_err}", fg=typer.colors.RED)
                            else:
                                typer.echo(f"  ⚠️ Confidence too low ({best['score']}), skipping auto-join.")
                                
                        except Exception as e:
                            typer.secho(f"  ⚠️ Pipeline error: {e}", fg=typer.colors.YELLOW)
                        
                        # Add jitter to the search delay
                        import random
                        jitter = random.uniform(0.8, 1.2)
                        from olmas_kashey.core.settings import settings
                        actual_delay = settings.telegram_limits.search_interval_seconds * jitter
                        if await sig_handler.sleep(actual_delay):
                            break
                # 3. Wait before next cycle
                if not sig_handler.check_shutdown:
                    typer.echo(f"\n🏁 Cycle complete. Waiting {delay}s for next batch...")
                    if await sig_handler.sleep(delay):
                        break
                    await asyncio.sleep(5)
                    
        except asyncio.CancelledError:
            pass
        finally:
            typer.echo(f"\n\n📊 Summary:")
            typer.echo(f"   Groups matched: {total_groups_found}")
            typer.echo(f"   Groups joined: {total_joined}")
            typer.echo(f"   Keywords processed: {len(keywords_used)}")
            await client.stop()
    
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        typer.echo("\n\n🛑 Search stopped by user.")


# Allowlist Commands
allowlist_app = typer.Typer(help="Manage the allowlist for joining groups")
app.add_typer(allowlist_app, name="allowlist")

@allowlist_app.command("add")
def allowlist_add(
    target: str = typer.Argument(..., help="Username or ID of the group/channel"),
    note: Optional[str] = typer.Option(None, help="Optional note")
) -> None:
    """Add a target to the allowlist."""
    async def _add():
        # We need a dummy client or just service without client for DB ops?
        # Service needs client in init. Let's make client optional or mock it?
        # Or just use DB session directly here for simple ops?
        # Better to reuse service logic. We can pass None as client if we don't use it.
        # But OlmasClient init connects to Telegram... expensive/slow for CLI add.
        # Let's use service but mock client or make client lazy?
        # For adding to DB, we don't need Telegram connection.
        # Accessing DB directly in CLI command is fine for simple CRUD.
        # But wait, MembershipService.add_to_allowlist is business logic.
        # Let's instantiate service with a dummy client if possible, or just reimplement simple add here?
        # Re-implementing duplicates logic.
        # Let's use MembershipService but modify it to accept optional client?
        # Re-factoring Service to intake client optionally is cleaner.
        
        # For now, let's just use DB session directly here to keep it fast and simple.
        from olmas_kashey.db.models import AllowlistItem
        from olmas_kashey.db.session import get_db
        from sqlalchemy import select

        normalized = target.strip().lower()
        async for session in get_db():
            stmt = select(AllowlistItem).where(AllowlistItem.target == normalized)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            
            if existing:
                if note:
                    existing.note = note
                    await session.commit()
                    typer.echo(f"Updated note for {target}")
                else:
                    typer.echo(f"{target} already in allowlist.")
                return

            item = AllowlistItem(target=normalized, note=note)
            session.add(item)
            await session.commit()
            typer.echo(f"Added {target} to allowlist.")

    asyncio.run(_add())


@allowlist_app.command("remove")
def allowlist_remove(target: str) -> None:
    """Remove a target from the allowlist."""
    async def _remove():
        from olmas_kashey.db.models import AllowlistItem
        from olmas_kashey.db.session import get_db
        from sqlalchemy import select

        normalized = target.strip().lower()
        async for session in get_db():
            stmt = select(AllowlistItem).where(AllowlistItem.target == normalized)
            existing = (await session.execute(stmt)).scalar_one_or_none()
            
            if not existing:
                typer.echo(f"{target} not found in allowlist.")
                return

            await session.delete(existing)
            await session.commit()
            typer.echo(f"Removed {target} from allowlist.")

    asyncio.run(_remove())


@allowlist_app.command("list")
def allowlist_list() -> None:
    """List all targets in the allowlist."""
    async def _list():
        from olmas_kashey.db.models import AllowlistItem
        from olmas_kashey.db.session import get_db
        from sqlalchemy import select

        async for session in get_db():
            stmt = select(AllowlistItem)
            items = (await session.execute(stmt)).scalars().all()
            
            if not items:
                typer.echo("Allowlist is empty.")
                return
            
            typer.echo(f"Found {len(items)} allowed targets:")
            for item in items:
                typer.echo(f"- {item.target} (Note: {item.note or 'N/A'})")

    asyncio.run(_list())


@app.command()
def status() -> None:
    """
    Check the current health and restriction status of the account.
    """
    async def _check():
        client = OlmasClient()
        monitor = HealthMonitor(client)
        
        await client.start()
        try:
            logger.info("Checking account status...")
            is_healthy = await monitor.check_health()
            
            if is_healthy:
                typer.echo("✅ Account Status: HEALTHY (Unrestricted)")
            else:
                typer.secho(f"⚠️ Account Status: RESTRICTED", fg=typer.colors.RED)
                if monitor.restriction_reason:
                    typer.echo(f"Reason: {monitor.restriction_reason}")
                typer.echo("Sensitive operations will be paused in daemon mode.")
                
        finally:
            await client.stop()

    asyncio.run(_check())


@app.command("sync-groups")
def sync_groups() -> None:
    """
    Sync all groups your account has already joined into the local database.
    """
    async def _run():
        from olmas_kashey.db.session import get_db
        from olmas_kashey.db.models import Entity, Membership, MembershipState, EntityKind
        from sqlalchemy import select
        from datetime import datetime, timezone
        
        client = OlmasClient()
        await client.start()
        
        total_synced = 0
        total_updated = 0
        
        try:
            telegram_groups = await client.get_joined_groups()
            
            async for session in get_db():
                for tg_entity in telegram_groups:
                    # 1. Check/Create Entity
                    stmt = select(Entity).where(Entity.tg_id == tg_entity.id)
                    res = await session.execute(stmt)
                    db_entity = res.scalar_one_or_none()
                    
                    if not db_entity:
                        db_entity = Entity(
                            tg_id=tg_entity.id,
                            username=tg_entity.username,
                            title=tg_entity.title,
                            kind="channel" if getattr(tg_entity, 'broadcast', False) else "group"
                        )
                        session.add(db_entity)
                        await session.flush() # Get ID
                        total_synced += 1
                    
                    # 2. Check/Update Membership
                    stmt = select(Membership).where(Membership.entity_id == db_entity.id)
                    res = await session.execute(stmt)
                    mem = res.scalar_one_or_none()
                    
                    if not mem:
                        mem = Membership(
                            entity_id=db_entity.id,
                            state=MembershipState.JOINED,
                            joined_at=datetime.now(timezone.utc)
                        )
                        session.add(mem)
                    elif mem.state != MembershipState.JOINED:
                        mem.state = MembershipState.JOINED
                        mem.joined_at = datetime.now(timezone.utc)
                        total_updated += 1
                
                await session.commit()
                
            typer.echo(f"\n✅ Sync Complete!")
            typer.echo(f"   New groups added: {total_synced}")
            typer.echo(f"   Existing memberships updated: {total_updated}")
            
        finally:
            await client.stop()

    asyncio.run(_run())


@app.command("broadcast")
def broadcast(
    message: str = typer.Argument(..., help="Message to send to all joined groups"),
    delay: int = typer.Option(5, help="Delay between messages in seconds"),
) -> None:
    """
    Send a message to all groups where the account is currently joined.
    """
    async def _run():
        from olmas_kashey.db.session import get_db
        from olmas_kashey.db.models import Entity, Membership, MembershipState
        from sqlalchemy import select
        
        client = OlmasClient()
        await client.start()
        
        total_sent = 0
        total_failed = 0
        
        try:
            async for session in get_db():
                stmt = select(Entity).join(Membership).where(Membership.state == MembershipState.JOINED)
                res = await session.execute(stmt)
                joined_entities = res.scalars().all()
                
                if not joined_entities:
                    typer.echo("ℹ️ No joined groups found to broadcast to.")
                    return
                
                typer.echo(f"📢 Starting broadcast to {len(joined_entities)} groups...")
                
                for entity in joined_entities:
                    target = entity.username or entity.tg_id
                    try:
                        # Use random delay for safety
                        import random
                        from olmas_kashey.core.settings import settings
                        wait_time = random.uniform(settings.discovery.message_delay_min, settings.discovery.message_delay_max)
                        typer.echo(f"  ⏳ Waiting {wait_time:.1f}s (safety delay) before message...")
                        await asyncio.sleep(wait_time)

                        typer.echo(f"  📤 Sending to: {entity.title or target}...")
                        await client.send_message(target, message)
                        total_sent += 1
                        
                        # Add incremental jitter delay
                        jitter = random.uniform(1.0, 3.0)
                        await asyncio.sleep(jitter)
                    except Exception as e:
                        typer.secho(f"  ❌ Failed to send to {target}: {e}", fg=typer.colors.RED)
                        total_failed += 1
                        
            typer.echo(f"\n📊 Broadcast Summary:")
            typer.echo(f"   Successfully sent: {total_sent}")
            typer.echo(f"   Failed: {total_failed}")
            
        finally:
            await client.stop()

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        typer.echo("\n🛑 Broadcast stopped by user.")


@app.command()
def search(
    keyword: str = typer.Argument(..., help="Specific keyword or username to search for")
) -> None:
    """
    Perform a direct, one-off search for a specific keyword or username.
    No AI expansion, just direct discovery.
    """
    async def _run():
        from olmas_kashey.core.signal_handler import SignalHandler
        sig_handler = SignalHandler()
        sig_handler.install()

        client = OlmasClient()
        pipeline = DiscoveryPipeline(client)
        
        await client.start()
        try:
            typer.echo(f"🔍 Direct search for: '{keyword}'...")
            result = await pipeline.discover(keyword)
            
            if result["status"] == "not_found":
                typer.secho(f"❌ No good candidates found for '{keyword}'", fg=typer.colors.RED)
                return
            
            best = result["best"]
            typer.secho(f"🎯 Found best match: {best['title']} (@{best['username'] or 'no-username'})", fg=typer.colors.GREEN, bold=True)
            typer.echo(f"   Score: {best['score']}")
            typer.echo(f"   Chat ID: {best['chat_id']}")
            
            if best["score"] >= 0.7:
                confirm = typer.confirm(f"Do you want to join '{best['title']}'?")
                if confirm:
                    typer.echo("➕ Attempting to join...")
                    await client.join_channel(best["username"] or best["chat_id"])
                    await pipeline._cache_entity(best["entity"])
                    typer.secho("✅ Joined successfully!", fg=typer.colors.GREEN)
            
        finally:
            await client.stop()

    asyncio.run(_run())


@app.command()
def reset(
    force: bool = typer.Option(False, "--force", "-f", help="Force reset without confirmation")
) -> None:
    """
    Reset all discovered data (entities, memberships, search runs, events).
    WARNING: This will permanently delete all collected data.
    """
    if not force:
        confirm = typer.confirm("Are you sure you want to delete all discovered data? This cannot be undone.")
        if not confirm:
            typer.echo("Aborted.")
            return

    async def _reset():
        from olmas_kashey.db.session import get_db
        from olmas_kashey.db.models import Entity, Membership, SearchRun, Event, KeywordUsage
        from sqlalchemy import delete
        
        async for session in get_db():
            try:
                logger.info("Resetting data...")
                await session.execute(delete(Event))
                await session.execute(delete(Membership))
                await session.execute(delete(Entity))
                await session.execute(delete(SearchRun))
                await session.execute(delete(KeywordUsage))
                await session.commit()
                typer.secho("✅ Data reset successfully.", fg=typer.colors.GREEN)
            except Exception as e:
                logger.error(f"Failed to reset data: {e}")
                typer.secho(f"❌ Reset failed: {e}", fg=typer.colors.RED)

    asyncio.run(_reset())


if __name__ == "__main__":
    app()
