# Copyright 2026 Element Creations Ltd
#
# SPDX-License-Identifier: AGPL-3.0-only

# Conteneur lancé comme sur le NAS : Element Call (MatrixRTC) et TURN activés.
# Les flux audio/vidéo ne sont pas testés (ils nécessitent une IP publique joignable) :
# on vérifie la configuration, la signalisation et la délivrance des jetons.

import pytest

from .utils import run_ess_container

# Adresse de documentation (RFC 5737) : évite toute découverte de l'IP publique par STUN
PUBLIC_IP = "203.0.113.10"

# Synapse relaie ces endpoints vers le MatrixRTC Authorisation Service (MSC4512)
PROXIED_MATRIX_RTC_PATH = "/_matrix/client/unstable/io.element.msc4195/rtc/livekit"


@pytest.fixture(scope="module")
def ess(ess_image):
    envs = {"ENABLE_MATRIX_RTC": "true", "ENABLE_TURN": "true", "PUBLIC_IP": PUBLIC_IP}
    with run_ess_container(ess_image, "calls", envs) as ess:
        yield ess


@pytest.fixture(scope="module")
def access_token(ess):
    return ess.login()


@pytest.fixture(scope="module")
def livekit_public_url(ess):
    return f"wss://{ess.public_baseurl.removeprefix('http://')}/livekit/sfu"


def test_well_known_client_declares_rtc_foci(ess):
    well_known = ess.get("/.well-known/matrix/client").json()
    assert well_known["org.matrix.msc4143.rtc_foci"] == [
        {"type": "livekit", "livekit_service_url": f"{ess.public_baseurl}/livekit/jwt"}
    ]


def test_element_web_uses_element_call(ess):
    assert ess.get("/config.json").json()["element_call"]["use_exclusively"] is True


def test_call_services_are_running(ess):
    commands = " | ".join(ess.running_commands())
    for service in ("livekit-server", "lk-jwt-service", "turnserver"):
        assert service in commands


def test_lk_jwt_service_health(ess):
    assert ess.get("/livekit/jwt/healthz").status_code == 200


def test_livekit_sfu(ess):
    response = ess.get("/livekit/sfu/")
    assert response.status_code == 200
    assert response.text.strip() == "OK"


def test_lk_jwt_service_cors_preflight(ess):
    # Régression : des en-têtes CORS en double empêchaient Element X d'obtenir son jeton LiveKit
    response = ess.options(
        "/livekit/jwt/sfu/get",
        headers={
            "Origin": "https://call.element.io",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert response.status_code < 300
    assert response.headers.get_list("access-control-allow-origin") == ["*"]


# La délivrance complète d'un jeton LiveKit n'est pas testable localement : lk-jwt-service
# rappelle le serveur par son adresse publique, pour valider le jeton OpenID (fédération, port 443
# ou 8448) et pour créer la salle sur le SFU (LIVEKIT_URL en wss://). Sur le NAS, ces requêtes
# ressortent vers la box, qui les renvoie au conteneur (NAT loopback) ; en local, rien n'écoute
# sur ces adresses. On vérifie donc la chaîne Synapse -> lk-jwt-service jusqu'au contrôle
# d'appartenance au salon, qui précède ces appels.
def test_livekit_jwt_through_synapse_checks_membership(ess, access_token, livekit_public_url):
    request = {
        "url": livekit_public_url,
        "room_id": f"!not-joined:{ess.server_name}",
        "slot_id": "m.call#ROOM",
        "member_id": "pytest-member",
    }
    # Synapse authentifie l'utilisateur et relaie la requête (MSC4512) ; le service vérifie
    # avec son as_token que l'utilisateur est membre du salon (MSC4502)
    response = ess.post(f"{PROXIED_MATRIX_RTC_PATH}/get_token", json=request, headers=ess.auth_headers(access_token))
    assert response.status_code == 403, response.text


def test_livekit_jwt_requires_authentication(ess, livekit_public_url):
    request = {"url": livekit_public_url, "room_id": f"!room:{ess.server_name}", "slot_id": "m.call#ROOM"}
    assert ess.post(f"{PROXIED_MATRIX_RTC_PATH}/get_token", json=request).status_code == 401


def test_turn_credentials(ess, access_token):
    turn = ess.get("/_matrix/client/v3/voip/turnServer", headers=ess.auth_headers(access_token)).json()
    assert turn["uris"] == ["turn:localhost:3478?transport=udp", "turn:localhost:3478?transport=tcp"]
    assert turn["username"]
    assert turn["password"]
    assert turn["ttl"] == 3600


def test_public_ip_is_announced(ess):
    assert f"external-ip={PUBLIC_IP}/" in ess.read_file("/data/config/turnserver.conf")
    livekit = ess.read_file("/data/config/livekit.yaml")
    assert "use_external_ip: false" in livekit
    assert f'node_ip: "{PUBLIC_IP}"' in livekit
