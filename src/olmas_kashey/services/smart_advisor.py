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

    async def get_floodwait_sleep(self, floodwait_seconds: int) -> float:
        """
        Calculates a safe sleep duration when a FloodWaitError is encountered.
        """
        if not self.client:
            return self._fallback_floodwait(floodwait_seconds)

        try:
            user_prompt = f"""
Telegram just gave a FloodWait error of {floodwait_seconds} seconds.
Calculate a new sleep duration that is slightly longer than the required wait, adding a realistic human-like delay.
The new sleep should be random, but safe. 

Return JSON:
{{
    "recommended_sleep_seconds": <float>
}}
"""
            response = await self._call_ai(user_prompt)
            if response and "recommended_sleep_seconds" in response:
                recommended = float(response["recommended_sleep_seconds"])
                # Sanity check: ensure it's at least the required wait
                if recommended > floodwait_seconds:
                    logger.info(f"SmartAdvisor (AI): Recommended wait {recommended:.1f}s for FloodWait {floodwait_seconds}s")
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
                    logger.debug(f"SmartAdvisor (AI): Recommended join delay {delay:.1f}s")
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
                logger.debug(f"SmartAdvisor API error with model {model}: {e}")
                continue # Try next model
        return None

    def _fallback_floodwait(self, floodwait_seconds: int) -> float:
        """Fallback calculation if AI fails."""
        padding = random.uniform(5.0, 30.0)
        # Add a multiplier based on the length of the wait (longer waits get more padding)
        multiplier = 1.0 + (random.random() * 0.5) # 1.0 to 1.5x
        calculated = (floodwait_seconds * multiplier) + padding
        logger.debug(f"SmartAdvisor (Fallback): Calculated {calculated:.1f}s for FloodWait {floodwait_seconds}s")
        return calculated

    def _fallback_join_delay(self) -> float:
        """Fallback logic if AI fails."""
        delay = random.uniform(3.0, 10.0)
        logger.debug(f"SmartAdvisor (Fallback): Calculated join delay {delay:.1f}s")
        return delay

# Singleton instance
smart_advisor = SmartAdvisor()
