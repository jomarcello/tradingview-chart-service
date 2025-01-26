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
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
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
    chrome_options.add_argument("--headless")  # Run in headless mode
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--window-size=1920,1080")  # Set window size
    
    driver = webdriver.Chrome(options=chrome_options)
    return driver

def get_tradingview_url(symbol: str, timeframe: str) -> str:
    """Generate TradingView URL with proper symbol mapping"""
    # Map common symbols to TradingView format
    tv_symbol_map = {
        "EURUSD": "FX:EURUSD",
        "GBPUSD": "FX:GBPUSD",
        "USDJPY": "FX:USDJPY",
        "BTCUSD": "BINANCE:BTCUSDT",  # Using Binance as source
        "ETHUSD": "BINANCE:ETHUSDT",
        "US30": "DJ:DJI",
        "SPX500": "SP:SPX",
        "NAS100": "NASDAQ:NDX",
        "XAUUSD": "OANDA:XAUUSD"
    }
    
    # Map timeframes to TradingView format
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
    
    return f"https://www.tradingview.com/chart/?symbol={tv_symbol}&interval={tv_timeframe}"

@app.post("/capture-chart")
async def capture_chart(request: ChartRequest):
    """Capture a screenshot of the TradingView chart"""
    try:
        driver = setup_driver()
        url = get_tradingview_url(request.symbol, request.timeframe)
        logger.info(f"Capturing chart for URL: {url}")
        
        try:
            # Load the page
            driver.get(url)
            
            # Wait for the chart to load
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CLASS_NAME, "chart-container"))
            )
            
            # Wait a bit more for the chart to fully render
            driver.implicitly_wait(5)
            
            # Take screenshot of the chart container
            chart_element = driver.find_element(By.CLASS_NAME, "chart-container")
            screenshot = chart_element.screenshot_as_png
            
            # Convert to base64
            img_base64 = base64.b64encode(screenshot).decode()
            
            return {
                "status": "success",
                "image": img_base64,
                "message": "Chart captured successfully"
            }
            
        finally:
            driver.quit()
            
    except Exception as e:
        logger.error(f"Error capturing chart: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to capture chart: {str(e)}")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
