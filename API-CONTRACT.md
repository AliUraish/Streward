# Local Steward implementation contract

Run locally only. Do not deploy to Vercel or another cloud. The video is the visual reference; the original 3D scan/source is unavailable, so build an original navigable industrial room with real geometry. Never represent fixture evidence as real statutory certification or configured model access.

Frontend: Next.js/React/TypeScript at http://127.0.0.1:3000. Backend: FastAPI at http://127.0.0.1:8001 (8000 is occupied by an unrelated existing app). TypeScript mcp-use adapter: http://127.0.0.1:8002/mcp. Browser uses `/api/...`, proxied by Next to FastAPI; `/mcp` proxies to the TypeScript adapter. SQLite is the local persistent store. Services without credentials report `not_configured`; local workflows remain functional and are identified as local.

## Shared types

Use `shared/types.ts` and `shared/scene.json`. Properties: `cedar`, `harbor`, `juniper`. Component identifiers and world positions come from scene.json. All timestamps ISO UTC. Status values: `verified`, `pending`, `issue`, `unknown`. JSON responses use camelCase.

## HTTP API

- GET /health: {status, database, mode}
- GET /api/properties: Property[]
- GET /api/properties/{id}/workspace: Workspace
- GET /api/properties/{id}/components: Component[]
- GET /api/properties/{id}/components/{componentId}: ComponentDetail
- GET /api/properties/{id}/requirements?search=&system=&status=: Requirement[]
- GET /api/properties/{id}/documents?search=&category=: Document[]
- GET /api/documents/{documentId}/file: PDF file response
- POST /api/properties/{id}/documents: multipart file and optional category; ingest and persist
- POST /api/properties/{id}/inspections: {scope?: string}; returns Job, starts actual local analysis workflow, persists component/requirement changes and events
- GET /api/jobs/{jobId}: Job
- GET /api/properties/{id}/events?after=0: ActivityEvent[]
- GET /api/properties/{id}/agents: Agent[]
- POST /api/properties/{id}/agents/run: {goal:string}; returns Job
- GET /api/properties/{id}/chat: ChatMessage[]
- POST /api/properties/{id}/chat: {message:string}; returns {message:ChatMessage, job?:Job}
- GET /api/properties/{id}/memory: Memory[]
- GET /api/integrations: Integration[]
- POST /api/properties/{id}/evidence: multipart file, componentId, requirementId, optional note. Validate and update evidence state.
- POST /api/properties/{id}/purchases: {componentId, description, amount, currency?:string}; persist purchase proposal, never perform unapproved real purchase
- GET /api/properties/{id}/purchases: Purchase[]
- GET /api/properties/{id}/report: downloadable HTML/JSON evidence report
- The primary MCP interface is the TypeScript mcp-use adapter on port 8002: tools, guide resource and inspection prompt over the same FastAPI services. FastAPI's original JSON-RPC `/mcp` endpoint remains available on port 8001 for compatibility and backend tests. See `mcp-runtime/README.md` for two-client verification.

The frontend polls workspace/events during running jobs; do not fabricate live completion animations without backend job state. Browser error states must be visible and retryable. Seeding is idempotent; runtime modifications survive backend restart.

## Ownership while working in parallel

- Root: shared contracts/data, root scripts and docs, integration, API client, runtime setup, QA.
- Frontend agent: frontend app shell, styles, panels, component/requirements/document/agent interfaces; do not modify scene implementation, root package or backend.
- Backend agent: backend/** including domain data, API, persistence, tests, requirements, local job execution.
- Scene agent: frontend/src/components/scene/** only. Export PlantRoom and CameraWall from index.tsx; use shared types/data. Do not edit frontend app shell or package.json.

Scene API: `PlantRoom({components: Component[], selectedId: string|null, onSelect:(id:string)=>void, showMarkers?:boolean, showGuides?:boolean, viewMode?:'orbit'|'walk', cameraTarget?:string|null})`. `CameraWall({components: Component[], onSelect:(id:string)=>void, running?:boolean})`. Root containers determine dimensions; fill parent, no page chrome. Use one canvas for multi-view wall where practical, rather than twelve independent contexts. Maintain stable object IDs, click selection and reset/camera navigation. Render real geometry, not a screenshot substitute.
