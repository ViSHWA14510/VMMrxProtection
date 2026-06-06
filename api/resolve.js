import crypto from "crypto";

// POST /api/resolve  { code: "zIJr8iIV" }
// → 200 { success: true, token: "payload.sig" }
// → 404 { error: "Short link not found or expired" }

async function redisGet(key) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/get/${key}`;
  const res = await fetch(url, {
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.result ?? null;
}

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");

  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  const body = req.body;
  if (!body || typeof body !== "object")
    return res.status(400).json({ error: "Invalid request body" });

  const { code } = body;
  if (!code || typeof code !== "string" || !code.trim())
    return res.status(400).json({ error: "Missing code" });

  const safeCode = code.trim().replace(/[^a-zA-Z0-9_-]/g, "");
  if (!safeCode) return res.status(400).json({ error: "Invalid code" });

  if (!process.env.UPSTASH_REDIS_REST_URL || !process.env.UPSTASH_REDIS_REST_TOKEN) {
    console.error("[resolve] Upstash env vars not set");
    return res.status(500).json({ error: "Server misconfiguration" });
  }

  const token = await redisGet(`short:${safeCode}`);

  if (!token) {
    return res.status(404).json({ error: "Short link not found or expired" });
  }

  return res.status(200).json({ success: true, token });
}
