# Copyright 2022 jose
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


class TestCharm(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @patch("lightkube.core.client.GenericSyncClient")
    def setUp(self, *_):
        ops.testing.SIMULATE_CAN_CONNECT = True

        self.addCleanup(setattr, ops.testing, "SIMULATE_CAN_CONNECT", False)
        self.container_name: str = "mimir"
        self.harness = Harness(MimirK8SOperatorCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("charm.MimirK8SOperatorCharm._current_mimir_config", new_callable=PropertyMock)
    @patch("charm.MimirK8SOperatorCharm._set_alerts", new_callable=Mock)
    @patch("charm.MimirK8SOperatorCharm._mimir_version", new_callable=PropertyMock)
    def test_pebble_ready_and_config_ok(
        self, mock_version, mock_set_alerts, mock_current_mimir_config
    ):
        mock_version.return_value = "2.4.0"
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
    @patch("charm.MimirK8SOperatorCharm._mimir_version", new_callable=PropertyMock)
    def test_set_alerts_error(self, mock_version, mock_set_alerts):
        mock_version.return_value = "2.4.0"
        mock_set_alerts.side_effect = PebbleError
        self.harness.container_pebble_ready("mimir")
        self.assertEqual(
            self.harness.model.unit.status,
            BlockedStatus("Failed to push updated alert files; see debug logs"),
        )

    @patch("charm.MimirK8SOperatorCharm._mimir_version", new_callable=PropertyMock)
    def test_mimir_pebble_ready_cannot_connect(self, mock_version):
        mock_version.return_value = "2.4.0"
        ops.testing.SIMULATE_CAN_CONNECT = False
        self.harness.container_pebble_ready("mimir")
        self.assertEqual(self.harness.model.unit.status, WaitingStatus("Waiting for Pebble ready"))

    @patch.object(Container, "push")
    @patch("charm.MimirK8SOperatorCharm._current_mimir_config", new_callable=PropertyMock)
    @patch("charm.MimirK8SOperatorCharm._set_alerts", new_callable=Mock)
    @patch("charm.MimirK8SOperatorCharm._mimir_version", new_callable=PropertyMock)
    def test_mimir_pebble_ready_cannot_push_config(
        self, mock_version, mock_set_alerts, mock_current_mimir_config, mock_push
    ):
        mock_version.return_value = "2.4.0"
        mock_set_alerts.return_value = True
        mock_current_mimir_config.return_value = {}
        mock_push.side_effect = PathError("kind", "error")

        self.harness.container_pebble_ready("mimir")
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        mock_push.side_effect = Exception()
        self.harness.container_pebble_ready("mimir")
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)
