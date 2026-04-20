---
description: Check the current Railway deployment status for cachin-app (web, worker, beat services)
---

# Railway Deployment Status

Check the latest deployment status for all cachin-app services on Railway.

## Setup
- Railway token is in `~/.railway/config.json` under `user.token`
- Project ID: `246f879e-30bd-400e-ae30-83fceb906cc6`
- Services:
  - **web**: `c67ee567-b38b-4b81-a371-02ac7b2bef94`
  - **worker**: `07543960-44f0-40d1-9094-0377bc77296b`
  - **beat**: `e485718f-e2f1-4100-bc3f-b79cfcadbb0f`

## Steps

1. Read the token from `~/.railway/config.json`

2. For each service (web, worker, beat), query Railway's GraphQL API for the latest deployment:
```bash
curl -s -X POST https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ deployments(input: { serviceId: \"SERVICE_ID\" }) { edges { node { id status createdAt } } } }"}'
```

3. Display a clear summary table showing service name, status, and timestamp for the most recent deployment of each service.

Status meanings:
- `BUILDING` — currently building/deploying
- `SUCCESS` — running normally
- `CRASHED` — failed, needs investigation
- `REMOVED` — replaced by a newer deployment
- `DEPLOYING` — being deployed

4. If any service shows `CRASHED`, automatically fetch and display the last 30 lines of logs using:
```bash
curl -s -X POST https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ deploymentLogs(deploymentId: \"DEPLOYMENT_ID\") { message } }"}'
```
Filter for lines containing errors or the crash reason.
