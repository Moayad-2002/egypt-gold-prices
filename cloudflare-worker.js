/**
 * cloudflare-worker.js
 * ════════════════════════════════════════════════════════
 * Cloudflare Worker — proxy for edahabapp.com
 * 
 * FREE SETUP (3 minutes):
 * ──────────────────────
 * 1. Go to https://dash.cloudflare.com  (free account)
 * 2. Left menu → Workers & Pages → Create
 * 3. Click "Create Worker"
 * 4. Delete ALL existing code in the editor
 * 5. Paste THIS entire file
 * 6. Click "Deploy"
 * 7. Copy the worker URL shown:
 *       https://YOUR-WORKER-NAME.YOUR-SUBDOMAIN.workers.dev
 *
 * THEN in GitHub:
 * ──────────────
 * Repo → Settings → Secrets and variables → Actions
 * → New repository secret
 *   Name:  PROXY_URL
 *   Value: https://YOUR-WORKER-NAME.YOUR-SUBDOMAIN.workers.dev
 *
 * Free tier: 100,000 requests/day — more than enough.
 * ════════════════════════════════════════════════════════
 */

const TARGET_URL = "https://edahabapp.com/";

export default {
  async fetch(request) {
    if (request.method !== "GET") {
      return new Response("Method Not Allowed", { status: 405 });
    }

    try {
      const response = await fetch(TARGET_URL, {
        headers: {
          "User-Agent":
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) " +
            "AppleWebKit/537.36 (KHTML, like Gecko) " +
            "Chrome/124.0.0.0 Safari/537.36",
          "Accept-Language": "ar-EG,ar;q=0.9,en;q=0.8",
          "Accept":
            "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
      });

      const html = await response.text();

      return new Response(html, {
        status: response.status,
        headers: {
          "Content-Type":                "text/html; charset=utf-8",
          "Access-Control-Allow-Origin": "*",
          "Cache-Control":               "no-store",
        },
      });
    } catch (err) {
      return new Response(`Worker error: ${err.message}`, { status: 502 });
    }
  },
};
