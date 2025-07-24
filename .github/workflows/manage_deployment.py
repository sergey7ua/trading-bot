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

def get_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

def validate_environment_variables():
    token = os.getenv("RAILWAY_TOKEN")
    project_id = os.getenv("RAILWAY_PROJECT_ID")
    environment_id = os.getenv("RAILWAY_ENVIRONMENT_ID")
    service_id = os.getenv("RAILWAY_SERVICE_ID")
    
    if not all([token, project_id, environment_id, service_id]):
        raise ValueError("Не встановлені всі необхідні змінні середовища")
    
    return token, project_id, environment_id, service_id

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def validate_token(token):
    query = """query { me { id email } }"""
    response = requests.post(
        RAILWAY_API_URL,
        headers=get_headers(token),
        json={"query": query},
        timeout=10
    )
    response.raise_for_status()
    data = response.json()
    if "errors" in data:
        raise ValueError(f"GraphQL error: {data['errors']}")
    return data.get("data", {}).get("me", {}).get("email")

def is_deployment_time():
    kyiv_tz = ZoneInfo("Europe/Kyiv")
    now = datetime.now(kyiv_tz)
    return now.weekday() < 5 and dtime(3, 0) <= now.time() <= dtime(23, 0)

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_active_deployment(token, project_id, environment_id):
    query = """
    query GetDeployments($projectId: ID!, $environmentId: ID!) {
        deployments(
            projectId: $projectId
            environmentId: $environmentId
            first: 1
            orderBy: { field: CREATED_AT, direction: DESC }
        ) {
            edges {
                node {
                    id
                    status
                    createdAt
                }
            }
        }
    }
    """
    variables = {
        "projectId": project_id,
        "environmentId": environment_id
    }
    response = requests.post(
        RAILWAY_API_URL,
        headers=get_headers(token),
        json={"query": query, "variables": variables},
        timeout=15
    )
    response.raise_for_status()
    data = response.json()
    
    if "errors" in data:
        raise ValueError(f"GraphQL error: {data['errors']}")
    
    deployments = data.get("data", {}).get("deployments", {}).get("edges", [])
    if deployments and deployments[0]["node"]["status"] == "SUCCESS":
        return deployments[0]["node"]["id"]
    return None

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def deploy_service(token, project_id, environment_id, service_id):
    mutation = """
    mutation Deploy($input: DeploymentTriggerInput!) {
        deploymentTrigger(input: $input) {
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
    response = requests.post(
        RAILWAY_API_URL,
        headers=get_headers(token),
        json={"query": mutation, "variables": variables},
        timeout=15
    )
    response.raise_for_status()
    data = response.json()
    
    if "errors" in data:
        raise ValueError(f"GraphQL error: {data['errors']}")
    
    return data.get("data", {}).get("deploymentTrigger", {}).get("id")

def main():
    try:
        logger.info("Скрипт запущено")
        
        token, project_id, environment_id, service_id = validate_environment_variables()
        
        user_email = validate_token(token)
        logger.info(f"Токен валідний для: {user_email}")
        
        if is_deployment_time():
            logger.info("Поточний час підходить для деплою")
            deployment_id = get_active_deployment(token, project_id, environment_id)
            
            if deployment_id:
                logger.info(f"Активний деплой вже існує: {deployment_id}")
            else:
                deployment_id = deploy_service(token, project_id, environment_id, service_id)
                logger.info(f"Успішно розгорнуто: {deployment_id}")
        else:
            logger.info("Поточний час не підходить для деплою")
            
    except Exception as e:
        logger.error(f"Помилка: {str(e)}")
        raise

if __name__ == "__main__":
    main()
