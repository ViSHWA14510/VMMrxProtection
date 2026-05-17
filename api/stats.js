// stats.js — returns full analytics for stats.html dashboard (admin-key protected)

let kv = null;
async function getKV() {
  if (kv) return kv;
  try { const mod = await import("@vercel/kv"); kv = mod.kv; return kv; }
  catch { return null; }
}

const mem = {};
function memNum(k) { return Number(mem[k]) || 0; }
function memGet(k) { return mem[k]; }

export default async function handler(req, res) {
  res.setHeader("Access-Control-Allow-Origin", "*");
  res.setHeader("Access-Control-Allow-Methods", "GET, OPTIONS");
  res.setHeader("Access-Control-Allow-Headers", "Content-Type, x-admin-key");
  if (req.method === "OPTIONS") return res.status(200).end();
  if (req.method !== "GET") return res.status(405).json({ error: "Method not allowed" });

  if (!process.env.ADMIN_KEY) return res.status(500).json({ error: "Server misconfiguration" });
  if (req.headers["x-admin-key"] !== process.env.ADMIN_KEY)
    return res.status(401).json({ error: "Unauthorized" });

  // Last 14 days
  const days = Array.from({ length: 14 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (13 - i));
    return d.toISOString().slice(0, 10);
  });

  const db = await getKV();
  let siteViews, siteVisits, totalViews, totalVisits, daily, links;

  if (db) {
    [siteViews, siteVisits, totalViews, totalVisits] = await Promise.all([
      db.get("stats:site:views").then(v => Number(v) || 0),
      db.get("stats:site:visits").then(v => Number(v) || 0),
      db.get("stats:total:views").then(v => Number(v) || 0),
      db.get("stats:total:visits").then(v => Number(v) || 0),
    ]);

    const dayKeys = days.flatMap(d => [`stats:daily:${d}:views`, `stats:daily:${d}:visits`]);
    const dayVals = await db.mget(...dayKeys);
    daily = days.map((d, i) => ({
      date: d,
      views: Number(dayVals[i * 2]) || 0,
      visits: Number(dayVals[i * 2 + 1]) || 0
    }));

    const tokenArr = await db.smembers("stats:tokens") || [];
    links = await Promise.all(tokenArr.map(async tok => {
      const [v, vi, url] = await Promise.all([
        db.get(`stats:link:${tok}:views`).then(x => Number(x) || 0),
        db.get(`stats:link:${tok}:visits`).then(x => Number(x) || 0),
        db.get(`stats:link:${tok}:url`).then(x => x || ""),
      ]);
      return { token: tok, views: v, visits: vi, url };
    }));

  } else {
    siteViews    = memNum("stats:site:views");
    siteVisits   = memNum("stats:site:visits");
    totalViews   = memNum("stats:total:views");
    totalVisits  = memNum("stats:total:visits");
    daily = days.map(d => ({
      date: d,
      views:  memNum(`stats:daily:${d}:views`),
      visits: memNum(`stats:daily:${d}:visits`)
    }));
    const tokenSet = memGet("stats:tokens") || new Set();
    links = [...tokenSet].map(tok => ({
      token: tok,
      views:  memNum(`stats:link:${tok}:views`),
      visits: memNum(`stats:link:${tok}:visits`),
      url:    memGet(`stats:link:${tok}:url`) || ""
    }));
  }

  // Sort by views desc, cap at 200
  links = links.sort((a, b) => b.views - a.views).slice(0, 200);

  return res.status(200).json({
    success: true,
    site: { views: siteViews, visits: siteVisits },
    total: { views: totalViews, visits: totalVisits },
    daily,
    links,
    storage: db ? "vercel-kv" : "in-memory",
    generatedAt: new Date().toISOString()
  });
}
