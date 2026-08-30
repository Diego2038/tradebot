# --- Stage 1: build de la app Flutter web (no requiere Flutter en el host) ---
FROM debian:bookworm-slim AS build

ENV FLUTTER_HOME=/opt/flutter \
    PATH=/opt/flutter/bin:/opt/flutter/bin/cache/dart-sdk/bin:$PATH \
    DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl ca-certificates unzip xz-utils && \
    rm -rf /var/lib/apt/lists/*

# SDK de Flutter (canal estable).
RUN git clone --depth 1 --branch stable https://github.com/flutter/flutter.git /opt/flutter && \
    flutter config --enable-web && \
    flutter precache --web

WORKDIR /app
COPY pubspec.yaml ./
RUN flutter pub get
COPY . .
# API_BASE_URL / WS_BASE_URL pueden sobreescribirse en build con --build-arg.
ARG API_BASE_URL=http://localhost:8000
ARG WS_BASE_URL=ws://localhost:8000/ws/bot
RUN flutter build web --release \
    --dart-define=API_BASE_URL=$API_BASE_URL \
    --dart-define=WS_BASE_URL=$WS_BASE_URL

# --- Stage 2: servir los estáticos con nginx ---
FROM nginx:1.27-alpine AS serve
COPY --from=build /app/build/web /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
