import { NextResponse, type NextRequest } from 'next/server';

/* Hosted deployments: the backend requires a bearer token for requests that arrive through a public proxy (Render,
   the tunnel). The browser never sees it: this adds it server-side to every /api request, and the rewrite in
   next.config.ts forwards the request to BACKEND_URL with it. Locally STEWARD_BACKEND_TOKEN is unset and this is a no-op. */
export function proxy(request: NextRequest) {
  const token = process.env.STEWARD_BACKEND_TOKEN;
  if (!token) return NextResponse.next();
  const headers = new Headers(request.headers);
  headers.set('authorization', `Bearer ${token}`);
  return NextResponse.next({ request: { headers } });
}

export const config = { matcher: '/api/:path*' };
