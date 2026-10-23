import { buildServer } from "./app.js";

const port = Number(process.env.PORT ?? 8080);
const host = process.env.HOST ?? "0.0.0.0";

const app = buildServer({ version: process.env.APP_VERSION });

app.listen({ port, host }).catch((error: unknown) => {
  console.error(error);
  process.exit(1);
});
