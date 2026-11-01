# Copyright 2026 Element Creations Ltd
#
# SPDX-License-Identifier: AGPL-3.0-only

# Conteneur lancé comme avec docker-compose.dev.yml : appels audio/vidéo désactivés.

import base64
import json
import re
import uuid

import pytest

from .utils import ADMIN_USER, run_ess_container


@pytest.fixture(scope="module")
def ess(ess_image):
    with run_ess_container(ess_image, "default", {"ENABLE_MATRIX_RTC": "false", "ENABLE_TURN": "false"}) as ess:
        yield ess


@pytest.fixture(scope="module")
def access_token(ess):
    return ess.login()


def test_client_versions(ess):
    response = ess.get("/_matrix/client/versions")
    assert response.status_code == 200
    assert "v1.11" in response.json()["versions"]


def test_well_known_server(ess):
    response = ess.get("/.well-known/matrix/server")
    assert response.headers["content-type"] == "application/json"
    assert response.json() == {"m.server": "localhost:443"}


def test_well_known_client(ess):
    well_known = ess.get("/.well-known/matrix/client").json()
    assert well_known["m.homeserver"]["base_url"] == ess.public_baseurl
    assert well_known["org.matrix.msc2965.authentication"] == {
        "issuer": f"{ess.public_baseurl}/auth/",
        "account": f"{ess.public_baseurl}/auth/account",
    }
    assert "org.matrix.msc4143.rtc_foci" not in well_known


@pytest.mark.parametrize("path", ["/.well-known/openid-configuration", "/auth/.well-known/openid-configuration"])
def test_mas_openid_configuration(ess, path):
    configuration = ess.get(path).json()
    assert configuration["issuer"] == f"{ess.public_baseurl}/auth/"
    assert configuration["authorization_endpoint"].startswith(f"{ess.public_baseurl}/auth/")


def test_synapse_delegates_authentication_to_mas(ess):
    response = ess.get("/_matrix/client/v1/auth_metadata")
    assert response.status_code == 200
    assert response.json()["issuer"] == f"{ess.public_baseurl}/auth/"


def test_cors_headers_are_not_duplicated(ess):
    # Synapse envoie ses propres en-têtes CORS : Caddy ne doit pas en ajouter un second
    response = ess.get("/_matrix/client/versions", headers={"Origin": "https://app.element.io"})
    assert response.headers.get_list("access-control-allow-origin") == ["*"]


def test_element_web(ess):
    response = ess.get("/")
    assert response.status_code == 200
    assert "<title>Element</title>" in response.text


def test_element_web_config(ess):
    config = ess.get("/config.json").json()
    assert config["default_server_config"]["m.homeserver"] == {
        "base_url": ess.public_baseurl,
        "server_name": "localhost",
    }
    assert config["element_call"]["use_exclusively"] is False


def element_admin_config(index_html: str) -> dict:
    encoded = re.search(r'window\.APP_CONFIG_BASE64 = "([^"]*)"', index_html)
    assert encoded, "Configuration d'Element Admin introuvable dans l'index"
    return json.loads(base64.b64decode(encoded.group(1)))


@pytest.mark.parametrize("path", ["/", "/callback", "/users"])
def test_element_admin_index(ess, path):
    # Element Admin est servi à la racine du port 8088 ; ses routes (dont le retour de connexion
    # /callback) sont gérées par l'application et renvoient toutes l'index
    response = ess.get_admin(path)
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache"
    assert element_admin_config(response.text) == {"serverName": "localhost"}


def test_element_admin_assets(ess):
    index = ess.get_admin("/").text
    assets = re.findall(r'<(?:script|link)[^>]+(?:src|href)="(/assets/[^"]+)"', index)
    assert assets
    for path in assets:
        asset = ess.get_admin(path)
        assert asset.status_code == 200, path
        # Un repli vers l'index renverrait du HTML à la place
        expected = "text/css" if path.endswith(".css") else "javascript"
        assert expected in asset.headers["content-type"], path
        assert "immutable" in asset.headers["cache-control"], path


def test_admin_path_redirects_to_admin_port(ess):
    # Sans ADMIN_BASEURL, l'entrypoint reprend le nom d'hôte de PUBLIC_BASEURL (HTTP : port 8088)
    response = ess.get("/admin/")
    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:8088/"


def test_well_known_client_allows_element_admin_origin(ess):
    # Element Admin, servi sur un autre port, lit ce fichier depuis le navigateur
    response = ess.get("/.well-known/matrix/client", headers={"Origin": "https://matrix.example.com:8443"})
    assert response.headers.get_list("access-control-allow-origin") == ["*"]


def test_mas_accepts_element_admin_registration(ess):
    # Enregistrement dynamique effectué par Element Admin à la connexion, depuis son origine
    # publique sur le NAS (proxy inversé HTTPS de DSM vers le port 8088)
    origin = "https://matrix.example.com:8443"
    response = ess.post(
        "/auth/oauth2/registration",
        json={
            "application_type": "web",
            "client_name": "Element Admin",
            "client_uri": f"{origin}/",
            "redirect_uris": [f"{origin}/callback"],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["client_id"]


def test_initial_admin_is_admin(ess, access_token):
    whoami = ess.get("/_matrix/client/v3/account/whoami", headers=ess.auth_headers(access_token)).json()
    assert whoami["user_id"] == ess.user_id(ADMIN_USER)
    assert ess.exec("test", "-f", "/data/secrets/.initial_admin_created") == ""


def test_wrong_password_is_rejected(ess):
    response = ess.post(
        "/_matrix/client/v3/login",
        json={"type": "m.login.password", "identifier": {"type": "m.id.user", "user": ADMIN_USER}, "password": "x"},
    )
    assert response.status_code == 403


def test_registration_is_disabled(ess):
    response = ess.post("/_matrix/client/v3/register", json={"username": "intruder", "password": "x"})
    assert response.status_code in (403, 404)


def test_send_and_read_message(ess, access_token):
    headers = ess.auth_headers(access_token)
    room_id = ess.create_room(access_token, name="Test Synology")
    body = f"Bonjour depuis pytest {uuid.uuid4()}"
    response = ess.put(
        f"/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{uuid.uuid4()}",
        json={"msgtype": "m.text", "body": body},
        headers=headers,
    )
    assert response.status_code == 200

    messages = ess.get(f"/_matrix/client/v3/rooms/{room_id}/messages", params={"dir": "b"}, headers=headers).json()
    assert body in [event["content"].get("body") for event in messages["chunk"]]


def test_register_user_script(ess):
    # Commande documentée dans le guide (Option A de la gestion des utilisateurs)
    ess.exec("register-user", "--yes", "--password", "Alice-Test-Password-2026!", "alice")
    access_token = ess.login("alice", "Alice-Test-Password-2026!")
    whoami = ess.get("/_matrix/client/v3/account/whoami", headers=ess.auth_headers(access_token)).json()
    assert whoami["user_id"] == ess.user_id("alice")


def test_call_services_are_not_started(ess):
    commands = " | ".join(ess.running_commands())
    for service in ("postgres -D /data/postgres", "synapse.app.homeserver", "mas-cli server", "caddy run"):
        assert service in commands
    for service in ("livekit-server", "lk-jwt-service", "turnserver"):
        assert service not in commands


def test_call_configuration_is_absent(ess):
    homeserver = ess.read_file("/data/config/homeserver.yaml")
    assert "matrix_rtc:" not in homeserver
    assert "turn_uris:" not in homeserver


# Dernier test du module : il redémarre le conteneur partagé par les tests précédents
def test_data_persists_across_restart(ess, access_token):
    secrets = {
        name: ess.read_file(f"/data/secrets/{name}")
        for name in ("synapse.signing.key", "mas_encryption_secret", "postgres_password", "mas-rsa.key")
    }
    room_id = ess.create_room(access_token, name="Avant redémarrage")

    ess.restart()

    for name, content in secrets.items():
        assert ess.read_file(f"/data/secrets/{name}") == content, name
    # L'ancien jeton reste valide : les sessions sont stockées dans PostgreSQL
    joined = ess.get("/_matrix/client/v3/joined_rooms", headers=ess.auth_headers(access_token)).json()
    assert room_id in joined["joined_rooms"]
    # Le compte administrateur n'est pas recréé au second démarrage
    assert ess.logs().count("Création du compte administrateur initial") == 1
