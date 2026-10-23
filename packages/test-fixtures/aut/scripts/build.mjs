import { cp, mkdir, rm } from "node:fs/promises";

import { build } from "esbuild";

await rm("dist", { recursive: true, force: true });
await mkdir("dist/public", { recursive: true });

await build({
  entryPoints: ["src/server.ts"],
  bundle: true,
  platform: "node",
  format: "esm",
  target: "node20",
  outfile: "dist/server.js",
  sourcemap: true,
  external: ["express"],
});

await build({
  entryPoints: ["src/client.ts"],
  bundle: true,
  platform: "browser",
  format: "iife",
  target: "es2020",
  outfile: "dist/public/app.js",
  sourcemap: true,
});

await cp("public", "dist/public", { recursive: true });
console.log("fixture-aut build complete");
