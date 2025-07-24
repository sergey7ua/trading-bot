import os
import logging
import requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import yaml
from tenacity import retry, stop_after_attempt, wait_exponential
import schedule
import time
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

# --- Налаштування логування ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("trading_bot.log"), logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# --- Завантаження змінних середовища ---
load_dotenv()
TD_API_KEY = os.getenv("TWELVEDATA_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# Перевірка змінних середовища
if not all([TD_API_KEY, TELEGRAM_TOKEN, TELEGRAM_CHAT_ID]):
    logger.error("Не встановлені всі необхідні змінні середовища")
    raise ValueError("Не встановлені всі необхідні змінні середовища")

# --- Глобальні змінні ---
SYMBOL = None
RSI_PERIOD = None
INTERVAL = None
LIMIT = None
MA_PERIOD = None
MA_TYPE = None
API_WAIT_TIME = None
last_signal = None

# --- Завантаження конфігурації ---
def update_config():
    global SYMBOL, RSI_PERIOD, INTERVAL, LIMIT, MA_PERIOD, MA_TYPE, API_WAIT_TIME
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        SYMBOL = config["symbol"]
        RSI_PERIOD = config["rsi_period"]
        INTERVAL = config["interval"]
        LIMIT = config["limit"]
        MA_PERIOD = config["ma_period"]
        MA_TYPE = config["ma_type"]
        API_WAIT_TIME = config["api_wait_time"]
    except Exception as e:
        logger.error(f"Помилка завантаження конфігурації: {e}")
        raise

update_config()

# --- Отримання даних ---
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_klines(symbol, interval, limit=LIMIT):
    url = "https://api.twelvedata.com/time_series"
    params = {
        "symbol": symbol,
        "interval": "3min",  # Змінено на 3-хвилинний таймфрейм
        "outputsize": limit,
        "apikey": TD_API_KEY
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "values" not in data:
            logger.error(f"Некоректна відповідь API: {data}")
            raise ValueError("Некоректна відповідь API")
        df = pd.DataFrame(data["values"])
        columns = ["open", "high", "low", "close"]
        available_columns = [col for col in columns if col in df.columns]
        if len(available_columns) < 4:
            logger.error(f"Відсутні необхідні стовпці в даних API: {df.columns}")
            raise ValueError("Відсутні необхідні стовпці")
        df = df[available_columns].astype(float)
        if "volume" in df.columns:
            df["volume"] = df["volume"].astype(float)
        df = df.iloc[::-1].reset_index(drop=True)
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining and int(remaining) < 10:
            logger.warning(f"Ліміт API низький: {remaining}. Очікування {API_WAIT_TIME} секунд")
            time.sleep(API_WAIT_TIME)
        return df
    except Exception as e:
        logger.error(f"Помилка запиту до API: {e}")
        raise

# --- Обчислення RSI ---
def calculate_rsi(prices, period=14):
    deltas = prices.diff()
    gain = deltas.where(deltas > 0, 0)
    loss = -deltas.where(deltas < 0, 0)
    avg_gain = gain.rolling(window=period, min_periods=1).mean()
    avg_loss = loss.rolling(window=period, min_periods=1).mean()
    rs = avg_gain / (avg_loss + 1e-10)
    rsi = 100 - (100 / (1 + rs))
    return rsi

# --- Обчислення MA ---
def calculate_ma(prices, period=20, ma_type="SMA"):
    if ma_type == "SMA":
        return prices.rolling(window=period, min_periods=1).mean()
    elif ma_type == "EMA":
        return prices.ewm(span=period, adjust=False).mean()
    else:
        logger.warning(f"Невідомий тип MA: {ma_type}. Використовується SMA")
        return prices.rolling(window=period, min_periods=1).mean()

# --- Надсилання повідомлень у Telegram ---
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {"chat_id": TELEGRAM_CHAT_ID, "text": message}
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Помилка надсилання в Telegram: {e}")

# --- Патерни ---
def is_bullish_engulfing(o1, c1, o2, c2):
    return (c1 < o1) and (c2 > o2) and (o2 <= c1) and (c2 >= o1)

def is_bearish_engulfing(o1, c1, o2, c2):
    return (c1 > o1) and (c2 < o2) and (o2 >= c1) and (c2 <= o1)

def is_hammer(o, c, h, l):
    body = abs(c - o)
    lower_wick = min(o, c) - l
    upper_wick = h - max(o, c)
    return lower_wick >= 1.5 * body and upper_wick <= body * 0.5 and body > 0

def is_shooting_star(o, c, h, l):
    body = abs(c - o)
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return upper_wick >= 2 * body and lower_wick <= body * 0.5 and body > 0

# --- Аналіз ---
def analyze(df):
    global last_signal
    if len(df) < 3:
        logger.warning("Недостатньо даних для аналізу")
        return None, None

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
    o3, c3 = df["high"].iloc[-1], df["low"].iloc[-1]
    h3, l3 = df["high"].iloc[-1], df["low"].iloc[-1]

    # Фільтр обсягу (вимкнено для EUR/USD)
    volume_filter = True

    signal = None
    pattern = None
    # Умови для сигналів
    rsi_buy_threshold = 40 if len(df) > 10 else 70
    if last_rsi < rsi_buy_threshold and last_price >= last_ma * 0.99 and volume_filter:
        if is_bullish_engulfing(o1, c1, o2, c2):
            signal, pattern = "BUY", "Bullish Engulfing"
        elif is_hammer(o3, c3, h3, l3):
            signal, pattern = "BUY", "Hammer"
    elif last_rsi > 60 and last_price <= last_ma * 1.01 and volume_filter:
        if is_bearish_engulfing(o1, c1, o2, c2):
            signal, pattern = "SELL", "Bearish Engulfing"
        elif is_shooting_star(o3, c3, h3, l3):
            signal, pattern = "SELL", "Shooting Star"

    if signal and signal != last_signal:
        last_signal = signal
        return signal, pattern, last_rsi, last_ma, last_price
    return None, None, last_rsi, last_ma, last_price

# --- Основна задача ---
def job():
    df = None
    try:
        update_config()
        df = get_klines(SYMBOL, INTERVAL)
        signal, pattern, rsi, ma, price = analyze(df)
        if signal and pattern:
            msg = (
                f"{signal} сигнал по {SYMBOL} @ {price:.5f}\n"
                f"Патерн: {pattern}\n"
                f"RSI: {rsi:.2f}\n"
                f"MA ({MA_TYPE}, {MA_PERIOD}): {ma:.5f}"
            )
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

# --- Перевірка робочих годин ---
def is_working_hours():
    kyiv_tz = ZoneInfo("Europe/Kyiv")
    now = datetime.now(kyiv_tz)
    return now.weekday() < 5 and dtime(8, 0) <= now.time() <= dtime(23, 0)

# --- Основний цикл ---
if __name__ == "__main__":
    logger.info("Бот запущено.")
    send_telegram("Бот запущено на Railway")
    schedule.every(3).minutes.do(lambda: job() if is_working_hours() else None)
    while True:
        schedule.run_pending()
        time.sleep(1)
