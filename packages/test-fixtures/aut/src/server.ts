import express, { type Express } from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const publicDir = path.join(here, "public");

interface Product {
  id: string;
  name: string;
  price: number;
}

const PRODUCTS: Product[] = [
  { id: "p-kebab", name: "Kebab skewer", price: 1200 },
  { id: "p-flatbread", name: "Flatbread", price: 400 },
  { id: "p-mint-tea", name: "Mint tea", price: 300 },
];

export function createApp(): Express {
  const app = express();
  app.use(express.json());

  const cart: Array<{ id: string; qty: number }> = [];

  app.get("/api/health", (_req, res) => {
    res.json({ status: "ok", service: "fixture-aut" });
  });

  app.get("/api/products", (_req, res) => {
    res.json({ products: PRODUCTS });
  });

  app.get("/api/cart", (_req, res) => {
    res.json({ items: cart, count: cart.reduce((n, item) => n + item.qty, 0) });
  });

  app.post("/api/checkout", (_req, res) => {
    res.json({ orderId: "ord_fixture_1", total: 2400, status: "confirmed" });
  });

  app.get("/", (_req, res) => res.sendFile(path.join(publicDir, "index.html")));
  app.get("/cart", (_req, res) => res.sendFile(path.join(publicDir, "cart.html")));
  app.get("/checkout", (_req, res) => res.sendFile(path.join(publicDir, "checkout.html")));

  app.use(express.static(publicDir));
  return app;
}

const isMain = process.argv[1] === fileURLToPath(import.meta.url);
if (isMain) {
  const port = Number(process.env.PORT ?? 8080);
  createApp().listen(port, "0.0.0.0", () => {
    console.log(`fixture-aut listening on :${port}`);
  });
}
