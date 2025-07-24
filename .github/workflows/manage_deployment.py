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
    project_id = os.getenv("PROJECT_ID") or os.getenv("RAILWAY_PROJECT_ID")
    environment_id = os.getenv("ENVIRONMENT_ID") or os.getenv("RAILWAY_ENVIRONMENT_ID")
    service_id = os.getenv("SERVICE_ID") or os.getenv("RAILWAY_SERVICE_ID")
    
    if not all([token, project_id, environment_id, service_id]):
        logger.error("Не встановлені всі необхідні змінні середовища: RAILWAY_TOKEN, PROJECT_ID/RAILWAY_PROJECT_ID, ENVIRONMENT_ID/RAILWAY_ENVIRONMENT_ID, SERVICE_ID/RAILWAY_SERVICE_ID")
        raise ValueError("Не встановлені всі необхідні змінні середовища")
    
    # Очистка ID від префіксів
    cleaned_project_id = project_id.replace("project/", "").strip() if project_id else None
    cleaned_environment_id = environment_id.replace("env/", "").strip() if environment_id else None
    cleaned_service_id = service_id.replace("service/", "").strip() if service_id else None
    
    return token, cleaned_project_id, cleaned_environment_id, cleaned_service_id

# Перевірка токена через GraphQL API
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def validate_token(token):
    query = """
    query {
        me {
            id
            email
        }
    }
    """
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

# Перевірка проєкту та сервісу
def validate_project_and_service(token, project_id, environment_id, service_id):
    project = get_project_info(token, project_id)
    if not project:
        logger.error(f"Проєкт з ID {project_id} не знайдено")
        return False
    
    logger.info(f"Проєкт: {project['name']} (ID: {project['id']})")
    
    # Перевірка середовища
    env_found = False
    for env in project.get("environments", {}).get("edges", []):
        if env["node"]["id"] == environment_id:
            env_found = True
            logger.info(f"Середовище: {env['node']['name']} (ID: {env['node']['id']})")
            break
    
    if not env_found:
        logger.error(f"Середовище з ID {environment_id} не знайдено")
        return False
    
    # Перевірка сервісу
    service_found = False
    for svc in project.get("services", {}).get("edges", []):
        if svc["node"]["id"] == service_id:
            service_found = True
            logger.info(f"Сервіс: {svc['node']['name']} (ID: {svc['node']['id']})")
            break
    
    if not service_found:
        logger.error(f"Сервіс з ID {service_id} не знайдено")
        return False
    
    return True

# Інші функції залишаються без змін (get_active_deployment, deploy_service, remove_deployment, is_deployment_time)

if __name__ == "__main__":
    logger.info("Скрипт запущено")
    try:
        # Валідація змінних
        token, project_id, environment_id, service_id = validate_environment_variables()
        
        # Перевірка токена
        if not validate_token(token):
            raise ValueError("Невалідний RAILWAY_TOKEN")
        
        # Перевірка проєкту та сервісу
        if not validate_project_and_service(token, project_id, environment_id, service_id):
            raise ValueError("Невалідні PROJECT_ID, ENVIRONMENT_ID або SERVICE_ID")
        
        # Основна логіка
        if is_deployment_time():
            deployment_id = get_active_deployment(token, project_id, environment_id)
            if not deployment_id:
                deployment_id = deploy_service(token, project_id, environment_id, service_id)
                if deployment_id:
                    logger.info(f"Розгорнуто сервіс з ID: {deployment_id}")
                else:
                    logger.error("Не вдалося розгорнути сервіс")
            else:
                logger.info(f"Знайдено активний деплой: {deployment_id}")
        else:
            deployment_id = get_active_deployment(token, project_id, environment_id)
            if deployment_id:
                remove_deployment(token, project_id, environment_id, deployment_id)
                logger.info(f"Видалено деплой: {deployment_id}")
            else:
                logger.info("Немає активного деплою для видалення")
    except Exception as e:
        logger.error(f"Критична помилка: {str(e)}")
        raise
