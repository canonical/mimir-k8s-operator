# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import Mock, PropertyMock

import pytest
from charms.harness_extensions.v0.evt_sequences import Event, Scenario
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from ops.model import BlockedStatus, Container
from ops.pebble import Error as PebbleError
from ops.pebble import PathError

from charm import MimirK8SOperatorCharm


@pytest.fixture(scope="module")
def setup():
    MimirK8SOperatorCharm._mimir_version = PropertyMock(return_value="2.4.0")
    MimirK8SOperatorCharm._current_mimir_config = PropertyMock(return_value={})
    MimirK8SOperatorCharm._set_alerts = Mock(return_value=True)
    KubernetesServicePatch.__init__ = Mock(return_value=None)


def generate_scenario():
    return Scenario.from_events(
        ("install", "config-changed", "start", Event("mimir-pebble-ready", workload=Mock()))
    )(MimirK8SOperatorCharm).play_until_complete()


def test_deploy_ok_scenario(setup):
    expected_plan = {
        "services": {
            "mimir": {
                "override": "replace",
                "summary": "mimir daemon",
                "command": "/bin/mimir --config.file=/etc/mimir/mimir-config.yaml",
                "startup": "enabled",
            }
        },
    }
    cc = generate_scenario()
    assert cc[2].harness.get_container_pebble_plan("mimir").to_dict() == expected_plan
    assert (
        cc[2].harness.model.unit.get_container("mimir").get_service("mimir").is_running() is True
    )
    assert cc[2].harness.charm.unit.status.name == "active"


def test_deploy_and_set_alerts_error_scenario(setup):
    MimirK8SOperatorCharm._set_alerts = Mock(side_effect=PebbleError)
    cc = generate_scenario()
    assert cc[2].harness.charm.unit.status == BlockedStatus(
        "Failed to push updated alert files; see debug logs"
    )


def test_deploy_and_cannot_push_scenario(setup):
    Container.push = Mock(side_effect=PathError("kind", "error"))
    cc = generate_scenario()
    assert cc[2].harness.charm.unit.status.name == "blocked"
