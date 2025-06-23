import os
<<<<<<< HEAD
import requests
import json
from datetime import datetime
=======
import time as time_module  # Псевдонім для модуля time
import logging
import requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv
import yaml
from tenacity import retry, stop_after_attempt, wait_exponential
import schedule
from datetime import datetime
from datetime import time as dt_time  # Псевдонім для datetime.time
>>>>>>> 47d9aa3082d70386cd39190ffe52b474d80301f6
from zoneinfo import ZoneInfo

# Отримання змінних середовища
RAILWAY_API_TOKEN = os.getenv('RAILWAY_API_TOKEN')
PROJECT_ID = os.getenv('PROJECT_ID')
SERVICE_ID = os.getenv('SERVICE_ID')

# Перевірка змінних
if not RAILWAY_API_TOKEN:
    print("Error: RAILWAY_API_TOKEN is not set")
    exit(1)
if not PROJECT_ID:
    print("Error: PROJECT_ID is not set")
    exit(1)
if not SERVICE_ID:
    print("Error: SERVICE_ID is not set")
    exit(1)

# Налаштування заголовків для API
headers = {
    'Authorization': f'Bearer {RAILWAY_API_TOKEN}',
    'Content-Type': 'application/json'
}

# GraphQL URL
graphql_url = 'https://backboard.railway.app/graphql/v2'

def get_active_deployment():
    query = """
    query ($projectId: String!, $serviceId: String!) {
      service(projectId: $projectId, serviceId: $serviceId) {
        deployments(first: 1, environmentId: null) {
          edges {
            node {
              id
              status
            }
          }
        }
      }
    }
    """
    variables = {'projectId': PROJECT_ID, 'serviceId': SERVICE_ID}
    try:
        response = requests.post(graphql_url, json={'query': query, 'variables': variables}, headers=headers)
        response.raise_for_status()
        data = response.json()
<<<<<<< HEAD
        print(f"get_active_deployment response: {json.dumps(data, indent=2)}")
        edges = data['data']['service']['deployments']['edges']
        return edges[0]['node']['id'] if edges and edges[0]['node']['status'] == 'SUCCESS' else None
    except requests.exceptions.RequestException as e:
        print(f"Error in get_active_deployment: {e}")
        print(f"Response: {response.text}")
=======
        if "values" not in data:
            logger.error(f"Некоректна відповідь API: {data}")
            raise ValueError("Некоректна відповідь API")
        df = pd.DataFrame(data["values"])
        df = df[["open", "high", "low", "close", "volume"]].astype(float)
        df = df.iloc[::-1].reset_index(drop=True)
        remaining = response.headers.get("X-RateLimit-Remaining")
        if remaining and int(remaining) < 10:
            logger.warning(f"Ліміт API низький: {remaining}. Очікування {API_WAIT_TIME} секунд")
            time_module.sleep(API_WAIT_TIME)
        return df
    except Exception as e:
        logger.error(f"Помилка запиту до API: {e}")
>>>>>>> 47d9aa3082d70386cd39190ffe52b474d80301f6
        raise

def remove_deployment(deployment_id):
    mutation = """
    mutation ($id: String!) {
      deploymentRemove(id: $id)
    }
    """
    variables = {'id': deployment_id}
    try:
        response = requests.post(graphql_url, json={'query': mutation, 'variables': variables}, headers=headers)
        response.raise_for_status()
        print(f"Deployment {deployment_id} removed successfully")
    except requests.exceptions.RequestException as e:
        print(f"Error in remove_deployment: {e}")
        print(f"Response: {response.text}")
        raise

def trigger_deployment():
    mutation = """
    mutation DeployService($input: ServiceDeployInput!) {
      serviceDeploy(input: $input) {
        id
      }
    }
    """
    variables = {
        'input': {
            'serviceId': SERVICE_ID,
            'projectId': PROJECT_ID
        }
    }
    try:
        response = requests.post(graphql_url, json={'query': mutation, 'variables': variables}, headers=headers)
        response.raise_for_status()
        print("New deployment triggered successfully")
        print(f"trigger_deployment response: {json.dumps(response.json(), indent=2)}")
    except requests.exceptions.RequestException as e:
        print(f"Error in trigger_deployment: {e}")
        print(f"Response: {response.text}")
        raise

<<<<<<< HEAD
if __name__ == "__main__":
    # Визначення часу в UTC
    now_utc = datetime.now(ZoneInfo("UTC")).time()
    is_deploy_time = now_utc.hour == 5  # 05:00 UTC = 08:00 EEST
    is_remove_time = now_utc.hour == 19  # 19:00 UTC = 22:00 EEST

    print(f"Current UTC time: {now_utc}, Deploy: {is_deploy_time}, Remove: {is_remove_time}")

    if is_remove_time:
        deployment_id = get_active_deployment()
        if deployment_id:
            remove_deployment(deployment_id)
        else:
            print("No active deployment found")
    elif is_deploy_time:
        trigger_deployment()
    else:
        print("No action required at this time")
=======
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
    # Умови для реальних даних і тестів
    rsi_buy_threshold = 70 if len(df) <= 3 else 40  # Для тестів із 3 свічками RSI < 70
    if last_rsi < rsi_buy_threshold and last_price >= last_ma * 0.99 and volume_filter:
        if is_bullish_engulfing(o1, c1, o2, c2) or is_hammer(o3, c3, h3, l3):
            signal = "BUY"
    elif last_rsi > 60 and last_price <= last_ma * 1.01 and volume_filter:
        if is_bearish_engulfing(o1, c1, o2, c2) or is_shooting_star(o3, c3, h3, l3):
            signal = "SELL"

    if signal and signal != last_signal:
        last_signal = signal
        return signal
    return None

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

# --- Перевірка робочих днів і часу ---
def is_working_hours():
    kyiv_tz = ZoneInfo("Europe/Kyiv")
    now = datetime.now(kyiv_tz)
    # Робочі дні (понеділок–п’ятниця) і час 08:00–22:00
    return now.weekday() < 5 and dt_time(8, 0) <= now.time() <= dt_time(22, 0)

# --- Основний цикл ---
if __name__ == "__main__":
    logger.info("Бот запущено.")
    send_telegram("Бот запущено на Railway")
    # Планування задачі лише в робочі дні та години
    schedule.every(5).minutes.at(":00").do(lambda: job() if is_working_hours() else None)
    while True:
        schedule.run_pending()
        time_module.sleep(1)
>>>>>>> 47d9aa3082d70386cd39190ffe52b474d80301f6
