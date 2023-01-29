#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from types import SimpleNamespace

import pytest
import yaml
from helpers import get_address, oci_image
from pytest_operator.plugin import OpsTest
from workload import Mimir

logger = logging.getLogger(__name__)

mimir = SimpleNamespace(
    name="mimir", resources={"mimir-image": oci_image("./metadata.yaml", "mimir-image")}
)
tester = SimpleNamespace(charm="avalanche-k8s", name="avalanche")
storage = SimpleNamespace(charm="s3proxy-k8s", name="s3proxy")


@pytest.mark.abort_on_fail
async def test_deploy_and_relate_charms(ops_test: OpsTest, mimir_charm):
    """Build up the model for verification."""
    await asyncio.gather(
        ops_test.model.deploy(
            mimir_charm,
            resources=mimir.resources,
            application_name=mimir.name,
            trust=True,
        ),
        ops_test.model.deploy(
            tester.charm,
            application_name=tester.name,
            channel="edge",
        ),
        ops_test.model.deploy(storage.charm, application_name=storage.name, channel="edge"),
    )

    await asyncio.gather(
        ops_test.model.add_relation(f"{mimir.name}:receive-remote-write", tester.name),
        ops_test.model.add_relation(f"{mimir.name}:s3", storage.name),
    )
    await ops_test.model.wait_for_idle(
        status="active", apps=[mimir.name, tester.name, storage.name]
    )


@pytest.mark.abort_on_fail
async def test_object_storage_propagates(ops_test):
    address = await get_address(ops_test, mimir.name, 0)
    client = Mimir(host=address)

    logger.info("Waiting for avalanche to push.")
    await asyncio.sleep(75)
    config = yaml.safe_load(await client.api_request("/config"))
    assert "s3" in config["common"]["storage"]["backend"]

    labels = await client.api_request("/prometheus/api/v1/labels", response_type="json")
    assert labels["data"] != []
