import os
import requests
import json
from datetime import datetime
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
        print(f"get_active_deployment response: {json.dumps(data, indent=2)}")
        edges = data['data']['service']['deployments']['edges']
        return edges[0]['node']['id'] if edges and edges[0]['node']['status'] == 'SUCCESS' else None
    except requests.exceptions.RequestException as e:
        print(f"Error in get_active_deployment: {e}")
        print(f"Response: {response.text}")
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