# Steward MCP on Manufact: fallback build when the auto-detected Node preset's
# Node version is below the 24 that mcp-runtime/scripts/run.sh requires.
# Build context must be the repository root (Manufact "Dockerfile path" setting:
# manufact/Dockerfile, root directory: repo root). mcp-runtime has no imports
# outside its own folder (tsconfig include: src, scripts, tests).
FROM node:24-slim
WORKDIR /app/mcp-runtime
COPY mcp-runtime/package.json mcp-runtime/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY mcp-runtime/ ./
RUN npm run build
ENV NODE_ENV=production
# Manufact injects PORT; start.ts must honour PORT/HOST (see manufact/README.md, "Required code change").
EXPOSE 3000
CMD ["npm", "start"]
