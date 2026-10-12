# Copyright 2026 Element Creations Ltd
#
# SPDX-License-Identifier: AGPL-3.0-only

# Stage 1: Extraction des binaires et assets officiels ESS
FROM oci.element.io/matrix-authentication-service:1.26.0 AS mas-src
FROM oci.element.io/element-web:v1.12.30 AS element-web-src
FROM oci.element.io/element-admin:0.1.15 AS element-admin-src

# Stage 2: Image finale basée sur Synapse officiel
FROM oci.element.io/synapse:v1.162.0

USER root

# Définition des variables d'environnement
ENV DEBIAN_FRONTEND=noninteractive \
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
    ENABLE_MAS=true

# Installation des dépendances (PostgreSQL, Caddy, Supervisor, OpenSSL, curl, jq)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    jq \
    openssl \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc | gpg --dearmor -o /usr/share/keyrings/postgresql-archive-keyring.gpg \
    && echo "deb [signed-by=/usr/share/keyrings/postgresql-archive-keyring.gpg] http://apt.postgresql.org/pub/repos/apt $(lsb_release -cs)-pgdg main" | tee /etc/apt/sources.list.d/postgresql.list \
    && apt-get update && apt-get install -y --no-install-recommends \
    postgresql-16 \
    postgresql-client-16 \
    supervisor \
    gettext-base \
    debian-keyring \
    apt-transport-https \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg \
    && curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | tee /etc/apt/sources.list.d/caddy-stable.list \
    && apt-get update && apt-get install -y --no-install-recommends caddy \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copie du binaire MAS (Matrix Authentication Service)
COPY --from=mas-src /usr/local/bin/mas-cli /usr/local/bin/mas-cli

# Copie des applications Element Web et Element Admin
COPY --from=element-web-src /app /var/www/element-web
COPY --from=element-admin-src /dist /var/www/element-admin

# Création des répertoires de données et templates
RUN mkdir -p /data /templates /var/log/supervisor /var/run/postgresql \
    && chown -R postgres:postgres /var/run/postgresql

# Copie des configurations et scripts
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf
COPY Caddyfile /templates/Caddyfile.template
COPY homeserver.yaml.template /templates/homeserver.yaml.template
COPY mas.yaml.template /templates/mas.yaml.template
COPY element-config.json.template /templates/element-config.json.template
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
COPY register-user.sh /usr/local/bin/register-user

RUN chmod +x /usr/local/bin/entrypoint.sh /usr/local/bin/register-user

# Exposition des ports :
# 8080 : Port HTTP principal (Reverse proxy Caddy vers Synapse, MAS, Element Web/Admin)
# 8448 : Port Matrix Federation (optionnel)
EXPOSE 8080 8448

VOLUME ["/data"]

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["supervisord", "-n", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
