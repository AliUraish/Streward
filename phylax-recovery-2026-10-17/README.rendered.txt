Phylax


Next.js frontend, FastAPI backend, PostgreSQL (
Phylax
 on the Swivel RDS
server), and Claude via the Claude Agent SDK on your Claude subscription.


Repository layout


phylax/
├── backend/                 FastAPI application
│   ├── run.sh               venv + deps + SSH tunnel + uvicorn
│   ├── src/
│   │   ├── main.py          FastAPI composition root
│   │   ├── database/        Connection settings and pooling
│   │   ├── claude/          Subscription-first Claude Agent SDK transport
│   │   └── features/
│   │       └── system/      Reference feature (status endpoint)
│   │           ├── controllers/
│   │           ├── steps/
│   │           └── pipelines/
│   ├── sql/
│   │   ├── database.sql     Current database bootstrap definition
│   │   └── legacy/          Applied migrations
│   ├── scripts/
│   └── tests/
├── frontend/                Next.js App Router + TypeScript + shadcn/ui
└── docs/                    Architecture and Claude Agent SDK docs





















Run locally


Backend (requires Python 3.12+ and the Swivel bastion SSH key):


cd
 backend
cp .env.example .env     
#
 then fill in values, if .env does not exist yet

./run.sh




















Frontend (requires Node.js 20.9+ and npm):


cd
 frontend
npm install
npm run dev




















Open 
http://localhost:3000
. The home page shows whether the backend reached
the database and which Claude authentication mode is active. The backend
health endpoint is 
GET /health
; API docs are at 
/docs
 outside production.


Claude


Log in once with 
claude auth login
. Backend model calls then run on that
subscription with no API key. See 
docs/claude-agent-sdk.md
.


Production hosting


The frontend uses AWS Amplify static hosting, and the backend runs on ECS
Fargate with Secrets Manager. See 
AWS deployment

for the Cloudflare records, initial setup, and deployments on pushes to 
main
.


Guidance for coding agents


AGENTS.md
 (root, 
backend/
, 
frontend/
) and the scoped rules in

.claude/rules/
 (mirrored in 
.codex/rules/
) describe the architecture,
full-stack workflow, database, and git conventions.

