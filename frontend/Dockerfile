# --- Stage build: compila el frontend React con Vite ---
FROM node:20-alpine AS build
WORKDIR /app

# Instalar dependencias (aprovecha la cache si package*.json no cambia).
COPY package.json package-lock.json* ./
RUN npm install

# Copiar el resto del código y construir.
COPY . .

# Config inyectada en build-time (Vite embebe las VITE_* en el bundle).
ARG VITE_API_BASE_URL=http://localhost:8000
ARG VITE_WS_BASE_URL=ws://localhost:8000/ws/bot
RUN VITE_API_BASE_URL=$VITE_API_BASE_URL VITE_WS_BASE_URL=$VITE_WS_BASE_URL npm run build

# --- Stage serve: sirve los estáticos con nginx ---
FROM nginx:1.27-alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
