#!/bin/bash
# cron.sh
EEST_TIME=$(TZ=Europe/Kyiv date +%H:%M:%S)
DAY=$(date -u +%u)
if [ "$DAY" -le 5 ] && [ "$EEST_TIME" = "08:00:00" ]; then
  echo "Deploying service at 8:00:00 EEST"
  RESPONSE=$(curl -X POST https://backboard.railway.app/graphql/v2 \
    -H "Authorization: Bearer $RAILWAY_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"mutation ServiceInstanceRedeploy { serviceInstanceRedeploy(environmentId: \\\"$RAILWAY_ENVIRONMENT_ID\\\", serviceId: \\\"$RAILWAY_SERVICE_ID\\\") }\"}" \
    --silent)
  echo "API Response: $RESPONSE"
  if echo "$RESPONSE" | jq -e '.errors' >/dev/null; then
    echo "API deployment failed: $(echo "$RESPONSE" | jq '.errors')"
    exit 1
  fi
  echo "Deployment triggered successfully"
elif [ "$DAY" -le 5 ] && [ "$EEST_TIME" = "20:00:00" ]; then
  echo "Stopping service at 20:00:00 EEST"
  RESPONSE=$(curl -X POST https://backboard.railway.app/graphql/v2 \
    -H "Authorization: Bearer $RAILWAY_TOKEN" \
    -H "Content-Type: application/json" \
    -d "{\"query\":\"mutation ServiceInstanceStop { serviceInstanceStop(environmentId: \\\"$RAILWAY_ENVIRONMENT_ID\\\", serviceId: \\\"$RAILWAY_SERVICE_ID\\\") }\"}" \
    --silent)
  echo "API Response: $RESPONSE"
  if echo "$RESPONSE" | jq -e '.errors' >/dev/null; then
    echo "API stop failed: $(echo "$RESPONSE" | jq '.errors')"
    exit 1
  fi
  echo "Service stopped successfully"
fi
