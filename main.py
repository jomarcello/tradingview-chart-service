from fastapi import FastAPI, HTTPException, Response
from fastapi.responses import JSONResponse
from playwright.async_api import async_playwright
import asyncio
import base64
from typing import Optional, Tuple
import os
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

async def capture_tradingview_chart(symbol: str, interval: str = "1h", theme: str = "dark", max_retries: int = 2) -> Tuple[Optional[bytes], bool]:
    """Capture TradingView chart"""
    for attempt in range(max_retries):
        try:
            # Construct URL
            url = f"https://www.tradingview.com/chart/?symbol={symbol}&interval={interval}&hidesidetoolbar=1"
            logger.info(f"Starting chart capture for {symbol} {interval}")
            
            # Use direct connection without proxy
            logger.info("Using direct connection")
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
                        '--disable-web-security',
                        '--no-first-run',
                        '--no-zygote',
                        '--single-process'
                    ]
                )
                logger.info("Browser launched successfully")

                # Create new page with optimized settings
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},  
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    bypass_csp=True,
                    ignore_https_errors=True
                )
                page = await context.new_page()
                logger.info("New page created")

                # Set longer timeouts for better loading
                page.set_default_timeout(30000)
                page.set_default_navigation_timeout(30000)

                # Navigate and wait for full load
                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    logger.info("Page loaded successfully")

                    # Wait for chart container
                    await page.wait_for_selector(".chart-container", timeout=30000)
                    logger.info("Chart container found")

                    # Wait for price axis and chart to be fully loaded
                    await page.wait_for_selector(".price-axis", timeout=30000)
                    await page.wait_for_selector(".chart-markup-table", timeout=30000)
                    
                    # Hide elements using JavaScript
                    await page.evaluate("""() => {
                        // Make chart container full screen
                        const container = document.querySelector('.chart-container');
                        if (container) {
                            container.style.width = '100vw';
                            container.style.height = '100vh';
                            container.style.position = 'fixed';
                            container.style.top = '0';
                            container.style.left = '0';
                            container.style.zIndex = '9999';
                        }
                        
                        // Hide ALL UI elements
                        const elementsToHide = [
                            '.header-chart-panel',
                            '.left-toolbar',
                            '.right-toolbar',
                            '.bottom-toolbar',
                            '.layout__area--left',
                            '.layout__area--right',
                            'header',
                            '.drawingToolbar',
                            '.chart-controls-bar',
                            '.control-bar',
                            '.botbar',
                            '[role="dialog"]'
                        ];
                        
                        elementsToHide.forEach(selector => {
                            const elements = document.querySelectorAll(selector);
                            elements.forEach(el => {
                                if (el) el.style.display = 'none';
                            });
                        });
                        
                        // Force chart to take full width/height
                        const chartContainer = document.querySelector('.chart-container');
                        if (chartContainer) {
                            chartContainer.style.width = '100%';
                            chartContainer.style.height = '100%';
                        }
                    }""")
                    logger.info("Hidden UI elements and maximized chart")

                    # Wait a bit for the chart to adjust
                    await asyncio.sleep(2)
                    
                    # Take full page screenshot
                    screenshot = await page.screenshot(
                        type='png',
                        scale='device',
                        full_page=True
                    )
                    logger.info("Screenshot captured successfully")
                    
                    # Close browser
                    await browser.close()
                    logger.info("Browser closed")
                    
                    return screenshot, True
                    
                except Exception as e:
                    logger.error(f"Error during chart capture: {str(e)}")
                    raise
                    
        except Exception as e:
            logger.error(f"Error in attempt {attempt + 1}: {str(e)}")
            if attempt == max_retries - 1:
                raise

    return None, False

@app.get("/chart")
async def get_chart(symbol: str, interval: str = "15m", theme: str = "dark"):
    """Get chart screenshot"""
    try:
        # Capture new chart
        logger.info(f"Capturing new chart for {symbol}")
        screenshot, success = await capture_tradingview_chart(symbol, interval, theme)
        
        if success and screenshot:
            logger.info(f"New chart captured for {symbol}")
            return Response(content=screenshot, media_type="image/png")
        else:
            logger.error("Failed to capture chart")
            raise HTTPException(status_code=500, detail="Failed to capture chart")
            
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
            "browser": browser_status,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {"status": "unhealthy", "error": str(e)}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
