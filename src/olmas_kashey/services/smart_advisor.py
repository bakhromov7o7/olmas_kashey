import json
import random
from typing import Optional
from loguru import logger
from typing import Optional
from loguru import logger
from groq import AsyncGroq
import httpx
from olmas_kashey.core.settings import settings

class SmartAdvisor:
    """
    AI-powered advisor to calculate dynamic, human-like sleep and join delays
    to maximize throughput while minimizing the risk of Telegram bans.
    """

    SYSTEM_PROMPT = """You are an expert Telegram Automation Safety Advisor.
Your job is to recommend safe sleep durations to avoid account bans.
Output MUST be a valid JSON object. Do not include markdown formatting or explanations.
"""

    def __init__(self):
        self.api_key = settings.groq.api_key
        # Use a fast, reliable model for quick calculations. 
        # Llama 3 is extremely fast on Groq.
        self.primary_model = "llama3-8b-8192" 
        self.fallback_model = "mixtral-8x7b-32768"
        self.client = None

        if self.api_key:
            try:
                # Proxy support for Groq
                proxy_url = str(settings.proxy.url) if settings.proxy.enabled and settings.proxy.url else None
                client_kwargs = {"api_key": self.api_key}
                
                if proxy_url:
                    logger.info(f"Using proxy for Groq (SmartAdvisor): {proxy_url}")
                    client_kwargs["http_client"] = httpx.AsyncClient(
                        proxy=proxy_url,
                        timeout=30.0
                    )
                self.client = AsyncGroq(**client_kwargs)
            except Exception as e:
                logger.error(f"Failed to initialize Groq client for SmartAdvisor: {e}")

    async def get_floodwait_sleep(self, floodwait_seconds: int, context: Optional[dict] = None) -> float:
        """
        Calculates a safe sleep duration when a FloodWaitError is encountered.
        """
        if not self.client:
            return self._fallback_floodwait(floodwait_seconds)

        try:
            context_str = ""
            if context:
                context_str = f"""
Current Account Health Context:
- Groups joined today: {context.get('joined_today', 0)}
- Lifetime bans/blocks: {context.get('ban_count', 0)}
- Healthy status: {context.get('is_healthy', True)}
- Eco Mode: {context.get('eco_mode', False)}
"""
            user_prompt = f"""
Telegram has imposed a penalty wait of {floodwait_seconds} seconds. 
{context_str}

YOUR MISSION: Decide how long the bot should stay OFFLINE (Cooldown) to avoid being flagged as a bot.

CRITICAL SAFETY RULES:
1. **Never** just add seconds. Adding 10-60 seconds is USELESS and looks like a robot waiting for a timer.
2. **Think like a human**: If you were blocked for 15 minutes, you wouldn't come back in 16 minutes. You would wait an hour or two.
3. **MANDATORY OVERHEAD**: 
   - For any penalty > 120s, you MUST add at least 30 to 120 EXTRA MINUTES of rest.
   - For penalties > 600s, recommend staying offline for 2-6 hours.
   - If 'ban_count' is > 0 or health is poor, stay offline for 12-24 hours.

Analyze the metrics and recommend a TOTAL sleep duration (Penalty + Cooldown).
The user wants the bot to "shut down" for a safe duration determined by YOU.

Return JSON:
{{
    "total_off_time_seconds": <float>,
    "extra_cooldown_minutes": <int>,
    "reasoning": "<brief_explanation_in_uzbek_about_why_we_stay_offline_this_long>"
}}
"""
            response = await self._call_ai(user_prompt)
            if response and "total_off_time_seconds" in response:
                recommended = float(response["total_off_time_seconds"])
                
                # 🛡️ AGGRESSIVE SAFETY FLOOR: 
                # Avoid "The Robotic Interval": if penalty > 2 mins, add at least 30 mins (1800s) extra.
                if floodwait_seconds > 120:
                    min_safe = floodwait_seconds + 1800
                    if recommended < min_safe:
                        logger.warning(f"SmartAdvisor AI recommended too little ({recommended:.1f}s). Enforcing massive safety floor: {min_safe:.1f}s")
                        recommended = min_safe
                else:
                    # For short waits, at least penalty + 2 mins
                    min_safe = floodwait_seconds + 120
                    if recommended < min_safe:
                        recommended = min_safe

                if recommended >= floodwait_seconds:
                    reason = response.get('reasoning', 'Human-like rest')
                    logger.info(f"SmartAdvisor (AI): Strategic Cooldown {recommended/60:.1f}m for Penalty {floodwait_seconds/60:.1f}m. Reason: {reason}")
                    return recommended
                
            return self._fallback_floodwait(floodwait_seconds)
            
        except Exception as e:
            logger.warning(f"SmartAdvisor failed to calculate FloodWait (using fallback): {e}")
            return self._fallback_floodwait(floodwait_seconds)

    async def get_join_delay(self, context: Optional[dict] = None) -> float:
        """
        Calculates a dynamic delay before joining a new group.
        """
        if not self.client:
            return self._fallback_join_delay()

        try:
            context_str = self._format_context(context)
            user_prompt = f"""
We are about to join a new Telegram group. 
{context_str}
To avoid triggering spam filters, we need a realistic human-like delay before clicking 'join'.
Calculate a random delay in seconds (can be a float) between 10 and 45 seconds.

Return JSON:
{{
    "recommended_join_delay_seconds": <float>
}}
"""
            response = await self._call_ai(user_prompt)
            if response and "recommended_join_delay_seconds" in response:
                delay = float(response["recommended_join_delay_seconds"])
                # Sanity check bounds
                if 1.0 <= delay <= 120.0:
                    logger.info(f"SmartAdvisor (AI): Recommended join delay {delay:.1f}s")
                    return delay
                    
            return self._fallback_join_delay()
            
        except Exception as e:
            logger.warning(f"SmartAdvisor failed to calculate join delay: {e}")
            return self._fallback_join_delay()

    async def get_iteration_delay(self, context: Optional[dict] = None) -> float:
        """
        Calculates a strategic delay between processing keyword batches.
        """
        if not self.client:
            return random.uniform(300, 900) # 5-15 mins fallback

        try:
            context_str = self._format_context(context)
            user_prompt = f"""
We just finished a discovery batch. 
{context_str}

YOUR MISSION: Decide how long the bot should rest before starting the NEXT keyword/batch.
Think like a human: Don't just do fixed intervals. Sometimes wait 10 mins, sometimes 45 mins. 
If 'is_healthy' is false or joins are high today, be very conservative (30-120 mins).
If everything is clean, 5-15 mins is typical for a human.

Return JSON:
{{
    "recommended_rest_seconds": <float>,
    "reasoning": "<brief_explanation_in_uzbek>"
}}
"""
            response = await self._call_ai(user_prompt)
            if response and "recommended_rest_seconds" in response:
                delay = float(response["recommended_rest_seconds"])
                # Sanity bounds: 2 mins to 4 hours
                delay = max(120.0, min(delay, 14400.0))
                logger.info(f"SmartAdvisor (AI): Strategic Rest {delay/60:.1f}m. Reason: {response.get('reasoning')}")
                return delay
                
            return random.uniform(300, 900)
        except Exception as e:
            logger.warning(f"SmartAdvisor failed iteration delay: {e}")
            return random.uniform(300, 900)

    async def get_action_delay(self, action_type: str, context: Optional[dict] = None) -> float:
        """
        Calculates a small jittery delay for a specific action (search, join, resolve).
        """
        if not self.client:
            return random.uniform(2.0, 5.0)

        # We don't want to call AI for EVERY tiny action, so we use a small heuristic 
        # based on context or occasionally call AI for a 'strategy'
        if random.random() > 0.1: # Only call AI 10% of the time for micro-delays, otherwise jitter
            return random.uniform(1.5, 4.0)

        try:
            user_prompt = f"Action Type: {action_type}. Suggest a micro-delay (1-10s) to look human. Return JSON: {{\"delay\": <float>}}"
            response = await self._call_ai(user_prompt)
            return float(response.get("delay", 2.0))
        except:
            return random.uniform(2.0, 5.0)

    async def get_behavior_decision(self, context: Optional[dict] = None) -> dict:
        """
        Decides if the bot should perform a 'decoy' action to look more human.
        """
        if not self.client:
            return {"action": "none"}

        try:
            context_str = self._format_context(context)
            user_prompt = f"""
Current State: {context_str}
Decide if the bot should do a "human-like" decoy action instead of searching.
Actions: 
- "browse": List dialogs and read a few messages.
- "idle": Just sit there for a bit.
- "none": Continue with normal work.

Return JSON:
{{
    "action": "browse" | "idle" | "none",
    "duration_seconds": <float>,
    "reasoning": "<uzbek>"
}}
"""
            response = await self._call_ai(user_prompt)
            return response or {"action": "none"}
        except:
            return {"action": "none"}

    def _format_context(self, context: Optional[dict]) -> str:
        if not context: return "No context available."
        return f"""
- Joined today: {context.get('joined_today', 0)}
- Acc Health: {'Healthy' if context.get('is_healthy', True) else 'Restricted'}
- Eco Mode: {context.get('eco_mode', False)}
- Time: {datetime.now().strftime('%H:%M')}
"""

    async def _call_ai(self, user_prompt: str) -> Optional[dict]:
        """Helper to call AI (Groq only)."""
        if self.client:
            # Try models in order of speed/capability
            models = ["llama-3.3-70b-versatile", "llama3-8b-8192", "mixtral-8x7b-32768"]
            for model in models:
                try:
                    # logger.debug(f"Calling SmartAdvisor AI with model {model}")
                    response = await self.client.chat.completions.create(
                        model=model,
                        messages=[
                            {"role": "system", "content": self.SYSTEM_PROMPT},
                            {"role": "user", "content": user_prompt}
                        ],
                        max_tokens=200,
                        temperature=0.7,
                        response_format={"type": "json_object"}
                    )
                    
                    content = response.choices[0].message.content
                    if content:
                        return json.loads(content)
                except Exception as e:
                    # logger.info(f"SmartAdvisor Groq error with model {model}: {e}")
                    continue 
        return None

    def _fallback_floodwait(self, floodwait_seconds: int) -> float:
        """Fallback calculation if AI fails."""
        padding = random.uniform(600.0, 1800.0) if floodwait_seconds > 60 else random.uniform(30, 90)
        calculated = floodwait_seconds + padding
        logger.info(f"SmartAdvisor (Fallback): Calculated {calculated:.1f}s for FloodWait {floodwait_seconds}s")
        return calculated

    def _fallback_join_delay(self) -> float:
        """Fallback logic if AI fails."""
        delay = random.uniform(5.0, 15.0)
        logger.info(f"SmartAdvisor (Fallback): Calculated join delay {delay:.1f}s")
        return delay

# Singleton instance
smart_advisor = SmartAdvisor()
