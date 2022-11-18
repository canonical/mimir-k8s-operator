# Mimir Charmed Operator for K8s

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
