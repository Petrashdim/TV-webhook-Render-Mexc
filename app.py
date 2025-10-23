import hmac
import hashlib
import json
import requests
import time
import threading
import os
import csv
from flask import Flask, request, jsonify
import logging
from typing import Dict
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class MexcTradingBot:
    def __init__(self):
        self.api_key = os.getenv('MEXC_API_KEY', '')
        self.api_secret = os.getenv('MEXC_API_SECRET', '')
        
        # CSV лог
        self.csv_path = "trade_log.csv"
        self.init_csv()
        
        if not self.api_key or not self.api_secret:
            logger.warning("⚠️ API ключи не настроены. Используется симуляция.")
            self.simulation_mode = True
        else:
            logger.info("✅ Режим реальных ордеров MEXC")
            self.simulation_mode = False

    def init_csv(self):
        """Инициализация CSV файла"""
        if not os.path.exists(self.csv_path):
            with open(self.csv_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    "timestamp", "symbol", "action", "strategy_price", 
                    "order_price", "quantity", "bid", "ask", "status", "message"
                ])

    def log_trade(self, symbol: str, action: str, strategy_price: float, order_price: float, 
                 quantity: float, bid: float, ask: float, status: str, message: str):
        """Запись сделки в CSV"""
        try:
            with open(self.csv_path, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow([
                    datetime.now().isoformat(),
                    symbol,
                    action,
                    strategy_price,
                    order_price,
                    quantity,
                    bid,
                    ask,
                    status,
                    message
                ])
        except Exception as e:
            logger.error(f"Ошибка записи в CSV: {e}")

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

    def place_real_order(self, symbol: str, side: str, quantity: float, strategy_price: float) -> Dict:
        """Размещение реального ордера"""
        try:
            # Получаем текущие цены для ордера и логов
            prices = self.get_current_prices(symbol)
            current_bid = prices.get('bid', 0)
            current_ask = prices.get('ask', 0)
            
            if current_ask <= 0 or current_bid <= 0:
                return {"error": "Не удалось получить цены с биржи"}
            
            # Определяем цену ордера
            if side.upper() == "BUY":
                order_price = current_ask  # Покупаем по аску
                order_type = "BUY"
            else:
                order_price = current_bid  # Продаем по биду
                order_type = "SELL"
            
            # Проверяем минимальный объем (1 USDT)
            order_value = quantity * order_price
            min_usdt_value = 1.0
            
            if order_value < min_usdt_value:
                logger.warning(f"⚠️ Объем меньше минимального: {order_value:.2f} USDT")
                # Не корректируем количество - пусть TradingView контролирует
                return {"error": f"Объем меньше минимального: {order_value:.2f} USDT < {min_usdt_value} USDT"}
            
            logger.info(f"💰 {order_type}: strategy_price={strategy_price}, order_price={order_price}, quantity={quantity}")
            logger.info(f"💰 Market: bid={current_bid}, ask={current_ask}")
            
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
            
            logger.info(f"📤 Отправка ордера: {side} {quantity} {symbol} по {order_price}")
            
            # Отправляем запрос
            response = requests.post(url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Ордер размещен: {result}")
                
                # Логируем успешный ордер
                self.log_trade(
                    symbol=symbol,
                    action=side.upper(),
                    strategy_price=strategy_price,
                    order_price=order_price,
                    quantity=quantity,
                    bid=current_bid,
                    ask=current_ask,
                    status="SUCCESS",
                    message=f"Order {result.get('orderId', '')}"
                )
                
                return {"status": "success", "real_order": result}
            else:
                error_msg = f"❌ MEXC API error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                
                # Логируем ошибку
                self.log_trade(
                    symbol=symbol,
                    action=side.upper(),
                    strategy_price=strategy_price,
                    order_price=order_price,
                    quantity=quantity,
                    bid=current_bid,
                    ask=current_ask,
                    status="ERROR",
                    message=error_msg
                )
                
                return {"error": error_msg}
            
        except Exception as e:
            error_msg = f"❌ Ошибка ордера: {e}"
            logger.error(error_msg)
            return {"error": error_msg}

    def process_tradingview_alert(self, message: str) -> Dict:
        """Обработка алерта от TradingView - новый формат с количеством в монетах"""
        try:
            logger.info(f"📨 Получено сообщение от TV: {message}")
            
            # ФОРМАТ: ACTION:SYMBOL:QUANTITY:STRATEGY_PRICE
            parts = message.split(':')
            
            if len(parts) < 4:
                return {"error": "Неверный формат сообщения", "received": message}
                
            action = parts[0].strip().upper()
            symbol = parts[1].strip().upper()
            quantity = float(parts[2].strip())  # Количество в монетах
            strategy_price = float(parts[3].strip())  # Цена срабатывания стратегии
            
            logger.info(f"🔍 Обработка: {action} {symbol} qty={quantity} strategy_price={strategy_price}")
            
            if quantity <= 0:
                return {"error": "Неверное количество"}
            
            if action == "BUY":
                result = self.place_real_order(symbol, "BUY", quantity, strategy_price)
                return {
                    "status": "buy_order_placed", 
                    "symbol": symbol,
                    "quantity": quantity,
                    "strategy_price": strategy_price,
                    "result": result
                }
                
            elif action == "SELL":
                result = self.place_real_order(symbol, "SELL", quantity, strategy_price)
                return {
                    "status": "sell_order_placed", 
                    "symbol": symbol,
                    "quantity": quantity,
                    "strategy_price": strategy_price,
                    "result": result
                }
                
            else:
                return {"error": f"Неизвестное действие: {action}"}
                
        except Exception as e:
            logger.error(f"❌ Ошибка обработки алерта: {e}")
            return {"error": str(e)}

# Инициализация бота
bot = MexcTradingBot()

@app.route('/')
def home():
    """Корневой эндпоинт для проверки работы сервера"""
    return jsonify({
        "status": "online",
        "service": "TradingView Webhook to MEXC",
        "timestamp": datetime.now().isoformat(),
        "endpoints": {
            "webhook": "/webhook/tradingview (POST)",
            "logs": "/logs (GET)",
            "health": "/health (GET)",
            "test": "/test (GET)"
        }
    })

@app.route('/health')
def health_check():
    """Проверка здоровья сервера"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "simulation_mode": bot.simulation_mode
    })

@app.route('/test')
def test_webhook():
    """Тестовый эндпоинт для проверки вебхука"""
    test_message = "BUY:XRPUSDT:100:0.5"
    result = bot.process_tradingview_alert(test_message)
    return jsonify({
        "test": "completed",
        "message": test_message,
        "result": result
    })

@app.route('/webhook/tradingview', methods=['POST', 'GET'])
def tradingview_webhook():
    """Основной эндпоинт для вебхуков от TradingView"""
    try:
        # Логируем все детали запроса
        logger.info(f"🌐 Получен запрос на /webhook/tradingview")
        logger.info(f"📦 Метод: {request.method}")
        logger.info(f"📦 Headers: {dict(request.headers)}")
        logger.info(f"📦 Content-Type: {request.content_type}")
        
        if request.method == 'GET':
            return jsonify({
                "status": "webhook_is_ready",
                "message": "Send POST request with your TradingView alert",
                "example": {
                    "message": "BUY:XRPUSDT:100:0.5"
                }
            })
        
        # Обработка POST запроса от TradingView
        message = ""
        
        # TradingView отправляет JSON с полем 'message'
        if request.content_type == 'application/json':
            data = request.get_json()
            logger.info(f"📦 JSON данные: {data}")
            
            if data and 'message' in data:
                message = data['message']
            elif data and 'text' in data:
                message = data['text']
            elif data:
                # Если нет поля message, пробуем взять первое значение
                first_key = next(iter(data.keys()))
                message = data[first_key]
        else:
            # Если не JSON, берем как plain text
            message = request.get_data(as_text=True).strip()
        
        logger.info(f"📨 Извлеченное сообщение: '{message}'")
        
        if not message:
            return jsonify({
                "error": "No message received", 
                "details": "Empty message body",
                "content_type": request.content_type,
                "data_received": request.get_data(as_text=True)
            }), 400
        
        result = bot.process_tradingview_alert(message)
        
        logger.info(f"📊 Результат обработки: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"💥 Ошибка вебхука: {e}")
        return jsonify({
            "error": str(e), 
            "type": type(e).__name__,
            "content_type": request.content_type if request else "No request"
        }), 500

@app.route('/logs')
def get_logs():
    """Получение логов"""
    try:
        if not os.path.exists(bot.csv_path):
            return jsonify({"error": "No logs yet"})
        
        logs = []
        with open(bot.csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                logs.append(row)
        
        return jsonify({"logs": logs, "count": len(logs)})
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/clear-logs', methods=['POST'])
def clear_logs():
    """Очистка логов (для тестирования)"""
    try:
        if os.path.exists(bot.csv_path):
            os.remove(bot.csv_path)
        bot.init_csv()
        return jsonify({"status": "logs_cleared"})
    except Exception as e:
        return jsonify({"error": str(e)})

# Новый эндпоинт для прямого тестирования вебхука
@app.route('/test-webhook-direct', methods=['POST'])
def test_webhook_direct():
    """Прямой тест вебхука с разными форматами"""
    test_data = {
        "message": "BUY:XRPUSDT:100:0.5"
    }
    
    # Имитируем запрос от TradingView
    with app.test_client() as client:
        response = client.post('/webhook/tradingview', 
                             json=test_data,
                             content_type='application/json')
    
    return jsonify({
        "test_request": test_data,
        "test_response": response.get_json()
    })

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    logger.info(f"🚀 Запуск сервера на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)