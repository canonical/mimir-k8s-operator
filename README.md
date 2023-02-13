# Mimir Charmed Operator for K8s

[![CharmHub Badge](https://charmhub.io/mimir-k8s/badge.svg)](https://charmhub.io/mimir-k8s)
[![Release Edge](https://github.com/canonical/mimir-k8s-operator/actions/workflows/release-edge.yaml/badge.svg)](https://github.com/canonical/mimir-k8s-operator/actions/workflows/release-edge.yaml)
[![Release Libraries](https://github.com/canonical/mimir-k8s-operator/actions/workflows/release-libs.yaml/badge.svg)](https://github.com/canonical/mimir-k8s-operator/actions/workflows/release-libs.yaml)
[![Discourse Status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat&label=CharmHub%20Discourse)](https://discourse.charmhub.io)

## Description

The Mimir Charmed Operator provides a monitoring solution using [Mimir](https://github.com/grafana/mimir), which is an open source software project that provides a scalable long-term storage for [Prometheus](https://prometheus.io).

This repository contains a [Juju](https://juju.is/) Charm for deploying the monitoring component of Prometheus in a Kubernetes cluster.


## Usage

The Mimir Operator may be deployed using the Juju command line:

```sh
$ juju deploy mimir-k8s --trust
```

## OCI Images

This charm by default uses the last stable release of the [grafana/mimir](https://hub.docker.com/r/grafana/mimir/) image.
