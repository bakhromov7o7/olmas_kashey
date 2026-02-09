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
    planner = QueryPlanner() # fallback
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
        client = OlmasClient()
        planner = QueryPlanner()
        service = GroupDiscoveryService(client, planner)
        
        await client.start()
        try:
            await service.run(iterations=limit)
        finally:
            await client.stop()

    asyncio.run(_run())


@app.command()
def start() -> None:
    """
    Start the automation daemon (monitor, discovery, health check).
    """
    async def _runner():
        # Setup Services
        client = OlmasClient()
        manager = Manager(client) # wait, Manager removed?
        # Re-check imports/usage.
        # Manager was removed in previous steps. 
        # But `_monitor` function uses `GroupDiscoveryService` now.
        # This is `start` command calling `_monitor`.
        # I should replace `_monitor` function content actually, or rewrite `_runner` here completely if I inline it.
        # But `start` calls `asyncio.run(_monitor())`.
        pass

    # The current `start` calls `_monitor`. I should update `_monitor`.
    pass

async def _monitor() -> None:
    # Setup Signal Handler
    sig_handler = SignalHandler()
    sig_handler.install()

    client = OlmasClient()
    planner = QueryPlanner()
    discovery_service = GroupDiscoveryService(client, planner)
    # MembershipMonitor
    membership_monitor = MembershipMonitor(client)
    # HealthMonitor
    health_monitor = HealthMonitor(client)
    
    await client.start()
    
    try:
        logger.info("Starting monitor loop...")
        while not sig_handler.check_shutdown:
            # 0. Check Health (Restricted Mode)
            is_healthy = await health_monitor.check_health()
            if not is_healthy:
                logger.warning("System in RESTRICTED MODE. Pausing sensitive operations.")
                # We can still run read-only checks if safe, but usually best to pause all.
                # Maybe run membership check if it's considered safe (read-only)?
                # "continue only safe read-only tasks if possible"
                # Searching public groups is read-only but might be flagged if spamming search.
                # Membership check is read-only (GetParticipant).
                # Let's Skip Discovery, allow Membership Check with caution?
                # Or just pause everything to be safe.
                # User said: "pause discovery and join operations", "continue only safe read-only tasks"
                
                # Membership Check
                await membership_monitor.run(once=True)
                
                # Sleep and continue
                await asyncio.sleep(300) 
                continue

            # 1. Run Discovery
            # Process 1 keyword per cycle
            await discovery_service.run(iterations=1)

            # 2. Join/Maintain Groups (Future)
            # await membership_service.process_joins()
            
            # 3. Membership Monitor (Periodic)
            # Run once per cycle? Or check interval?
            # MembershipMonitor has internal loop logic but we want to step it here.
            # We can use `run(once=True)`
            await membership_monitor.run(once=True)

            # Sleep logic
            interval = 60 # 1 min
            logger.info(f"Monitor cycle complete. Sleeping for {interval}s...")
            
            # Sleep with signal check
            for _ in range(interval):
                if sig_handler.check_shutdown:
                    break
                await asyncio.sleep(1)
                
    except asyncio.CancelledError:
        logger.info("Monitor task cancelled.")
    except Exception as e:
        logger.critical(f"Critical error in monitor loop: {e}")
    finally:
        logger.info("Stopping client...")
        await client.stop()


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
    daemon: bool = typer.Option(False, "--daemon", help="Run in a continuous loop (default behavior if --once not specified)")
) -> None:
    """
    Run the membership monitor to verify status of joined groups.
    """
    async def _run():
        client = OlmasClient()
        monitor = MembershipMonitor(client)
        
        await client.start()
        try:
            # If daemon flag is explicit or once is False (default), loop. 
            # But the service `run` method handles loop if `once=False`.
            # So we just pass `once` flag.
            # Behavior: 
            # --once -> once=True
            # --daemon -> once=False
            # default -> once=False (daemon)
            
            # If both are False (default), run as daemon.
            is_once = once
            
            await monitor.run(once=is_once)
        finally:
            await client.stop()

    asyncio.run(_run())


@app.command()
def start() -> None:
    """
    Start the automation daemon (monitor and auto-join).
    """
    asyncio.run(_monitor())


@app.command("continuous-search")
def continuous_search(
    topic: str = typer.Option("education", help="Topic for AI keyword generation"),
    delay: int = typer.Option(5, help="Delay between searches in seconds"),
) -> None:
    """
    AI-powered continuous group search with fuzzy matching.
    Uses DiscoveryPipeline to find best candidates even with noisy AI output.
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
            typer.echo("🚀 Robust AI-powered continuous search started!")
            typer.echo(f"📝 Topic: {topic}")
            typer.echo("⏹️  Press Ctrl+C to stop\n")
            
            while not sig_handler.check_shutdown:
                typer.echo("🤖 Generating keywords with AI...")
                keywords = ai_gen.generate_keywords(topic=topic, count=10)
                
                if not keywords:
                    typer.echo("⚠️  Failed to generate keywords, using fallback...")
                    keywords = ["ielts", "uzbekistan education"]
                
                for keyword in keywords:
                    if sig_handler.check_shutdown:
                        break
                    
                    if keyword in keywords_used:
                        continue
                    keywords_used.add(keyword)
                    
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
                                    typer.echo(f"  ➕ Attempting to join...")
                                    await asyncio.sleep(2)
                                    await client.join_channel(best["username"] or best["chat_id"])
                                    
                                    # Refresh/Create entity and membership records (pipeline._cache_entity handles part of this)
                                    # But let's ensure state is updated
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
                    
                    await asyncio.sleep(delay)
                
                # Variations for next round
                if not sig_handler.check_shutdown:
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


if __name__ == "__main__":
    app()
