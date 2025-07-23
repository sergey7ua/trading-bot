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
    logger.info(f"Валідовані ID: PROJECT_ID={cleaned_project_id}, ENVIRONMENT_ID={cleaned_environment_id}, SERVICE_ID={cleaned_service_id}")
    
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
    logger.info(f"Надсилаємо запит validate_token до {RAILWAY_API_URL}")
    try:
        response = requests.post(RAILWAY_API_URL, headers=get_headers(token), json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            if any("Unauthorized" in error.get("message", "") for error in data["errors"]):
                logger.error("Токен невалідний або не має доступу")
                return False
            return False
        if data.get("data", {}).get("me", {}).get("email"):
            logger.info(f"Токен валідний для користувача: {data['data']['me']['email']}")
            return True
        logger.error("Токен невалідний: відповідь не містить даних користувача")
        return False
    except Exception as e:
        logger.error(f"Помилка в validate_token: {str(e)}")
        return False

# Перевірка проєкту та сервісу через GraphQL API
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def validate_project_and_service(token, project_id, environment_id, service_id):
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
    logger.info(f"Надсилаємо запит validate_project_and_service до {RAILWAY_API_URL}")
    try:
        response = requests.post(RAILWAY_API_URL, headers=get_headers(token), json=payload, timeout=10)
        if response.status_code != 200:
            logger.error(f"HTTP {response.status_code}: {response.text}")
            response.raise_for_status()
        data = response.json()
        if "errors" in data:
            logger.error(f"GraphQL errors: {json.dumps(data['errors'], indent=2)}")
            return False
        
        projects = data.get("data", {}).get("projects", {}).get("edges", [])
        if not projects:
            logger.error("Список проєктів порожній. Перевірте, чи є активні проєкти в акаунті та чи використовується Account Token.")
            return False
        
        # Логування всіх доступних проєктів, середовищ і сервісів
        logger.info("Доступні проєкти:")
        for project in projects:
            project_data = project["node"]
            logger.info(f"Проєкт: {project_data['name']} (ID: {project_data['id']})")
            for env in project_data.get("environments", {}).get("edges", []):
                logger.info(f"  Середовище: {env['node']['name']} (ID: {env['node']['id']})")
            for svc in project_data.get("services", {}).get("edges", []):
                logger.info(f"  Сервіс: {svc['node']['name']} (ID: {svc['node']['id']})")
        
        # Перевірка відповідності ID
        for project in projects:
            if project["node"]["id"] == project_id:
                logger.info(f"Знайдено проєкт: {project['node']['name']} (ID: {project_id})")
                for env in project["node"].get("environments", {}).get("edges", []):
                    if env["node"]["id"] == environment_id:
                        logger.info(f"Знайдено середовище: {env['node']['name']} (ID: {environment_id})")
                        for svc in project["node"].get("services", {}).get("edges", []):
                            if svc["node"]["id"] == service_id:
                                logger.info(f"Знайдено сервіс: {svc['node']['name']} (ID: {service_id})")
                                return True
        logger.error(f"Проєкт, середовище або сервіс не знайдено: PROJECT_ID={project_id}, ENVIRONMENT_ID={environment_id}, SERVICE_ID={service_id}")
        return False
    except Exception as e:
        logger.error(f"Помилка в validate_project_and_service: {str(e)}")
        return False

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
    variables = {
        "projectId": project_id,
        "environmentId": environment_id
    }
    payload = {"query": query, "variables": variables}
    logger.info(f"Надсилаємо запит get_active_deployment: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(RAILWAY_API_URL, headers=get_headers(token), json=payload, timeout=10)
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
    logger.info(f"Надсилаємо запит deploy_service: {json.dumps(payload, indent=2)}")
    try:
        response = requests.post(RAILWAY_API_URL, headers=get_headers(token), json=payload, timeout=10)
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

# Видалення деплою
@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def remove_deployment(token, project_id, environment_id, deployment_id):
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
        response = requests.post(RAILWAY_API_URL, headers=get_headers(token), json=payload, timeout=10)
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
        token, project_id, environment_id, service_id = validate_environment_variables()
        
        # Перевірка токена
        if not validate_token(token):
            logger.error("Невалідний RAILWAY_TOKEN. Оновіть токен у GitHub Secrets.")
            raise ValueError("Невалідний RAILWAY_TOKEN")
        
        # Перевірка проєкту та сервісу
        if not validate_project_and_service(token, project_id, environment_id, service_id):
            logger.error("Валідація проєкту/середовища/сервісу не пройшла. Перевірте ID у GitHub Secrets або Railway Provided Variables.")
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
