// go.js — server-side redirect for a verified session
// GET /api/go?session=<sessionId>   (cookie vmmrx_sess=<sessionId>.<sessionSecret> must be present)
//
// The browser navigates here directly (not via fetch), so the destination
// URL is never returned as a JSON value that a script could read — the
// response is a plain HTTP 302 with a Location header.
//
// The session is single-use: it's deleted from Redis on first successful use,
// and it also expires on its own after a short TTL if never used.

async function redisGet(key) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/get/${encodeURIComponent(key)}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.result ?? null;
}

async function redisDel(key) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/del/${encodeURIComponent(key)}`;
  await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  }).catch(() => {});
}

function parseCookies(header) {
  const out = {};
  if (!header) return out;
  header.split(";").forEach(part => {
    const idx = part.indexOf("=");
    if (idx === -1) return;
    const k = part.slice(0, idx).trim();
    const v = part.slice(idx + 1).trim();
    if (k) out[k] = decodeURIComponent(v);
  });
  return out;
}

export default async function handler(req, res) {
  if (req.method !== "GET") {
    return res.status(405).send("Method not allowed");
  }

  if (!process.env.UPSTASH_REDIS_REST_URL || !process.env.UPSTASH_REDIS_REST_TOKEN) {
    console.error("[go] Upstash env vars not set");
    return res.status(500).send("Server misconfiguration");
  }

  const sessionId = typeof req.query.session === "string" ? req.query.session : "";
  if (!sessionId) {
    return res.status(400).send("Missing session");
  }

  const cookies = parseCookies(req.headers.cookie);
  const cookieVal = cookies["vmmrx_sess"] || "";
  const dotIndex = cookieVal.indexOf(".");
  if (dotIndex === -1) {
    return res.status(403).send("Missing or invalid session cookie");
  }
  const cookieSessionId = cookieVal.substring(0, dotIndex);
  const cookieSessionSecret = cookieVal.substring(dotIndex + 1);

  if (cookieSessionId !== sessionId) {
    return res.status(403).send("Session does not match this browser");
  }

  const stored = await redisGet(`redir:${sessionId}`);
  if (!stored) {
    return res.status(404).send("This link has expired or was already used. Please go back and verify again.");
  }

  const pipeIndex = stored.lastIndexOf("|");
  if (pipeIndex === -1) {
    await redisDel(`redir:${sessionId}`);
    return res.status(500).send("Corrupt session data");
  }
  const destUrl = stored.substring(0, pipeIndex);
  const expectedSecret = stored.substring(pipeIndex + 1);

  // Single-use: delete immediately, regardless of outcome
  await redisDel(`redir:${sessionId}`);

  if (cookieSessionSecret !== expectedSecret) {
    return res.status(403).send("Invalid session");
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(destUrl);
  } catch {
    return res.status(400).send("Invalid destination");
  }
  if (!["http:", "https:"].includes(parsedUrl.protocol)) {
    return res.status(400).send("Unsafe destination protocol");
  }

  // Clear the session cookie now that it's used
  res.setHeader("Set-Cookie", "vmmrx_sess=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Strict");
  res.setHeader("Cache-Control", "no-store");
  res.writeHead(302, { Location: destUrl });
  return res.end();
}
