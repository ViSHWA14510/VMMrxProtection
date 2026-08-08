import crypto from "crypto";

const SESSION_TTL = 10 * 60;

function sign(data, secret) {
  return crypto.createHmac("sha256", secret).update(data).digest("hex");
}

function safeEqual(a, b) {
  if (typeof a !== "string" || typeof b !== "string" || a.length !== b.length) return false;
  try { return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b)); }
  catch { return false; }
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

function getCookie(req, name) {
  const raw = req.headers.cookie || "";
  const parts = raw.split(";");
  for (const part of parts) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return null;
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

async function redisSetEx(key, value, seconds) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/set/${encodeURIComponent(key)}/${encodeURIComponent(value)}/EX/${seconds}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!res.ok) throw new Error("Redis set failed");
}

async function redisDel(key) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/del/${encodeURIComponent(key)}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  return res.ok;
}

async function rateLimit(key, limit, windowSeconds) {
  const incrUrl = `${process.env.UPSTASH_REDIS_REST_URL}/incr/${encodeURIComponent(key)}`;
  const res = await fetch(incrUrl, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!res.ok) return true;
  const data = await res.json();
  const count = Number(data.result) || 1;
  if (count === 1) {
    await fetch(
      `${process.env.UPSTASH_REDIS_REST_URL}/expire/${encodeURIComponent(key)}/${windowSeconds}`,
      { method: "POST", headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` } }
    ).catch(() => {});
  }
  return count <= limit;
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store");
  res.setHeader("Access-Control-Allow-Origin", process.env.SITE_URL || "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") return res.status(204).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  for (const key of ["TURNSTILE_SECRET_KEY", "TOKEN_SECRET", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"]) {
    if (!process.env[key]) {
      console.error(`[verify] ${key} is not set`);
      return res.status(500).json({ error: "Server misconfiguration" });
    }
  }

  // Rate limit verification attempts per IP — scrapers that got past
  // /resolve will typically hammer /verify trying to brute or replay tokens.
  const limitIp = getClientIp(req);
  const allowed = await rateLimit(`rl:verify:${limitIp}`, 15, 60);
  if (!allowed) {
    res.setHeader("Retry-After", "60");
    return res.status(429).json({ error: "Too many requests, slow down" });
  }

  const body = req.body;
  if (!body || typeof body !== "object") return res.status(400).json({ error: "Invalid request body" });

  const sessionId = typeof body.sessionId === "string" ? body.sessionId.trim() : "";
  const cfToken = typeof body.cfToken === "string" ? body.cfToken.trim() : "";

  if (!/^[A-Za-z0-9_-]{40,64}$/.test(sessionId)) return res.status(400).json({ error: "Invalid verification session" });
  if (!cfToken) return res.status(400).json({ error: "Missing cfToken" });

  const cookieSession = getCookie(req, "vg_session");
  if (!cookieSession || !safeEqual(cookieSession, sessionId)) {
    return res.status(403).json({ error: "Verification session mismatch" });
  }

  const rawSession = await redisGet(`verify:${sessionId}`);
  if (!rawSession) return res.status(410).json({ error: "Verification session expired" });

  let session;
  try { session = JSON.parse(rawSession); }
  catch { return res.status(410).json({ error: "Invalid verification session" }); }

  if (session.used || session.fp !== fingerprint(req)) {
    return res.status(403).json({ error: "Verification session is no longer valid" });
  }

  // Timing check: a real visitor needs at least ~1.2s to load the page,
  // render Turnstile, and solve it. Anything faster is almost certainly an
  // automated client replaying a captured token.
  const elapsed = Date.now() - (Number(session.createdAt) || 0);
  if (elapsed < 60000) {
    return res.status(403).json({ error: "Verification failed" });
  }

  // Verify Cloudflare Turnstile on the server.
  let cfData;
  try {
    const cfRes = await fetch("https://challenges.cloudflare.com/turnstile/v0/siteverify", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        secret: process.env.TURNSTILE_SECRET_KEY,
        response: cfToken,
        remoteip: getClientIp(req),
      }),
    });

    if (!cfRes.ok) return res.status(502).json({ error: "Could not reach verification service" });
    cfData = await cfRes.json();
  } catch (err) {
    console.error("[verify] Turnstile error:", err);
    return res.status(502).json({ error: "Could not reach verification service" });
  }

  if (!cfData.success) {
    console.warn("[verify] Turnstile rejected:", cfData["error-codes"]);
    return res.status(403).json({ error: "Human verification failed. Please try again." });
  }

  // Validate the signed destination stored server-side.
  const token = session.token;
  const dotIndex = typeof token === "string" ? token.indexOf(".") : -1;
  if (dotIndex === -1) return res.status(403).json({ error: "Invalid protected link" });

  const payload = token.substring(0, dotIndex);
  const signature = token.substring(dotIndex + 1);
  const expectedSig = sign(payload, process.env.TOKEN_SECRET);
  if (!safeEqual(signature, expectedSig)) return res.status(403).json({ error: "Invalid protected link" });

  let decoded;
  try { decoded = Buffer.from(payload, "base64url").toString("utf-8"); }
  catch { return res.status(403).json({ error: "Invalid protected link" }); }

  try {
    const parsed = new URL(decoded);
    if (!["http:", "https:"].includes(parsed.protocol)) throw new Error("bad protocol");
  } catch {
    return res.status(403).json({ error: "Protected link contains an invalid destination" });
  }

  // Mark the session as used before allowing the redirect.
  // This prevents reusing the same verification session after successful verification.
  await redisSetEx(`verify:${sessionId}`, JSON.stringify({ ...session, used: true }), 60);

  // Do NOT return the destination URL. The browser only gets an internal route.
  res.setHeader(
    "Set-Cookie",
    "vg_verified=1; Path=/; Max-Age=60; HttpOnly; Secure; SameSite=Lax"
  );

  return res.status(200).json({
    success: true,
    redirect: `/api/go?sid=${encodeURIComponent(sessionId)}`,
  });
}
