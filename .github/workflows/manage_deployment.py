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

# API URL
RAILWAY_API_URL = "https://backboard.railway.app/graphql/v2"

# Заголовки
HEADERS = {
    "Authorization": f"Bearer {RAILWAY_TOKEN}",
    "Content-Type": "application/json",
}

# Перевірка змінних середовища
def validate_environment_variables():
    if not all([RAILWAY_TOKEN, PROJECT_ID, ENVIRONMENT_ID, SERVICE_ID]):
        logger.error("Не встановлені всі необхідні змінні середовища: RAILWAY_TOKEN, PROJECT_ID, ENVIRONMENT_ID, SERVICE_ID")
        raise ValueError("Не встановлені всі необхідні змінні середовища")
    # Очистка ID від префіксів
    cleaned_project_id = PROJECT_ID.replace("project/", "").strip()
    cleaned_environment_id = ENVIRONMENT_ID.replace("env/", "").strip()
    cleaned_service_id = SERVICE_ID.replace("service/", "").strip()
    return cleaned_project_id, cleaned_environment_id, cleaned_service_id

# Отримання списку проєктів для валідації ID
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def validate_project_and_service():
    query = """
    query {
        projects {
            edges {
                node {
                    id
                    name
                    environments {
                        edges {
                            node {
                                id
                                name
                            }
                        }
                    }
                    services {
                        edges {
                            node {
                                id
                                name
                            }
                        }
                    }
                }
            }
        }
    }
    """
    payload = {"query": query}
    logger.info(f"Надсилаємо запит validate_project_and_service: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(RAILWAY_API_URL, headers=HEADERS, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            return None
        projects = data.get("data", {}).get("projects", {}).get("edges", [])
        for project in projects:
            project_id = project["node"]["id"]
            if project_id == PROJECT_ID:
                logger.info(f"Знайдено проєкт: {project['node']['name']} (ID: {project_id})")
                environments = project["node"].get("environments", {}).get("edges", [])
                for env in environments:
                    if env["node"]["id"] == ENVIRONMENT_ID:
                        logger.info(f"Знайдено середовище: {env['node']['name']} (ID: {ENVIRONMENT_ID})")
                services = project["node"].get("services", {}).get("edges", [])
                for svc in services:
                    if svc["node"]["id"] == SERVICE_ID:
                        logger.info(f"Знайдено сервіс: {svc['node']['name']} (ID: {SERVICE_ID})")
                        return True
        logger.error(f"Проєкт, середовище або сервіс не знайдено: PROJECT_ID={PROJECT_ID}, ENVIRONMENT_ID={ENVIRONMENT_ID}, SERVICE_ID={SERVICE_ID}")
        return False
    except Exception as e:
        logger.error(f"Помилка в validate_project_and_service: {str(e)}")
        return False

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_active_deployment():
    query = """
    query GetDeployments($projectId: String!, $environmentId: String!) {
        deployments(projectId: $projectId, environmentId: $environmentId, first: 10) {
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
        "environmentId": ENVIRONMENT_ID
    }
    payload = {"query": query, "variables": variables}
    
    logger.info(f"Надсилаємо запит get_active_deployment: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(RAILWAY_API_URL, headers=HEADERS, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            return None
        for edge in data.get("data", {}).get("deployments", {}).get("edges", []):
            if edge["node"]["status"] == "SUCCESS":
                logger.info(f"Знайдено активний деплой: {edge['node']['id']}")
                return edge["node"]["id"]
        logger.info("Активний деплой не знайдено")
        return None
    except Exception as e:
        logger.error(f"Помилка в get_active_deployment: {str(e)}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def deploy_service():
    mutation = """
    mutation Deploy($input: DeploymentInput!) {
        deploymentCreate(input: $input) {
            id
            status
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
    
    logger.info(f"Надсилаємо запит deploy_service: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(RAILWAY_API_URL, headers=HEADERS, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            return None
        deployment_id = data.get("data", {}).get("deploymentCreate", {}).get("id")
        if deployment_id:
            logger.info(f"Розгорнуто сервіс з ID: {deployment_id}")
            return deployment_id
        logger.error("Не вдалося отримати ID деплою")
        return None
    except Exception as e:
        logger.error(f"Помилка в deploy_service: {str(e)}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def remove_deployment(deployment_id):
    mutation = """
    mutation RemoveDeployment($id: String!) {
        deploymentRemove(id: $id) {
            success
        }
    }
    """
    variables = {"id": deployment_id}
    payload = {"query": mutation, "variables": variables}
    
    logger.info(f"Надсилаємо запит remove_deployment: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(RAILWAY_API_URL, headers=HEADERS, json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            return
        if data.get("data", {}).get("deploymentRemove", {}).get("success"):
            logger.info(f"Видалено деплой: {deployment_id}")
        else:
            logger.error(f"Не вдалося видалити деплой: {deployment_id}")
    except Exception as e:
        logger.error(f"Помилка в remove_deployment: {str(e)}")
        raise

def is_deployment_time():
    kyiv_tz = ZoneInfo("Europe/Kyiv")
    now = datetime.now(kyiv_tz)
    result = now.weekday() < 5 and dtime(3, 0) <= now.time() <= dtime(22, 59)
    logger.info(f"Перевірка часу деплою: {result} (час: {now})")
    return result

if __name__ == "__main__":
    logger.info("Скрипт запущено")
    try:
        # Валідація змінних
        global PROJECT_ID, ENVIRONMENT_ID, SERVICE_ID
        PROJECT_ID, ENVIRONMENT_ID, SERVICE_ID = validate_environment_variables()
        
        # Перевірка проєкту та сервісу
        if not validate_project_and_service():
            logger.error("Валідація проєкту/середовища/сервісу не пройшла. Перевірте ID у GitHub Secrets.")
            raise ValueError("Невалідні PROJECT_ID, ENVIRONMENT_ID або SERVICE_ID")
        
        # Основна логіка
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
        logger.error(f"Критична помилка в скрипті: {str(e)}")
        raise
