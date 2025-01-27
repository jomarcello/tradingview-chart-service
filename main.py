from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
import asyncio
import base64
from typing import Optional
import os
import redis.asyncio as redis
import logging
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI()

# Initialize Redis
redis_client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))

async def get_cached_chart(cache_key: str) -> Optional[str]:
    """Get cached chart from Redis"""
    try:
        cached = await redis_client.get(cache_key)
        if cached:
            logger.info(f"Cache hit for {cache_key}")
            return cached.decode('utf-8')
    except Exception as e:
        logger.error(f"Redis error: {str(e)}")
    return None

async def cache_chart(cache_key: str, chart_data: str, ttl: int = 900):
    """Cache chart in Redis with 15 min TTL"""
    try:
        await redis_client.setex(cache_key, ttl, chart_data)
        logger.info(f"Cached chart for {cache_key}")
    except Exception as e:
        logger.error(f"Redis error: {str(e)}")

async def capture_tradingview_chart(symbol: str, interval: str = "1h", theme: str = "dark") -> str:
    """Capture TradingView chart using Playwright"""
    try:
        # Build TradingView URL
        url = f"https://www.tradingview.com/chart/?symbol={symbol}&interval={interval}"
        
        async with async_playwright() as p:
            # Launch browser
            browser = await p.chromium.launch()
            page = await browser.new_page()
            
            # Set viewport
            await page.set_viewport_size({"width": 1200, "height": 800})
            
            # Navigate to TradingView
            await page.goto(url, wait_until="networkidle", timeout=15000)
            
            # Wait for chart to load
            await page.wait_for_selector(".chart-container", timeout=15000)
            
            # Add technical indicators
            await page.evaluate("""() => {
                window.TradingView.activeChart().executeActionById('INSERT_INDICATOR_PACKAGE_MACD');
                window.TradingView.activeChart().executeActionById('INSERT_INDICATOR_PACKAGE_RSI');
                window.TradingView.activeChart().executeActionById('INSERT_INDICATOR_PACKAGE_BB');
            }""")
            
            # Wait for indicators to load
            await asyncio.sleep(2)
            
            # Take screenshot
            screenshot = await page.screenshot(
                clip={"x": 0, "y": 0, "width": 1200, "height": 800},
                type="png"
            )
            
            # Close browser
            await browser.close()
            
            # Encode screenshot
            return base64.b64encode(screenshot).decode('utf-8')
            
    except Exception as e:
        logger.error(f"Error capturing chart: {str(e)}")
        # Return error image
        with open("chart_error.png", "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')

@app.get("/screenshot")
async def get_chart_screenshot(symbol: str, interval: str = "1h", theme: str = "dark"):
    """Get chart screenshot with caching"""
    try:
        # Create cache key
        cache_key = f"chart:{symbol}:{interval}:{theme}"
        
        # Try to get from cache
        cached_chart = await get_cached_chart(cache_key)
        if cached_chart:
            return JSONResponse({
                "status": "success",
                "image": cached_chart,
                "cached": True
            })
            
        # Capture new screenshot
        chart_data = await capture_tradingview_chart(symbol, interval, theme)
        
        # Cache the result
        await cache_chart(cache_key, chart_data)
        
        return JSONResponse({
            "status": "success",
            "image": chart_data,
            "cached": False
        })
        
    except Exception as e:
        logger.error(f"Error in screenshot endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
