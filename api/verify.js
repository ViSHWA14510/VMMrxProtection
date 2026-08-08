import crypto from "crypto";

// ── Upstash Redis helper (used to store short-lived, single-use redirect sessions) ──
async function redisSetEx(key, value, ttlSeconds) {
  // Upstash REST: POST /set/key/value?EX=ttl
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/set/${encodeURIComponent(key)}/${encodeURIComponent(value)}?EX=${ttlSeconds}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!res.ok) throw new Error("Redis set failed");
}

function sign(data, secret) {
  return crypto.createHmac("sha256", secret).update(data).digest("hex");
}


// FIX: Timing-safe comparison to prevent HMAC timing attacks
function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  try {
    return crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
  } catch {
    return false;
  }
}

export default async function handler(req, res) {
  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  // FIX: Guard against missing/malformed body
  const body = req.body;
  if (!body || typeof body !== "object") {
    return res.status(400).json({ error: "Invalid request body" });
  }

  const { token, cfToken } = body;

  if (!token || typeof token !== "string" || !token.trim()) {
    return res.status(400).json({ error: "Missing token" });
  }
  if (!cfToken || typeof cfToken !== "string" || !cfToken.trim()) {
    return res.status(400).json({ error: "Missing cfToken" });
  }

  // FIX: Validate required env vars upfront
  if (!process.env.TURNSTILE_SECRET_KEY) {
    console.error("[verify] TURNSTILE_SECRET_KEY env var is not set");
    return res.status(500).json({ error: "Server misconfiguration" });
  }
  if (!process.env.TOKEN_SECRET) {
    console.error("[verify] TOKEN_SECRET env var is not set");
    return res.status(500).json({ error: "Server misconfiguration" });
  }

  // ── Step 1: Verify Cloudflare Turnstile ──
  let cfData;
  try {
    const cfRes = await fetch(
      "https://challenges.cloudflare.com/turnstile/v0/siteverify",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          secret: process.env.TURNSTILE_SECRET_KEY,
          response: cfToken
        })
      }
    );

    // FIX: Handle Turnstile API non-200 responses
    if (!cfRes.ok) {
      console.error("[verify] Turnstile API HTTP error:", cfRes.status);
      return res.status(502).json({ error: "Could not reach verification service" });
    }

    cfData = await cfRes.json();
  } catch (err) {
    console.error("[verify] Turnstile fetch error:", err);
    return res.status(502).json({ error: "Could not reach verification service" });
  }

  if (!cfData.success) {
    // FIX: Log Turnstile error codes for debugging
    console.warn("[verify] Turnstile rejected:", cfData["error-codes"]);
    return res.status(403).json({ error: "Human verification failed. Please try again." });
  }

  // ── Step 2: Validate signed token ──
  try {
    // FIX: Validate token format before splitting
    const dotIndex = token.indexOf(".");
    if (dotIndex === -1) {
      return res.status(400).json({ error: "Invalid token format" });
    }

    const payload = token.substring(0, dotIndex);
    const signature = token.substring(dotIndex + 1);

    if (!payload || !signature) {
      return res.status(400).json({ error: "Invalid token format" });
    }

    const expectedSig = sign(payload, process.env.TOKEN_SECRET);
    if (!safeEqual(signature, expectedSig)) {
      return res.status(403).json({ error: "Invalid token signature" });
    }

    // ── Step 3: Decode and validate the URL inside ──
    let decoded;
    try {
      decoded = Buffer.from(payload, "base64url").toString("utf-8");
    } catch {
      return res.status(400).json({ error: "Could not decode token" });
    }

    // FIX: Validate decoded value is a valid URL
    let parsedUrl;
    try {
      parsedUrl = new URL(decoded);
    } catch {
      return res.status(400).json({ error: "Token contains invalid URL" });
    }

    // FIX: Only allow http/https redirect targets
    if (!["http:", "https:"].includes(parsedUrl.protocol)) {
      return res.status(400).json({ error: "Token contains unsafe URL protocol" });
    }

    // ── Never return the raw destination URL to the client ──
    // Instead, store it server-side under a random, single-use session id
    // with a short TTL, bind it to this browser via an httpOnly cookie,
    // and let /api/go perform the actual server-side redirect.
    if (!process.env.UPSTASH_REDIS_REST_URL || !process.env.UPSTASH_REDIS_REST_TOKEN) {
      console.error("[verify] Upstash env vars not set");
      return res.status(500).json({ error: "Server misconfiguration" });
    }

    const sessionId = crypto.randomBytes(24).toString("base64url");
    const sessionSecret = crypto.randomBytes(24).toString("base64url");
    const SESSION_TTL_SECONDS = 60;

    // Store "url|sessionSecret" so /api/go can confirm the cookie matches
    await redisSetEx(`redir:${sessionId}`, `${decoded}|${sessionSecret}`, SESSION_TTL_SECONDS);

    // Bind the session to this browser with an httpOnly cookie so a token
    // solved elsewhere (e.g. by a script) can't be handed to another client.
    res.setHeader("Set-Cookie", [
      `vmmrx_sess=${sessionId}.${sessionSecret}; Path=/; Max-Age=${SESSION_TTL_SECONDS}; HttpOnly; Secure; SameSite=Strict`
    ]);

    return res.status(200).json({
      success: true,
      session: sessionId
    });

  } catch (err) {
    console.error("[verify] Token validation error:", err);
    return res.status(400).json({ error: "Invalid token" });
  }
}
