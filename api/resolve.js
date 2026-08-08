import crypto from "crypto";

const SESSION_TTL = 10 * 60;

// ── Known scraper / automation signatures ──────────────────────────
// Blocks the most common non-browser HTTP clients used for scraping.
// Not exhaustive (nothing is), but it filters the bulk of naive bots.
const BOT_UA_PATTERNS = [
  /curl\//i, /wget/i, /python-requests/i, /python-urllib/i, /aiohttp/i,
  /scrapy/i, /httpclient/i, /okhttp/i, /go-http-client/i, /libwww-perl/i,
  /axios\//i, /node-fetch/i, /^java\//i, /^ruby/i, /phantomjs/i,
  /headlesschrome/i, /puppeteer/i, /playwright/i, /selenium/i,
  /bot|crawl|spider|scraper|slurp|fetch\b/i,
];

function isBotRequest(req) {
  const ua = req.headers["user-agent"] || "";
  if (!ua) return true; // real browsers always send a UA
  if (BOT_UA_PATTERNS.some((re) => re.test(ua))) return true;

  // Real browsers send Accept and Accept-Language on a top-level navigation.
  const accept = req.headers["accept"] || "";
  if (!accept.includes("text/html") && !accept.includes("*/*")) return true;

  return false;
}

function randomId(bytes = 32) {
  return crypto.randomBytes(bytes).toString("base64url");
}

function getClientIp(req) {
  const forwarded = req.headers["x-forwarded-for"];
  if (forwarded) return String(forwarded).split(",")[0].trim();
  return req.socket?.remoteAddress || "unknown";
}

function fingerprint(req) {
  const ip = getClientIp(req);
  const ua = req.headers["user-agent"] || "";
  const secret = process.env.SESSION_SECRET || process.env.TOKEN_SECRET || "";
  return crypto.createHash("sha256").update(`${secret}|${ip}|${ua}`).digest("hex");
}

async function redisSetEx(key, value, seconds) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/set/${encodeURIComponent(key)}/${encodeURIComponent(value)}/EX/${seconds}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!res.ok) throw new Error("Redis set failed");
}

async function redisGet(key) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/get/${encodeURIComponent(key)}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.result ?? null;
}

// ── Simple fixed-window rate limiter, backed by Redis INCR + EXPIRE ─
// Returns true if the request should be allowed.
async function rateLimit(key, limit, windowSeconds) {
  const incrUrl = `${process.env.UPSTASH_REDIS_REST_URL}/incr/${encodeURIComponent(key)}`;
  const res = await fetch(incrUrl, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!res.ok) return true; // fail open if Redis is briefly unavailable
  const data = await res.json();
  const count = Number(data.result) || 1;

  if (count === 1) {
    // First hit in this window — set expiry.
    await fetch(
      `${process.env.UPSTASH_REDIS_REST_URL}/expire/${encodeURIComponent(key)}/${windowSeconds}`,
      { method: "POST", headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` } }
    ).catch(() => {});
  }

  return count <= limit;
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", process.env.SITE_URL || "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  res.setHeader("Cache-Control", "no-store");

  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  if (!process.env.UPSTASH_REDIS_REST_URL || !process.env.UPSTASH_REDIS_REST_TOKEN) {
    console.error("[resolve] Upstash env vars are not set");
    return res.status(500).json({ error: "Server misconfiguration" });
  }

  // Reject obvious non-browser clients before doing any work.
  if (isBotRequest(req)) {
    return res.status(403).json({ error: "Automated access is not permitted" });
  }

  // Rate limit per IP: 20 resolve attempts per minute is generous for a
  // human clicking a link, but chokes off scrapers hitting many codes fast.
  const ip = getClientIp(req);
  const allowed = await rateLimit(`rl:resolve:${ip}`, 20, 60);
  if (!allowed) {
    res.setHeader("Retry-After", "60");
    return res.status(429).json({ error: "Too many requests, slow down" });
  }

  const body = req.body;
  if (!body || typeof body !== "object") return res.status(400).json({ error: "Invalid request body" });

  const code = typeof body.code === "string" ? body.code.trim() : "";
  if (!/^[A-Za-z0-9_-]{4,32}$/.test(code)) {
    return res.status(400).json({ error: "Invalid code" });
  }

  // short:<code> contains the signed destination token, but that token is
  // NEVER returned to the browser.
  const token = await redisGet(`short:${code}`);
  if (!token) return res.status(404).json({ error: "Short link not found or expired" });

  const sessionId = randomId(32);
  const session = JSON.stringify({
    token,
    fp: fingerprint(req),
    createdAt: Date.now(),
    used: false,
  });

  await redisSetEx(`verify:${sessionId}`, session, SESSION_TTL);

  // The browser gets only an opaque session ID. The destination remains in Redis.
  res.setHeader(
    "Set-Cookie",
    `vg_session=${sessionId}; Path=/; Max-Age=${SESSION_TTL}; HttpOnly; Secure; SameSite=Lax`
  );

  return res.status(200).json({
    success: true,
    sessionId,
    expiresIn: SESSION_TTL,
  });
}
