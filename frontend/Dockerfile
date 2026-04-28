# =============================================================================
# Delphi dashboard (Next.js 14, standalone output)
# =============================================================================
FROM node:20-alpine AS build
WORKDIR /app
# Next.js bakes the rewrite `destination` URLs into routes-manifest.json
# at build time (not runtime), so anything next.config.mjs reads from
# process.env must be set HERE, before `npm run build`. INTERNAL_API_URL
# is the docker-network hostname the Next server will fetch through.
ARG INTERNAL_API_URL=http://api:8742
# NEXT_PUBLIC_API_URL is what `lib/api.ts` reads as DIRECT_API_URL,
# inlined into the BROWSER bundle at build time. The default
# (localhost:8742) is correct for the common case; CLI-driven installs
# pass through a different host port when 8742 was busy.
ARG NEXT_PUBLIC_API_URL=http://localhost:8742
ENV INTERNAL_API_URL=${INTERNAL_API_URL} \
    NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL} \
    NEXT_TELEMETRY_DISABLED=1
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

# Runtime ships only the traced standalone bundle (server.js + minimal
# node_modules) — much smaller than copying the full dev node_modules,
# and avoids ENOSPC on disk-tight Docker VMs.
FROM node:20-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 1001 nextjs \
 && adduser  --system --uid 1001 nextjs

COPY --from=build --chown=nextjs:nextjs /app/public ./public
COPY --from=build --chown=nextjs:nextjs /app/.next/standalone ./
COPY --from=build --chown=nextjs:nextjs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000
CMD ["node", "server.js"]
