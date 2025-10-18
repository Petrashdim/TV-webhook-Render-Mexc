import hmac
import hashlib
import json
import requests
import time  # Добавляем импорт time
from flask import Flask, request, jsonify
import logging
from typing import Dict, Optional

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

class MexcTradingBot:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        
        # Настройки риска
        self.max_position_size = 100  # USD
        self.risk_per_trade = 0.02  # 2%
        
        logger.info("MEXC Trading Bot инициализирован")

    def calculate_position_size(self, current_price: float) -> float:
        """Расчет размера позиции на основе риска"""
        risk_amount = self.max_position_size * self.risk_per_trade
        position_size = risk_amount / current_price
        return round(position_size, 3)

    def place_order_direct(self, symbol: str, side: str, price: float, qty: float) -> Dict:
        """Прямой вызов MEXC API"""
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
            
            logger.info(f"Отправка запроса к MEXC: {params}")
            response = requests.post(endpoint, data=params, headers=headers, timeout=10)
            
            if response.status_code == 200:
                result = response.json()
                logger.info(f"Успешный ордер: {result}")
                return result
            else:
                error_msg = f"MEXC API error: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return {"error": error_msg}
            
        except Exception as e:
            logger.error(f"Ошибка прямого вызова API: {e}")
            return {"error": str(e)}

    def get_symbol_info(self, symbol: str) -> Dict:
        """Получение информации о символе (лимиты количества и цены)"""
        try:
            endpoint = "https://api.mexc.com/api/v3/exchangeInfo"
            response = requests.get(endpoint, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                for s in data['symbols']:
                    if s['symbol'] == symbol:
                        return s
            return {}
        except Exception as e:
            logger.error(f"Ошибка получения информации о символе: {e}")
            return {}

    def adjust_quantity(self, symbol: str, qty: float) -> float:
        """Корректировка количества по правилам биржи"""
        try:
            symbol_info = self.get_symbol_info(symbol)
            if not symbol_info:
                return qty
                
            # Получаем шаг количества
            step_size = float(symbol_info['filters'][1]['stepSize'])
            
            # Округляем до нужного шага
            adjusted_qty = round(qty // step_size * step_size, 8)
            logger.info(f"Скорректировано количество: {qty} -> {adjusted_qty}")
            
            return adjusted_qty
            
        except Exception as e:
            logger.error(f"Ошибка корректировки количества: {e}")
            return qty

    def process_tradingview_alert(self, alert_data: Dict) -> Dict:
        """Обработка алерта от TradingView"""
        try:
            # Разбираем сообщение от TradingView
            message = alert_data.get('message', '')
            logger.info(f"Получено сообщение: {message}")
            
            # Формат: BUY|SYMBOL|PRICE или SELL|SYMBOL|PRICE
            parts = message.split('|')
            
            if len(parts) < 3:
                return {"error": "Invalid message format", "received": message}
                
            action = parts[0].strip().upper()  # "BUY" или "SELL"
            symbol = parts[1].strip().upper()  # "BTCUSDT"
            price = float(parts[2].strip())  # цена
            
            logger.info(f"Получен алерт: {action} {symbol} по цене {price}")
            
            # Расчет размера позиции
            qty = self.calculate_position_size(price)
            
            # Корректируем количество по правилам биржи
            qty = self.adjust_quantity(symbol, qty)
            
            if qty <= 0:
                return {"error": "Invalid quantity calculated"}
            
            if action == "BUY":
                limit_price = price * 0.998  # На 0.2% ниже для лимитного ордера
                return self.place_order_direct(symbol, "BUY", limit_price, qty)
                
            elif action == "SELL":
                limit_price = price * 1.002  # На 0.2% выше для лимитного ордера
                return self.place_order_direct(symbol, "SELL", limit_price, qty)
                
            else:
                return {"error": f"Неизвестное действие: {action}"}
                
        except Exception as e:
            logger.error(f"Ошибка обработки алерта: {e}")
            return {"error": str(e)}

# Инициализация бота
bot = MexcTradingBot(
    api_key="YOUR_MEXC_API_KEY",
    api_secret="YOUR_MEXC_API_SECRET"
)

@app.route('/webhook/tradingview', methods=['POST'])
def tradingview_webhook():
    """Эндпоинт для вебхуков от TradingView"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "No JSON data received"}), 400
            
        logger.info(f"Получен вебхук: {data}")
        
        result = bot.process_tradingview_alert(data)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"Ошибка обработки вебхука: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "active", "service": "MEXC Trading Bot"})

@app.route('/test', methods=['GET'])
def test_endpoint():
    """Тестовый эндпоинт для проверки"""
    return jsonify({
        "message": "Server is running",
        "timestamp": time.time()
    })

if __name__ == '__main__':
    logger.info("Запуск MEXC Trading Bot сервера...")
    app.run(host='0.0.0.0', port=5000, debug=False)