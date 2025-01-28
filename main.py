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
            # Construct URL with chart ID and FX prefix for forex pairs
            symbol_with_prefix = f"FX:{symbol}" if "USD" in symbol or "EUR" in symbol or "GBP" in symbol or "JPY" in symbol else symbol
            url = f"https://www.tradingview.com/chart/aBxuyRGJ/?symbol={symbol_with_prefix}"
            logger.info(f"Starting chart capture for {symbol_with_prefix} {interval}")
            
            async with async_playwright() as p:
                # Launch browser with optimized settings
                browser = await p.chromium.launch(
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-gpu',
                        '--no-first-run',
                        '--window-size=1920,1080'
                    ]
                )
                logger.info("Browser launched successfully")

                # Create new page with specific viewport
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    device_scale_factor=2,  # Higher resolution
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                )
                page = await context.new_page()
                logger.info("New page created")

                # Navigate and wait for full load
                try:
                    await page.goto(url, wait_until="networkidle", timeout=30000)
                    logger.info("Page loaded successfully")

                    # Wait for essential elements
                    await page.wait_for_selector(".chart-container", timeout=30000)
                    await page.wait_for_selector(".price-axis", timeout=30000)
                    await page.wait_for_selector(".chart-markup-table", timeout=30000)
                    logger.info("Chart elements loaded")

                    # Set chart preferences using JavaScript
                    await page.evaluate("""() => {
                        // Function to wait for an element
                        function waitForElement(selector, timeout = 10000) {
                            return new Promise((resolve, reject) => {
                                const element = document.querySelector(selector);
                                if (element) {
                                    resolve(element);
                                    return;
                                }
                                
                                const observer = new MutationObserver(() => {
                                    const element = document.querySelector(selector);
                                    if (element) {
                                        resolve(element);
                                        observer.disconnect();
                                    }
                                });
                                
                                observer.observe(document.body, {
                                    childList: true,
                                    subtree: true
                                });
                                
                                setTimeout(() => {
                                    observer.disconnect();
                                    reject(new Error(`Timeout waiting for ${selector}`));
                                }, timeout);
                            });
                        }

                        // Hide all toolbars and UI elements
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
                            '[role="dialog"]',
                            '.tv-floating-toolbar'
                        ];
                        
                        elementsToHide.forEach(selector => {
                            const elements = document.querySelectorAll(selector);
                            elements.forEach(el => {
                                if (el) el.style.display = 'none';
                            });
                        });

                        // Maximize chart container
                        const container = document.querySelector('.chart-container');
                        if (container) {
                            container.style.position = 'fixed';
                            container.style.top = '0';
                            container.style.left = '0';
                            container.style.width = '100vw';
                            container.style.height = '100vh';
                            container.style.zIndex = '9999';
                        }

                        // Force dark theme
                        document.body.className = 'theme-dark';
                        
                        // Remove any popups or overlays
                        const popups = document.querySelectorAll('.tv-popup-dialog');
                        popups.forEach(popup => popup.remove());
                    }""")
                    logger.info("Chart preferences set")

                    # Wait for any animations to complete
                    await asyncio.sleep(2)
                    
                    # Take screenshot of the specific chart area
                    chart_element = await page.query_selector('.chart-container')
                    if chart_element:
                        screenshot = await chart_element.screenshot(
                            type='png',
                            scale='device',
                            animations='disabled'
                        )
                        logger.info("Screenshot captured successfully")
                        return screenshot, True
                    else:
                        logger.error("Chart container not found")
                        raise Exception("Chart container not found")

                except Exception as e:
                    logger.error(f"Error during chart capture: {str(e)}")
                    raise

                finally:
                    await browser.close()
                    logger.info("Browser closed")

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
