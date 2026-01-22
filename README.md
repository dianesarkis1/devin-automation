# Devin GitHub Automation

Automated GitHub issue management using Devin - list out issues, scope them and assign confidence scores, and trigger a session to take the action plan and complete the ticket with simple clicks.

## Features

- **Triage**: Analyze issues, generate implementation plans, assign confidence scores
- **Execute**: Automatically implement fixes and create pull requests
- **Verify**: Run tests on PR branches to confirm merge readiness
- **Real-time Dashboard**: Monitor Devin sessions with live status updates

## Setup

1. Copy `.env.example` to `.env` and configure:
   ```bash
   cp apps/api/.env.example apps/api/.env
   ```

2. Add your credentials:
   ```
   DEVIN_API_KEY=your_devin_api_key
   DEVIN_BASE_URL=https://api.devin.ai
   GITHUB_TOKEN=your_github_token
   GITHUB_OWNER=your_org
   GITHUB_REPO=your_repo
   ```

3. Install requirements as needed:
   ```
   pip install uvicorn fastapi python-dotenv requests
   ```

## Run

```bash
cd apps/api
uvicorn main:app --reload
```

Open dashboard at: **http://localhost:8000/dashboard**
