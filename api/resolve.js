import crypto from "crypto";

const SESSION_TTL = 10 * 60;

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
