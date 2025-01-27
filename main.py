from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from PIL import Image
import base64
from io import BytesIO
import logging
import time
import os

# Set up logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('chart_service.log')
    ]
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="TradingView Chart Service",
    description="Service for capturing TradingView chart screenshots",
    version="1.0.0"
)

class ChartRequest(BaseModel):
    symbol: str
    timeframe: str

def setup_driver():
    """Setup Chrome driver with required options"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36")
    
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(60)  # Increased timeout
        logger.info("Chrome driver setup successful")
        return driver
    except Exception as e:
        logger.exception("Failed to setup Chrome driver")
        raise

def get_tradingview_url(symbol: str, timeframe: str) -> str:
    """Generate TradingView chart URL"""
    # Map timeframes
    tv_timeframe_map = {
        "1m": "1",
        "5m": "5",
        "15m": "15",
        "30m": "30",
        "1h": "60",
        "4h": "240",
        "1d": "D",
        "1w": "W"
    }
    
    # Map symbols
    tv_symbol_map = {
        "EURUSD": "FX:EURUSD",
        "GBPUSD": "FX:GBPUSD",
        "USDJPY": "FX:USDJPY",
        "BTCUSD": "BINANCE:BTCUSDT",
        "ETHUSD": "BINANCE:ETHUSDT",
        "US30": "DJ:DJI",
        "SPX500": "SP:SPX",
        "NAS100": "NASDAQ:NDX",
        "XAUUSD": "OANDA:XAUUSD"
    }
    
    symbol = tv_symbol_map.get(symbol.upper(), symbol)
    timeframe = tv_timeframe_map.get(timeframe.lower(), timeframe)
    
    return f"https://www.tradingview.com/chart/?symbol={symbol}&interval={timeframe}"

@app.post("/capture-chart")
async def capture_chart(request: ChartRequest):
    """Capture a screenshot of the TradingView chart"""
    start_time = time.time()
    logger.info(f"Starting chart capture for {request.symbol} {request.timeframe}")
    
    try:
        driver = setup_driver()
        url = get_tradingview_url(request.symbol, request.timeframe)
        logger.info(f"Loading URL: {url}")
        
        try:
            # Load the page
            driver.get(url)
            logger.info("Page loaded successfully")
            
            # Wait for any chart element to appear
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
                # Take full page screenshot as fallback
                logger.info("Taking full page screenshot as fallback")
                screenshot = driver.get_screenshot_as_png()
            else:
                # Wait additional time for chart to render
                logger.info("Waiting for chart to fully render...")
                time.sleep(5)
                
                # Scroll to element and take screenshot
                driver.execute_script("arguments[0].scrollIntoView(true);", chart_element)
                screenshot = chart_element.screenshot_as_png
            
            logger.info(f"Screenshot taken, size: {len(screenshot)} bytes")
            
            # Process image
            logger.info("Processing image...")
            img = Image.open(BytesIO(screenshot))
            
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Save to bytes with better quality
            img_bytes = BytesIO()
            img.save(img_bytes, format='JPEG', quality=95)
            img_bytes = img_bytes.getvalue()
            
            # Encode to base64
            img_base64 = base64.b64encode(img_bytes).decode()
            
            end_time = time.time()
            logger.info(f"Chart capture completed in {end_time - start_time:.2f} seconds")
            
            return {
                "status": "success",
                "image": img_base64,
                "message": "Chart captured successfully"
            }
            
        except Exception as e:
            logger.exception("Error during chart capture")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to capture chart: {str(e)}"
            )
        finally:
            logger.info("Closing Chrome driver")
            driver.quit()
            
    except Exception as e:
        logger.exception("Error in capture_chart endpoint")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to capture chart: {str(e)}"
        )

@app.get("/test-chrome")
async def test_chrome():
    """Test if Chrome and ChromeDriver are working"""
    try:
        driver = setup_driver()
        driver.get("https://www.google.com")
        title = driver.title
        driver.quit()
        return {"status": "success", "message": f"Chrome is working, loaded page with title: {title}"}
    except Exception as e:
        logger.exception("Chrome test failed")
        return {"status": "error", "message": str(e)}

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "chrome_driver": "installed"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
