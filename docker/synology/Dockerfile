# Copyright 2026 Element Creations Ltd
#
# SPDX-License-Identifier: AGPL-3.0-only

# Version de Synapse utilisée comme image de base
ARG SYNAPSE_VERSION=1.162.0

# Stage 1: Extraction des binaires et assets officiels ESS
FROM oci.element.io/matrix-authentication-service:1.26.0 AS mas-src
FROM oci.element.io/element-web:v1.12.30 AS element-web-src
FROM oci.element.io/element-admin:0.1.15 AS element-admin-src
# MatrixRTC (Element Call) : SFU LiveKit et MatrixRTC Authorisation Service
FROM docker.io/livekit/livekit-server:v1.13.9 AS livekit-src
FROM oci.element.io/lk-jwt-service:0.8.0 AS lk-jwt-service-src

# Stage 2: Image finale basée sur Synapse officiel
FROM oci.element.io/synapse:v${SYNAPSE_VERSION}
ARG SYNAPSE_VERSION

USER root

# Définition des variables d'environnement
# SYNAPSE_VERSION_STRING est héritée vide de l'image Synapse, or l'interface
# Docker de DSM 7.1 refuse d'enregistrer une variable d'environnement vide.
ENV SYNAPSE_VERSION_STRING=${SYNAPSE_VERSION} \
    DEBIAN_FRONTEND=noninteractive \
    DATA_DIR=/data \
    CONFIG_DIR=/data/config \
    SECRETS_DIR=/data/secrets \
    MEDIA_DIR=/data/media \
    PGDATA=/data/postgres \
    SERVER_NAME=matrix.local \
    PUBLIC_BASEURL=http://localhost:8080 \
    ENABLE_INTERNAL_POSTGRES=true \
    ENABLE_ELEMENT_WEB=true \
    ENABLE_ELEMENT_ADMIN=true \
    ENABLE_MAS=true \
    ENABLE_MATRIX_RTC=true \
    ENABLE_TURN=true

# Installation des dépendances (PostgreSQL, Caddy, coturn, Supervisor, OpenSSL, curl, jq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    jq \
    openssl \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg \
    && . /etc/os-release \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] http://apt.postgresql.org/pub/repos/apt ${VERSION_CODENAME}-pgdg main" | tee /etc/apt/sources.list.d/postgresql.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    postgresql-16 \
    postgresql-client-16 \
    coturn \
    supervisor \
    gettext-base \
    debian-keyring \
    apt-transport-https \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list \
    && apt-get update && apt-get install -y --no-install-recommends caddy \
    # Suppression du cluster par défaut créé par le paquet Debian : seul le cluster
    # persistant /data/postgres (initialisé par l'entrypoint) doit être utilisé
    && pg_dropcluster 16 main \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copie du binaire MAS (Matrix Authentication Service) et de ses ressources
# (templates, policy.wasm, assets, traductions), indispensables à `mas-cli server`
COPY --from=mas-src /usr/local/bin/mas-cli /usr/local/bin/mas-cli
COPY --from=mas-src /usr/local/share/mas-cli /usr/local/share/mas-cli

# Copie des applications Element Web et Element Admin
COPY --from=element-web-src /app /var/www/element-web
COPY --from=element-admin-src /dist /var/www/element-admin

# Copie des binaires statiques MatrixRTC (LiveKit SFU et lk-jwt-service)
COPY --from=livekit-src /livekit-server /usr/local/bin/livekit-server
COPY --from=lk-jwt-service-src /lk-jwt-service /usr/local/bin/lk-jwt-service

# Création des répertoires de données et templates
RUN mkdir -p /data /templates /var/log/supervisor /var/run/postgresql \
    && chown -R postgres:postgres /var/run/postgresql

# Copie des configurations et scripts
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY Caddyfile /templates/Caddyfile.template
COPY homeserver.yaml.template /templates/homeserver.yaml.template
COPY mas.yaml.template /templates/mas.yaml.template
COPY element-config.json.template /templates/element-config.json.template
COPY homeserver-matrix-rtc.yaml.template /templates/homeserver-matrix-rtc.yaml.template
COPY homeserver-turn.yaml.template /templates/homeserver-turn.yaml.template
COPY matrix-rtc-registration.yaml.template /templates/matrix-rtc-registration.yaml.template
COPY livekit.yaml.template /templates/livekit.yaml.template
COPY turnserver.conf.template /templates/turnserver.conf.template
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY register-user.sh /usr/local/bin/register-user

RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/register-user

# Exposition des ports :
# 8080 : Port HTTP principal (Reverse proxy Caddy vers Synapse, MAS, Element Web/Admin)
# 8448 : Port Matrix Federation (optionnel)
# 7881/tcp, 7882/udp : Flux audio/vidéo MatrixRTC (LiveKit SFU)
# 3478/udp+tcp, 49160-49169/udp : Serveur TURN coturn (appels 1:1 historiques)
EXPOSE 8080 8448 7881/tcp 7882/udp 3478/tcp 3478/udp 49160-49169/udp

VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
