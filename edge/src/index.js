/**
 * Edge redirect cache for the URL shortener.
 *
 * GET /{code}  -> look the code up in Workers KV.
 *                 hit:  302 straight from the edge, origin never sees it.
 *                 miss: ask the FastAPI origin, store the answer in KV, 302.
 * anything else (POST /shorten, /inspect/*, /docs) -> proxied to the origin.
 *
 * Every response carries `x-edge-cache: HIT|MISS|BYPASS` so you can see
 * what happened.
 */

const CODE_RE = /^\/[0-9A-Za-z_-]{1,32}$/;
const RESERVED = new Set(["/docs", "/redoc", "/openapi.json", "/favicon.ico", "/shorten"]);

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const origin = env.ORIGIN_URL.replace(/\/$/, "");
    const isRedirect =
      request.method === "GET" && CODE_RE.test(url.pathname) && !RESERVED.has(url.pathname);

    if (!isRedirect) {
      return proxy(request, origin, url);
    }

    const code = url.pathname.slice(1);

    // 1. Edge hit: answer without touching the origin.
    const cached = await env.LINKS.get(code, { cacheTtl: 300 });
    if (cached) {
      return redirect(cached, "HIT");
    }

    // 2. Miss: let the origin resolve it (it also records the click).
    const res = await fetch(`${origin}/${code}`, { redirect: "manual" });
    const location = res.headers.get("location");
    if (res.status !== 302 || !location) {
      return new Response(res.body, {
        status: res.status,
        headers: { ...Object.fromEntries(res.headers), "x-edge-cache": "MISS" },
      });
    }

    // Store for next time without making this request wait on the write.
    ctx.waitUntil(env.LINKS.put(code, location, { expirationTtl: Number(env.KV_TTL_SECONDS || 3600) }));
    return redirect(location, "MISS");
  },
};

function redirect(location, cacheState) {
  return new Response(null, {
    status: 302,
    headers: { location, "x-edge-cache": cacheState },
  });
}

async function proxy(request, origin, url) {
  const target = origin + url.pathname + url.search;
  const res = await fetch(new Request(target, request), { redirect: "manual" });
  const out = new Response(res.body, res);
  out.headers.set("x-edge-cache", "BYPASS");
  return out;
}
