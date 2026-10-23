# Build context is the repository root so the control plane can typecheck against
# the workspace shared-types package. The runtime image only needs fastify.
FROM node:22-alpine AS build
RUN corepack enable
WORKDIR /repo

COPY pnpm-workspace.yaml pnpm-lock.yaml package.json ./
COPY apps/control-plane/package.json apps/control-plane/
COPY apps/web/package.json apps/web/
COPY packages/shared-types/package.json packages/shared-types/
COPY packages/test-fixtures/aut/package.json packages/test-fixtures/aut/
COPY packages/test-fixtures/mock-oidc/package.json packages/test-fixtures/mock-oidc/
RUN pnpm install --frozen-lockfile

COPY apps/control-plane apps/control-plane
COPY packages/shared-types packages/shared-types
RUN pnpm --filter @testradius/control-plane build

FROM node:22-alpine
WORKDIR /app
ENV NODE_ENV=production PORT=8080

# Remove workspace-only dev dependencies before installing runtime deps; the
# emitted JS contains no import of @testradius/shared-types (type-only).
COPY apps/control-plane/package.json ./package.json
RUN npm pkg delete devDependencies \
    && npm install --omit=dev \
    && npm cache clean --force

COPY --from=build /repo/apps/control-plane/dist ./dist
USER node
EXPOSE 8080
CMD ["node", "dist/index.js"]
