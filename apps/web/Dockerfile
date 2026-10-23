# Build context is the repository root: the web typecheck consumes the workspace
# shared-types package. The runtime image is nginx + static assets only.
FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /repo

COPY pnpm-workspace.yaml pnpm-lock.yaml package.json ./
COPY apps/web/package.json apps/web/
COPY apps/control-plane/package.json apps/control-plane/
COPY packages/shared-types/package.json packages/shared-types/
COPY packages/test-fixtures/aut/package.json packages/test-fixtures/aut/
COPY packages/test-fixtures/mock-oidc/package.json packages/test-fixtures/mock-oidc/
RUN pnpm install --frozen-lockfile

COPY apps/web apps/web
COPY packages/shared-types packages/shared-types
RUN pnpm --filter @testradius/web build

FROM nginx:1.27-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
EXPOSE 80
