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
        
        # Настройки риска
        self.max_position_size = 50  # USD - уменьшил для безопасности
        self.risk_per_trade = 0.01   # 1% - уменьшил риск
        
        if not self.api_key or not self.api_secret:
            logger.warning("⚠️ API ключи не настроены. Используется симуляция.")
            self.simulation_mode = True
        else:
            logger.info("✅ Режим реальных ордеров MEXC")
            self.simulation_mode = False

    def calculate_position_size(self, current_price: float) -> float:
        """Расчет размера позиции на основе риска"""
        risk_amount = self.max_position_size * self.risk_per_trade
        
        if current_price <= 0:
            return 0
            
        position_size = risk_amount / current_price
        
        # Минимальный размер позиции
        min_position = 0.001
        if position_size < min_position:
            position_size = min_position
            
        return round(position_size, 6)

    def place_real_order(self, symbol: str, side: str, price: float, qty: float) -> Dict:
        """Размещение реального ордера на MEXC"""
        try:
            endpoint = "https://api.mexc.com/api/v3/order"
            timestamp = str(int(time.time() * 1000))
            
            params = {
                'symbol': symbol,
                'side': side.upper(),
                'type': 'LIMIT',
                'quantity': str(qty),
                'price': str(price),
                'recvWindow': '5000',
                'timestamp': timestamp
            }
            
            # Создание подписи
            query_string = '&'.join([f"{k}={v}" for k, v in sorted(params.items())])
            signature = hmac.new(
                self.api_secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            params['signature'] = signature
            
            headers = {
                'X-MEXC-APIKEY': self.api_key,
                'Content-Type': 'application/x-www-form-urlencoded'
            }
            
            logger.info(f"📤 Отправка реального ордера: {side} {qty} {symbol} по {price}")
            response = requests.post(endpoint, data=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"✅ Реальный ордер размещен: {result}")
                return {"status": "success", "real_order": result}
            else:
                error_msg = f"❌ MEXC API error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {"error": error_msg}
            
        except Exception as e:
            logger.error(f"❌ Ошибка реального ордера: {e}")
            return {"error": str(e)}

    def simulate_order(self, symbol: str, side: str, price: float, qty: float) -> Dict:
        """Симуляция ордера"""
        logger.info(f"🎮 СИМУЛЯЦИЯ: {side} {qty} {symbol} по цене {price}")
        return {
            "status": "success",
            "order_id": f"SIM_{int(time.time())}",
            "symbol": symbol,
            "side": side,
            "price": price,
            "quantity": qty,
            "timestamp": time.time(),
            "note": "Симуляционный ордер"
        }

    def place_order(self, symbol: str, side: str, price: float, qty: float) -> Dict:
        """Общая функция размещения ордера"""
        if self.simulation_mode:
            return self.simulate_order(symbol, side, price, qty)
        else:
            return self.place_real_order(symbol, side, price, qty)

    def process_tradingview_alert(self, message: str) -> Dict:
        """Обработка алерта от TradingView"""
        try:
            logger.info(f"📨 Получено сообщение от TV: {message}")
            
            parts = message.split(':')
            
            if len(parts) < 3:
                return {"error": "Неверный формат сообщения", "received": message}
                
            action = parts[0].strip().upper()
            symbol = parts[1].strip().upper()
            price = float(parts[2].strip())
            
            logger.info(f"🔍 Обработка алерта: {action} {symbol} по цене {price}")
            
            # Расчет размера позиции
            qty = self.calculate_position_size(price)
            
            if qty <= 0:
                return {"error": "Неверный расчет количества"}
            
            if action == "BUY":
                limit_price = price * 0.998
                result = self.place_order(symbol, "BUY", limit_price, qty)
                return {
                    "status": "buy_order_placed", 
                    "symbol": symbol,
                    "price": limit_price,
                    "quantity": qty,
                    "mode": "REAL" if not self.simulation_mode else "SIMULATION",
                    "result": result
                }
                
            elif action == "SELL":
                limit_price = price * 1.002
                result = self.place_order(symbol, "SELL", limit_price, qty)
                return {
                    "status": "sell_order_placed", 
                    "symbol": symbol,
                    "price": limit_price,
                    "quantity": qty,
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

# ... остальные роуты без изменений ...

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