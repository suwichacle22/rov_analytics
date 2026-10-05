# syntax=docker/dockerfile:1
# The dashboard as a server on port 3000. Build it from the repo root, the workspace needs
# packages/backend too:  docker build -f apps/web/Dockerfile --build-arg VITE_CONVEX_URL=... .

FROM oven/bun:1.4.2-alpine AS deps
WORKDIR /app
COPY package.json bun.lock ./
COPY apps/web/package.json apps/web/
COPY packages/backend/package.json packages/backend/
RUN bun install --frozen-lockfile

# Built on top of deps: Bun keeps a node_modules folder in every workspace, not only in the root.
FROM deps AS build
ENV NITRO_PRESET=bun
COPY . .

# The address is compiled into the pages, so it has to be known here.
ARG VITE_CONVEX_URL
ENV VITE_CONVEX_URL=$VITE_CONVEX_URL
ENV NODE_ENV=production

RUN bun run typecheck
RUN bun run build

FROM oven/bun:1.4.2-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production
ENV HOST=0.0.0.0
ENV PORT=3000

COPY --from=build --chown=bun:bun /app/apps/web/.output ./.output
USER bun
EXPOSE 3000
CMD ["bun", "run", ".output/server/index.mjs"]
