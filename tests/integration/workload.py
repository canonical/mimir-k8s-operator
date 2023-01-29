#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import Dict, Literal, Optional
from urllib.parse import urljoin

import aiohttp

logger = logging.getLogger(__name__)


class Mimir:
    """A class that represents a running instance of Mimir."""

    def __init__(self, host="localhost", port=9009):
        """Utility to manage a Mimir application.

        Args:
            host: Optional; host address of Mimir application.
            port: Optional; port on which Mimir service is exposed.
        """
        self.base_url = f"http://{host}:{port}"

        # Set a timeout of 5 second - should be sufficient for all the checks here.
        # The default (5 min) prolongs itests unnecessarily.
        self.timeout = aiohttp.ClientTimeout(total=5)

    async def is_ready(self) -> bool:
        """Send a GET request to check readiness.

        Returns:
          True if Mimir is ready (returned 200 OK); False otherwise.
        """
        url = f"{self.base_url}/ready"

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url) as response:
                return response.status == 200

    async def config(self) -> str:
        """Send a GET request to get Mimir configuration.

        Returns:
          YAML config in string format or empty string
        """
        url = f"{self.base_url}/config"
        # Response looks like this:
        # {
        #   "status": "success",
        #   "data": {
        #     "yaml": "global:\n
        #       scrape_interval: 1m\n
        #       scrape_timeout: 10s\n
        #       evaluation_interval: 1m\n
        #       rule_files:\n
        #       - /etc/prometheus/rules/juju_*.rules\n
        #       scrape_configs:\n
        #       - job_name: prometheus\n
        #       honor_timestamps: true\n
        #       scrape_interval: 5s\n
        #       scrape_timeout: 5s\n
        #       metrics_path: /metrics\n
        #       scheme: http\n
        #       static_configs:\n
        #       - targets:\n
        #       - localhost:9090\n"
        #   }
        # }
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.text()
                return result if response.status == 200 else ""

    async def api_request(
        self,
        endpoint: str,
        response_type: Optional[Literal["json"]] = None,
        params: Optional[Dict] = {},
    ):
        url = urljoin(self.base_url, endpoint)
        async with aiohttp.ClientSession() as session:
            async with session.request("GET", url, params=params) as response:
                if response_type == "json":
                    result = await response.json()
                    return result if response.status == 200 else ""
                else:
                    result = await response.text()
                    return result if response.status == 200 else ""
