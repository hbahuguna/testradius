import assert from "node:assert/strict";
import { spawn } from "node:child_process";

const PORT = process.env.VERIFY_PORT ?? "59999";
const BASE = `http://127.0.0.1:${PORT}`;

const child = spawn(process.execPath, ["dist/server.js"], {
  env: { ...process.env, PORT },
  stdio: ["ignore", "pipe", "pipe"],
});

let stderr = "";
child.stderr.on("data", (chunk) => {
  stderr += String(chunk);
});

async function waitFor(url, attempts = 60) {
  for (let i = 0; i < attempts; i += 1) {
    try {
      const response = await fetch(url);
      if (response.ok) return response;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 100));
  }
  throw new Error(`fixture-aut did not become ready: ${stderr}`);
}

try {
  await waitFor(`${BASE}/api/health`);

  const pages = {};
  for (const route of ["/", "/cart", "/checkout"]) {
    const response = await fetch(`${BASE}${route}`);
    assert.equal(response.status, 200, `${route} should return 200`);
    pages[route] = await response.text();
  }

  const products = await (await fetch(`${BASE}/api/products`)).json();
  assert.equal(products.products.length, 3, "three seeded products");

  const cart = await (await fetch(`${BASE}/api/cart`)).json();
  assert.equal(cart.items.length, 0, "cart starts empty");

  const order = await (
    await fetch(`${BASE}/api/checkout`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: "{}",
    })
  ).json();
  assert.equal(order.status, "confirmed");

  const home = pages["/"];
  const allHtml = Object.values(pages).join("\n");
  assert.match(home, /data-testid="cart-link"/, "fixture cart link present");
  assert.equal(
    (allHtml.match(/class="icon-link"/g) ?? []).length,
    1,
    "exactly one icon-only link defect across the fixture UI",
  );
  assert.equal(
    (allHtml.match(/class="icon-btn"/g) ?? []).length,
    1,
    "exactly one unlabeled button defect across the fixture UI",
  );
  assert.doesNotMatch(
    home,
    /class="icon-link"[^>]*aria-label=/,
    "a11y defect #1 must stay unlabeled until a story fixes it",
  );
  assert.doesNotMatch(
    home,
    /class="icon-btn"[^>]*aria-label=/,
    "a11y defect #2 must stay unlabeled until a story fixes it",
  );
  assert.match(
    home,
    /<button[^>]*class="icon-btn"[^>]*>\s*<\/button>/,
    "a11y defect #2 must remain an empty button",
  );

  const appJs = await fetch(`${BASE}/app.js`);
  assert.equal(appJs.status, 200, "source-mapped client bundle is served");

  console.log("fixture-aut verification passed");
} finally {
  child.kill("SIGTERM");
}
