# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from urllib.parse import urljoin

import requests
import yaml

logger = logging.getLogger(__name__)


async def get_unit_address(ops_test, app_name: str, unit_num: int) -> str:
    status = await ops_test.model.get_status()  # noqa: F821
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


async def mimir_endpoint_request(ops_test, app_name: str, endpoint: str, unit_num: int = 0):
    address = await get_unit_address(ops_test, app_name, unit_num)
    url = urljoin(f"http://{address}:9009/", endpoint)
    try:
        response = requests.get(url)
        if response.status_code == 200:
            return response.text
        return ""
    except requests.exceptions.RequestException:
        return ""


def oci_image(metadata_file: str, image_name: str) -> str:
    """Find upstream source for a container image.

    Args:
        metadata_file: string path of metadata YAML file relative
            to top level charm directory
        image_name: OCI container image string name as defined in
            metadata.yaml file
    Returns:
        upstream image source
    Raises:
        FileNotFoundError: if metadata_file path is invalid
        ValueError: if upstream source for image name can not be found
    """
    metadata = yaml.safe_load(Path(metadata_file).read_text())

    resources = metadata.get("resources", {})
    if not resources:
        raise ValueError("No resources found")

    image = resources.get(image_name, {})
    if not image:
        raise ValueError("{} image not found".format(image_name))

    upstream_source = image.get("upstream-source", "")
    if not upstream_source:
        raise ValueError("Upstream source not found")

    return upstream_source
