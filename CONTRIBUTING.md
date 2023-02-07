# Contributing

![GitHub License](https://img.shields.io/github/license/canonical/mimir-k8s-operator)
![GitHub Commit Activity](https://img.shields.io/github/commit-activity/y/canonical/mimir-k8s-operator)
![GitHub Lines of Code](https://img.shields.io/tokei/lines/github/canonical/mimir-k8s-operator)
![GitHub Issues](https://img.shields.io/github/issues/canonical/mimir-k8s-operator)
![GitHub PRs](https://img.shields.io/github/issues-pr/canonical/mimir-k8s-operator)
![GitHub Contributors](https://img.shields.io/github/contributors/canonical/mimir-k8s-operator)
![GitHub Watchers](https://img.shields.io/github/watchers/canonical/mimir-k8s-operator?style=social)

To make contributions to this charm, you'll need a working [development setup](https://juju.is/docs/sdk/dev-setup).

You can use the environments created by `tox` for development:

```shell
tox --notest -e unit
source .tox/unit/bin/activate
```

## Testing

This project uses `tox` for managing test environments. There are some pre-configured environments
that can be used for linting and formatting code when you're preparing contributions to the charm:

```shell
tox -e fmt           # update your code according to linting rules
tox -e lint          # code style
tox -e unit          # unit tests
tox -e integration   # integration tests
tox                  # runs 'lint' and 'unit' environments
```

## Build the charm

Build the charm in this git repository using:

```shell
charmcraft pack
```

<!-- You may want to include any contribution/style guidelines in this document>
