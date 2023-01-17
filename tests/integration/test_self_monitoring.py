#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
import requests
from helpers import get_unit_address, mimir_endpoint_request, oci_image

logger = logging.getLogger(__name__)

MIMIR = "mimir"
PROMETHEUS = "prometheus"


@pytest.mark.abort_on_fail
async def test_deploy_and_relate_charms(ops_test, mimir_charm):
    """Test that Mimir can be related with Prometheus over prometheus_scrape."""
    await asyncio.gather(
        ops_test.model.deploy(
            mimir_charm,
            resources={"mimir-image": oci_image("./metadata.yaml", "mimir-image")},
            application_name=MIMIR,
            trust=True,
        ),
        ops_test.model.deploy(
            "prometheus-k8s",
            application_name=PROMETHEUS,
            channel="edge",
            trust=True,
        ),
    )

    await ops_test.model.add_relation(MIMIR, f"{PROMETHEUS}:metrics-endpoint")
    apps = [MIMIR, PROMETHEUS]
    await ops_test.model.wait_for_idle(apps=apps, status="active")


async def test_metrics_are_available(ops_test):
    metrics = await mimir_endpoint_request(ops_test, MIMIR, "metrics", 0)
    assert len(metrics) > 0


async def test_query_metrics_from_prometheus(ops_test):
    address = await get_unit_address(ops_test, PROMETHEUS, 0)
    url = f"http://{address}:9090/api/v1/query"
    params = {"query": f"up{{juju_application='{MIMIR}'}}"}
    try:
        response = requests.get(url, params=params)
        assert response.json()["status"] == "success"
    except requests.exceptions.RequestException:
        assert False
