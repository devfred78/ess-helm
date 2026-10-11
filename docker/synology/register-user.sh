#!/bin/bash
set -e

# ==============================================================================
# Helper Script for creating/registering users in MAS (Synology Docker)
# ==============================================================================

CONFIG_FILE="/data/config/mas.yaml"

if [ ! -f "$CONFIG_FILE" ]; then
    echo "Erreur : Le fichier de configuration $CONFIG_FILE n'existe pas encore."
    exit 1
fi

echo "=== Enregistrement d'un utilisateur Matrix dans Element Server Suite ==="
mas-cli manage register-user --config "$CONFIG_FILE" "$@"
