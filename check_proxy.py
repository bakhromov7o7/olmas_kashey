import asyncio
import httpx
from telethon import TelegramClient
from olmas_kashey.core.settings import settings

async def test_proxy_protocol(protocol):
    print(f"\n--- Testing {protocol.upper()} Proxy ---")
    proxy_url = str(settings.proxy.url).replace(str(settings.proxy.url.scheme), protocol)
    print(f"Testing with: {proxy_url}")
    
    # Test Groq (HTTPX)
    try:
        async with httpx.AsyncClient(proxy=proxy_url, timeout=10.0) as client:
            response = await client.get("https://api.groq.com/openai/v1/models")
            print(f"✅ Groq ({protocol}) Success! Status: {response.status_code}")
    except Exception as e:
        print(f"❌ Groq ({protocol}) Failed: {e}")

    # Test Telegram (Telethon)
    ptype = "socks5" if protocol == "socks5" else "http"
    rdns = True if protocol == "socks5" else False
    proxy_config = {
        'proxy_type': ptype,
        'addr': str(settings.proxy.url.host),
        'port': int(settings.proxy.url.port),
        'username': settings.proxy.url.username,
        'password': settings.proxy.url.password,
        'rdns': rdns
    }
    
    client = TelegramClient(f'test_{protocol}', settings.telegram.api_id, settings.telegram.api_hash, proxy=proxy_config)
    try:
        await client.connect()
        print(f"✅ Telegram ({protocol}) Success!")
        await client.disconnect()
    except Exception as e:
        print(f"❌ Telegram ({protocol}) Failed: {e}")

if __name__ == "__main__":
    if not settings.proxy.enabled or not settings.proxy.url:
        print("Proxy is disabled in .env")
    else:
        asyncio.run(test_proxy_protocol("socks5"))
        asyncio.run(test_proxy_protocol("http"))
