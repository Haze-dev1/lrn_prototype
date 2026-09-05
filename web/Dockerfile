# syntax=docker/dockerfile:1

FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci


# Development target: source is bind-mounted by Compose, so only dependencies live in the image.
FROM node:24-alpine AS dev
ENV NODE_ENV=development
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
EXPOSE 3000
CMD ["npm", "run", "dev"]


FROM node:24-alpine AS build
ENV NEXT_TELEMETRY_DISABLED=1
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build


FROM node:24-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app
RUN addgroup --system --gid 1001 lrn && adduser --system --uid 1001 --ingroup lrn lrn

# `output: 'standalone'` emits a server bundle with only the modules actually reached, so the
# runtime image ships without the full node_modules tree.
COPY --from=build --chown=lrn:lrn /app/.next/standalone ./
COPY --from=build --chown=lrn:lrn /app/.next/static ./.next/static
COPY --from=build --chown=lrn:lrn /app/public ./public

USER lrn
EXPOSE 3000
CMD ["node", "server.js"]
