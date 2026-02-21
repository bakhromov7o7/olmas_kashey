import json
import random
from typing import Optional
from loguru import logger
from groq import AsyncGroq
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
                self.client = AsyncGroq(api_key=self.api_key)
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

    async def get_join_delay(self) -> float:
        """
        Calculates a dynamic delay before joining a new group.
        """
        if not self.client:
            return self._fallback_join_delay()

        try:
            user_prompt = """
We are about to join a new Telegram group. 
To avoid triggering spam filters, we need a realistic human-like delay before clicking 'join'.
Calculate a random delay in seconds (can be a float) between 3 and 15 seconds.

Return JSON:
{
    "recommended_join_delay_seconds": <float>
}
"""
            response = await self._call_ai(user_prompt)
            if response and "recommended_join_delay_seconds" in response:
                delay = float(response["recommended_join_delay_seconds"])
                # Sanity check bounds
                if 1.0 <= delay <= 30.0:
                    logger.info(f"SmartAdvisor (AI): Recommended join delay {delay:.1f}s")
                    return delay
                    
            return self._fallback_join_delay()
            
        except Exception as e:
            logger.warning(f"SmartAdvisor failed to calculate join delay (using fallback): {e}")
            return self._fallback_join_delay()

    async def _call_ai(self, user_prompt: str) -> Optional[dict]:
        """Helper to call Groq API with failover."""
        for model in [self.primary_model, self.fallback_model, settings.groq.model]:
            try:
                response = await self.client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": self.SYSTEM_PROMPT},
                        {"role": "user", "content": user_prompt}
                    ],
                    max_tokens=150,
                    temperature=0.7,
                    response_format={"type": "json_object"}
                )
                
                content = response.choices[0].message.content
                if content:
                    return json.loads(content)
            except Exception as e:
                logger.info(f"SmartAdvisor API error with model {model}: {e}")
                continue # Try next model
        return None

    def _fallback_floodwait(self, floodwait_seconds: int) -> float:
        """Fallback calculation if AI fails."""
        # Just add a human-like jitter on top of the MANDATORY wait
        padding = random.uniform(5.0, 45.0)
        calculated = floodwait_seconds + padding
        logger.info(f"SmartAdvisor (Fallback): Calculated {calculated:.1f}s for FloodWait {floodwait_seconds}s")
        return calculated

    def _fallback_join_delay(self) -> float:
        """Fallback logic if AI fails."""
        delay = random.uniform(3.0, 10.0)
        logger.info(f"SmartAdvisor (Fallback): Calculated join delay {delay:.1f}s")
        return delay

# Singleton instance
smart_advisor = SmartAdvisor()
