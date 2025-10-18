import hmac
import hashlib
import json
import requests
import time
import threading
import os
from flask import Flask, request, jsonify
import logging
from typing import Dict

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class MexcTradingBot:
    def __init__(self):
        self.api_key = os.getenv('MEXC_API_KEY', '')
        self.api_secret = os.getenv('MEXC_API_SECRET', '')
        
        if not self.api_key or not self.api_secret:
            logger.warning("⚠️ API ключи не настроены. Используется симуляция.")
            self.simulation_mode = True
        else:
            logger.info("✅ Режим реальных ордеров MEXC")
            self.simulation_mode = False

    def get_current_prices(self, symbol: str) -> Dict:
        """Получение текущих цен bid/ask"""
        try:
            endpoint = "https://api.mexc.com/api/v3/ticker/bookTicker"
            params = {'symbol': symbol}
            
            response = requests.get(endpoint, params=params, timeout=5)
            if response.status_code == 200:
                data = response.json()
                return {
                    'bid': float(data['bidPrice']),
                    'ask': float(data['askPrice']),
                    'bid_qty': float(data['bidQty']),
                    'ask_qty': float(data['askQty'])
                }
            return {'bid': 0, 'ask': 0}
        except Exception as e:
            logger.error(f"Ошибка получения цен: {e}")
            return {'bid': 0, 'ask': 0}

    def calculate_quantity(self, size_usdt: float, price: float) -> float:
        """Расчет количества на основе размера в USDT и цены"""
        if price <= 0:
            return 0
            
        quantity = size_usdt / price
        
        # МИНИМАЛЬНЫЙ ОБЪЕМ MEXC: 1 USDT
        min_usdt_value = 1.0
        if size_usdt < min_usdt_value:
            logger.warning(f"⚠️ Размер меньше минимального: {size_usdt} USDT < {min_usdt_value} USDT")
            return min_usdt_value / price
            
        return round(quantity, 6)

    def place_real_order(self, symbol: str, side: str, size_usdt: float) -> Dict:
        """Размещение лимитного ордера - цена определяется биржей"""
        try:
            # Получаем текущие цены с биржи
            prices = self.get_current_prices(symbol)
            current_bid = prices.get('bid', 0)
            current_ask = prices.get('ask', 0)
            
            if current_ask <= 0 or current_bid <= 0:
                return {"error": "Не удалось получить цены с биржи"}
            
            # Определяем цену ордера
            if side.upper() == "BUY":
                order_price = current_ask  # Покупаем по цене аск
                order_type = "BUY (market price)"
            else:
                order_price = current_bid  # Продаем по цене бид
                order_type = "SELL (market price)"
            
            # Расчет количества
            quantity = self.calculate_quantity(size_usdt, order_price)
            
            if quantity <= 0:
                return {"error": "Неверный расчет количества"}
            
            logger.info(f"💰 {order_type}: price={order_price}, size={size_usdt} USDT, quantity={quantity}")
            logger.info(f"💰 Market: bid={current_bid}, ask={current_ask}")
            
            # Проверяем минимальный объем
            order_value = quantity * order_price
            min_usdt_value = 1.0
            if order_value < min_usdt_value:
                logger.warning(f"⚠️ Объем меньше минимального: {order_value:.2f} USDT")
                # Корректируем количество
                quantity = min_usdt_value / order_price
                logger.info(f"🔄 Автокоррекция количества: {quantity:.6f}")
            
            # Формируем ордер
            timestamp = str(int(time.time() * 1000))
            
            params = {
                'symbol': symbol,
                'side': side.upper(),
                'type': 'LIMIT',
                'timeInForce': 'GTC',
                'quantity': str(round(quantity, 6)),
                'price': str(round(order_price, 6)),
                'timestamp': timestamp,
                'recvWindow': '5000'
            }
            
            # Создание подписи
            query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
            signature = hmac.new(
                self.api_secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Формируем URL
            url = f"https://api.mexc.com/api/v3/order?{query_string}&signature={signature}"
            
            headers = {
                'X-MEXC-APIKEY': self.api_key
            }
            
            logger.info(f"📤 Отправка лимитного ордера: {side} {quantity} {symbol} по {order_price}")
            
            # Отправляем запрос
            response = requests.post(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Лимитный ордер размещен: {result}")
                return {"status": "success", "real_order": result}
            else:
                error_msg = f"❌ MEXC API error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {"error": error_msg}
            
        except Exception as e:
            logger.error(f"❌ Ошибка реального ордера: {e}")
            return {"error": str(e)}

    def simulate_order(self, symbol: str, side: str, size_usdt: float) -> Dict:
        """Симуляция ордера"""
        prices = self.get_current_prices(symbol)
        current_bid = prices.get('bid', 0)
        current_ask = prices.get('ask', 0)
        
        if side.upper() == "BUY":
            order_price = current_ask
        else:
            order_price = current_bid
            
        quantity = self.calculate_quantity(size_usdt, order_price)
        
        logger.info(f"🎮 СИМУЛЯЦИЯ: {side} {quantity} {symbol} по {order_price} (size: {size_usdt} USDT)")
        logger.info(f"🎮 Market: bid={current_bid}, ask={current_ask}")
        
        return {
            "status": "success",
            "order_id": f"SIM_{int(time.time())}",
            "symbol": symbol,
            "side": side,
            "price": order_price,
            "quantity": quantity,
            "size_usdt": size_usdt,
            "timestamp": time.time(),
            "note": "Симуляционный ордер"
        }

    def place_order(self, symbol: str, side: str, size_usdt: float) -> Dict:
        """Общая функция размещения ордера"""
        if self.simulation_mode:
            return self.simulate_order(symbol, side, size_usdt)
        else:
            return self.place_real_order(symbol, side, size_usdt)

    def process_tradingview_alert(self, message: str) -> Dict:
        """Обработка алерта от TradingView - новый формат"""
        try:
            logger.info(f"📨 Получено сообщение от TV: {message}")
            
            # НОВЫЙ ФОРМАТ: ACTION:SYMBOL:SIZE_USDT
            parts = message.split(':')
            
            if len(parts) < 3:
                return {"error": "Неверный формат сообщения", "received": message}
                
            action = parts[0].strip().upper()
            symbol = parts[1].strip().upper()
            size_usdt = float(parts[2].strip())  # Размер в USDT
            
            logger.info(f"🔍 Обработка алерта: {action} {symbol} размер {size_usdt} USDT")
            
            if size_usdt <= 0:
                return {"error": "Неверный размер позиции"}
            
            if action == "BUY":
                result = self.place_order(symbol, "BUY", size_usdt)
                return {
                    "status": "buy_order_placed", 
                    "symbol": symbol,
                    "size_usdt": size_usdt,
                    "mode": "REAL" if not self.simulation_mode else "SIMULATION",
                    "result": result
                }
                
            elif action == "SELL":
                result = self.place_order(symbol, "SELL", size_usdt)
                return {
                    "status": "sell_order_placed", 
                    "symbol": symbol,
                    "size_usdt": size_usdt,
                    "mode": "REAL" if not self.simulation_mode else "SIMULATION",
                    "result": result
                }
                
            else:
                return {"error": f"Неизвестное действие: {action}"}
                
        except Exception as e:
            logger.error(f"❌ Ошибка обработки алерта: {e}")
            return {"error": str(e)}

# Инициализация бота
bot = MexcTradingBot()

@app.route('/webhook/tradingview', methods=['POST'])
def tradingview_webhook():
    """Основной эндпоинт для вебхуков от TradingView"""
    try:
        if request.content_type == 'application/json':
            data = request.get_json()
            message = data.get('message', '') if data else ''
        else:
            message = request.get_data(as_text=True)
        
        logger.info(f"🌐 Получен вебхук. Content-Type: {request.content_type}")
        logger.info(f"💬 Сообщение: {message}")
        
        if not message:
            return jsonify({"error": "No message received"}), 400
        
        result = bot.process_tradingview_alert(message)
        
        logger.info(f"📊 Результат обработки: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"💥 Ошибка обработки вебхука: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({
        "status": "active", 
        "service": "TradingView Webhook Bot",
        "mode": "REAL" if not bot.simulation_mode else "SIMULATION",
        "timestamp": time.time()
    })

@app.route('/')
def home():
    return jsonify({
        "service": "TradingView Webhook Bot for MEXC",
        "version": "3.0",
        "mode": "REAL" if not bot.simulation_mode else "SIMULATION",
        "message_format": "ACTION:SYMBOL:SIZE_USDT",
        "examples": [
            "BUY:XRPUSDT:10",
            "SELL:BTCUSDT:50"
        ]
    })

# ---------------- Ping loop ----------------
def ping_loop():
    PING_URL = "https://tv-webhook-render-mexc.onrender.com/health"
    
    while True:
        try:
            requests.get(PING_URL, timeout=5)
            logger.info("🔄 Self-ping выполнен")
        except Exception as e:
            logger.warning(f"⚠️ Ping failed: {e}")
        time.sleep(300)

ping_thread = threading.Thread(target=ping_loop, daemon=True)
ping_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🚀 Запуск сервера на порту {port}")
    logger.info(f"🔧 Режим: {'СИМУЛЯЦИЯ' if bot.simulation_mode else 'РЕАЛЬНЫЕ ОРДЕРА'}")
    app.run(host='0.0.0.0', port=port, debug=False)