from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
import asyncio
import base64
from typing import Optional, Tuple
import os
import redis.asyncio as redis
import logging
from datetime import datetime, timedelta
import logging.handlers
import aiohttp

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Add file handler for detailed logging
file_handler = logging.handlers.RotatingFileHandler(
    'chart_service.log',
    maxBytes=10485760,  # 10MB
    backupCount=5
)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger.addHandler(file_handler)

# Initialize FastAPI
app = FastAPI()

# Initialize Redis with error handling
async def init_redis():
    try:
        client = redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379"))
        await client.ping()
        logger.info("Redis connection established")
        return client
    except Exception as e:
        logger.error(f"Redis connection failed: {str(e)}")
        return None

# Initialize Redis client
redis_client = None

@app.on_event("startup")
async def startup_event():
    global redis_client
    redis_client = await init_redis()

async def get_cached_chart(cache_key: str) -> Tuple[Optional[str], bool]:
    """Get cached chart from Redis with improved error handling"""
    try:
        if not redis_client:
            logger.warning("Redis not available, skipping cache check")
            return None, False
            
        cached = await redis_client.get(cache_key)
        if cached:
            logger.info(f"Cache hit for {cache_key}")
            return cached.decode('utf-8'), True
            
        logger.info(f"Cache miss for {cache_key}")
        return None, False
        
    except Exception as e:
        logger.error(f"Redis error in get_cached_chart: {str(e)}")
        return None, False

async def cache_chart(cache_key: str, chart_data: str, ttl: int = 900):
    """Cache chart in Redis with improved error handling"""
    try:
        if not redis_client:
            logger.warning("Redis not available, skipping cache write")
            return
            
        await redis_client.setex(cache_key, ttl, chart_data)
        logger.info(f"Successfully cached chart for {cache_key}")
        
    except Exception as e:
        logger.error(f"Redis error in cache_chart: {str(e)}")

async def rotate_proxy() -> Optional[str]:
    """Get a fresh proxy from the proxy service"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(os.getenv("PROXY_SERVICE_URL")) as response:
                if response.status == 200:
                    proxy_data = await response.json()
                    return proxy_data.get("proxy")
    except Exception as e:
        logger.error(f"Error getting proxy: {str(e)}")
    return None

async def capture_tradingview_chart(symbol: str, interval: str = "1h", theme: str = "dark", max_retries: int = 2) -> Tuple[Optional[str], bool]:
    """Capture TradingView chart with retries and detailed logging"""
    logger.info(f"Starting chart capture for {symbol} {interval}")
    
    for attempt in range(max_retries):
        try:
            # Get fresh proxy
            proxy = await rotate_proxy()
            logger.info(f"Using proxy: {proxy if proxy else 'direct connection'}")
            
            # Build TradingView URL
            url = f"https://www.tradingview.com/chart/?symbol={symbol}&interval={interval}"
            logger.info(f"Accessing URL: {url}")
            
            async with async_playwright() as p:
                # Launch browser with proxy if available
                browser_args = [
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage'
                ]
                if proxy:
                    browser_args.append(f'--proxy-server={proxy}')
                
                browser = await p.chromium.launch(
                    args=browser_args,
                    timeout=60000  # 60 second timeout
                )
                
                logger.info("Browser launched successfully")
                
                # Create new context with custom viewport
                context = await browser.new_context(
                    viewport={'width': 1200, 'height': 800},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                )
                
                page = await context.new_page()
                logger.info("New page created")
                
                # Navigate with timeout
                try:
                    await page.goto(url, wait_until="networkidle", timeout=60000)
                    logger.info("Page loaded successfully")
                except Exception as e:
                    logger.error(f"Page load timeout: {str(e)}")
                    raise
                
                # Wait for chart container
                try:
                    await page.wait_for_selector(".chart-container", timeout=60000)
                    logger.info("Chart container found")
                    
                    # Try to close any popups
                    try:
                        # Wait for and click the "Got it" button if present
                        got_it_button = await page.wait_for_selector('button:text("Got it")', timeout=5000)
                        if got_it_button:
                            await got_it_button.click()
                            logger.info("Closed 'Got it' popup")
                    except:
                        logger.info("No 'Got it' popup found")

                    try:
                        # Wait for and click the "Reconnect" button if present
                        reconnect_button = await page.wait_for_selector('button:text("Reconnect")', timeout=5000)
                        if reconnect_button:
                            await reconnect_button.click()
                            logger.info("Clicked 'Reconnect' button")
                            # Wait a bit for the reconnection
                            await asyncio.sleep(5)
                    except:
                        logger.info("No 'Reconnect' button found")
                    
                    # Wait for the loading indicator to disappear
                    await page.wait_for_selector(".loading-indicator", state="hidden", timeout=60000)
                    logger.info("Chart loading completed")
                    
                    # Wait for the main chart element
                    await page.wait_for_selector(".chart-markup-table", timeout=60000)
                    logger.info("Chart markup loaded")
                    
                    # Wait a bit longer for everything to settle
                    await asyncio.sleep(5)
                    
                except Exception as e:
                    logger.error(f"Chart container or elements not found: {str(e)}")
                    raise
                
                # Take screenshot
                screenshot = await page.screenshot(
                    clip={"x": 0, "y": 0, "width": 1200, "height": 800},
                    type="png"
                )
                logger.info("Screenshot captured successfully")
                
                # Close browser
                await browser.close()
                logger.info("Browser closed")
                
                # Return successful screenshot
                return base64.b64encode(screenshot).decode('utf-8'), True
                
        except Exception as e:
            logger.error(f"Attempt {attempt + 1}/{max_retries} failed: {str(e)}")
            if attempt < max_retries - 1:
                wait_time = 10 * (attempt + 1)  # Exponential backoff
                logger.info(f"Waiting {wait_time} seconds before retry")
                await asyncio.sleep(wait_time)
            else:
                logger.error("All retry attempts failed")
                # Return error image on final attempt
                try:
                    with open("chart_error.png", "rb") as f:
                        return base64.b64encode(f.read()).decode('utf-8'), False
                except Exception as read_error:
                    logger.error(f"Failed to read error image: {str(read_error)}")
                    return None, False

@app.get("/screenshot")
async def get_chart_screenshot(symbol: str, interval: str = "1h", theme: str = "dark"):
    """Get chart screenshot with improved error handling and logging"""
    logger.info(f"Received screenshot request for {symbol} {interval}")
    
    try:
        # Validate inputs
        if not symbol or not interval:
            raise HTTPException(status_code=400, detail="Missing required parameters")
            
        # Create cache key
        cache_key = f"chart:{symbol}:{interval}:{theme}"
        
        # Try to get from cache
        cached_chart, is_cached = await get_cached_chart(cache_key)
        if cached_chart:
            logger.info(f"Returning cached chart for {symbol}")
            return JSONResponse({
                "status": "success",
                "image": cached_chart,
                "cached": True
            })
            
        # Capture new screenshot
        chart_data, success = await capture_tradingview_chart(symbol, interval, theme)
        if not chart_data:
            raise HTTPException(status_code=500, detail="Failed to generate chart")
            
        # Cache successful screenshots
        if success:
            await cache_chart(cache_key, chart_data)
            logger.info(f"New chart cached for {symbol}")
        
        return JSONResponse({
            "status": "success",
            "image": chart_data,
            "cached": False,
            "error_fallback": not success
        })
        
    except Exception as e:
        logger.error(f"Error in screenshot endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/logs")
async def get_logs():
    """Get the last 100 lines of logs"""
    try:
        with open("chart_service.log", "r") as f:
            lines = f.readlines()[-100:]
            return {"logs": "".join(lines)}
    except Exception as e:
        logger.error(f"Error reading logs: {str(e)}")
        return {"error": str(e)}

@app.get("/health")
async def health_check():
    """Enhanced health check endpoint"""
    try:
        # Check Redis connection
        redis_status = "healthy" if redis_client else "unavailable"
        
        # Check if we can launch browser
        browser_status = "unknown"
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(
                    args=['--no-sandbox', '--disable-setuid-sandbox']
                )
                await browser.close()
                browser_status = "healthy"
        except Exception as e:
            browser_status = f"error: {str(e)}"
        
        return {
            "status": "healthy",
            "redis": redis_status,
            "browser": browser_status,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
