#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""A Juju Charmed Operator for Mimir."""

import hashlib
import logging
import os
import re
import socket
from typing import Optional

import yaml
from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider
from charms.observability_libs.v0.juju_topology import JujuTopology
from charms.observability_libs.v1.kubernetes_service_patch import (
    KubernetesServicePatch,
    ServicePort,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import PrometheusRemoteWriteProvider
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import Error as PebbleError
from ops.pebble import Layer, PathError, ProtocolError

MIMIR_CONFIG = "/etc/mimir/mimir-config.yaml"
MIMIR_DIR = "/mimir"

# Ruler dirs cannot overlap, otherwise mimir complains:
# error validating config: the configured ruler data directory "/mimir/rules" cannot overlap with
# the configured ruler storage local directory "/mimir/rules"; please set different paths, also
# ensuring one is not a subdirectory of the other one
RULER_STORAGE_DIR = f"{MIMIR_DIR}/ruler_storage"
RULER_DATA_DIR = f"{MIMIR_DIR}/ruler_data"

# Not storing under `/mimir` because that path is persistent storage (see metadata.yaml)
ALERTS_HASH_PATH = "/etc/mimir/alerts.sha256"

logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


class MimirK8SOperatorCharm(CharmBase):
    """A Juju Charmed Operator for Mimir."""

    _name = "mimir"
    _http_listen_port = 9009
    _instance_addr = "127.0.0.1"

    def __init__(self, *args):
        super().__init__(*args)
        self._container = self.unit.get_container(self._name)

        self.topology = JujuTopology.from_charm(self)

        self.service_patch = KubernetesServicePatch(
            self, [ServicePort(self._http_listen_port, name=self.app.name)]
        )

        self.metrics_provider = MetricsEndpointProvider(
            self,
            jobs=[
                {
                    "static_configs": [
                        {
                            "targets": [f"*:{self._http_listen_port}"],
                            "labels": {
                                "cluster": self.topology.model_uuid,
                                "namespace": self.topology.model,
                                "job": f"{self.topology.model}/mimir",
                                "pod": self.topology.unit,
                            },
                        }
                    ],
                    "scrape_interval": "15s",
                }
            ],
        )

        self.remote_write_provider = PrometheusRemoteWriteProvider(
            charm=self,
            endpoint_address=self.hostname,
            endpoint_port=self._http_listen_port,
            endpoint_path="/api/v1/push",
        )

        self.grafana_source_provider = GrafanaSourceProvider(
            charm=self,
            source_type="mimir",
            source_port="9009",
        )

        self.framework.observe(self.on.mimir_pebble_ready, self._on_mimir_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.stop, self._on_stop)

    def _on_mimir_pebble_ready(self, event):
        self._set_mimir_version()
        self._configure(event)

    def _on_config_changed(self, event):
        self._configure(event)

    def _on_stop(self, _):
        # Clear the workload version in case something's wrong after an upgrade.
        self.unit.set_workload_version("")

    def _configure(self, event):
        if not self._container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble ready")
            return

        try:
            restart = any(
                [
                    self._set_alerts(),
                    self._set_mimir_config(),
                    self._set_pebble_layer(),
                ]
            )
        except BlockedStatusError as e:
            self.unit.status = BlockedStatus(e.message)
            return

        if restart:
            self._container.restart(self._name)
            logger.info("Mimir (re)started")

        self.remote_write_provider.update_endpoint()
        self.unit.status = ActiveStatus()

    def _set_mimir_version(self) -> bool:
        version = self._mimir_version

        if version is None:
            logger.debug("Cannot set workload version at this time: could not get Mimir version.")
            return False

        self.unit.set_workload_version(version)
        return True

    def _set_pebble_layer(self) -> bool:
        """Set Pebble layer.

        Returns: True if Pebble layer was added, otherwise False.
        """
        current_layer = self._container.get_plan()
        new_layer = self._pebble_layer

        if (
            "services" not in current_layer.to_dict()
            or current_layer.services != new_layer.services
        ):
            self._container.add_layer(self._name, new_layer, combine=True)
            return True

        return False

    def _set_mimir_config(self) -> bool:
        """Set Mimir config.

        Returns: True if config have changed, otherwise False.
        Raises: BlockedStatusError exception if PebbleError, ProtocolError, PathError exceptions
            are raised by container.remove_path
        """
        config = self._mimir_config

        try:
            if self._current_mimir_config != config:
                config_as_yaml = yaml.safe_dump(config)
                self._container.push(MIMIR_CONFIG, config_as_yaml, make_dirs=True)
                logger.info("Pushed new Mimir configuration")
                return True

            return False
        except (ProtocolError, Exception) as e:
            logger.error("Failed to push updated config file: %s", e)
            raise BlockedStatusError(str(e))

    def _set_alerts(self) -> bool:
        """Create alert rule files for all Mimir consumers.

        Returns: True if alerts rules have changed, otherwise False.
        Raises: BlockedStatusError exception if PebbleError, ProtocolError, PathError exceptions
            are raised by container.remove_path
        """
        remote_write_alerts = self.remote_write_provider.alerts()
        alerts_hash = sha256(str(remote_write_alerts))
        alert_rules_changed = alerts_hash != self._pull(ALERTS_HASH_PATH)

        if alert_rules_changed:
            self._container.remove_path(RULER_STORAGE_DIR, recursive=True)
            self._push_alert_rules(remote_write_alerts)
            self._push(ALERTS_HASH_PATH, alerts_hash)

        return alert_rules_changed

    def _push_alert_rules(self, alerts):
        """Push alert rules from a rules file to the mimir container.

        Args:
            alerts: a dictionary of alert rule files.
        """
        # Without multitenancy, the default is `anonymous`, and the ruler checks under
        # {RULES_DIR}/<tenant_id>
        tenant_dir = f"{RULER_STORAGE_DIR}/anonymous"
        for topology_identifier, rules_file in alerts.items():
            filename = f"juju_{topology_identifier}.rules"
            path = os.path.join(tenant_dir, filename)
            rules = yaml.safe_dump(rules_file)
            self._push(path, rules)
            logger.debug("Updated alert rules file %s/%s", path, filename)

    @property
    def _pebble_layer(self):
        return Layer(
            {
                "summary": "mimir layer",
                "description": "pebble config layer for mimir",
                "services": {
                    "mimir": {
                        "override": "replace",
                        "summary": "mimir daemon",
                        "command": f"/bin/mimir --config.file={MIMIR_CONFIG}",
                        "startup": "enabled",
                    }
                },
            }
        )

    @property
    def _mimir_config(self) -> dict:
        return {
            "multitenancy_enabled": False,
            "blocks_storage": {
                "backend": "filesystem",
                "bucket_store": {
                    "sync_dir": f"{MIMIR_DIR}/tsdb-sync",
                },
                "filesystem": {
                    "dir": f"{MIMIR_DIR}/data/tsdb",
                },
                "tsdb": {
                    "dir": f"{MIMIR_DIR}/tsdb",
                },
            },
            "compactor": {
                "data_dir": f"{MIMIR_DIR}/compactor",
                "sharding_ring": {"kvstore": {"store": "memberlist"}},
            },
            "distributor": {
                "ring": {
                    "instance_addr": f"{self._instance_addr}",
                    "kvstore": {"store": "memberlist"},
                }
            },
            "ingester": {
                "ring": {
                    "instance_addr": f"{self._instance_addr}",
                    "kvstore": {"store": "memberlist"},
                    "replication_factor": 1,
                }
            },
            # "ruler": {
            #     "rule_path": RULER_DATA_DIR,
            # },
            "ruler_storage": {
                "backend": "local",
                "local": {
                    "directory": RULER_STORAGE_DIR,
                },
            },
            "server": {
                "http_listen_port": self._http_listen_port,
                "log_level": "error",
            },
            "store_gateway": {
                "sharding_ring": {"replication_factor": 1},
            },
        }

    @property
    def _current_mimir_config(self) -> dict:
        if not self._container.can_connect():
            logger.debug("Could not connect to Mimir container")
            return {}

        try:
            raw_current = self._container.pull(MIMIR_CONFIG).read()
            return yaml.safe_load(raw_current)
        except (ProtocolError, PathError) as e:
            logger.warning(
                "Could not check the current Mimir configuration due to "
                "a failure in retrieving the file: %s",
                e,
            )
            return {}

    @property
    def _mimir_version(self) -> Optional[str]:
        if not self._container.can_connect():
            return None

        version_output, _ = self._container.exec(["/bin/mimir", "-version"]).wait_output()
        # Output looks like this:
        # Mimir, version 2.4.0 (branch: HEAD, revision: 32137ee)
        if result := re.search(r"[Vv]ersion:?\s*(\S+)", version_output):
            return result.group(1)
        return None

    @property
    def hostname(self) -> str:
        """Unit's hostname."""
        return socket.getfqdn()

    def _pull(self, path) -> Optional[str]:
        """Pull file from container (without raising pebble errors).

        Returns:
            File contents if exists; None otherwise.
        """
        try:
            return self._container.pull(path, encoding="utf-8").read()
        except (FileNotFoundError, PebbleError):
            # Drop FileNotFoundError https://github.com/canonical/operator/issues/896
            return None

    def _push(self, path, contents):
        """Push file to container, creating subdirs as necessary."""
        self._container.push(path, contents, make_dirs=True, encoding="utf-8")


class BlockedStatusError(Exception):
    """Raised if there is an error that should set BlockedStatus."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(self.message)


if __name__ == "__main__":  # pragma: nocover
    main(MimirK8SOperatorCharm)
