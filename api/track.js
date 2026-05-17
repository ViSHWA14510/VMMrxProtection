// track.js — records per-link stats AND site-wide visitor counts
// type: "view"  → user opened a protected link page
// type: "visit" → user passed Cloudflare and was redirected
//
// Storage keys:
//   stats:total:views          — total link page opens
//   stats:total:visits         — total successful verifications
//   stats:site:views           — site-wide page hits (same as total:views, alias for clarity)
//   stats:site:visits          — site-wide successful verifications
//   stats:link:{token}:views   — views per token
//   stats:link:{token}:visits  — visits per token
//   stats:link:{token}:url     — destination URL (stored once)
//   stats:daily:{YYYY-MM-DD}:views
//   stats:daily:{YYYY-MM-DD}:visits
//   stats:tokens               — set of all seen token keys

let kv = null;
async function getKV() {
  if (kv) return kv;
  try { const mod = await import("@vercel/kv"); kv = mod.kv; return kv; }
  catch { return null; }
}

const mem = {};
function memInc(k) { mem[k] = (mem[k] || 0) + 1; }
function memSet(k, v) { mem[k] = v; }
function memGet(k) { return mem[k]; }

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type");
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "POST") return res.status(405).json({ error: "Method not allowed" });

  const body = req.body;
  if (!body || typeof body !== "object") return res.status(400).json({ error: "Bad body" });

  const { type, token, url } = body;
  if (!type || !["view", "visit"].includes(type))
    return res.status(400).json({ error: "type must be view or visit" });
  if (!token || typeof token !== "string")
    return res.status(400).json({ error: "Missing token" });

  const today = new Date().toISOString().slice(0, 10);
  const safeToken = token.slice(0, 200).replace(/[^a-zA-Z0-9._-]/g, "");
  const db = await getKV();

  if (db) {
    const p = db.pipeline();
    p.incr(`stats:total:${type}s`);
    // site-wide mirrors (views = page opens, visits = verifications passed)
    p.incr(`stats:site:${type}s`);
    p.incr(`stats:daily:${today}:${type}s`);
    p.incr(`stats:link:${safeToken}:${type}s`);
    if (url) p.set(`stats:link:${safeToken}:url`, url, { nx: true });
    p.sadd("stats:tokens", safeToken);
    await p.exec();
  } else {
    memInc(`stats:total:${type}s`);
    memInc(`stats:site:${type}s`);
    memInc(`stats:daily:${today}:${type}s`);
    memInc(`stats:link:${safeToken}:${type}s`);
    if (url && !memGet(`stats:link:${safeToken}:url`)) memSet(`stats:link:${safeToken}:url`, url);
    const tokens = memGet("stats:tokens") || new Set();
    tokens.add(safeToken);
    memSet("stats:tokens", tokens);
  }

  return res.status(200).json({ success: true });
}
