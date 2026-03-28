/**
 * Cloudflare Worker — edahabapp proxy
 * 
 * Deploy steps (free — 100,000 requests/day):
 * 1. Go to https://dash.cloudflare.com → Workers & Pages → Create
 * 2. Click "Create Worker" → paste this code → Deploy
 * 3. Copy your worker URL (e.g. https://gold-proxy.YOUR-NAME.workers.dev)
 * 4. Add it as a GitHub secret: PROXY_URL = https://gold-proxy.YOUR-NAME.workers.dev
 */

const TARGET = "https://edahabapp.com/";

export default {
  async fetch(request) {
    // Only allow GET
    if (request.method !== "GET") {
      return new Response("Method not allowed", { status: 405 });
    }

    try {
      const resp = await fetch(TARGET, {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/124.0.0.0 Safari/537.36",
          "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
          Accept:
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
      });

      const html = await resp.text();

      return new Response(html, {
        status: resp.status,
        headers: {
          "Content-Type": "text/html; charset=utf-8",
          "Access-Control-Allow-Origin": "*",
          "X-Proxied-By": "cloudflare-worker",
        },
      });
    } catch (err) {
      return new Response(`Proxy error: ${err.message}`, { status: 502 });
    }
  },
};
