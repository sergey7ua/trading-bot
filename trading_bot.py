import time
import os
import requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler
import schedule
from tenacity import retry, stop_after_attempt, wait_exponential
import yaml
from datetime import datetime, timedelta

# --- Налаштування логування ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        RotatingFileHandler('trading_bot.log', maxBytes=5*1024*1024, backupCount=5),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Завантаження конфігурації ---
def load_config():
    try:
        with open('config.yaml', 'r') as file:
            return yaml.safe_load(file)
    except FileNotFoundError:
        logger.error("Файл config.yaml не знайдено")
        raise

# --- Ініціалізація змінних ---
CONFIG = load_config()
SYMBOL = CONFIG['symbol']
RSI_PERIOD = CONFIG['rsi_period']
INTERVAL = CONFIG['interval']
LIMIT = CONFIG['limit']
MA_PERIOD = CONFIG.get('ma_period', 20)
MA_TYPE = CONFIG.get('ma_type', 'SMA').upper()
API_WAIT_TIME = min(CONFIG.get('api_wait_time', 3600), 7200)  # Максимум 2 години
CONFIG_UPDATE_INTERVAL = 300  # Оновлення конфігурації кожні 5 хвилин
last_config_update = datetime.now()

# --- Завантаження змінних середовища ---
load_dotenv()
TD_API_KEY = os.getenv("TWELVEDATA_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Перевірка змінних середовища
if not all([TD_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    logger.error("Не встановлені всі необхідні змінні середовища")
    raise ValueError("Не встановлені всі необхідні змінні середовища")

# --- Змінні для відстеження ---
last_signal = None
last_message_time = None
TELEGRAM_MESSAGE_COOLDOWN = 300  # 5 хвилин

# --- Альтернативний RSI ---
def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0).rolling(window=period).mean()
    loss = -delta.where(delta < 0, 0).rolling(window=period).mean()
    rs = gain / loss
    rs = rs.replace([np.inf, -np.inf], np.nan).fillna(0)
    return 100 - (100 / (1 + rs))

# --- Альтернативний MA ---
def calculate_ma(series, period=20, ma_type='SMA'):
    if ma_type == 'EMA':
        return series.ewm(span=period, adjust=False).mean()
    return series.rolling(window=period).mean()

# --- Отримання даних з TwelveData ---
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_klines(symbol, interval, outputsize=LIMIT):
    logger.info(f"Запит даних для {symbol} з інтервалом {interval}")
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": interval,
        "outputsize": outputsize,
        "apikey": TD_API_KEY,
    }
    response = requests.get(url, params=params)
    
    if 'X-RateLimit-Remaining' in response.headers and int(response.headers['X-RateLimit-Remaining']) < 1:
        logger.warning(f"Досягнуто ліміт API. Очікування {API_WAIT_TIME} секунд...")
        send_telegram(f"Бот зупинено: досягнуто ліміт API TwelveData. Очікування {API_WAIT_TIME//60} хвилин.")
        time.sleep(API_WAIT_TIME)
        raise Exception("Досягнуто ліміт API")
    
    if response.status_code != 200:
        logger.error(f"Помилка API: {response.status_code}, {response.text}")
        raise Exception(f"Помилка API: {response.status_code}, {response.text}")
    
    data = response.json()
    if "values" not in data or not isinstance(data["values"], list):
        logger.error(f"Невірний формат даних від TwelveData: {data}")
        raise Exception(f"Невірний формат даних від TwelveData: {data}")
    
    df = pd.DataFrame(data["values"])
    df = df.iloc[::-1]
    try:
        df["open"] = df["open"].astype(float)
        df["high"] = df["high"].astype(float)
        df["low"] = df["low"].astype(float)
        df["close"] = df["close"].astype(float)
        if "volume" in df:
            df["volume"] = df["volume"].astype(float)
    except (ValueError, KeyError) as e:
        logger.error(f"Помилка конвертації даних: {e}")
        raise Exception(f"Помилка конвертації даних: {e}")
    
    return df

# --- Патерни ---
def is_bullish_engulfing(o1, c1, o2, c2):
    return (c1 < o1) and (c2 > o2) and (o2 < c1) and (c2 > o1)

def is_bearish_engulfing(o1, c1, o2, c2):
    return (c1 > o1) and (c2 < o2) and (o2 > c1) and (c2 < o1)

def is_hammer(o, c, h, l):
    body = abs(c - o)
    lower = min(o, c) - l
    upper = h - max(o, c)
    return lower > 2 * body and upper < body

def is_shooting_star(o, c, h, l):
    body = abs(c - o)
    upper = h - max(o, c)
    lower = min(o, c) - l
    return upper > 2 * body and lower < body

# --- Аналіз ---
def analyze(df):
    global last_signal
    if len(df) < 3:
        logger.warning("Недостатньо даних для аналізу")
        return None

    # Обчислення RSI
    try:
        from ta.momentum import RSIIndicator
        rsi = RSIIndicator(close=df["close"], window=RSI_PERIOD).rsi()
    except ImportError:
        logger.info("ta-lib недоступний, використовується альтернативний RSI")
        rsi = calculate_rsi(df["close"], RSI_PERIOD)
    last_rsi = rsi.iloc[-1]

    # Обчислення MA
    ma = calculate_ma(df["close"], MA_PERIOD, MA_TYPE)
    last_ma = ma.iloc[-1]
    last_price = df["close"].iloc[-1]

    # Дані для свічок
    o1, c1 = df["open"].iloc[-3], df["close"].iloc[-3]
    o2, c2 = df["open"].iloc[-2], df["close"].iloc[-2]
    o3, c3 = df["open"].iloc[-1], df["close"].iloc[-1]
    h3, l3 = df["high"].iloc[-1], df["low"].iloc[-1]

    # Фільтр обсягу
    volume_filter = df["volume"].iloc[-1] > df["volume"].mean() if "volume" in df else True

    signal = None
    if last_rsi < 30 and last_price > last_ma and volume_filter:
        if is_bullish_engulfing(o1, c1, o2, c2) or is_hammer(o3, c3, h3, l3):
            signal = "BUY"
    elif last_rsi > 70 and last_price < last_ma and volume_filter:
        if is_bearish_engulfing(o1, c1, o2, c2) or is_shooting_star(o3, c3, h3, l3):
            signal = "SELL"

    if signal and signal != last_signal:
        last_signal = signal
        return signal
    return None

# --- Telegram ---
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=2, min=4, max=20))
def send_telegram(message):
    global last_message_time
    current_time = datetime.now()
    if last_message_time and (current_time - last_message_time).total_seconds() < TELEGRAM_MESSAGE_COOLDOWN:
        logger.info("Повідомлення ігнорується через кулдаун")
        return
    logger.info(f"Надсилання повідомлення в Telegram: {message}")
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    response = requests.post(url, data=data)
    if response.status_code != 200:
        logger.error(f"Помилка Telegram: {response.status_code}, {response.text}")
        raise Exception(f"Помилка Telegram: {response.text}")
    last_message_time = current_time

# --- Оновлення конфігурації ---
def update_config():
    global CONFIG, SYMBOL, RSI_PERIOD, INTERVAL, LIMIT, MA_PERIOD, MA_TYPE, API_WAIT_TIME, last_config_update
    if (datetime.now() - last_config_update).total_seconds() < CONFIG_UPDATE_INTERVAL:
        return
    try:
        new_config = load_config()
        if new_config != CONFIG:
            logger.info("Оновлено конфігурацію")
            CONFIG = new_config
            SYMBOL = CONFIG['symbol']
            RSI_PERIOD = CONFIG['rsi_period']
            INTERVAL = CONFIG['interval']
            LIMIT = CONFIG['limit']
            MA_PERIOD = CONFIG.get('ma_period', 20)
            MA_TYPE = CONFIG.get('ma_type', 'SMA').upper()
            API_WAIT_TIME = min(CONFIG.get('api_wait_time', 3600), 7200)
        last_config_update = datetime.now()
    except Exception as e:
        logger.error(f"Помилка оновлення конфігурації: {e}")

# --- Основна задача ---
def job():
    df = None
    try:
        update_config()
        df = get_klines(SYMBOL, INTERVAL)
        signal = analyze(df)
        if signal:
            price = df['close'].iloc[-1]
            msg = f"{signal} сигнал по {SYMBOL} @ {price}"
            send_telegram(msg)
            logger.info(msg)
        else:
            logger.info("Сигналів немає.")
    except Exception as e:
        logger.error(f"Помилка в основному циклі: {e}")
    finally:
        df = None
        import gc
        gc.collect()

# --- Основний цикл ---
if __name__ == "__main__":
    logger.info("Бот запущено.")
    send_telegram("Бот запущено на Railway")
    schedule.every(1).minutes.at(":00").do(job)
    while True:
        schedule.run_pending()
        time.sleep(1)