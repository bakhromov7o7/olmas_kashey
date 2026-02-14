import asyncio
from unittest.mock import AsyncMock
from olmas_kashey.services.discovery_pipeline import DiscoveryPipeline

async def debug():
    pipeline = DiscoveryPipeline(AsyncMock())
    queries, keywords = pipeline.build_query_plan("IELTS Study Club")
    print(f"Generated {len(queries)} queries:")
    for q in queries:
        print(f" - {q}")
    
    if "ielts_prep" in queries:
        print("\nSUCCESS: 'ielts_prep' found.")
    else:
        print("\nFAILURE: 'ielts_prep' NOT found.")

if __name__ == "__main__":
    asyncio.run(debug())
