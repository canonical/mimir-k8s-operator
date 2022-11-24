# Copyright 2022 Canonical
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest
from unittest.mock import Mock, PropertyMock, patch

import ops.testing
from ops.model import ActiveStatus, BlockedStatus, Container, WaitingStatus
from ops.pebble import Error as PebbleError
from ops.pebble import PathError
from ops.testing import Harness

from charm import MimirK8SOperatorCharm

ops.testing.SIMULATE_CAN_CONNECT = True


class TestCharm(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("lightkube.core.client.GenericSyncClient")
    def setUp(self, *_):
        self.container_name: str = "mimir"
        self.harness = Harness(MimirK8SOperatorCharm)
        patcher = patch.object(MimirK8SOperatorCharm, "_mimir_version", new_callable=PropertyMock)
        self.mock_version = patcher.start()
        self.mock_version.return_value = "2.4.0"
        self.addCleanup(patcher.stop)
        self.harness.begin()

    @patch("charm.MimirK8SOperatorCharm._current_mimir_config", new_callable=PropertyMock)
    @patch("charm.MimirK8SOperatorCharm._set_alerts", new_callable=Mock)
    def test_pebble_ready_and_config_ok(self, mock_set_alerts, mock_current_mimir_config):
        mock_set_alerts.return_value = True
        mock_current_mimir_config.return_value = {}
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

        self.harness.container_pebble_ready("mimir")
        updated_plan = self.harness.get_container_pebble_plan("mimir").to_dict()
        self.assertEqual(expected_plan, updated_plan)
        service = self.harness.model.unit.get_container("mimir").get_service("mimir")
        self.assertTrue(service.is_running())
        self.assertEqual(self.harness.model.unit.status, ActiveStatus())

    @patch("charm.MimirK8SOperatorCharm._set_alerts", new_callable=Mock)
    def test_set_alerts_error(self, mock_set_alerts):
        mock_set_alerts.side_effect = PebbleError
        self.harness.container_pebble_ready("mimir")
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Failed to push updated alert files; see debug logs"),
        )

    def test_config_changed_cannot_connect(self):
        ops.testing.SIMULATE_CAN_CONNECT = False
        self.harness.update_config({"cpu": "256"})
        self.assertEqual(self.harness.model.unit.status, WaitingStatus("Waiting for Pebble ready"))

    @patch.object(Container, "push")
    @patch("charm.MimirK8SOperatorCharm._current_mimir_config", new_callable=PropertyMock)
    @patch("charm.MimirK8SOperatorCharm._set_alerts", new_callable=Mock)
    def test_mimir_pebble_ready_cannot_push_config(
        self, mock_set_alerts, mock_current_mimir_config, mock_push
    ):
        mock_set_alerts.return_value = True
        mock_current_mimir_config.return_value = {}
        mock_push.side_effect = PathError("kind", "error")

        self.harness.container_pebble_ready("mimir")
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        mock_push.side_effect = Exception()
        self.harness.container_pebble_ready("mimir")
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)
