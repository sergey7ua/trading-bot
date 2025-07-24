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

# API URL
RAILWAY_API_URL = "https://backboard.railway.app/graphql/v2"

# Заголовки
def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

# Перевірка змінних середовища
def validate_environment_variables():
    token = os.getenv("RAILWAY_TOKEN")
    project_id = os.getenv("RAILWAY_PROJECT_ID")
    environment_id = os.getenv("RAILWAY_ENVIRONMENT_ID")
    service_id = os.getenv("RAILWAY_SERVICE_ID")
    
    if not all([token, project_id, environment_id, service_id]):
        logger.error("Не встановлені всі необхідні змінні середовища")
        raise ValueError("Не встановлені всі необхідні змінні середовища")
    
    # Очистка ID від префіксів
    cleaned_project_id = project_id.replace("project/", "").strip()
    cleaned_environment_id = environment_id.replace("env/", "").strip()
    cleaned_service_id = service_id.replace("service/", "").strip()
    
    return token, cleaned_project_id, cleaned_environment_id, cleaned_service_id

# Перевірка токена
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def validate_token(token):
    query = """query { me { id email } }"""
    payload = {"query": query}
    try:
        response = requests.post(RAILWAY_API_URL, headers=get_headers(token), json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            return False
        if data.get("data", {}).get("me", {}).get("email"):
            logger.info(f"Токен валідний для користувача: {data['data']['me']['email']}")
            return True
        return False
    except Exception as e:
        logger.error(f"Помилка в validate_token: {str(e)}")
        return False

# Отримання інформації про проект
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_project_info(token, project_id):
    query = """
    query GetProject($id: String!) {
        project(id: $id) {
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
    """
    variables = {"id": project_id}
    payload = {"query": query, "variables": variables}
    try:
        response = requests.post(RAILWAY_API_URL, headers=get_headers(token), json=payload, timeout=15)
        response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            return None
        return data.get("data", {}).get("project")
    except Exception as e:
        logger.error(f"Помилка в get_project_info: {str(e)}")
        return None

# Перевірка часу деплою
def is_deployment_time():
    kyiv_tz = ZoneInfo("Europe/Kyiv")
    now = datetime.now(kyiv_tz)
    # Деплой з 3:00 до 23:00 по Києву (00:00-20:00 UTC)
    result = now.weekday() < 5 and dtime(3, 0) <= now.time() <= dtime(23, 0)
    logger.info(f"Поточний час: {now}. Час деплою: {result}")
    return result

# Перевірка активного деплою
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_active_deployment(token, project_id, environment_id):
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
    variables = {"projectId": project_id, "environmentId": environment_id}
    payload = {"query": query, "variables": variables}
    try:
        response = requests.post(RAILWAY_API_URL, headers=get_headers(token), json=payload, timeout=10)
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

# Розгортання сервісу
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def deploy_service(token, project_id, environment_id, service_id):
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
            "projectId": project_id,
            "environmentId": environment_id,
            "serviceId": service_id
        }
    }
    payload = {"query": mutation, "variables": variables}
    try:
        response = requests.post(RAILWAY_API_URL, headers=get_headers(token), json=payload, timeout=10)
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

if __name__ == "__main__":
    try:
        logger.info("Скрипт запущено")
        
        # Валідація змінних
        token, project_id, environment_id, service_id = validate_environment_variables()
        
        # Перевірка токена
        if not validate_token(token):
            raise ValueError("Невалідний RAILWAY_TOKEN")
        
        # Перевірка проєкту та сервісу
        project_info = get_project_info(token, project_id)
        if not project_info:
            raise ValueError("Проєкт не знайдено")
        
        logger.info(f"Проєкт: {project_info['name']} (ID: {project_info['id']})")
        
        # Основна логіка
        if is_deployment_time():
            deployment_id = get_active_deployment(token, project_id, environment_id)
            if not deployment_id:
                deployment_id = deploy_service(token, project_id, environment_id, service_id)
                if deployment_id:
                    logger.info(f"Успішно розгорнуто: {deployment_id}")
                else:
                    logger.error("Не вдалося розгорнути сервіс")
            else:
                logger.info(f"Активний деплой вже існує: {deployment_id}")
        else:
            logger.info("Поточний час не в межах часу деплою")
            
    except Exception as e:
        logger.error(f"Критична помилка: {str(e)}")
        raise
