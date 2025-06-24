import os
import requests
import json
import logging
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo
from tenacity import retry, stop_after_attempt, wait_exponential

# Налаштування логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# Змінні середовища
RAILWAY_TOKEN = os.getenv("RAILWAY_TOKEN")
PROJECT_ID = os.getenv("PROJECT_ID")
ENVIRONMENT_ID = os.getenv("ENVIRONMENT_ID")
SERVICE_ID = os.getenv("SERVICE_ID")

# Перевірка змінних середовища
if not all([RAILWAY_TOKEN, PROJECT_ID, ENVIRONMENT_ID, SERVICE_ID]):
    logger.error("Не встановлені всі необхідні змінні середовища")
    raise ValueError("Не встановлені всі необхідні змінні середовища")

# API URL
RAILWAY_API_URL = "https://backboard.railway.app/graphql/v2"

# Заголовки
HEADERS = {
    "Project-Access-Token": RAILWAY_TOKEN,  # Для проєктного токена
    "Content-Type": "application/json",
}

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_active_deployment():
    query = """
    query Deployments($projectId: String!, $environmentId: String!, $serviceId: String!) {
        deployments(projectId: $projectId, environmentId: $environmentId, serviceId: $serviceId) {
            edges {
                node {
                    id
                    status
                }
            }
        }
    }
    """
    variables = {
        "projectId": PROJECT_ID,
        "environmentId": ENVIRONMENT_ID,
        "serviceId": SERVICE_ID
    }
    payload = {"query": query, "variables": variables}
    
    try:
        logger.info(f"Надсилаємо запит get_active_deployment: {json.dumps(payload, indent=2)}")
        response = requests.post(RAILWAY_API_URL, headers=HEADERS, json=payload)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            return None
        for edge in data["data"]["deployments"]["edges"]:
            if edge["node"]["status"] == "ACTIVE":
                logger.info(f"Знайдено активний деплой: {edge['node']['id']}")
                return edge["node"]["id"]
        return None
    except Exception as e:
        logger.error(f"Помилка в get_active_deployment: {e}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def deploy_service():
    mutation = """
    mutation Deploy($input: DeploymentInput!) {
        deploymentCreate(input: $input) {
            id
        }
    }
    """
    variables = {
        "input": {
            "projectId": PROJECT_ID,
            "environmentId": ENVIRONMENT_ID,
            "serviceId": SERVICE_ID
        }
    }
    payload = {"query": mutation, "variables": variables}
    
    try:
        logger.info(f"Надсилаємо запит deploy_service: {json.dumps(payload, indent=2)}")
        response = requests.post(RAILWAY_API_URL, headers=HEADERS, json=payload)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            return None
        deployment_id = data["data"]["deploymentCreate"]["id"]
        logger.info(f"Розгорнуто сервіс з ID: {deployment_id}")
        return deployment_id
    except Exception as e:
        logger.error(f"Помилка в deploy_service: {e}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def remove_deployment(deployment_id):
    mutation = """
    mutation RemoveDeployment($id: String!) {
        deploymentRemove(id: $id)
    }
    """
    variables = {"id": deployment_id}
    payload = {"query": mutation, "variables": variables}
    
    try:
        logger.info(f"Надсилаємо запит remove_deployment: {json.dumps(payload, indent=2)}")
        response = requests.post(RAILWAY_API_URL, headers=HEADERS, json=payload)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
        else:
            logger.info(f"Видалено деплой: {deployment_id}")
    except Exception as e:
        logger.error(f"Помилка в remove_deployment: {e}")
        raise

def is_deployment_time():
    kyiv_tz = ZoneInfo("Europe/Kyiv")
    now = datetime.now(kyiv_tz)
    return now.weekday() < 5 and dtime(3, 0) <= now.time() <= dtime(22, 59)

if __name__ == "__main__":
    logger.info("Скрипт запущено")
    try:
        if is_deployment_time():
            deployment_id = get_active_deployment()
            if not deployment_id:
                deployment_id = deploy_service()
                if deployment_id:
                    logger.info(f"Розгорнуто сервіс з ID: {deployment_id}")
                else:
                    logger.error("Не вдалося розгорнути сервіс")
            else:
                logger.info(f"Знайдено активний деплой: {deployment_id}")
        else:
            deployment_id = get_active_deployment()
            if deployment_id:
                remove_deployment(deployment_id)
                logger.info(f"Видалено деплой: {deployment_id}")
            else:
                logger.info("Немає активного деплою для видалення")
    except Exception as e:
        logger.error(f"Критична помилка в скрипті: {e}")
        exit(1)
