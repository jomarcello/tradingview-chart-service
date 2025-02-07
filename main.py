from fastapi import FastAPI, HTTPException, Response
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
import base64
from io import BytesIO
import logging
import time
import os
from typing import Optional, Tuple
import urllib.parse
import traceback

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

# Create downloads directory
DOWNLOADS_DIR = '/tmp/downloads'
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

def setup_driver():
    """Setup Chrome driver with optimized settings"""
    chrome_options = Options()
    chrome_options.add_argument('--headless')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--start-maximized')  # Start maximized
    chrome_options.add_argument('--kiosk')  # This forces fullscreen
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument('--disable-infobars')
    chrome_options.add_argument('--disable-notifications')
    chrome_options.add_argument('--hide-scrollbars')
    
    # Set download directory
    prefs = {
        "download.default_directory": DOWNLOADS_DIR,
        "download.prompt_for_download": False,
        "download.directory_upgrade": True
    }
    chrome_options.add_experimental_option("prefs", prefs)
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_window_size(1920, 1080)  # Set a consistent window size
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
            # Use exact TradingView URL format
            encoded_symbol = urllib.parse.quote(f"FX:{symbol}")
            url = f"https://www.tradingview.com/chart/?symbol={encoded_symbol}"
            logger.info(f"Generated TradingView URL: {url}")
            logger.info(f"Starting chart capture for {symbol}")
            
            driver = setup_driver()
            try:
                # Load the page
                driver.get(url)
                logger.info("Page loaded successfully")
                
                # Wait for chart to load
                logger.info("Waiting for chart container...")
                chart_element = WebDriverWait(driver, 20).until(
                    EC.presence_of_element_located((By.CLASS_NAME, "chart-container"))
                )
                logger.info("Chart container found")
                
                # Wait for chart to render
                logger.info("Waiting for chart to render...")
                time.sleep(5)
                logger.info("Chart should be rendered now")
                
                # Hide UI elements
                logger.info("Hiding UI elements...")
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
                        '.chart-controls-bar'
                    ];
                    
                    elementsToHide.forEach(selector => {
                        const elements = document.querySelectorAll(selector);
                        elements.forEach(el => {
                            if (el) el.style.display = 'none';
                        });
                    });
                """)
                logger.info("UI elements hidden")
                
                # Take screenshot
                logger.info("Taking screenshot...")
                screenshot = driver.get_screenshot_as_png()
                logger.info(f"Screenshot taken, size: {len(screenshot)} bytes")
                
                return screenshot, True
                
            except Exception as e:
                logger.error(f"Error during chart capture: {str(e)}")
                logger.error(f"Full error traceback: {traceback.format_exc()}")
                if attempt < max_retries - 1:
                    logger.info(f"Retrying... ({attempt + 2}/{max_retries})")
                    continue
                return None, False
                
            finally:
                try:
                    driver.quit()
                    logger.info("Browser closed")
                except Exception as e:
                    logger.error(f"Error closing browser: {str(e)}")
                
        except Exception as e:
            logger.error(f"Error setting up chart capture: {str(e)}")
            logger.error(f"Full error traceback: {traceback.format_exc()}")
            if attempt < max_retries - 1:
                logger.info(f"Retrying... ({attempt + 2}/{max_retries})")
                continue
            return None, False
            
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
    uvicorn.run(app, host="0.0.0.0", port=8080)
