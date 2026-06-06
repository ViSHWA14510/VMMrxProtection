import crypto from "crypto";

// ── Upstash Redis helper ───────────────────────────────────────────
async function redisSet(key, value) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/set/${key}`;
  const res = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify(value),
  });
  if (!res.ok) throw new Error("Redis set failed");
}

function generateCode(len = 8) {
  const chars = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789";
  const bytes = crypto.randomBytes(len);
  return Array.from(bytes).map(b => chars[b % chars.length]).join("");
}
// ──────────────────────────────────────────────────────────────────

function sign(data, secret) {
  return crypto.createHmac("sha256", secret).update(data).digest("hex");
}

export default async function handler(req, res) {
  // FIX: Set CORS headers so generator.html can call this from any origin
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, x-admin-key");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  // FIX: Validate ADMIN_KEY env var exists before comparing
  if (!process.env.ADMIN_KEY) {
    console.error("[generate] ADMIN_KEY env var is not set");
    return res.status(500).json({ error: "Server misconfiguration" });
  }

  const adminKey = req.headers["x-admin-key"];
  if (!adminKey || adminKey !== process.env.ADMIN_KEY) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  // FIX: Guard against missing/malformed body
  const body = req.body;
  if (!body || typeof body !== "object") {
    return res.status(400).json({ error: "Invalid request body" });
  }

  const { url } = body;

  if (!url || typeof url !== "string" || !url.trim()) {
    return res.status(400).json({ error: "Missing url" });
  }

  // FIX: Validate URL before calling shortener
  let parsedUrl;
  try {
    parsedUrl = new URL(url.trim());
  } catch {
    return res.status(400).json({ error: "Invalid URL — must include http:// or https://" });
  }

  // FIX: Reject non-http(s) protocols for safety
  if (!["http:", "https:"].includes(parsedUrl.protocol)) {
    return res.status(400).json({ error: "Only http and https URLs are allowed" });
  }

  // FIX: Validate required env vars upfront
  if (!process.env.LKSFY_API_KEY) {
    console.error("[generate] LKSFY_API_KEY env var is not set");
    return res.status(500).json({ error: "Server misconfiguration: missing LKSFY_API_KEY" });
  }
  if (!process.env.TOKEN_SECRET) {
    console.error("[generate] TOKEN_SECRET env var is not set");
    return res.status(500).json({ error: "Server misconfiguration: missing TOKEN_SECRET" });
  }
  if (!process.env.SITE_URL) {
    console.error("[generate] SITE_URL env var is not set");
    return res.status(500).json({ error: "Server misconfiguration: missing SITE_URL" });
  }

  try {
    // Shorten URL via linkshortify
    const shortRes = await fetch(
      `https://linkshortify.com/api?api=${process.env.LKSFY_API_KEY}&url=${encodeURIComponent(url.trim())}`,
      { headers: { "Accept": "application/json" } }
    );

    // FIX: Handle non-200 HTTP responses from shortener
    if (!shortRes.ok) {
      const text = await shortRes.text().catch(() => "");
      console.error("[generate] Shortener HTTP error:", shortRes.status, text);
      return res.status(502).json({ error: "Link shortener returned an error" });
    }

    let shortData;
    try {
      shortData = await shortRes.json();
    } catch {
      console.error("[generate] Shortener returned non-JSON response");
      return res.status(502).json({ error: "Link shortener returned invalid response" });
    }

    if (shortData.status !== "success" || !shortData.shortenedUrl) {
      console.error("[generate] Shortener failure:", shortData);
      return res.status(500).json({ error: shortData.message || "Link shortener failed" });
    }

    const shortUrl = shortData.shortenedUrl;

    // Create signed token: base64url(shortUrl) + "." + HMAC
    const payload = Buffer.from(shortUrl).toString("base64url");
    const signature = sign(payload, process.env.TOKEN_SECRET);
    const token = `${payload}.${signature}`;

    // FIX: Strip trailing slash from SITE_URL to avoid double slashes
    const siteUrl = process.env.SITE_URL.replace(/\/$/, "");
    const protectedUrl = `${siteUrl}/token/${token}`;  // legacy — kept forever

    // Generate truly short code and store token in Upstash Redis
    const code = generateCode(8);
    await redisSet(`short:${code}`, token);
    const shortProtectedUrl = `${siteUrl}/s/${code}`;

    return res.status(200).json({
      success: true,
      short_url: shortUrl,
      protected_url: protectedUrl,           // old long format (still works)
      short_protected_url: shortProtectedUrl  // new short format
    });

  } catch (err) {
    console.error("[generate] Unexpected error:", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
