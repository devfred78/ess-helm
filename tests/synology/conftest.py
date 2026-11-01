# Copyright 2026 Element Creations Ltd
#
# SPDX-License-Identifier: AGPL-3.0-only

import os

import pytest
from python_on_whales import DockerException, docker
from python_on_whales.client_config import ClientNotFoundError

from .utils import SYNOLOGY_DIR

# Image à tester (ex : ghcr.io/devfred78/ess-helm/ess-synology:latest). Sans elle, l'image
# est construite depuis docker/synology sous l'étiquette LOCAL_IMAGE_TAG.
IMAGE_ENV_VAR = "ESS_SYNOLOGY_IMAGE"
LOCAL_IMAGE_TAG = "ess-synology:test"


@pytest.fixture(scope="session")
def docker_available() -> None:
    try:
        docker.info()
    except (ClientNotFoundError, DockerException) as e:
        pytest.skip(f"Docker n'est pas disponible ({type(e).__name__}) : démarrez Docker Desktop")


@pytest.fixture(scope="session")
def ess_image(docker_available) -> str:
    image = os.environ.get(IMAGE_ENV_VAR)
    if image:
        if not docker.image.exists(image):
            docker.pull(image)
        return image

    docker.build(SYNOLOGY_DIR, tags=[LOCAL_IMAGE_TAG], load=True)
    return LOCAL_IMAGE_TAG
