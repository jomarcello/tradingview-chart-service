from fastapi import FastAPI, HTTPException, Response
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
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Log to console
        logging.handlers.RotatingFileHandler(
            '/tmp/chart_service.log',  # Use /tmp for Railway
            maxBytes=10485760,  # 10MB
            backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)

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

async def capture_tradingview_chart(symbol: str, interval: str = "1h", theme: str = "dark", max_retries: int = 2) -> Tuple[Optional[bytes], bool]:
    """Capture TradingView chart with retries and detailed logging"""
    logger.info(f"Starting chart capture for {symbol} {interval}")
    
    for attempt in range(max_retries):
        try:
            # Get fresh proxy
            proxy = await rotate_proxy()
            logger.info(f"Using proxy: {proxy if proxy else 'direct connection'}")
            
            # Build TradingView URL - use chart layout without sidebar
            url = f"https://www.tradingview.com/chart/?symbol={symbol}&interval={interval}&hidesidetoolbar=1"
            logger.info(f"Accessing URL: {url}")
            
            async with async_playwright() as p:
                # Launch browser with optimized settings
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-accelerated-2d-canvas',
                        '--disable-gpu',
                        '--disable-extensions',
                        '--disable-sync',
                        '--disable-background-networking',
                        '--disable-default-apps',
                        '--disable-translate',
                        '--disable-web-security',  # Allow cross-origin requests
                        '--no-first-run',
                        '--no-zygote',
                        '--single-process'
                    ]
                )
                logger.info("Browser launched successfully")

                # Create new page with optimized settings
                context = await browser.new_context(
                    viewport={'width': 1280, 'height': 800},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    bypass_csp=True,  # Bypass Content Security Policy
                    ignore_https_errors=True
                )
                page = await context.new_page()
                logger.info("New page created")

                # Set shorter timeouts
                page.set_default_timeout(15000)
                page.set_default_navigation_timeout(15000)

                # Navigate with timeout
                try:
                    await page.goto(url, wait_until="networkidle", timeout=60000)
                    logger.info("Page loaded successfully")
                except Exception as e:
                    logger.error(f"Page load timeout: {str(e)}")
                    raise
                
                # Wait for chart container
                try:
                    # Wait longer for initial page load
                    await page.wait_for_selector(".chart-container", timeout=30000)
                    logger.info("Chart container found")
                    
                    # Wait for price axis to appear (indicates chart is loaded)
                    await page.wait_for_selector(".price-axis", timeout=30000)
                    logger.info("Price axis found")
                    
                    # Wait for candlesticks to appear
                    await page.wait_for_selector(".chart-markup-table", timeout=30000)
                    logger.info("Chart markup found")
                    
                    # Try to close any popups
                    try:
                        # Wait for and click any "Got it" buttons
                        got_it_buttons = await page.query_selector_all('button:has-text("Got it")')
                        for button in got_it_buttons:
                            await button.click()
                            logger.info("Closed 'Got it' popup")
                    except Exception as e:
                        logger.info(f"No 'Got it' popup found: {str(e)}")

                    # Hide elements using JavaScript
                    await page.evaluate("""() => {
                        // Hide right toolbar
                        const rightToolbar = document.querySelector('.right-toolbar');
                        if (rightToolbar) rightToolbar.style.display = 'none';
                        
                        // Hide any popups
                        const popups = document.querySelectorAll('[role="dialog"]');
                        popups.forEach(popup => popup.style.display = 'none');
                        
                        // Hide header
                        const header = document.querySelector('header');
                        if (header) header.style.display = 'none';
                        
                        // Hide bottom toolbar
                        const bottomToolbar = document.querySelector('.bottom-toolbar');
                        if (bottomToolbar) bottomToolbar.style.display = 'none';
                    }""")
                    logger.info("Hidden UI elements")

                    # Wait for loading indicator to disappear
                    await page.wait_for_selector(".loading-indicator", state="hidden", timeout=30000)
                    logger.info("Loading completed")
                    
                    # Extra wait to ensure everything is rendered
                    await asyncio.sleep(10)
                    logger.info("Extra wait completed")
                    
                    # Take screenshot with better quality
                    screenshot = await page.screenshot(
                        type='png',
                        scale=2,  # Higher resolution
                        full_page=False,
                        clip={
                            'x': 0,
                            'y': 0,
                            'width': 1280,
                            'height': 800
                        }
                    )
                    logger.info("Screenshot captured successfully")
                    
                    # Close browser
                    await browser.close()
                    logger.info("Browser closed")
                    
                    return screenshot, True
                    
                except Exception as e:
                    logger.error(f"Chart container or elements not found: {str(e)}")
                    raise
                
        except Exception as e:
            logger.error(f"Error in attempt {attempt + 1}: {str(e)}")
            if attempt == max_retries - 1:
                raise
            
            await asyncio.sleep(2)  # Wait before retry
            
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
            await cache_chart(cache_key, base64.b64encode(chart_data).decode('utf-8'))
            logger.info(f"New chart cached for {symbol}")
        
        return JSONResponse({
            "status": "success",
            "image": base64.b64encode(chart_data).decode('utf-8'),
            "cached": False,
            "error_fallback": not success
        })
        
    except Exception as e:
        logger.error(f"Error in screenshot endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/chart")
async def get_chart(symbol: str, interval: str = "15m", theme: str = "dark"):
    """Get chart screenshot with improved error handling and logging"""
    try:
        # Check cache first
        cache_key = f"chart:{symbol}:{interval}:{theme}"
        cached_chart, is_cached = await get_cached_chart(cache_key)
        
        if is_cached:
            logger.info(f"Returning cached chart for {symbol}")
            # Convert cached base64 back to bytes
            image_bytes = base64.b64decode(cached_chart)
            return Response(content=image_bytes, media_type="image/png")
        
        # Capture new chart
        logger.info(f"Capturing new chart for {symbol}")
        screenshot, success = await capture_tradingview_chart(symbol, interval, theme)
        
        if not success or not screenshot:
            raise HTTPException(status_code=500, detail="Failed to capture chart")
        
        # Cache the screenshot as base64
        base64_image = base64.b64encode(screenshot).decode('utf-8')
        await cache_chart(cache_key, base64_image)
        logger.info(f"New chart cached for {symbol}")
        
        # Return the raw bytes
        return Response(content=screenshot, media_type="image/png")
        
    except Exception as e:
        logger.error(f"Error getting chart: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/logs")
async def get_logs():
    """Get the last 100 lines of logs"""
    try:
        with open("/tmp/chart_service.log", "r") as f:
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
