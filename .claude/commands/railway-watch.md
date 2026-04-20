---
description: Watch a Railway deployment until it succeeds or crashes, then show logs if needed
---

# Watch Railway Deployment

Monitor the most recent Railway deployment for the **web** service until it reaches a terminal state (`SUCCESS` or `CRASHED`).

## Setup
- Railway token is in `~/.railway/config.json` under `user.token`
- Web service ID: `c67ee567-b38b-4b81-a371-02ac7b2bef94`

## Steps

1. Read the token from `~/.config/railway/config.json`

2. Poll the Railway GraphQL API every 20 seconds for the latest deployment status of the web service:
```bash
curl -s -X POST https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ deployments(input: { serviceId: \"c67ee567-b38b-4b81-a371-02ac7b2bef94\" }) { edges { node { id status createdAt } } } }"}'
```

3. Report the current status after each poll. Continue polling if status is `BUILDING` or `DEPLOYING`.

4. Stop when status is `SUCCESS` or `CRASHED`.

5. **If SUCCESS**: Report success and the deployment timestamp.

6. **If CRASHED**: Fetch the full deployment logs and show the relevant error:
```bash
curl -s -X POST https://backboard.railway.app/graphql/v2 \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query": "{ deploymentLogs(deploymentId: \"DEPLOYMENT_ID\") { message } }"}'
```
Display the last 40 log lines (or all lines containing "Error", "error", "Exception", "Traceback", "CommandError"). Then diagnose and fix the issue.

## Common crash causes in this project
- **Migration conflict**: Two migration branches with the same number → create a merge migration with `makemigrations --merge` or write one manually pointing to both leaf nodes
- **Import error**: A new model referenced in views/forms but not imported
- **Missing dependency**: Package added to code but not in requirements.txt
