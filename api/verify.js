import crypto from "crypto";

function sign(data, secret) {
  return crypto.createHmac("sha256", secret).update(data).digest("hex");
}

// Short tokens use a 32-char (128-bit) HMAC instead of 64-char
function signShort(data, secret) {
  return crypto.createHmac("sha256", secret).update(data).digest("hex").slice(0, 32);
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
    // Legacy /token/ uses dot separator with 64-char HMAC: payload.sig
    // Short  /s/     uses dash separator with 32-char HMAC: payload-sig
    // Detect which format by checking for dash-separated 32-char suffix first.
    let payload, signature;

    const dashIndex = token.lastIndexOf("-");
    const dotIndex  = token.indexOf(".");

    if (dashIndex !== -1 && token.length - dashIndex - 1 === 32) {
      // Short token format: payload-sig (32-char HMAC)
      payload   = token.substring(0, dashIndex);
      signature = token.substring(dashIndex + 1);
    } else if (dotIndex !== -1) {
      // Legacy token format: payload.sig (64-char HMAC)
      payload   = token.substring(0, dotIndex);
      signature = token.substring(dotIndex + 1);
    } else {
      return res.status(400).json({ error: "Invalid token format" });
    }

    if (!payload || !signature) {
      return res.status(400).json({ error: "Invalid token format" });
    }

    // Accept both full 64-char HMAC (legacy /token/) and 32-char HMAC (short /s/)
    const expectedSigFull  = sign(payload, process.env.TOKEN_SECRET);
    const expectedSigShort = signShort(payload, process.env.TOKEN_SECRET);

    const validFull  = signature.length === 64 && safeEqual(signature, expectedSigFull);
    const validShort = signature.length === 32 && safeEqual(signature, expectedSigShort);

    if (!validFull && !validShort) {
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

    return res.status(200).json({
      success: true,
      url: decoded
    });

  } catch (err) {
    console.error("[verify] Token validation error:", err);
    return res.status(400).json({ error: "Invalid token" });
  }
}
