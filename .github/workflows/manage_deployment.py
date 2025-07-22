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
RAILWAY_API_URL = "https://backboard.railway.app"

# Заголовки
def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

# Перевірка змінних середовища
def validate_environment_variables():
    token = os.getenv("RAILWAY_TOKEN")
    project_id = os.getenv("PROJECT_ID")
    environment_id = os.getenv("ENVIRONMENT_ID")
    service_id = os.getenv("SERVICE_ID")
    
    if not all([token, project_id, environment_id, service_id]):
        logger.error("Не встановлені всі необхідні змінні середовища: RAILWAY_TOKEN, PROJECT_ID, ENVIRONMENT_ID, SERVICE_ID")
        raise ValueError("Не встановлені всі необхідні змінні середовища")
    
    # Очистка ID від префіксів
    cleaned_project_id = project_id.replace("project/", "").strip()
    cleaned_environment_id = environment_id.replace("env/", "").strip()
    cleaned_service_id = service_id.replace("service/", "").strip()
    logger.info(f"Валідовані ID: PROJECT_ID={cleaned_project_id}, ENVIRONMENT_ID={cleaned_environment_id}, SERVICE_ID={cleaned_service_id}")
    
    return token, cleaned_project_id, cleaned_environment_id, cleaned_service_id

# Перевірка токена через REST API
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def validate_token(token):
    url = f"{RAILWAY_API_URL}/user"
    logger.info(f"Надсилаємо запит validate_token до {url}")
    try:
        response = requests.get(url, headers=get_headers(token), timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "email" in data:
            logger.info(f"Токен валідний для користувача: {data['email']}")
            return True
        logger.error("Токен невалідний: відповідь не містить даних користувача")
        return False
    except Exception as e:
        logger.error(f"Помилка в validate_token: {str(e)}")
        return False

# Перевірка проєкту та сервісу через REST API
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def validate_project_and_service(token, project_id, environment_id, service_id):
    url = f"{RAILWAY_API_URL}/projects"
    logger.info(f"Надсилаємо запит validate_project_and_service до {url}")
    try:
        response = requests.get(url, headers=get_headers(token), timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        projects = response.json().get("data", [])
        for project in projects:
            if project["id"] == project_id:
                logger.info(f"Знайдено проєкт: {project['name']} (ID: {project_id})")
                for env in project.get("environments", []):
                    if env["id"] == environment_id:
                        logger.info(f"Знайдено середовище: {env['name']} (ID: {environment_id})")
                for svc in project.get("services", []):
                    if svc["id"] == service_id:
                        logger.info(f"Знайдено сервіс: {svc['name']} (ID: {service_id})")
                        return True
        logger.error(f"Проєкт, середовище або сервіс не знайдено: PROJECT_ID={project_id}, ENVIRONMENT_ID={environment_id}, SERVICE_ID={service_id}")
        return False
    except Exception as e:
        logger.error(f"Помилка в validate_project_and_service: {str(e)}")
        return False

# Перевірка активного деплою
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_active_deployment(token, project_id, environment_id):
    url = f"{RAILWAY_API_URL}/projects/{project_id}/environments/{environment_id}/deployments"
    logger.info(f"Надсилаємо запит get_active_deployment до {url}")
    try:
        response = requests.get(url, headers=get_headers(token), timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        deployments = response.json().get("data", [])
        for dep in deployments:
            if dep["status"] == "SUCCESS":
                logger.info(f"Знайдено активний деплой: {dep['id']}")
                return dep["id"]
        logger.info("Активний деплой не знайдено")
        return None
    except Exception as e:
        logger.error(f"Помилка в get_active_deployment: {str(e)}")
        raise

# Розгортання сервісу
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def deploy_service(token, project_id, environment_id, service_id):
    url = f"{RAILWAY_API_URL}/projects/{project_id}/environments/{environment_id}/services/{service_id}/redeploy"
    logger.info(f"Надсилаємо запит deploy_service до {url}")
    try:
        response = requests.post(url, headers=get_headers(token), timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        deployment_id = data.get("data", {}).get("id")
        if deployment_id:
            logger.info(f"Розгорнуто сервіс з ID: {deployment_id}")
            return deployment_id
        logger.error("Не вдалося отримати ID деплою")
        return None
    except Exception as e:
        logger.error(f"Помилка в deploy_service: {str(e)}")
        raise

# Видалення деплою
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def remove_deployment(token, project_id, environment_id, deployment_id):
    url = f"{RAILWAY_API_URL}/projects/{project_id}/environments/{environment_id}/deployments/{deployment_id}"
    logger.info(f"Надсилаємо запит remove_deployment до {url}")
    try:
        response = requests.delete(url, headers=get_headers(token), timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        logger.info(f"Видалено деплой: {deployment_id}")
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
        token, project_id, environment_id, service_id = validate_environment_variables()
        
        # Перевірка токена
        if not validate_token(token):
            logger.error("Невалідний RAILWAY_TOKEN. Оновіть токен у GitHub Secrets.")
            raise ValueError("Невалідний RAILWAY_TOKEN")
        
        # Перевірка проєкту та сервісу
        if not validate_project_and_service(token, project_id, environment_id, service_id):
            logger.error("Валідація проєкту/середовища/сервісу не пройшла. Перевірте ID у GitHub Secrets.")
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
        logger.error(f"Критична помилка в скрипті: {str(e)}")
        raise
