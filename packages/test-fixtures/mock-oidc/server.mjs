import { createServer } from "node:http";

const PORT = Number(process.env.PORT ?? 8090);
const ISSUER = process.env.ISSUER ?? `http://localhost:58090`;

const discovery = {
  issuer: ISSUER,
  authorization_endpoint: `${ISSUER}/authorize`,
  token_endpoint: `${ISSUER}/token`,
  jwks_uri: `${ISSUER}/jwks`,
  response_types_supported: ["code"],
  subject_types_supported: ["public"],
  id_token_signing_alg_values_supported: ["RS256"],
  scopes_supported: ["openid", "profile", "email"],
};

const json = (res, status, body) => {
  res.writeHead(status, {
    "content-type": "application/json",
    "cache-control": "no-store",
  });
  res.end(JSON.stringify(body));
};

const server = createServer((req, res) => {
  const url = new URL(req.url ?? "/", ISSUER);

  if (url.pathname === "/healthz") return json(res, 200, { status: "ok" });
  if (url.pathname === "/.well-known/openid-configuration") return json(res, 200, discovery);
  // Dev-only stub: no keys, tokens are not verifiable. Real signing lands with E5-S2.
  if (url.pathname === "/jwks") return json(res, 200, { keys: [] });
  if (url.pathname === "/token" && req.method === "POST") {
    return json(res, 200, {
      access_token: "dev-access-token",
      token_type: "Bearer",
      expires_in: 3600,
    });
  }
  if (url.pathname === "/authorize") {
    const redirect = url.searchParams.get("redirect_uri") ?? "/";
    const state = url.searchParams.get("state") ?? "";
    res.writeHead(302, { location: `${redirect}?code=dev-code&state=${state}` });
    return res.end();
  }
  return json(res, 404, { error: "not_found" });
});

server.listen(PORT, "0.0.0.0", () => {
  console.log(`mock-oidc listening on :${PORT}`);
});
