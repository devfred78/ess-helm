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

# Appels audio/vidéo : MatrixRTC (Element Call, LiveKit) et TURN (appels 1:1 historiques).
# Les valeurs sont normalisées en true/false car Supervisor les utilise pour autostart.
normalize_bool() {
    case "${1,,}" in
        true|yes|on|1) echo true ;;
        *) echo false ;;
    esac
}
export ENABLE_MATRIX_RTC=$(normalize_bool "${ENABLE_MATRIX_RTC:-true}")
export ENABLE_TURN=$(normalize_bool "${ENABLE_TURN:-true}")
export TURN_MIN_PORT=${TURN_MIN_PORT:-49160}
export TURN_MAX_PORT=${TURN_MAX_PORT:-49169}
export LIVEKIT_KEY=matrix-rtc
# IP publique de la box (facultative : détectée automatiquement sinon)
export PUBLIC_IP=${PUBLIC_IP:-}

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

# Clé de signature Synapse (format attendu : "ed25519 <key_id> <clé base64>")
# Une clé existante au mauvais format (ancienne génération via openssl) est régénérée.
if [ ! -f "$SECRETS_DIR/synapse.signing.key" ] || ! grep -q '^ed25519 ' "$SECRETS_DIR/synapse.signing.key"; then
    echo "  -> Génération de la clé de signature Synapse..."
    python3 -c "import sys, secrets; from signedjson.key import generate_signing_key, write_signing_keys; write_signing_keys(open(sys.argv[1], 'w'), [generate_signing_key('a_' + secrets.token_hex(2))])" "$SECRETS_DIR/synapse.signing.key"
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

# Secret partagé LiveKit SFU <-> MatrixRTC Authorisation Service (sans retour à la ligne :
# lk-jwt-service le lit tel quel depuis le fichier)
if [ ! -f "$SECRETS_DIR/livekit_secret" ]; then
    openssl rand -hex 32 | tr -d '\n' > "$SECRETS_DIR/livekit_secret"
fi
export LIVEKIT_SECRET=$(cat "$SECRETS_DIR/livekit_secret")

# Jetons de l'application service MatrixRTC Authorisation Service
if [ ! -f "$SECRETS_DIR/matrix_rtc_as_token" ]; then
    openssl rand -hex 32 > "$SECRETS_DIR/matrix_rtc_as_token"
fi
export MATRIX_RTC_AS_TOKEN=$(cat "$SECRETS_DIR/matrix_rtc_as_token")

if [ ! -f "$SECRETS_DIR/matrix_rtc_hs_token" ]; then
    openssl rand -hex 32 > "$SECRETS_DIR/matrix_rtc_hs_token"
fi
export MATRIX_RTC_HS_TOKEN=$(cat "$SECRETS_DIR/matrix_rtc_hs_token")

# Secret partagé Synapse <-> coturn
if [ ! -f "$SECRETS_DIR/turn_shared_secret" ]; then
    openssl rand -hex 32 > "$SECRETS_DIR/turn_shared_secret"
fi
export TURN_SHARED_SECRET=$(cat "$SECRETS_DIR/turn_shared_secret")

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

export CONFIG_DIR

# Indique si une adresse IPv4 est privée (non joignable depuis Internet)
is_private_ipv4() {
    case "$1" in
        10.*|127.*|169.254.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[0-1].*|100.6[4-9].*|100.[7-9][0-9].*|100.1[0-1][0-9].*|100.12[0-7].*) return 0 ;;
        *) return 1 ;;
    esac
}

# MatrixRTC : sans PUBLIC_IP, LiveKit découvre lui-même l'IP publique par STUN
if [ -n "$PUBLIC_IP" ]; then
    export LIVEKIT_USE_EXTERNAL_IP=false
else
    export LIVEKIT_USE_EXTERNAL_IP=true
fi

if [ "$ENABLE_MATRIX_RTC" = "true" ]; then
    echo "  -> MatrixRTC (Element Call) activé"
    export LIVEKIT_PUBLIC_URL="wss://${PUBLIC_BASEURL#*://}/livekit/sfu"
    export WELL_KNOWN_RTC_FOCI=", \"org.matrix.msc4143.rtc_foci\": [{\"type\": \"livekit\", \"livekit_service_url\": \"${PUBLIC_BASEURL}/livekit/jwt\"}]"
    export ELEMENT_CALL_USE_EXCLUSIVELY=true
    envsubst < /templates/livekit.yaml.template > "$CONFIG_DIR/livekit.yaml"
    envsubst < /templates/matrix-rtc-registration.yaml.template > "$CONFIG_DIR/matrix-rtc-registration.yaml"
else
    export LIVEKIT_PUBLIC_URL=""
    export WELL_KNOWN_RTC_FOCI=""
    export ELEMENT_CALL_USE_EXCLUSIVELY=false
fi

envsubst < /templates/homeserver.yaml.template > "$CONFIG_DIR/homeserver.yaml"
if [ "$ENABLE_MATRIX_RTC" = "true" ]; then
    envsubst < /templates/homeserver-matrix-rtc.yaml.template >> "$CONFIG_DIR/homeserver.yaml"
fi

if [ "$ENABLE_TURN" = "true" ]; then
    echo "  -> Serveur TURN (coturn) activé"
    envsubst < /templates/homeserver-turn.yaml.template >> "$CONFIG_DIR/homeserver.yaml"
    envsubst < /templates/turnserver.conf.template > "$CONFIG_DIR/turnserver.conf"

    # Le conteneur est derrière le NAT de Docker et de la box : coturn doit annoncer
    # l'IP publique (PUBLIC_IP, ou à défaut celle vers laquelle pointe SERVER_NAME)
    CONTAINER_IP=$(hostname -i | awk '{print $1}')
    TURN_PUBLIC_IP="$PUBLIC_IP"
    if [ -z "$TURN_PUBLIC_IP" ]; then
        TURN_PUBLIC_IP=$(getent ahostsv4 "$SERVER_NAME" | awk 'NR==1 {print $1}')
        if [ -n "$TURN_PUBLIC_IP" ] && is_private_ipv4 "$TURN_PUBLIC_IP"; then
            TURN_PUBLIC_IP=""
        fi
    fi
    if [ -n "$TURN_PUBLIC_IP" ] && [ -n "$CONTAINER_IP" ]; then
        echo "     IP publique annoncée par coturn : $TURN_PUBLIC_IP (IP du conteneur : $CONTAINER_IP)"
        echo "external-ip=$TURN_PUBLIC_IP/$CONTAINER_IP" >> "$CONFIG_DIR/turnserver.conf"
    else
        echo "     ATTENTION : IP publique introuvable pour coturn. Renseignez la variable PUBLIC_IP."
    fi
    # Autorise le relais TURN -> TURN (deux participants passant tous deux par le relais)
    if [ -n "$CONTAINER_IP" ]; then
        echo "allowed-peer-ip=$CONTAINER_IP" >> "$CONFIG_DIR/turnserver.conf"
    fi
fi

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
if [ "$ENABLE_MATRIX_RTC" = "true" ]; then
echo " MatrixRTC      : $PUBLIC_BASEURL/livekit/jwt/ ($LIVEKIT_PUBLIC_URL)"
echo "                  ports 7881/tcp et 7882/udp"
fi
if [ "$ENABLE_TURN" = "true" ]; then
echo " TURN (coturn)  : ports 3478/udp+tcp et $TURN_MIN_PORT-$TURN_MAX_PORT/udp"
fi
echo "=================================================================="

# Création éventuelle de l'utilisateur initial si défini dans les variables.
# MAS interroge Synapse lors de l'enregistrement : on attend donc que Synapse
# soit démarré par Supervisor, en arrière-plan.
if [ -n "$INITIAL_ADMIN_USER" ] && [ -n "$INITIAL_ADMIN_PASSWORD" ] && [ ! -f "$SECRETS_DIR/.initial_admin_created" ]; then
    (
        until curl -fs http://127.0.0.1:8008/health > /dev/null; do sleep 5; done
        echo "  -> Création du compte administrateur initial ($INITIAL_ADMIN_USER)..."
        mas-cli manage register-user --yes --admin --password "$INITIAL_ADMIN_PASSWORD" "$INITIAL_ADMIN_USER" --config "$CONFIG_DIR/mas.yaml" \
            && touch "$SECRETS_DIR/.initial_admin_created"
    ) &
fi

exec "$@"
