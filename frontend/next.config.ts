import type { NextConfig } from 'next';
import path from 'node:path';
const backendUrl = process.env.BACKEND_URL ?? 'http://127.0.0.1:8001';
const mcpBaseUrl = (process.env.MCP_URL ?? 'http://127.0.0.1:8002').replace(/\/+$/, '');
const mcpUrl = mcpBaseUrl.endsWith('/mcp') ? mcpBaseUrl : `${mcpBaseUrl}/mcp`;
const config: NextConfig = {
  devIndicators: false,
  turbopack: { root: path.join(__dirname, '..') },
  outputFileTracingRoot: path.join(__dirname, '..'),
  allowedDevOrigins: ['localhost', '127.0.0.1'],
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${backendUrl}/api/:path*` },
      { source: '/mcp', destination: mcpUrl },
    ];
  },
};
export default config;
