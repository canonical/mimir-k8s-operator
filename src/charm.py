#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more at: https://juju.is/docs/sdk

"""Charm the service.

Refer to the following post for a quick-start guide that will help you
develop a new k8s charm using the Operator Framework:

    https://discourse.charmhub.io/t/4208
"""

import hashlib
import logging
import os
import socket
from typing import Optional

import yaml
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    DEFAULT_RELATION_NAME as DEFAULT_REMOTE_WRITE_RELATION_NAME,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import PrometheusRemoteWriteProvider
from deepdiff import DeepDiff  # type: ignore
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import Error as PebbleError
from ops.pebble import PathError, ProtocolError
from parse import search  # type: ignore

MIMIR_CONFIG = "/etc/mimir/mimir-config.yaml"
MIMIR_DIR = "/mimir"
RULES_DIR = f"{os.path.join(MIMIR_DIR, 'rules')}"

logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


class MimirK8SOperatorCharm(CharmBase):
    """Charm the service."""

    _name = "mimir"
    _http_listen_port = 9009
    _instance_addr = "127.0.0.1"
    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)
        self._stored.set_default(alerts_hash=None)
        self._container = self.unit.get_container(self._name)

        self.service_patch = KubernetesServicePatch(
            self, [(self.app.name, self._http_listen_port)]
        )

        self.remote_write_provider = PrometheusRemoteWriteProvider(
            charm=self,
            relation_name=DEFAULT_REMOTE_WRITE_RELATION_NAME,
            endpoint_address=self.hostname,
            endpoint_port=self._http_listen_port,
            endpoint_schema="http://",
            endpoint_path="/api/v1/push",
        )

        self.framework.observe(self.on.mimir_pebble_ready, self._on_mimir_pebble_ready)
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_mimir_pebble_ready(self, event):
        self._set_mimir_version()
        self._configure(event)

    def _on_config_changed(self, event):
        self._configure(event)

    def _configure(self, event):
        restart = False

        if not self._container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble ready")
            return

        try:
            restart = self._set_alerts(self._container)
        except PebbleError as e:
            logger.error("Failed to push updated alert files: %s", e)
            self.unit.status = BlockedStatus("Failed to push updated alert files; see debug logs")
            return

        current_layer = self._container.get_plan().to_dict()
        new_layer = self._pebble_layer

        if "services" not in current_layer or DeepDiff(
            current_layer["services"], new_layer["services"], ignore_order=True
        ):
            restart = True

        config = self._mimir_config

        try:
            if self._current_mimir_config != config:
                config_as_yaml = yaml.safe_dump(config)
                self._container.push(MIMIR_CONFIG, config_as_yaml, make_dirs=True)
                logger.info("Pushed new Mimir configuration")
                restart = True
        except (ProtocolError, PathError) as e:
            self.unit.status = BlockedStatus(str(e))
            return
        except Exception as e:
            self.unit.status = BlockedStatus(str(e))
            return

        if restart:
            self._container.add_layer(self._name, new_layer, combine=True)
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

    def _set_alerts(self, container) -> bool:
        """Create alert rule files for all Mimir consumers.

        Args:
            container: the Mimir workload container into which
                alert rule files need to be created. This container
                must be in a pebble ready state.

        Returns: A boolean indicating if new or different alert rules were pushed.
        """
        remote_write_alerts = self.remote_write_provider.alerts()
        alerts_hash = sha256(str(remote_write_alerts))
        alert_rules_changed = alerts_hash != self._stored.alerts_hash

        # Pushing files every time for situations such as cluster restart:
        # Relation data and stored state match, but files haven't been written yet.
        container.remove_path(RULES_DIR, recursive=True)
        self._push_alert_rules(container, self.remote_write_provider.alerts())
        self._stored.alerts_hash = alerts_hash
        return alert_rules_changed

    def _push_alert_rules(self, container, alerts):
        """Pushes alert rules from a rules file to the prometheus container.

        Args:
            container: the Mimir workload container into which
                alert rule files need to be created. This container
                must be in a pebble ready state.
            alerts: a dictionary of alert rule files, fetched from
                either a metrics consumer or a remote write provider.

        """
        container.make_dir(RULES_DIR)
        for topology_identifier, rules_file in alerts.items():
            filename = f"juju_{topology_identifier}.rules"
            path = os.path.join(RULES_DIR, filename)

            rules = yaml.safe_dump(rules_file)

            container.push(path, rules, make_dirs=True)
            logger.debug("Updated alert rules file %s", filename)

    @property
    def _pebble_layer(self):
        return {
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

    @property
    def _mimir_config(self) -> dict:
        return {
            "multitenancy_enabled": False,
            "blocks_storage": {
                "backend": "filesystem",
                "bucket_store": {
                    "sync_dir": f"{os.path.join(MIMIR_DIR, 'tsdb-sync')}",
                },
                "filesystem": {
                    "dir": f"{os.path.join(MIMIR_DIR, 'data', 'tsdb')}",
                },
                "tsdb": {
                    "dir": f"{os.path.join(MIMIR_DIR, 'tsdb')}",
                },
            },
            "compactor": {
                "data_dir": f"{os.path.join(MIMIR_DIR, 'compactor')}",
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
            "ruler_storage": {
                "backend": "filesystem",
                "filesystem": {
                    "dir": RULES_DIR,
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
        result = search("Mimir, version {} ", version_output)

        if result is None:
            return result

        return result[0]

    @property
    def hostname(self) -> str:
        """Unit's hostname."""
        return socket.getfqdn()


if __name__ == "__main__":  # pragma: nocover
    main(MimirK8SOperatorCharm)
