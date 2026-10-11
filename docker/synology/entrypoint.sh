#!/bin/bash
set -e

# ==============================================================================
# Element Server Suite (ESS) Community - All-in-One Entrypoint for Synology DSM
# ==============================================================================

echo "=================================================================="
echo " Starting Element Server Suite (ESS) Community for Synology DSM   "
echo "=================================================================="

# Définition des répertoires
DATA_DIR=${DATA_DIR:-/data}
CONFIG_DIR=${CONFIG_DIR:-/data/config}
SECRETS_DIR=${SECRETS_DIR:-/data/secrets}
MEDIA_DIR=${MEDIA_DIR:-/data/media}
PGDATA=${PGDATA:-/data/postgres}

mkdir -p "$DATA_DIR" "$CONFIG_DIR" "$SECRETS_DIR" "$MEDIA_DIR" "$PGDATA" /var/log/supervisor /var/run/postgresql
chown -R postgres:postgres "$PGDATA" /var/run/postgresql

# Définition des variables principales
export SERVER_NAME=${SERVER_NAME:-matrix.local}
export PUBLIC_BASEURL=${PUBLIC_BASEURL:-http://localhost:8080}
export ENABLE_INTERNAL_POSTGRES=${ENABLE_INTERNAL_POSTGRES:-true}
export ENABLE_MAS=${ENABLE_MAS:-true}

export POSTGRES_USER=${POSTGRES_USER:-synapse}
export POSTGRES_PORT=${POSTGRES_PORT:-5432}
export POSTGRES_HOST=${POSTGRES_HOST:-127.0.0.1}
export SYNAPSE_DB_NAME=${SYNAPSE_DB_NAME:-synapse}
export MAS_DB_NAME=${MAS_DB_NAME:-matrixauthenticationservice}

# Gestion du mot de passe PostgreSQL
if [ -z "$POSTGRES_PASSWORD" ]; then
    if [ -f "$SECRETS_DIR/postgres_password" ]; then
        export POSTGRES_PASSWORD=$(cat "$SECRETS_DIR/postgres_password")
    else
        export POSTGRES_PASSWORD=$(openssl rand -hex 16)
        echo "$POSTGRES_PASSWORD" > "$SECRETS_DIR/postgres_password"
    fi
fi

# ==============================================================================
# Génération automatique des clés et secrets
# ==============================================================================
echo "[1/4] Vérification et génération des clés de chiffrement..."

# Clé de signature Synapse
if [ ! -f "$SECRETS_DIR/synapse.signing.key" ]; then
    echo "  -> Génération de la clé de signature Synapse..."
    python3 -c "import synapse.app.homeserver; from synapse.crypto.keyring import generate_signing_key; open('$SECRETS_DIR/synapse.signing.key', 'w').write(generate_signing_key('a_' + '$SERVER_NAME'))" 2>/dev/null || \
    openssl rand -base64 32 > "$SECRETS_DIR/synapse.signing.key"
fi

# Secret Macaroon Synapse
if [ ! -f "$SECRETS_DIR/synapse_macaroon_secret" ]; then
    openssl rand -hex 32 > "$SECRETS_DIR/synapse_macaroon_secret"
fi
export SYNAPSE_MACAROON_SECRET=$(cat "$SECRETS_DIR/synapse_macaroon_secret")

# Secret d'enregistrement Synapse
if [ ! -f "$SECRETS_DIR/synapse_registration_shared_secret" ]; then
    openssl rand -hex 32 > "$SECRETS_DIR/synapse_registration_shared_secret"
fi
export SYNAPSE_REGISTRATION_SHARED_SECRET=$(cat "$SECRETS_DIR/synapse_registration_shared_secret")

# Secret partagé Synapse <-> MAS
if [ ! -f "$SECRETS_DIR/mas_synapse_shared_secret" ]; then
    openssl rand -hex 32 > "$SECRETS_DIR/mas_synapse_shared_secret"
fi
export MAS_SYNAPSE_SHARED_SECRET=$(cat "$SECRETS_DIR/mas_synapse_shared_secret")

# Secret de chiffrement MAS
if [ ! -f "$SECRETS_DIR/mas_encryption_secret" ]; then
    openssl rand -hex 32 > "$SECRETS_DIR/mas_encryption_secret"
fi
export MAS_ENCRYPTION_SECRET=$(cat "$SECRETS_DIR/mas_encryption_secret")

# Clés asymétriques MAS (RSA et ECDSA)
if [ ! -f "$SECRETS_DIR/mas-rsa.key" ]; then
    echo "  -> Génération de la clé privée RSA pour MAS..."
    openssl genrsa -out "$SECRETS_DIR/mas-rsa.key" 2048
fi

if [ ! -f "$SECRETS_DIR/mas-ecdsa.key" ]; then
    echo "  -> Génération de la clé privée ECDSA pour MAS..."
    openssl ecparam -name prime256v1 -genkey -noout -out "$SECRETS_DIR/mas-ecdsa.key"
fi

if [ ! -f "$SECRETS_DIR/mas_admin_token" ]; then
    openssl rand -hex 32 > "$SECRETS_DIR/mas_admin_token"
fi
export MAS_ADMIN_TOKEN=$(cat "$SECRETS_DIR/mas_admin_token")

# ==============================================================================
# Initialisation de la base de données PostgreSQL interne
# ==============================================================================
if [ "$ENABLE_INTERNAL_POSTGRES" = "true" ]; then
    echo "[2/4] Configuration de PostgreSQL interne..."
    if [ ! -f "$PGDATA/PG_VERSION" ]; then
        echo "  -> Initialisation du cluster PostgreSQL..."
        su - postgres -c "/usr/lib/postgresql/16/bin/initdb -D '$PGDATA' --encoding=UTF8 --locale=C"
    fi

    # Démarrage temporaire de PostgreSQL pour l'initialisation des bases
    echo "  -> Vérification des bases de données..."
    su - postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D '$PGDATA' -o '-k /var/run/postgresql' start -w"

    # Création du rôle et des bases s'ils n'existent pas
    su - postgres -c "psql -tc \"SELECT 1 FROM pg_roles WHERE rolname='$POSTGRES_USER'\" | grep -q 1 || psql -c \"CREATE USER $POSTGRES_USER WITH PASSWORD '$POSTGRES_PASSWORD';\""
    su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='$SYNAPSE_DB_NAME'\" | grep -q 1 || psql -c \"CREATE DATABASE $SYNAPSE_DB_NAME OWNER $POSTGRES_USER;\""
    su - postgres -c "psql -tc \"SELECT 1 FROM pg_database WHERE datname='$MAS_DB_NAME'\" | grep -q 1 || psql -c \"CREATE DATABASE $MAS_DB_NAME OWNER $POSTGRES_USER;\""

    # Configuration des droits
    su - postgres -c "psql -c \"ALTER DATABASE $SYNAPSE_DB_NAME OWNER TO $POSTGRES_USER;\""
    su - postgres -c "psql -c \"ALTER DATABASE $MAS_DB_NAME OWNER TO $POSTGRES_USER;\""
fi

# ==============================================================================
# Génération des fichiers de configuration à partir des templates
# ==============================================================================
echo "[3/4] Génération des fichiers de configuration..."

envsubst < /templates/homeserver.yaml.template > "$CONFIG_DIR/homeserver.yaml"
envsubst < /templates/mas.yaml.template > "$CONFIG_DIR/mas.yaml"
envsubst < /templates/Caddyfile.template > "$CONFIG_DIR/Caddyfile"

# Configuration d'Element Web
if [ -d "/var/www/element-web" ]; then
    envsubst < /templates/element-config.json.template > /var/www/element-web/config.json
fi

# Exécution des migrations MAS
if [ "$ENABLE_MAS" = "true" ]; then
    echo "  -> Migration et synchronisation de MAS..."
    mas-cli config sync --prune --config "$CONFIG_DIR/mas.yaml" || mas-cli database migrate --config "$CONFIG_DIR/mas.yaml" || true
fi

# Création éventuelle de l'utilisateur initial si défini dans les variables
if [ -n "$INITIAL_ADMIN_USER" ] && [ -n "$INITIAL_ADMIN_PASSWORD" ]; then
    echo "  -> Création du compte administrateur initial ($INITIAL_ADMIN_USER)..."
    mas-cli manage register-user --yes --admin "$INITIAL_ADMIN_USER" --config "$CONFIG_DIR/mas.yaml" || true
    mas-cli manage set-password --yes --password "$INITIAL_ADMIN_PASSWORD" "$INITIAL_ADMIN_USER" --config "$CONFIG_DIR/mas.yaml" || true
fi

# Arrêt de PostgreSQL temporaire avant passage de relais à Supervisor
if [ "$ENABLE_INTERNAL_POSTGRES" = "true" ]; then
    su - postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D '$PGDATA' stop -m fast"
fi

# ==============================================================================
# Lancement des services
# ==============================================================================
echo "[4/4] Démarrage des services ESS Community..."
echo "=================================================================="
echo " Server Name    : $SERVER_NAME"
echo " Public URL     : $PUBLIC_BASEURL"
echo " Web Client     : $PUBLIC_BASEURL/"
echo " Admin Console  : $PUBLIC_BASEURL/admin/"
echo " Matrix Endpoint: $PUBLIC_BASEURL/_matrix/"
echo " MAS Endpoint   : $PUBLIC_BASEURL/auth/"
echo "=================================================================="

exec "$@"
