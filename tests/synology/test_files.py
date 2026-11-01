# Copyright 2026 Element Creations Ltd
#
# SPDX-License-Identifier: AGPL-3.0-only

# Vérifications statiques des fichiers de docker/synology : elles ne nécessitent pas Docker
# et détectent avant la construction de l'image les erreurs qui empêcheraient le conteneur de démarrer.

import re
from urllib.parse import urlparse

import pytest
import yaml

from .utils import SYNOLOGY_DIR

TEMPLATES = sorted([*SYNOLOGY_DIR.glob("*.template"), SYNOLOGY_DIR / "Caddyfile"])
COPIED_FILES = sorted(p for p in SYNOLOGY_DIR.iterdir() if p.is_file() and not p.name.startswith("docker-compose"))


def entrypoint_variables() -> set[str]:
    """Variables d'environnement visibles par envsubst et Supervisor : ENV de l'image et exports de l'entrypoint."""
    dockerfile = (SYNOLOGY_DIR / "Dockerfile").read_text(encoding="utf-8")
    env_block = re.search(r"^ENV (.*?)(?<!\\)\n", dockerfile, re.MULTILINE | re.DOTALL)
    assert env_block, "Bloc ENV introuvable dans le Dockerfile"
    variables = set(re.findall(r"\b([A-Z_][A-Z0-9_]*)=", env_block.group(1)))
    entrypoint = (SYNOLOGY_DIR / "entrypoint.sh").read_text(encoding="utf-8")
    variables |= set(re.findall(r"^\s*export ([A-Z_][A-Z0-9_]*)", entrypoint, re.MULTILINE))
    return variables


@pytest.mark.parametrize("path", COPIED_FILES, ids=lambda p: p.name)
def test_files_use_lf_line_endings(path):
    # Un retour chariot casse l'entrypoint (« /bin/bash^M: bad interpreter ») et les templates
    assert b"\r" not in path.read_bytes(), f"{path.name} contient des fins de ligne CRLF (voir .gitattributes)"


@pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
def test_template_variables_are_defined(path):
    # envsubst remplace silencieusement une variable inconnue par une chaîne vide.
    # Les commentaires sont ignorés : celui du Caddyfile cite la syntaxe ${VAR}.
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith("#")]
    used = set(re.findall(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", "\n".join(lines)))
    assert used - entrypoint_variables() == set()


def test_supervisord_variables_are_defined():
    # Supervisor refuse de démarrer si une variable %(ENV_X)s n'existe pas
    supervisord = (SYNOLOGY_DIR / "supervisord.conf").read_text(encoding="utf-8")
    used = set(re.findall(r"%\(ENV_([A-Za-z0-9_]+)\)s", supervisord))
    assert used - entrypoint_variables() == set()


def test_dockerfile_copies_every_template():
    dockerfile = (SYNOLOGY_DIR / "Dockerfile").read_text(encoding="utf-8")
    copied = set(re.findall(r"^COPY (?!--from)(\S+)", dockerfile, re.MULTILINE))
    for source in copied:
        assert (SYNOLOGY_DIR / source).is_file(), f"COPY {source} : fichier absent de docker/synology"
    entrypoint = (SYNOLOGY_DIR / "entrypoint.sh").read_text(encoding="utf-8")
    for template in SYNOLOGY_DIR.glob("*.template"):
        assert template.name in copied, f"{template.name} n'est pas copié dans l'image"
        assert f"/templates/{template.name}" in entrypoint, f"{template.name} n'est pas utilisé par l'entrypoint"


@pytest.mark.parametrize(
    "path",
    [*SYNOLOGY_DIR.glob("*.yaml.template"), *SYNOLOGY_DIR.glob("docker-compose*.yml")],
    ids=lambda p: p.name,
)
def test_yaml_files_parse(path):
    # Les valeurs ${VAR} sont entre guillemets ou scalaires : le template brut reste du YAML valide
    assert yaml.safe_load(path.read_text(encoding="utf-8")) is not None


def test_dev_compose_publishes_the_port_of_public_baseurl():
    # Le guide demande de modifier les deux ensemble si le port 8080 est déjà pris
    service = yaml.safe_load((SYNOLOGY_DIR / "docker-compose.dev.yml").read_text(encoding="utf-8"))["services"][
        "ess-community"
    ]
    env = dict(item.split("=", 1) for item in service["environment"])
    host_ports = [int(mapping.split(":")[0]) for mapping in service["ports"] if mapping.endswith(":8080")]
    assert host_ports == [urlparse(env["PUBLIC_BASEURL"]).port]
