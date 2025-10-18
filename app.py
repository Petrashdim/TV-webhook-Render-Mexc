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

class TradingBot:
    def __init__(self):
        # Настройки риска
        self.max_position_size = 100  # USD
        self.risk_per_trade = 0.02  # 2%
        logger.info("Trading Bot инициализирован")

    def calculate_position_size(self, current_price: float) -> float:
        """Расчет размера позиции на основе риска"""
        risk_amount = self.max_position_size * self.risk_per_trade
        position_size = risk_amount / current_price
        return round(position_size, 3)

    def simulate_order(self, symbol: str, side: str, price: float, qty: float) -> Dict:
        """Симуляция ордера (заглушка вместо реального API)"""
        try:
            logger.info(f"СИМУЛЯЦИЯ: {side} {qty} {symbol} по цене {price}")
            
            # Заглушка для демонстрации
            return {
                "status": "success",
                "order_id": f"SIM_{int(time.time())}",
                "symbol": symbol,
                "side": side,
                "price": price,
                "quantity": qty,
                "timestamp": time.time()
            }
            
        except Exception as e:
            logger.error(f"Ошибка симуляции ордера: {e}")
            return {"error": str(e)}

    def process_tradingview_alert(self, message: str) -> Dict:
        """Обработка алерта от TradingView"""
        try:
            logger.info(f"Получено сообщение от TV: {message}")
            
            # Формат: BUY|SYMBOL|PRICE или SELL|SYMBOL|PRICE
            parts = message.split('|')
            
            if len(parts) < 3:
                return {"error": "Неверный формат сообщения", "received": message}
                
            action = parts[0].strip().upper()  # "BUY" или "SELL"
            symbol = parts[1].strip().upper()  # "BTCUSDT"
            price = float(parts[2].strip())  # цена
            
            logger.info(f"Обработка алерта: {action} {symbol} по цене {price}")
            
            # Расчет размера позиции
            qty = self.calculate_position_size(price)
            
            if qty <= 0:
                return {"error": "Неверный расчет количества"}
            
            if action == "BUY":
                limit_price = price * 0.998  # На 0.2% ниже для лимитного ордера
                result = self.simulate_order(symbol, "BUY", limit_price, qty)
                return {
                    "status": "buy_order_placed", 
                    "symbol": symbol,
                    "price": limit_price,
                    "quantity": qty,
                    "result": result
                }
                
            elif action == "SELL":
                limit_price = price * 1.002  # На 0.2% выше для лимитного ордера
                result = self.simulate_order(symbol, "SELL", limit_price, qty)
                return {
                    "status": "sell_order_placed", 
                    "symbol": symbol,
                    "price": limit_price,
                    "quantity": qty,
                    "result": result
                }
                
            else:
                return {"error": f"Неизвестное действие: {action}"}
                
        except Exception as e:
            logger.error(f"Ошибка обработки алерта: {e}")
            return {"error": str(e)}

# Инициализация бота
bot = TradingBot()

@app.route('/webhook/tradingview', methods=['POST'])
def tradingview_webhook():
    """Основной эндпоинт для вебхуков от TradingView"""
    try:
        # TradingView отправляет plain text, а не JSON
        if request.content_type == 'application/json':
            data = request.get_json()
            message = data.get('message', '') if data else ''
        else:
            # Получаем raw text от TradingView
            message = request.get_data(as_text=True)
        
        logger.info(f"📨 Получен вебхук. Content-Type: {request.content_type}")
        logger.info(f"📨 Сообщение: {message}")
        
        if not message:
            return jsonify({"error": "No message received"}), 400
        
        # Обрабатываем алерт
        result = bot.process_tradingview_alert(message)
        
        logger.info(f"✅ Результат обработки: {result}")
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Ошибка обработки вебхука: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/webhook/test', methods=['POST', 'GET'])
def test_webhook():
    """Тестовый эндпоинт для проверки вебхука"""
    if request.method == 'GET':
        return jsonify({
            "message": "Send POST request with data",
            "examples": {
                "json": '{"message": "BUY|BTCUSDT|50000"}',
                "plain_text": "BUY|BTCUSDT|50000"
            }
        })
    
    # Обрабатываем оба формата
    if request.content_type == 'application/json':
        data = request.get_json()
        message = data.get('message', '') if data else ''
    else:
        message = request.get_data(as_text=True)
    
    return jsonify({
        "status": "test_received",
        "content_type": request.content_type,
        "message": message,
        "timestamp": time.time()
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Проверка здоровья сервера"""
    return jsonify({
        "status": "active", 
        "service": "TradingView Webhook Bot",
        "timestamp": time.time(),
        "endpoints": {
            "webhook": "/webhook/tradingview",
            "test": "/webhook/test",
            "health": "/health"
        }
    })

@app.route('/')
def home():
    return jsonify({
        "service": "TradingView Webhook Bot",
        "version": "1.0",
        "status": "running",
        "usage": "Send POST requests to /webhook/tradingview",
        "supported_formats": [
            "application/json: {'message': 'BUY|SYMBOL|PRICE'}",
            "text/plain: BUY|SYMBOL|PRICE"
        ]
    })

# ---------------- Ping loop ----------------
def ping_loop():
    """Фоновая задача для self-ping чтобы сервер не засыпал"""
    # ЗАМЕНИТЕ на ваш реальный URL после деплоя
    PING_URL = "https://tv-webhook-render-mexc.onrender.com/health"
    
    while True:
        try:
            requests.get(PING_URL, timeout=5)
            logger.info("🔄 Self-ping выполнен")
        except Exception as e:
            logger.warning(f"⚠️ Ping failed: {e}")
        time.sleep(300)  # 5 минут

# Запуск пинга в отдельном потоке (раскомментируйте после настройки URL)
# ping_thread = threading.Thread(target=ping_loop, daemon=True)
# ping_thread.start()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Запуск сервера на порту {port}")
    app.run(host='0.0.0.0', port=port, debug=False)