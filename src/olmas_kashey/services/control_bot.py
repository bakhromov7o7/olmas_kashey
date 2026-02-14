import asyncio
import random
import re
from pathlib import Path
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any

from loguru import logger
from telethon import TelegramClient, events, Button
from sqlalchemy import select, func

from olmas_kashey.core.settings import settings
from olmas_kashey.db.session import get_db
from olmas_kashey.db.models import Entity, Membership, MembershipState, Event, SearchRun
from olmas_kashey.services.ai_keyword_generator import AIKeywordGenerator
from olmas_kashey.services.health_monitor import HealthMonitor

class TopicsChangedInterruption(Exception):
    """Raised when topics are updated during a search cycle."""
    pass

class ControlBotService:
    def __init__(self, client: Optional[TelegramClient] = None):
        self.client = client
        self.bot_client: Optional[TelegramClient] = None
        self.is_running = False
        self._pause_event = asyncio.Event()
        self._pause_event.set() # Not paused by default
        self.ai_gen = AIKeywordGenerator()
        self.topics_updated = False
        self._timed_pause_task: Optional[asyncio.Task] = None
        self.manual_resume_event = asyncio.Event()

    async def start(self):
        if not settings.telegram.bot_token:
            logger.warning("No bot token provided, remote control bot disabled.")
            return

        logger.info("Starting Remote Control Bot...")
        self.bot_client = TelegramClient(
            'bot_session', 
            settings.telegram.api_id, 
            settings.telegram.api_hash,
            proxy=settings.proxy.formatted_proxy()
        )
        
        await self.bot_client.start(bot_token=settings.telegram.bot_token)
        self.is_running = True
        
        # Start scheduled reports
        asyncio.create_task(self._report_scheduler())
        
        @self.bot_client.on(events.NewMessage(pattern=r'^/start(@\w+)?(\s|$)'))
        async def start_handler(event):
            logger.info(f"Command /start received from {event.sender_id}")
            if not await self._check_auth(event):
                return
            await event.respond("👋 Olmas Kashey Remote Control Botga xush kelibsiz!\n\n"
                                "Buyruqlar:\n"
                                "/status - Hozirgi holatni ko'rish\n"
                                "/resume - Discoveryni davom ettirish\n"
                                "/pause - Discoveryni to'xtatib turish\n"
                                "/set_interval <son> - Batch intervalni o'zgartirish (sekundda)\n"
                                "/set_topics <topic1,topic2> - Topiclar ro'yxatini yangilash\n"
                                "/id - Sizning ID raqamingiz")
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/id(@\w+)?(\s|$)'))
        async def id_handler(event):
            logger.info(f"Command /id received from {event.sender_id}")
            await event.respond(f"Sizning Telegram ID: `{event.sender_id}`\n"
                                f"Buni `.env` faylidagi `TELEGRAM__AUTHORIZED_USER_ID` ga qo'shing.")
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/status(@\w+)?(\s|$)'))
        async def status_handler(event):
            logger.info(f"Command /status received from {event.sender_id}")
            if not await self._check_auth(event):
                return
            try:
                status_text = await self._get_status_report()
                await event.respond(status_text)
            except Exception as e:
                logger.exception("Status report error")
                await event.respond(f"❌ Status olishda xatolik: {e}")
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/pause(@\w+)?(\s|$)'))
        async def pause_handler(event):
            logger.info(f"Command /pause received from {event.sender_id}")
            if not await self._check_auth(event):
                return
            self._pause_event.clear()
            await event.respond("⏸️ Discovery to'xtatildi.")
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/resume(@\w+)?(\s|$)'))
        async def resume_handler(event):
            logger.info(f"Command /resume received from {event.sender_id}")
            if not await self._check_auth(event):
                return
            self._pause_event.set()
            self.manual_resume_event.set()
            await event.respond("▶️ Discovery davom ettirilmoqda.")
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/set_interval(@\w+)?\s+(\d+)'))
        async def interval_handler(event):
            logger.info(f"Command /set_interval received from {event.sender_id}")
            if not await self._check_auth(event):
                return
            try:
                val = int(event.pattern_match.group(2))
                settings.discovery.batch_interval_seconds = val
                self._update_env_file("DISCOVERY__BATCH_INTERVAL_SECONDS", str(val))
                await event.respond(f"✅ Batch interval {val} sekundga o'zgartirildi.")
            except Exception as e:
                await event.respond(f"❌ Xatolik: {e}")
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/set_topics(@\w+)?\s+(.+)'))
        async def topics_handler(event):
            logger.info(f"Command /set_topics received from {event.sender_id}")
            if not await self._check_auth(event):
                return
            try:
                topics_str = event.pattern_match.group(2)
                topics = [t.strip() for t in topics_str.split(',')]
                settings.discovery.allowed_topics = topics
                # Construct JSON-like list for .env
                topics_env = '["' + '","'.join(topics) + '"]'
                self._update_env_file("DISCOVERY__ALLOWED_TOPICS", topics_env)
                self.topics_updated = True
                await event.respond(f"✅ Topiclar yangilandi: {', '.join(topics)}\n🔄 Hozirgi qidiruv to'xtatilib, yangi mavzularga o'tilmoqda...")
            except Exception as e:
                await event.respond(f"❌ Xatolik: {e}")
            raise events.StopPropagation

        @self.bot_client.on(events.CallbackQuery(data=re.compile(b'^pause$')))
        async def pause_callback_handler(event):
            if not await self._check_auth(event):
                await event.answer("Ruxsat berilmagan.")
                return
            
            buttons = [
                [Button.inline("10 minut", b"pause_time_10"), Button.inline("20 minut", b"pause_time_20")],
                [Button.inline("30 minut", b"pause_time_30"), Button.inline("1 soat", b"pause_time_60")],
                [Button.inline("3 soat", b"pause_time_180"), Button.inline("6 soat", b"pause_time_360")],
                [Button.inline("12 soat", b"pause_time_720")],
                [Button.inline("❌ Bekor qilish", b"cancel")]
            ]
            await event.edit("Qancha vaqtga pauza qilmoqchisiz?", buttons=buttons)

        @self.bot_client.on(events.CallbackQuery(data=re.compile(br'^pause_time_(\d+)$')))
        async def pause_time_handler(event):
            if not await self._check_auth(event):
                return
            
            mins = int(event.data_match.group(1).decode())
            self._pause_event.clear()
            
            # Cancel previous timed pause if any
            if self._timed_pause_task:
                self._timed_pause_task.cancel()
            
            # Start new timed pause task
            self._timed_pause_task = asyncio.create_task(self._timed_pause(mins))
            
            duration_str = f"{mins} minut" if mins < 60 else f"{mins//60} soat"
            await event.edit(f"⏸️ Discovery {duration_str}ga to'xtatildi. Vaqt tugagach avtomatik davom etadi.")
            await event.answer(f"Pauza: {duration_str}")

        @self.bot_client.on(events.CallbackQuery(data=re.compile(b'^cancel$')))
        async def cancel_handler(event):
            await event.delete()

        @self.bot_client.on(events.NewMessage)
        async def debug_handler(event):
            if event.message.text and event.message.text.startswith('/'):
                logger.debug(f"Unhandled command: {event.message.text} from {event.sender_id}")

        logger.info("Remote Control Bot started.")
        await self.bot_client.run_until_disconnected()

    async def _check_auth(self, event) -> bool:
        sender_id = event.sender_id
        
        if not event.is_private:
            await event.respond("⚠️ Bu buyruqni faqat shaxsiy chatda ishlatishingiz mumkin.")
            logger.warning(f"Unauthorized access attempt from {sender_id} in non-private chat.")
            return False

        if not settings.telegram.authorized_user_id:
            await event.respond("⚠️ Avtorizatsiya qilinmagan. Iltimos, `.env` faylida `TELEGRAM__AUTHORIZED_USER_ID` ni o'rnating.\n"
                                f"Sizning ID: `{sender_id}`")
            logger.warning(f"Unauthorized access: settings.telegram.authorized_user_id is {settings.telegram.authorized_user_id}")
            return False
            
        if sender_id != settings.telegram.authorized_user_id:
            logger.warning(f"ID Mismatch: sender={sender_id}, authorized={settings.telegram.authorized_user_id}")
            await event.respond(f"⛔ Kechirasiz, siz ushbu botni boshqarish huquqiga ega emassiz.\nSizning ID: `{sender_id}`")
            logger.warning(f"Unauthorized access attempt from {sender_id}")
            return False
        return True

    async def _get_status_report(self) -> str:
        uz_tz = timezone(timedelta(hours=5))
        now_uz = datetime.now(uz_tz)
        # Today start in UTC+5
        today_start_utc = now_uz.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        
        async for session in get_db():
            # Today's joined groups
            joined_stmt = select(func.count(Membership.id)).where(
                Membership.state == MembershipState.JOINED,
                Membership.joined_at >= today_start_utc
            )
            joined_count = (await session.execute(joined_stmt)).scalar() or 0
            
            # Total joined groups
            total_joined_stmt = select(func.count(Membership.id)).where(
                Membership.state == MembershipState.JOINED
            )
            total_joined = (await session.execute(total_joined_stmt)).scalar() or 0
            
            # Today's discovered entities (all states)
            discovered_stmt = select(func.count(Entity.id)).where(
                Entity.discovered_at >= today_start_utc
            )
            discovered_count = (await session.execute(discovered_stmt)).scalar() or 0
            
            # Ban count (REMOVED state)
            banned_stmt = select(func.count(Membership.id)).where(
                Membership.state == MembershipState.REMOVED
            )
            ban_count = (await session.execute(banned_stmt)).scalar() or 0
            
            # Last search runs
            search_stmt = select(SearchRun).order_by(SearchRun.started_at.desc()).limit(5)
            last_runs = (await session.execute(search_stmt)).scalars().all()
            
            # Health Status
            health_str = "Noma'lum"
            if self.client and self.client.is_connected():
                health_monitor = HealthMonitor(self.client)
                is_healthy = await health_monitor.check_health()
                health_str = "✅ Toza" if is_healthy else f"⚠️ Cheklov bor: {health_monitor.restriction_reason}"
            else:
                health_str = "💤 Client ulanmagan"

            status = "🟢 Ishlamoqda" if self._pause_event.is_set() else "⏸️ To'xtatilgan"
            
            report = (
                f"📊 **Hozirgi Holat:**\n"
                f"Status: {status}\n"
                f"🛡️ Account: {health_str}\n"
                f"🔍 Bugun topildi: {discovered_count}\n"
                f"📅 Bugun qo'shildi: {joined_count}\n"
                f"📈 Jami qo'shilganlar: {total_joined}\n"
                f"🚫 Jami banlar: {ban_count}\n"
                f"⏱️ Batch interval: {settings.discovery.batch_interval_seconds}s\n"
                f"📑 Topiclar: {', '.join(settings.discovery.allowed_topics)}\n\n"
            )
            
            if last_runs:
                report += "**Oxirgi qidiruvlar:**\n"
                for run in last_runs:
                    icon = "✅" if run.success else "❌"
                    report += f"{icon} {run.keyword} ({run.results_count} natija)\n"
            
            # AI insight
            if joined_count > 10:
                insight = "🚀 Bugun juda faolmiz! Telegram ban berish ehtimoli ortishi mumkin."
            elif joined_count == 0:
                insight = "🤔 Bugun hali hech narsa topilmadi. Topiclarni tekshirib ko'ring."
            else:
                insight = "✅ Barqaror ishlamoqda."
                
            report += f"\n🤖 **AI Insight:**\n{insight}"
            
            return report

    async def notify_flood_wait(self, seconds: float):
        """Send proactive notification about FloodWait."""
        if not self.bot_client or not settings.telegram.authorized_user_id:
            return

        mins = int(seconds // 60)
        secs = int(seconds % 60)
        time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        
        msg = (f"⚠️ **FloodWait aniqlandi!**\n\n"
               f"Telegram cheklovi tufayli bot {time_str} kutishga majbur. "
               f"Ban xavfini kamaytirish uchun discoveryni bir muddatga pauza qilishni tavsiya qilamiz.")
        
        buttons = [
            [Button.inline("⏸️ Pauza qilish", b"pause")],
            [Button.inline("✅ Tushunarli", b"cancel")]
        ]
        
        try:
            await self.bot_client.send_message(
                settings.telegram.authorized_user_id,
                msg,
                buttons=buttons
            )
        except Exception as e:
            logger.error(f"Failed to send FloodWait notification: {e}")

    async def notify_join(self, title: str, username: Optional[str] = None):
        """Send proactive notification about a new group join."""
        if not self.bot_client or not settings.telegram.authorized_user_id:
            return

        link = f"@{username}" if username else "shaxsiy havola"
        msg = f"✅ **Yangi guruhga a'zo bo'ldi!**\n\nNom: **{title}**\nHavola: {link}"
        
        try:
            await self.bot_client.send_message(
                settings.telegram.authorized_user_id,
                msg
            )
        except Exception as e:
            logger.error(f"Failed to send join notification: {e}")

    async def _timed_pause(self, minutes: int):
        """Background task to auto-resume after pause."""
        try:
            await asyncio.sleep(minutes * 60)
            self._pause_event.set()
            self.manual_resume_event.set()
            if self.bot_client and settings.telegram.authorized_user_id:
                await self.bot_client.send_message(
                    settings.telegram.authorized_user_id,
                    "▶️ Kutish vaqti tugadi. Discovery davom ettirilmoqda."
                )
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Timed pause error: {e}")

    async def _report_scheduler(self):
        """Send daily reports at 10:00 and 18:00 UZ time."""
        uz_tz = timezone(timedelta(hours=5))
        logger.info("Report scheduler started (10:00 and 18:00 UZ time)")
        
        while self.is_running:
            try:
                now_uz = datetime.now(uz_tz)
                current_time = now_uz.strftime("%H:%M")
                
                if current_time in ["10:00", "18:00"]:
                    logger.info(f"Sending scheduled report at {current_time} UZ time")
                    report = await self._get_status_report()
                    await self.bot_client.send_message(
                        settings.telegram.authorized_user_id,
                        f"📅 **Rejali Hisobot ({current_time}):**\n\n{report}"
                    )
                    # Sleep for 61 seconds to avoid double trigger
                    await asyncio.sleep(61)
                else:
                    # Check every minute
                    await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Report scheduler error: {e}")
                await asyncio.sleep(60)

    async def wait_if_paused(self):
        """Called by discovery service to support pausing."""
        await self._pause_event.wait()

    async def stop(self):
        if self.bot_client:
            await self.bot_client.disconnect()
        self.is_running = False

    def _update_env_file(self, key: str, value: str):
        env_path = Path(".env")
        if not env_path.exists():
            return

        content = env_path.read_text()
        new_line = f"{key}={value}"
        
        # Check if key already exists
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
        if pattern.search(content):
            new_content = pattern.sub(new_line, content)
        else:
            new_content = content.rstrip() + f"\n{new_line}\n"
        
        env_path.write_text(new_content)
        logger.info(f"Updated .env: {key}={value}")
