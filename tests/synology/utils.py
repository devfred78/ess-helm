# Copyright 2026 Element Creations Ltd
#
# SPDX-License-Identifier: AGPL-3.0-only

import os
import socket
import time
import uuid
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from python_on_whales import Container, DockerException, docker

REPO_ROOT = Path(__file__).resolve().parents[2]
SYNOLOGY_DIR = REPO_ROOT / "docker" / "synology"

# Les journaux des conteneurs de test sont écrits ici, à côté de ceux des tests d'intégration
LOGS_DIR = Path("ess-helm-logs") / "synology"

ADMIN_USER = "admin"
ADMIN_PASSWORD = "Synology-Test-Admin-2026!"

# Le premier démarrage (initdb, migrations Synapse et MAS) prend une à deux minutes,
# nettement plus sous émulation (--platform linux/arm64)
STARTUP_TIMEOUT = int(os.environ.get("ESS_SYNOLOGY_STARTUP_TIMEOUT", "600"))

# ESS_SYNOLOGY_KEEP=1 conserve les conteneurs après les tests, pour les inspecter
KEEP_CONTAINERS = os.environ.get("ESS_SYNOLOGY_KEEP", "") == "1"


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@dataclass
class EssContainer:
    container: Container
    # URL publique vue par le conteneur (PUBLIC_BASEURL)
    public_baseurl: str
    # URL utilisée par les tests : 127.0.0.1 plutôt que localhost, que Windows résout d'abord en ::1
    endpoint: str
    server_name: str

    def url(self, path: str) -> str:
        return f"{self.endpoint}{path}"

    def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return httpx.get(self.url(path), timeout=30, **kwargs)

    def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return httpx.post(self.url(path), timeout=30, **kwargs)

    def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return httpx.put(self.url(path), timeout=30, **kwargs)

    def options(self, path: str, **kwargs: Any) -> httpx.Response:
        return httpx.options(self.url(path), timeout=30, **kwargs)

    def exec(self, *command: str) -> str:
        return str(docker.execute(self.container, list(command)))

    def read_file(self, path: str) -> str:
        return self.exec("cat", path)

    def logs(self) -> str:
        return str(docker.logs(self.container))

    def running_commands(self) -> list[str]:
        """Lignes de commande des processus du conteneur (ps n'est pas installé dans l'image)."""
        output = self.exec(
            "sh", "-c", "for f in /proc/[0-9]*/cmdline; do tr '\\0' ' ' < \"$f\" 2>/dev/null; echo; done"
        )
        return [line.strip() for line in output.splitlines() if line.strip()]

    def user_id(self, localpart: str) -> str:
        return f"@{localpart}:{self.server_name}"

    def login(self, user: str = ADMIN_USER, password: str = ADMIN_PASSWORD) -> str:
        """Connexion par mot de passe via l'API de compatibilité de MAS. Renvoie le jeton d'accès.

        MAS limite les tentatives de connexion par IP (rafale de 3 par défaut) : chaque scénario
        doit en faire le moins possible, d'où les fixtures access_token de portée module.
        """
        response = self.post(
            "/_matrix/client/v3/login",
            json={
                "type": "m.login.password",
                "identifier": {"type": "m.id.user", "user": user},
                "password": password,
            },
        )
        response.raise_for_status()
        return response.json()["access_token"]

    def auth_headers(self, access_token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {access_token}"}

    def create_room(self, access_token: str, **content: Any) -> str:
        response = self.post("/_matrix/client/v3/createRoom", json=content, headers=self.auth_headers(access_token))
        response.raise_for_status()
        return response.json()["room_id"]

    def assert_running(self) -> None:
        self.container.reload()
        if not self.container.state.running:
            raise AssertionError(
                f"Le conteneur {self.container.name} s'est arrêté (code {self.container.state.exit_code}).\n"
                f"Journal :\n{tail(self.logs())}"
            )

    def wait_until_ready(self, timeout: float = STARTUP_TIMEOUT) -> None:
        """Attend que Synapse, MAS et Caddy répondent, et que le compte administrateur initial existe."""
        deadline = time.monotonic() + timeout
        last_error: Exception | str = "aucune tentative"
        for check in (self._synapse_ready, self._mas_ready, self._admin_ready):
            while True:
                self.assert_running()
                try:
                    if check():
                        break
                    last_error = f"{check.__name__} : réponse inattendue"
                except httpx.HTTPError as e:
                    last_error = e
                if time.monotonic() > deadline:
                    raise TimeoutError(
                        f"{self.container.name} n'est pas prêt après {timeout} s ({last_error}).\n"
                        f"Journal :\n{tail(self.logs())}"
                    )
                time.sleep(2)

    def _synapse_ready(self) -> bool:
        return self.get("/_matrix/client/versions").status_code == 200

    def _mas_ready(self) -> bool:
        return self.get("/auth/.well-known/openid-configuration").status_code == 200

    def _admin_ready(self) -> bool:
        # Le compte est créé en arrière-plan par l'entrypoint, une fois Synapse démarré. On ne
        # sonde pas par des connexions : MAS les limite à quelques-unes par minute et par IP.
        try:
            self.exec("test", "-f", "/data/secrets/.initial_admin_created")
        except DockerException:
            return False
        return True

    def restart(self) -> None:
        docker.restart(self.container)
        self.wait_until_ready()


def tail(text: str, lines: int = 200) -> str:
    return "\n".join(text.splitlines()[-lines:])


@contextmanager
def run_ess_container(image: str, scenario: str, envs: Mapping[str, str]) -> Iterator[EssContainer]:
    """Démarre le conteneur all-in-one sur un port libre, attend qu'il soit prêt puis le supprime.

    Le volume anonyme /data déclaré par l'image est supprimé avec le conteneur : chaque scénario
    part d'une installation vierge.
    """
    port = free_port()
    public_baseurl = f"http://localhost:{port}"
    container = docker.run(
        image,
        detach=True,
        name=f"ess-synology-test-{scenario}-{uuid.uuid4().hex[:8]}",
        publish=[(f"127.0.0.1:{port}", 8080)],
        envs={
            "SERVER_NAME": "localhost",
            "PUBLIC_BASEURL": public_baseurl,
            "INITIAL_ADMIN_USER": ADMIN_USER,
            "INITIAL_ADMIN_PASSWORD": ADMIN_PASSWORD,
            "TZ": "Europe/Paris",
            **envs,
        },
    )
    ess = EssContainer(container, public_baseurl, f"http://127.0.0.1:{port}", "localhost")
    try:
        ess.wait_until_ready()
        yield ess
    finally:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        (LOGS_DIR / f"{scenario}.log").write_text(ess.logs(), encoding="utf-8")
        if not KEEP_CONTAINERS:
            docker.remove(container, force=True, volumes=True)
