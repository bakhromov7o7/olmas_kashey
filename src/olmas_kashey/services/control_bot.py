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
        self.membership_monitor = None
        self.bot_client: Optional[TelegramClient] = None
        self.is_running = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()  # Not paused by default
        self.ai_gen = AIKeywordGenerator()
        self.topics_updated = False
        self._timed_pause_task: Optional[asyncio.Task] = None
        self.manual_resume_event = asyncio.Event()
        self.timed_pause_until: Optional[float] = None
        self.eco_mode = getattr(settings.service, 'eco_mode', False)
        self.smart_mode = settings.service.smart_mode

    async def start(self):
        if not settings.telegram.bot_token:
            logger.warning("No bot token provided, remote control bot disabled.")
            return

        if not self.bot_client:
            self.bot_client = TelegramClient(
                'bot_session', 
                settings.telegram.api_id, 
                settings.telegram.api_hash,
                proxy=settings.proxy.formatted_proxy()
            )
        
        logger.info("Connecting to Telegram Bot API...")
        try:
            await self.bot_client.start(bot_token=settings.telegram.bot_token)
        except Exception as e:
            logger.error(f"Failed to start Bot Client: {e}")
            return

        self.is_running = True
        logger.info("Remote Control Bot connected and authorized.")
        
        # Start scheduled reports
        asyncio.create_task(self._report_scheduler())
        
        # Set bot command menu
        try:
            from telethon import functions, types
            await self.bot_client(functions.bots.SetBotCommandsRequest(
                scope=types.BotCommandScopeDefault(),
                lang_code='',
                commands=[
                    types.BotCommand(command='status', description='📊 Bot holati va statistika'),
                    types.BotCommand(command='pause', description='⏸️ To\'xtatish (Cheksiz)'),
                    types.BotCommand(command='resume', description='▶️ Davom ettirish'),
                    types.BotCommand(command='sleep', description='💤 Vaqtli uyquga yuborish'),
                    types.BotCommand(command='eco', description='🐢 Ekonom rejimni yoqish/o\'chirish'),
                    types.BotCommand(command='smart', description='🧠 Smart AI rejimni yoqish/o\'chirish'),
                    types.BotCommand(command='check_groups', description='🔍 Guruhlarni tekshirish'),
                    types.BotCommand(command='set_interval', description='⏱️ Batch interval (sekund)'),
                    types.BotCommand(command='set_cycle', description='🔄 Cycle delay (sekund)'),
                    types.BotCommand(command='id', description='🆔 ID ni aniqlash'),
                ]
            ))
            logger.info("Bot command menu updated.")
        except Exception as e:
            logger.error(f"Failed to set bot commands: {e}")

        # ── Helper methods (actual logic, no StopPropagation) ──

        async def _do_status(event):
            try:
                status_text = await self._get_status_report()
                await event.respond(status_text)
            except Exception as e:
                logger.exception("Status report error")
                await event.respond(f"❌ Status olishda xatolik: {e}")

        async def _do_pause(event):
            self._pause_event.clear()
            await event.respond("⏸️ Discovery to'xtatildi. Qaytish uchun /resume bosing.")

        async def _do_resume(event):
            self._pause_event.set()
            self.manual_resume_event.set()
            await event.respond("▶️ Discovery davom ettirilmoqda.")

        async def _do_sleep_menu(event):
            buttons = [
                [Button.inline("10 minut", b"pause_time_10"), Button.inline("20 minut", b"pause_time_20")],
                [Button.inline("30 minut", b"pause_time_30"), Button.inline("1 soat", b"pause_time_60")],
                [Button.inline("3 soat", b"pause_time_180"), Button.inline("6 soat", b"pause_time_360")],
                [Button.inline("12 soat", b"pause_time_720")],
                [Button.inline("❌ Bekor qilish", b"cancel")]
            ]
            await event.respond("Botni qancha vaqtga uxlatmoqchisiz?", buttons=buttons)

        async def _do_eco(event):
            self.eco_mode = not self.eco_mode
            status = "yoqildi 🐢" if self.eco_mode else "o'chirildi 🚀"
            msg = f"🛡️ **Ekonom rejim {status}.**\n\n"
            if self.eco_mode:
                msg += "• Interval: 120s\n• Kutish: 2x uzoqroq"
            await event.respond(msg)

        async def _do_check_groups(event):
            if not self.membership_monitor:
                await event.respond("❌ MembershipMonitor bog'lanmagan.")
                return
            await event.respond("👀 Guruhlarni tekshirish boshlandi...")
            try:
                await self.membership_monitor.check_all()
                await event.respond("✅ Tekshirish yakunlandi.")
            except Exception as e:
                logger.error(f"Manual check error: {e}")
                await event.respond(f"❌ Xatolik: {e}")

        # ── Slash command handlers ──

        @self.bot_client.on(events.NewMessage(pattern=r'^/start(@\w+)?(\s|$)'))
        async def start_handler(event):
            if not await self._check_auth(event):
                return
            keyboard = [
                [Button.text("📊 Status", resize=True), Button.text("🔍 Guruhlarni tekshirish")],
                [Button.text("⏸️ Pauza", resize=True), Button.text("▶️ Davom ettirish")],
                [Button.text("💤 Uyqu", resize=True), Button.text("🐢 Eco")],
            ]
            await event.respond("👋 Olmas Kashey botga xush kelibsiz!\n\n"
                                "Quyidagi tugmalar yoki /buyruqlardan foydalaning:",
                                buttons=keyboard)
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/id(@\w+)?(\s|$)'))
        async def id_handler(event):
            await event.respond(f"Sizning Telegram ID: `{event.sender_id}`\n"
                                f"`.env` → `TELEGRAM__AUTHORIZED_USER_ID={event.sender_id}`")
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/status(@\w+)?(\s|$)'))
        async def status_handler(event):
            if not await self._check_auth(event):
                return
            await _do_status(event)
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/pause(@\w+)?(\s|$)'))
        async def pause_handler(event):
            if not await self._check_auth(event):
                return
            await _do_pause(event)
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/sleep(@\w+)?(\s|$)'))
        async def sleep_menu_handler(event):
            if not await self._check_auth(event):
                return
            await _do_sleep_menu(event)
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/resume(@\w+)?(\s|$)'))
        async def resume_handler(event):
            if not await self._check_auth(event):
                return
            await _do_resume(event)
            raise events.StopPropagation

        # /set_interval WITH argument
        @self.bot_client.on(events.NewMessage(pattern=r'^/set_interval(@\w+)?\s+(\d+)'))
        async def interval_handler(event):
            if not await self._check_auth(event):
                return
            try:
                val = int(event.pattern_match.group(2))
                settings.discovery.batch_interval_seconds = val
                self._update_env_file("DISCOVERY__BATCH_INTERVAL_SECONDS", str(val))
                await event.respond(f"✅ Batch interval: {val}s")
            except Exception as e:
                await event.respond(f"❌ Xatolik: {e}")
            raise events.StopPropagation

        # /set_interval WITHOUT argument → show usage
        @self.bot_client.on(events.NewMessage(pattern=r'^/set_interval(@\w+)?(\s|$)'))
        async def interval_usage_handler(event):
            if not await self._check_auth(event):
                return
            cur = settings.discovery.batch_interval_seconds
            await event.respond(f"⏱️ Hozirgi interval: **{cur}s**\n\n"
                                f"O'zgartirish: `/set_interval 30`")
            raise events.StopPropagation

        # /set_cycle WITH argument
        @self.bot_client.on(events.NewMessage(pattern=r'^/set_cycle(@\w+)?\s+(\d+)'))
        async def cycle_handler(event):
            if not await self._check_auth(event):
                return
            try:
                val = int(event.pattern_match.group(2))
                if val < 10:
                    await event.respond("⚠️ Kamida 10 sekund.")
                    return
                settings.service.scheduler_interval_seconds = val
                self._update_env_file("SERVICE__SCHEDULER_INTERVAL_SECONDS", str(val))
                await event.respond(f"✅ Cycle delay: {val}s")
            except Exception as e:
                await event.respond(f"❌ Xatolik: {e}")
            raise events.StopPropagation

        # /set_cycle WITHOUT argument → show usage
        @self.bot_client.on(events.NewMessage(pattern=r'^/set_cycle(@\w+)?(\s|$)'))
        async def cycle_usage_handler(event):
            if not await self._check_auth(event):
                return
            cur = settings.service.scheduler_interval_seconds
            await event.respond(f"🔄 Hozirgi delay: **{cur}s**\n\n"
                                f"O'zgartirish: `/set_cycle 60`")
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/eco(@\w+)?(\s|$)'))
        async def eco_handler(event):
            if not await self._check_auth(event):
                return
            
            self.eco_mode = not self.eco_mode
            if self.eco_mode:
                self.smart_mode = False 
                self._update_env_file("SERVICE__SMART_MODE", "false")
                settings.service.smart_mode = False
                
            self._update_env_file("SERVICE__ECO_MODE", str(self.eco_mode).lower())
            
            status = "yoqildi 🐢" if self.eco_mode else "o'chirildi 🚀"
            msg = f"🛡️ **Ekonom rejim {status}.**\n\n"
            if self.eco_mode:
                msg += "• Interval: 120s\n• Kutish: 2x uzoqroq"
            await event.respond(msg)
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/smart(@\w+)?(\s|$)'))
        async def smart_handler(event):
            if not await self._check_auth(event):
                return
            
            self.smart_mode = not self.smart_mode
            if self.smart_mode:
                self.eco_mode = False 
                self._update_env_file("SERVICE__ECO_MODE", "false")
                
            self._update_env_file("SERVICE__SMART_MODE", str(self.smart_mode).lower())
            settings.service.smart_mode = self.smart_mode
            
            status = "yoqildi 🧠" if self.smart_mode else "o'chirildi 🚀"
            msg = f"🤖 **Smart AI Rejim {status}.**\n\n"
            if self.smart_mode:
                msg += "• Kutish vaqtlari AI tomonidan hisoblanadi\n• Insoniy xulq-atvor simulyatsiyasi aktiv\n• Rebootdan keyin ham saqlanib qoladi"
            await event.respond(msg)
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/check_groups(@\w+)?(\s|$)'))
        async def check_groups_handler(event):
            if not await self._check_auth(event):
                return
            await _do_check_groups(event)
            raise events.StopPropagation

        @self.bot_client.on(events.NewMessage(pattern=r'^/set_topics(@\w+)?\s+(.+)'))
        async def topics_handler(event):
            if not await self._check_auth(event):
                return
            try:
                topics_str = event.pattern_match.group(2)
                topics = [t.strip() for t in topics_str.split(',')]
                settings.discovery.allowed_topics = topics
                topics_env = '["' + '","'.join(topics) + '"]'
                self._update_env_file("DISCOVERY__ALLOWED_TOPICS", topics_env)
                self.topics_updated = True
                await event.respond(f"✅ Topiclar yangilandi: {', '.join(topics)}")
            except Exception as e:
                await event.respond(f"❌ Xatolik: {e}")
            raise events.StopPropagation

        # ── Inline button (callback) handlers ──

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
            if self._timed_pause_task:
                self._timed_pause_task.cancel()
            self._timed_pause_task = asyncio.create_task(self._timed_pause(mins))
            duration_str = f"{mins} minut" if mins < 60 else f"{mins//60} soat"
            await event.edit(f"⏸️ Discovery {duration_str}ga to'xtatildi.")
            await event.answer(f"Pauza: {duration_str}")

        @self.bot_client.on(events.CallbackQuery(data=re.compile(b'^cancel$')))
        async def cancel_handler(event):
            await event.delete()

        # ── Text button handler (MUST be registered LAST) ──

        @self.bot_client.on(events.NewMessage)
        async def main_handler(event):
            """Route Reply Keyboard text buttons to _do_* helpers."""
            msg_text = event.message.text
            if not msg_text or msg_text.startswith('/'):
                return  # Skip commands — they're handled above

            if not await self._check_auth(event):
                return

            if "Status" in msg_text:
                await _do_status(event)
            elif "Pauza" in msg_text:
                await _do_pause(event)
            elif "Davom ettirish" in msg_text:
                await _do_resume(event)
            elif "Uyqu" in msg_text:
                await _do_sleep_menu(event)
            elif "Eco" in msg_text:
                await eco_handler(event)
            elif "Smart" in msg_text:
                await smart_handler(event)

        logger.info("Remote Control Bot started.")
        await self.bot_client.run_until_disconnected()

    async def _check_auth(self, event) -> bool:
        sender_id = event.sender_id
        
        if not event.is_private:
            await event.respond("⚠️ Bu buyruqni faqat shaxsiy chatda ishlatishingiz mumkin.")
            return False

        if not settings.telegram.authorized_user_id:
            await event.respond(f"⚠️ `.env` faylida `TELEGRAM__AUTHORIZED_USER_ID` ni o'rnating.\n"
                                f"Sizning ID: `{sender_id}`")
            return False
            
        if sender_id != settings.telegram.authorized_user_id:
            await event.respond(f"⛔ Siz ushbu botni boshqarish huquqiga ega emassiz.\nSizning ID: `{sender_id}`")
            return False
        return True

    async def _get_status_report(self) -> str:
        uz_tz = timezone(timedelta(hours=5))
        now_uz = datetime.now(uz_tz)
        today_start_utc = now_uz.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
        
        async for session in get_db():
            joined_stmt = select(func.count(Membership.id)).where(
                Membership.state == MembershipState.JOINED,
                Membership.joined_at >= today_start_utc
            )
            joined_count = (await session.execute(joined_stmt)).scalar() or 0
            
            total_joined_stmt = select(func.count(Membership.id)).where(
                Membership.state == MembershipState.JOINED
            )
            total_joined = (await session.execute(total_joined_stmt)).scalar() or 0
            
            discovered_stmt = select(func.count(Entity.id)).where(
                Entity.discovered_at >= today_start_utc
            )
            discovered_count = (await session.execute(discovered_stmt)).scalar() or 0
            
            banned_stmt = select(func.count(Membership.id)).where(
                Membership.state == MembershipState.REMOVED
            )
            ban_count = (await session.execute(banned_stmt)).scalar() or 0
            
            search_stmt = select(SearchRun).order_by(SearchRun.started_at.desc()).limit(5)
            last_runs = (await session.execute(search_stmt)).scalars().all()
            
            # Health
            health_str = "Noma'lum"
            if self.client and self.client.is_connected():
                health_monitor = HealthMonitor(self.client)
                is_healthy = await health_monitor.check_health()
                health_str = "✅ Toza" if is_healthy else f"⚠️ Cheklov: {health_monitor.restriction_reason}"
            else:
                health_str = "💤 Ulanmagan"

            status = "🟢 Ishlamoqda" if self._pause_event.is_set() else "⏸️ To'xtatilgan"
            eco_status = " 🐢" if self.eco_mode else ""
            smart_status = " 🧠" if getattr(self, 'smart_mode', False) else ""
            
            report = (
                f"📊 **Holat:**\n"
                f"Status: {status}{eco_status}{smart_status}\n"
                f"🛡️ Account: {health_str}\n"
                f"🔍 Bugun topildi: {discovered_count}\n"
                f"📅 Bugun qo'shildi: {joined_count}\n"
                f"📈 Jami: {total_joined}\n"
                f"🚫 Banlar: {ban_count}\n"
                f"⏱️ Interval: {settings.discovery.batch_interval_seconds}s\n"
                f"🔄 Cycle: {settings.service.scheduler_interval_seconds}s\n"
                f"📑 Topiclar: {', '.join(settings.discovery.allowed_topics)}\n"
            )

            # Countdown timers
            now_loop = asyncio.get_running_loop().time()
            if self.timed_pause_until and self.timed_pause_until > now_loop:
                rem = int(self.timed_pause_until - now_loop)
                mins, secs = divmod(rem, 60)
                report += f"⏳ Pauza tugashiga: {mins}m {secs}s\n"
            
            if self.client and hasattr(self.client, 'flood_wait_until') and self.client.flood_wait_until:
                if self.client.flood_wait_until > now_loop:
                    rem = int(self.client.flood_wait_until - now_loop)
                    report += f"⚠️ Telegram cheklovi: {rem}s qoldi\n"

            report += "\n"
            
            if last_runs:
                report += "**Oxirgi qidiruvlar:**\n"
                for run in last_runs:
                    icon = "✅" if run.success else "❌"
                    report += f"{icon} {run.keyword} ({run.results_count} natija)\n"
            
            if joined_count > 10:
                insight = "🚀 Bugun juda faol!"
            elif joined_count == 0:
                insight = "🤔 Hali hech narsa topilmadi."
            else:
                insight = "✅ Barqaror."
                
            report += f"\n🤖 {insight}"
            
            return report

    async def notify_flood_wait(self, seconds: float, is_smart: bool = False):
        if not self.bot_client or not settings.telegram.authorized_user_id:
            return
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        time_str = f"{mins}m {secs}s" if mins > 0 else f"{secs}s"
        
        if is_smart:
            msg = (f"⚠️ **FloodWait!**\n\n"
                   f"🧠 **AI (Smart Rejim)** tahliliga ko'ra, bot qamalmasligi uchun kutilmagan {time_str} uxlashiga to'g'ri keldi.\n\n"
                   f"⏳ **Kutish tugagach, bot avtomatik ravishda ishini davom ettiradi.** Sizdan hech qanday harakat talab qilinmaydi.")
        else:
            msg = (f"⚠️ **FloodWait!**\n\n"
                   f"Bot {time_str} kutishga majbur.\n\n"
                   f"⏳ **Ushbu vaqt o'tgach bot avtomatik davom etadi.**")
        buttons = [
            [Button.inline("⏸️ Pauza", b"pause")],
            [Button.inline("✅ OK", b"cancel")]
        ]
        try:
            await self.bot_client.send_message(
                settings.telegram.authorized_user_id,
                msg, buttons=buttons
            )
        except Exception as e:
            logger.error(f"Failed to send FloodWait notification: {e}")

    async def notify_join(self, title: str, username: Optional[str] = None):
        if not self.bot_client or not settings.telegram.authorized_user_id:
            return
        link = f"@{username}" if username else "shaxsiy havola"
        msg = f"✅ **Yangi guruhga a'zo bo'ldi!**\n\nNom: **{title}**\nHavola: {link}"
        try:
            await self.bot_client.send_message(
                settings.telegram.authorized_user_id, msg
            )
        except Exception as e:
            logger.error(f"Failed to send join notification: {e}")

    async def _timed_pause(self, minutes: int):
        try:
            end_time = asyncio.get_running_loop().time() + (minutes * 60)
            self.timed_pause_until = end_time
            await asyncio.sleep(minutes * 60)
            self._pause_event.set()
            self.manual_resume_event.set()
            if self.bot_client and settings.telegram.authorized_user_id:
                await self.bot_client.send_message(
                    settings.telegram.authorized_user_id,
                    "▶️ Kutish tugadi. Discovery davom etmoqda."
                )
        except asyncio.CancelledError:
            pass
        finally:
            self.timed_pause_until = None
            self._timed_pause_task = None

    async def _report_scheduler(self):
        uz_tz = timezone(timedelta(hours=5))
        while self.is_running:
            try:
                now_uz = datetime.now(uz_tz)
                current_time = now_uz.strftime("%H:%M")
                if current_time in ["10:00", "18:00"]:
                    report = await self._get_status_report()
                    await self.bot_client.send_message(
                        settings.telegram.authorized_user_id,
                        f"📅 **Hisobot ({current_time}):**\n\n{report}"
                    )
                    await asyncio.sleep(61)
                else:
                    await asyncio.sleep(30)
            except Exception as e:
                logger.error(f"Report scheduler error: {e}")
                await asyncio.sleep(60)

    async def wait_if_paused(self):
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
        pattern = re.compile(rf"^{re.escape(key)}\s*=.*$", re.MULTILINE)
        if pattern.search(content):
            new_content = pattern.sub(new_line, content)
        else:
            new_content = content.rstrip() + f"\n{new_line}\n"
        env_path.write_text(new_content)
        logger.info(f"Updated .env: {key}={value}")
