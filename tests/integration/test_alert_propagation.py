#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest
import pytimeparse
import yaml
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


@pytest.mark.abort_on_fail
async def test_rules_are_loaded(ops_test):
    address = await get_address(ops_test, mimir.name, 0)
    client = Mimir(host=address)

    rules = json.loads(await client.api_request("/prometheus/api/v1/rules"))
    # Response looks like this:
    # {"status":"success","data":{"groups":[{"name":"test-alert-propagation-...
    assert len(rules["data"]["groups"]) > 0

    groups = yaml.safe_load(await client.api_request("/ruler/rule_groups"))
    # Response looks like this:
    # anonymous:
    #     juju_test-alert-propagation-nxl2_0badd9d0_avalanche-k8s.rules:
    #         - name: test-alert-propagation-...
    #           rules:
    #             - alert: AlwaysFiringDueToNumericValue
    #               expr: avalanche_metric_mmmmm_0_0...
    assert set(groups["anonymous"]) > set()


@pytest.mark.abort_on_fail
async def test_alerts_are_fired(ops_test):
    address = await get_address(ops_test, mimir.name, 0)
    client = Mimir(host=address)

    # Get evaluation interval (default is '1m0s')
    config = yaml.safe_load(await client.api_request("/config"))
    eval_interval = pytimeparse.parse(config["ruler"]["evaluation_interval"])
    logger.info("Waiting for mimir's rule evaluation interval to elapse...")
    await asyncio.sleep(eval_interval + 10)

    alerts = json.loads(await client.api_request("/prometheus/api/v1/alerts"))
    # Response looks like this (after a while; at the very beginning the list is empty):
    # {"status":"success","data":{"alerts":
    # [{"labels":{"alertname":"AlwaysFiringDueToAbsentMetric","job":"non_existing_job",...
    assert len(alerts) > 0
