# 1. Asama: Vue uygulamasini derle
FROM node:22-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# 2. Asama: statik dosyalari Caddy ile sun (ayni imaj /api'yi backend'e proxy'ler)
FROM caddy:2-alpine

COPY Caddyfile /etc/caddy/Caddyfile
COPY --from=build /app/dist /srv
