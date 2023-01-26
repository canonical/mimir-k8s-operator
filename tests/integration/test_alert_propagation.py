#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging
from types import SimpleNamespace

import pytest
from helpers import get_address, oci_image
from pytest_operator.plugin import OpsTest
from workload import Mimir

logger = logging.getLogger(__name__)

mimir = SimpleNamespace(
    name="mimir", resources={"mimir-image": oci_image("./metadata.yaml", "mimir-image")}
)
tester = SimpleNamespace(charm="avalanche-k8s", name="avalanche")


@pytest.mark.abort_on_fail
async def test_deploy_and_relate_charms(ops_test: OpsTest, mimir_charm):
    """Test that Mimir can be related with Prometheus over prometheus_scrape."""
    # Build charm from local source folder
    # mimir_charm = await ops_test.build_charm(".")
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
    )

    await ops_test.model.add_relation(f"{mimir.name}:receive-remote-write", tester.name)
    await ops_test.model.wait_for_idle(status="active")


# TODO wait until target is there


async def test_rules_and_alerts_are_available(ops_test):
    address = await get_address(ops_test, mimir.name, 0)
    client = Mimir(host=address)
    alerts = await client.api_request("/prometheus/api/v1/alerts")
    rules = await client.api_request("/prometheus/api/v1/rules")
    logger.info("alerts: %s", alerts)
    logger.info("rules: %s", rules)
