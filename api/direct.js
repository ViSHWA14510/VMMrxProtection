import crypto from "crypto";

// ── Short token helper ────────────────────────────────────────────
function signShort(data, secret) {
  return crypto.createHmac("sha256", secret).update(data).digest("hex").slice(0, 32);
}
// ──────────────────────────────────────────────────────────────────

function sign(data, secret) {
  return crypto.createHmac("sha256", secret).update(data).digest("hex");
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, x-admin-key");

  if (req.method === "OPTIONS") {
    return res.status(200).end();
  }

  if (req.method !== "POST") {
    return res.status(405).json({ error: "Method not allowed" });
  }

  if (!process.env.ADMIN_KEY) {
    console.error("[direct] ADMIN_KEY env var is not set");
    return res.status(500).json({ error: "Server misconfiguration" });
  }

  const adminKey = req.headers["x-admin-key"];
  if (!adminKey || adminKey !== process.env.ADMIN_KEY) {
    return res.status(401).json({ error: "Unauthorized" });
  }

  const body = req.body;
  if (!body || typeof body !== "object") {
    return res.status(400).json({ error: "Invalid request body" });
  }

  const { url } = body;

  if (!url || typeof url !== "string" || !url.trim()) {
    return res.status(400).json({ error: "Missing url" });
  }

  let parsedUrl;
  try {
    parsedUrl = new URL(url.trim());
  } catch {
    return res.status(400).json({ error: "Invalid URL — must include http:// or https://" });
  }

  if (!["http:", "https:"].includes(parsedUrl.protocol)) {
    return res.status(400).json({ error: "Only http and https URLs are allowed" });
  }

  if (!process.env.TOKEN_SECRET) {
    console.error("[direct] TOKEN_SECRET env var is not set");
    return res.status(500).json({ error: "Server misconfiguration: missing TOKEN_SECRET" });
  }
  if (!process.env.SITE_URL) {
    console.error("[direct] SITE_URL env var is not set");
    return res.status(500).json({ error: "Server misconfiguration: missing SITE_URL" });
  }

  try {
    // Encode the ORIGINAL URL directly — no shortener involved
    const payload = Buffer.from(url.trim()).toString("base64url");
    const signature = sign(payload, process.env.TOKEN_SECRET);
    const token = `${payload}.${signature}`;

    const siteUrl = process.env.SITE_URL.replace(/\/$/, "");
    const protectedUrl = `${siteUrl}/token/${token}`;  // legacy — kept forever

    const shortSig = signShort(payload, process.env.TOKEN_SECRET);
    const shortToken = `${payload}-${shortSig}`;
    const shortProtectedUrl = `${siteUrl}/s/${shortToken}`;

    return res.status(200).json({
      success: true,
      protected_url: protectedUrl,           // old long format (still works)
      short_protected_url: shortProtectedUrl, // new short format
      original_url: url.trim()
    });

  } catch (err) {
    console.error("[direct] Unexpected error:", err);
    return res.status(500).json({ error: "Internal server error" });
  }
}
