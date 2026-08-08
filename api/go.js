import crypto from "crypto";

function getCookie(req, name) {
  const raw = req.headers.cookie || "";
  for (const part of raw.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return null;
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

const BOT_UA_PATTERNS = [
  /curl\//i, /wget/i, /python-requests/i, /python-urllib/i, /aiohttp/i,
  /scrapy/i, /httpclient/i, /okhttp/i, /go-http-client/i, /libwww-perl/i,
  /axios\//i, /node-fetch/i, /^java\//i, /^ruby/i, /phantomjs/i,
  /headlesschrome/i, /puppeteer/i, /playwright/i, /selenium/i,
  /bot|crawl|spider|scraper|slurp/i,
];

function isBotRequest(req) {
  const ua = req.headers["user-agent"] || "";
  if (!ua) return true;
  return BOT_UA_PATTERNS.some((re) => re.test(ua));
}

async function redisGetDel(key) {
  const url = `${process.env.UPSTASH_REDIS_REST_URL}/getdel/${encodeURIComponent(key)}`;
  const res = await fetch(url, {
    method: "POST",
    headers: { Authorization: `Bearer ${process.env.UPSTASH_REDIS_REST_TOKEN}` },
  });
  if (!res.ok) return null;
  const data = await res.json();
  return data.result ?? null;
}

export default async function handler(req, res) {
  res.setHeader("Cache-Control", "no-store, no-cache, must-revalidate");
  if (req.method !== "GET") return res.status(405).send("Method not allowed");

  if (!process.env.UPSTASH_REDIS_REST_URL || !process.env.UPSTASH_REDIS_REST_TOKEN) {
    return res.status(500).send("Server misconfiguration");
  }

  if (isBotRequest(req)) return res.status(403).send("Automated access is not permitted");

  const sid = typeof req.query?.sid === "string" ? req.query.sid : "";
  if (!/^[A-Za-z0-9_-]{40,64}$/.test(sid)) return res.status(400).send("Invalid redirect session");

  const verified = getCookie(req, "vg_verified");
  if (verified !== "1") return res.status(403).send("Verification required");

  const raw = await redisGetDel(`verify:${sid}`);
  if (!raw) return res.status(410).send("Redirect session expired");

  let session;
  try { session = JSON.parse(raw); }
  catch { return res.status(410).send("Invalid redirect session"); }

  if (!session.used || typeof session.token !== "string") {
    return res.status(403).send("Verification required");
  }

  // Re-check the fingerprint here too. /verify already checked it, but this
  // stops a scraper that captured just the vg_verified cookie/sid pair
  // (e.g. via a proxy or shared log) from replaying it from a different
  // IP/User-Agent than the one that actually passed Turnstile.
  if (session.fp !== fingerprint(req)) {
    return res.status(403).send("Verification required");
  }

  const dot = session.token.indexOf(".");
  if (dot < 1) return res.status(403).send("Invalid protected link");

  const payload = session.token.slice(0, dot);
  const signature = session.token.slice(dot + 1);
  const expected = crypto.createHmac("sha256", process.env.TOKEN_SECRET).update(payload).digest("hex");

  if (signature.length !== expected.length || !crypto.timingSafeEqual(Buffer.from(signature), Buffer.from(expected))) {
    return res.status(403).send("Invalid protected link");
  }

  let destination;
  try {
    destination = Buffer.from(payload, "base64url").toString("utf8");
    const u = new URL(destination);
    if (!["http:", "https:"].includes(u.protocol)) throw new Error("bad protocol");
  } catch {
    return res.status(403).send("Invalid destination");
  }

  // Instead of redirecting straight to the destination, hop through the
  // Cloudflare Worker first. The payload is re-signed here with a short
  // expiry so the Worker can verify it came from this server and hasn't
  // been reused or tampered with — this keeps the Worker from being usable
  // as a generic open redirector by anyone who guesses its URL shape.
  if (!process.env.WORKER_BASE) {
    console.error("[go] WORKER_BASE env var is not set");
    return res.status(500).send("Server misconfiguration");
  }

  const exp = Date.now() + 60_000; // 1 minute to complete the final hop
  const hopPayload = Buffer.from(JSON.stringify({ d: destination, exp })).toString("base64url");
  const hopSignature = crypto.createHmac("sha256", process.env.TOKEN_SECRET).update(hopPayload).digest("hex");

  const workerBase = process.env.WORKER_BASE.replace(/\/$/, "");
  const workerUrl = `${workerBase}/go?u=${encodeURIComponent(hopPayload)}&sig=${hopSignature}`;

  // The session was atomically consumed by GETDEL above.
  res.setHeader("Set-Cookie", "vg_verified=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=None");
  res.setHeader("Location", workerUrl);
  return res.status(302).end();
}
