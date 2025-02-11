from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
from typing import Dict, Any, List
import logging
import os
from openai import AsyncOpenAI
import redis
from supabase import create_client
from app.services.chart_service import ChartService

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize clients
openai_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
redis_client = redis.Redis(host=os.getenv("REDIS_HOST"), port=6379)
supabase = create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_KEY"))

class TradingBot:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self._bot = None  # We zullen de bot later initialiseren
        self.chart_service = ChartService()
        
    @property
    def bot(self) -> Bot:
        if self._bot is None:
            self._bot = Bot(self.token)
        return self._bot

    def initialize(self, bot: Bot):
        """Initialize with existing bot instance"""
        self._bot = bot

    async def match_subscribers(self, signal: Dict) -> List[str]:
        """Match signal with subscribers"""
        try:
            response = supabase.table("signal_preferences").select("*").eq(
                "market", signal["market"]
            ).eq("instrument", signal["instrument"]).eq(
                "timeframe", signal["timeframe"]
            ).execute()
            
            return [str(pref["user_id"]) for pref in response.data]
        except Exception as e:
            logger.error(f"Error matching subscribers: {str(e)}")
            return []
            
    async def analyze_sentiment(self, symbol: str) -> str:
        """Analyze market sentiment"""
        try:
            cache_key = f"sentiment:{symbol}"
            cached = redis_client.get(cache_key)
            if cached:
                return cached.decode()
                
            response = await openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a market analyst."},
                    {"role": "user", "content": f"Analyze {symbol} sentiment briefly"}
                ]
            )
            
            sentiment = response.choices[0].message.content
            redis_client.setex(cache_key, 300, sentiment)  # Cache for 5 minutes
            return sentiment
            
        except Exception as e:
            logger.error(f"Error analyzing sentiment: {str(e)}")
            return "Sentiment analysis unavailable"
            
    async def send_signal_message(self, chat_id: str, signal: Dict, sentiment: str):
        """Send signal message with inline buttons"""
        try:
            # Format message
            message = (
                f"🔔 *TRADING SIGNAL*\n"
                f"Symbol: {signal['symbol']}\n"
                f"Action: {signal['action']}\n"
                f"Price: {signal['price']}\n\n"
                f"📊 *SENTIMENT*\n"
                f"{sentiment}\n\n"
                f"⚠️ *Risk Management*\n"
                f"• Always use proper position sizing\n"
                f"• Never risk more than 1-2% per trade\n"
                f"• Multiple take profit levels recommended\n\n"
                f"🤖 Generated by SigmaPips AI"
            )

            # Create inline keyboard
            keyboard = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "📊 Technical Analysis", 
                        callback_data=f"chart_{signal['symbol']}_{signal['timeframe']}"
                    ),
                    InlineKeyboardButton(
                        "🤖 Market Sentiment", 
                        callback_data=f"sentiment_{signal['symbol']}"
                    )
                ],
                [
                    InlineKeyboardButton(
                        "📅 Economic Calendar", 
                        callback_data=f"calendar_{signal['symbol']}"
                    )
                ]
            ])

            # Send message with buttons
            await self._bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode='Markdown',
                reply_markup=keyboard
            )

        except Exception as e:
            logger.error(f"Error sending signal message: {str(e)}")

    async def process_signal(self, signal: Dict[str, Any]):
        """Process trading signal"""
        try:
            # 1. Match subscribers
            chat_ids = await self.match_subscribers(signal)
            
            # 2. Get sentiment
            sentiment = await self.analyze_sentiment(signal["symbol"])
            
            # 3. Send to all matched subscribers
            for chat_id in chat_ids:
                await self.send_signal_message(chat_id, signal, sentiment)
            
            return {
                "status": "success",
                "sent_to": len(chat_ids),
                "signal": signal,
                "sentiment": sentiment
            }
            
        except Exception as e:
            logger.error(f"Error processing signal: {str(e)}")
            raise

    async def handle_button_click(self, callback_query: Dict):
        """Handle button clicks"""
        try:
            data = callback_query["data"]
            chat_id = callback_query["message"]["chat"]["id"]

            if data.startswith("chart_"):
                _, symbol, timeframe = data.split("_")
                # Generate and send chart
                chart_bytes = await self.chart_service.generate_chart(symbol, timeframe)
                if chart_bytes:
                    await self._bot.send_photo(
                        chat_id=chat_id,
                        photo=chart_bytes,
                        caption=f"📊 Technical Analysis for {symbol} ({timeframe})"
                    )
                else:
                    await self._bot.send_message(
                        chat_id=chat_id,
                        text="❌ Sorry, could not generate chart at this time."
                    )

        except Exception as e:
            logger.error(f"Error handling button click: {str(e)}")
            await self._bot.send_message(
                chat_id=chat_id,
                text="❌ An error occurred while processing your request."
            )

# Initialize singleton instance
trading_bot = TradingBot() 