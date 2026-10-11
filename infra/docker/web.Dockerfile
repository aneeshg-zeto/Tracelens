# Next.js dashboard (standalone output). NEXT_PUBLIC_* values are inlined at
# build time, so they are build args; server secrets are runtime env only.
FROM node:22-alpine AS base
RUN corepack enable
WORKDIR /srv/web

FROM base AS deps
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN --mount=type=cache,target=/root/.local/share/pnpm/store pnpm install --frozen-lockfile

FROM base AS build
ARG NEXT_PUBLIC_TRACELENS_INGEST_URL=http://localhost:8000
ARG NEXT_PUBLIC_GITHUB_URL=
ARG NEXT_PUBLIC_DOCS_URL=
ENV NEXT_PUBLIC_TRACELENS_INGEST_URL=$NEXT_PUBLIC_TRACELENS_INGEST_URL \
    NEXT_PUBLIC_GITHUB_URL=$NEXT_PUBLIC_GITHUB_URL \
    NEXT_PUBLIC_DOCS_URL=$NEXT_PUBLIC_DOCS_URL \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /srv/web/node_modules ./node_modules
COPY apps/web ./
RUN pnpm build

FROM node:22-alpine AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /srv/web
RUN addgroup -S -g 10001 tracelens && adduser -S -u 10001 -G tracelens tracelens
COPY --from=build --chown=tracelens:tracelens /srv/web/.next/standalone ./
COPY --from=build --chown=tracelens:tracelens /srv/web/.next/static ./.next/static
COPY --from=build --chown=tracelens:tracelens /srv/web/public ./public
USER tracelens
EXPOSE 3000
CMD ["node", "server.js"]
