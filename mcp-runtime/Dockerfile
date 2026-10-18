# Steward MCP for Manufact Cloud. Build context is mcp-runtime/ (deploy --root-dir mcp-runtime).
# Plain node commands: the alpine preset has no bash, and scripts/run.sh pins the project-local Node 24.
FROM node:24-slim
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npx tsc -p tsconfig.json
ENV NODE_ENV=production
# Manufact injects PORT; start.ts then binds 0.0.0.0 on that port.
EXPOSE 3000
CMD ["node", "dist/src/start.js"]
