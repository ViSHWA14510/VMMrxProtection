import crypto from "crypto";

function getCookie(req, name) {
  const raw = req.headers.cookie || "";
  for (const part of raw.split(";")) {
    const [k, ...rest] = part.trim().split("=");
    if (k === name) return decodeURIComponent(rest.join("="));
  }
  return null;
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

  // The session was atomically consumed by GETDEL above.
  res.setHeader("Set-Cookie", "vg_verified=; Path=/; Max-Age=0; HttpOnly; Secure; SameSite=Lax");
  res.setHeader("Location", destination);
  return res.status(302).end();
}
