import asyncio
import httpx
from telethon import TelegramClient
from olmas_kashey.core.settings import settings

async def test_groq_proxy():
    print("\n--- Testing Groq Proxy (HTTPX) ---")
    proxy_url = str(settings.proxy.url) if settings.proxy.enabled and settings.proxy.url else None
    if not proxy_url:
        print("Proxy is disabled in .env")
        return

    print(f"Testing with proxy: {proxy_url}")
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=10.0) as client:
            response = await client.get("https://api.groq.com/openai/v1/models")
            print(f"✅ Groq Proxy Success! Status: {response.status_code}")
    except Exception as e:
        print(f"❌ Groq Proxy Failed: {e}")
        if "socksio" in str(e):
            print("💡 TIP: Run 'pip install \"httpx[socks]\"' to fix this.")

async def test_telegram_proxy():
    print("\n--- Testing Telegram Proxy (Telethon) ---")
    proxy_config = settings.proxy.formatted_proxy()
    if not proxy_config:
        print("Proxy is disabled in .env")
        return

    print(f"Testing with config: {proxy_config['proxy_type']}://{proxy_config['addr']}:{proxy_config['port']} (Auth: {'Yes' if proxy_config['username'] else 'No'})")
    
    # We try a simple connect without full start
    client = TelegramClient(
        'proxy_test_session',
        settings.telegram.api_id,
        settings.telegram.api_hash,
        proxy=proxy_config
    )
    try:
        await client.connect()
        if await client.is_user_authorized():
            print("✅ Telegram Proxy Success! (Already authorized)")
        else:
            print("✅ Telegram Proxy Success! (Connected, but login needed)")
        await client.disconnect()
    except Exception as e:
        print(f"❌ Telegram Proxy Failed: {e}")
        if "Authentication Required" in str(e) or "authentication failure" in str(e).lower():
            print("💡 TIP: Login/Parol noto'g'ri yoki bu port SOCKS5 emas, balki HTTP bo'lishi mumkin.")

if __name__ == "__main__":
    asyncio.run(test_groq_proxy())
    asyncio.run(test_telegram_proxy())
