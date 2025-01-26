# TradingView Chart Service

This service captures screenshots of TradingView charts using Selenium. It provides a simple API endpoint to request chart screenshots for different symbols and timeframes.

## Features

- Captures high-quality screenshots of TradingView charts
- Supports multiple symbols (Forex, Crypto, Indices, Commodities)
- Configurable timeframes
- Returns base64 encoded images
- Built with FastAPI and Selenium

## API Endpoints

### POST /capture-chart

Request a chart screenshot.

Request body:
```json
{
    "symbol": "BTCUSD",
    "timeframe": "4h"
}
```

Response:
```json
{
    "status": "success",
    "image": "base64_encoded_image",
    "message": "Chart captured successfully"
}
```

### GET /health

Health check endpoint.

Response:
```json
{
    "status": "healthy"
}
```

## Setup

1. Install dependencies:
```bash
pip install -r requirements.txt
```

2. Run the service:
```bash
uvicorn main:app --reload
```

## Docker

Build and run with Docker:

```bash
docker build -t tradingview-chart-service .
docker run -p 8000:8000 tradingview-chart-service
```
