# syntax=docker/dockerfile:1

# ---- build ----------------------------------------------------------------
FROM node:22-alpine AS build

WORKDIR /srv

COPY package*.json ./
RUN npm ci

COPY . .

# O Vite embute a URL da API no bundle, então ela é um argumento de build e não
# uma variável de runtime: mudar de backend exige reconstruir a imagem.
ARG VITE_API_URL=http://127.0.0.1:8000
ENV VITE_API_URL=$VITE_API_URL
RUN npm run build

# ---- runtime --------------------------------------------------------------
FROM nginx:alpine

COPY --from=build /srv/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
