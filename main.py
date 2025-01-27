import os
import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import base64
from io import BytesIO
from PIL import Image

# Setup logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('chart_service.log')
    ]
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
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
        driver.set_page_load_timeout(30)
        logger.info("Chrome driver setup successful")
        return driver
    except Exception as e:
        logger.exception("Failed to setup Chrome driver")
        raise

def get_tradingview_url(symbol: str, timeframe: str) -> str:
    """Generate TradingView URL with proper symbol mapping"""
    # Map common symbols to TradingView format
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
    
    tv_symbol = tv_symbol_map.get(symbol.upper(), symbol)
    tv_timeframe = tv_timeframe_map.get(timeframe.lower(), "60")
    
    # Use the public chart URL format
    url = f"https://www.tradingview.com/chart/simple/?symbol={tv_symbol}&interval={tv_timeframe}"
    logger.info(f"Generated TradingView URL: {url}")
    return url

@app.post("/capture-chart")
async def capture_chart(request: ChartRequest):
    """Capture a screenshot of the TradingView chart"""
    logger.info(f"Received chart request for {request.symbol} {request.timeframe}")
    try:
        driver = setup_driver()
        url = get_tradingview_url(request.symbol, request.timeframe)
        
        try:
            logger.debug(f"Loading URL: {url}")
            driver.get(url)
            
            # Wait for chart container
            logger.debug("Waiting for chart container")
            chart_container = WebDriverWait(driver, 30).until(
                EC.presence_of_element_located((By.CLASS_NAME, "chart-markup-table"))
            )
            
            # Additional wait for chart to render
            logger.debug("Waiting for chart to render")
            driver.execute_script("window.scrollTo(0, 0)")
            driver.implicitly_wait(10)
            
            # Take screenshot
            logger.debug("Taking screenshot")
            screenshot = chart_container.screenshot_as_png
            
            # Process image
            logger.debug("Processing image")
            img = Image.open(BytesIO(screenshot))
            
            # Convert to RGB if necessary
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # Save to bytes with better quality
            img_bytes = BytesIO()
            img.save(img_bytes, format='JPEG', quality=95)
            img_bytes = img_bytes.getvalue()
            
            logger.info(f"Screenshot processed, size: {len(img_bytes)} bytes")
            img_base64 = base64.b64encode(img_bytes).decode()
            
            return {
                "status": "success",
                "image": img_base64,
                "message": "Chart captured successfully"
            }
            
        except Exception as e:
            logger.exception("Error capturing chart")
            raise HTTPException(status_code=500, detail=f"Failed to capture chart: {str(e)}")
        finally:
            logger.debug("Closing Chrome driver")
            driver.quit()
            
    except Exception as e:
        logger.exception("Error in capture_chart endpoint")
        raise HTTPException(status_code=500, detail=f"Failed to capture chart: {str(e)}")

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
