from fastapi import FastAPI, HTTPException, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import base64
from io import BytesIO
import logging
import time
import os
from typing import Optional, Tuple

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            '/tmp/chart_service.log',
            maxBytes=10485760,
            backupCount=5
        )
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI
app = FastAPI()

def setup_driver():
    """Setup Chrome driver with optimized settings"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument('--disable-infobars')
    chrome_options.add_argument('--disable-notifications')
    chrome_options.add_argument('--hide-scrollbars')
    chrome_options.add_argument('--log-level=3')
    chrome_options.add_argument('--silent')
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(60)
        logger.info("Chrome driver setup successful")
        return driver
    except Exception as e:
        logger.error(f"Failed to setup Chrome driver: {str(e)}")
        raise

async def capture_tradingview_chart(symbol: str, interval: str = "1h", theme: str = "dark", max_retries: int = 2) -> Tuple[Optional[bytes], bool]:
    """Capture TradingView chart"""
    for attempt in range(max_retries):
        try:
            # Construct URL with chart ID and FX prefix for forex pairs
            symbol_with_prefix = f"FX:{symbol}" if "USD" in symbol or "EUR" in symbol or "GBP" in symbol or "JPY" in symbol else symbol
            url = f"https://www.tradingview.com/chart/aBxuyRGJ/?symbol={symbol_with_prefix}"
            logger.info(f"Starting chart capture for {symbol_with_prefix} {interval}")
            
            driver = setup_driver()
            try:
                # Load the page
                driver.get(url)
                logger.info("Page loaded successfully")
                
                # Wait for chart elements with multiple selectors
                selectors = [
                    "div[class*='chart-container']",
                    "div[class*='chart-markup']",
                    "div[class*='chart-widget']",
                    "div[class*='layout__area--center']"
                ]
                
                chart_element = None
                for selector in selectors:
                    logger.info(f"Trying selector: {selector}")
                    try:
                        chart_element = WebDriverWait(driver, 10).until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                        )
                        logger.info(f"Found element with selector: {selector}")
                        break
                    except Exception as e:
                        logger.warning(f"Selector {selector} not found: {str(e)}")
                        continue
                
                if not chart_element:
                    logger.error("Could not find any chart element")
                    raise Exception("Chart element not found")
                
                # Hide UI elements
                driver.execute_script("""
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
                    
                    // Force dark theme
                    document.body.className = 'theme-dark';
                """)
                
                # Wait for chart to render
                time.sleep(5)
                
                # Take screenshot
                screenshot = chart_element.screenshot_as_png
                logger.info("Screenshot captured successfully")
                
                return screenshot, True
                
            except Exception as e:
                logger.error(f"Error during chart capture: {str(e)}")
                raise
                
            finally:
                driver.quit()
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
    """Health check endpoint"""
    try:
        # Check if we can launch browser
        browser_status = "unknown"
        try:
            driver = setup_driver()
            driver.quit()
            browser_status = "healthy"
        except Exception as e:
            browser_status = f"unhealthy: {str(e)}"
        
        return {
            "status": "healthy",
            "browser": browser_status,
            "timestamp": time.strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
