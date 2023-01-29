# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

r"""# S3-Compatible Object Storage Library.

This library wraps relation endpoints using the `s3` interface
and provides a Python API both for requesting and providing per-application
object storage.

## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`.

```shell
cd some-charm
charmcraft fetch-lib charms.s3proxy_k8s.v0.object-storage
```

In the `metadata.yaml` of the charm, add the following:

```yaml
requires:
    s3:
        interface: s3
```

Then, to initialise the library:

```python
from charms.s3proxy_k8s.v0.object_storage import (ObjectStorageRequirer,
  ObjectStorageReadyEvent)

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.blobstore = ObjectStorageRequirer(self, bucket="some-charm")
    # The following event is triggered when the Object Storage to be used
    # by this deployment of the `SomeCharm` is ready (or changes).
    self.framework.observe(
        self.blobstore.on.ready, self._on_object_storage_ready
    )

    def _on_object_storage_ready_ready(self, event: ObjectStorageReadyEvent):
        # Configure with:
        #  event.access_key
        #  event.secret_key
        #  event.path
        #  event.endpoint
        pass
"""

import logging
import typing
from typing import Any, Dict, List, Literal, Optional, Tuple, TypedDict  # noqa: F401

from ops.charm import CharmBase, HookEvent, RelationBrokenEvent, RelationEvent
from ops.framework import BoundEvent, EventSource, Object, ObjectEvents, StoredState
from ops.model import Application, ModelError, Relation

# The unique Charmhub library identifier, never change it
LIBID = "cd6f05f34ed64df9aa667ba2f1ce7e37"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

DEFAULT_RELATION_NAME = "s3"
RELATION_INTERFACE = "s3"

logger = logging.getLogger(__name__)


try:
    import jsonschema

    DO_VALIDATION = True
except ModuleNotFoundError:
    logger.warning(
        "The `ingress` library needs the `jsonschema` package to be able "
        "to do runtime data validation; without it, it will still work but validation "
        "will be disabled. \n"
        "It is recommended to add `jsonschema` to the 'requirements.txt' of your charm, "
        "which will enable this feature."
    )
    DO_VALIDATION = False

OBJECT_STORAGE_PROVIDES_APP_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2019-09/schema",
    "$id": "https://canonical.github.io/charm-relation-interfaces/interfaces/s3/schemas/provider.json",
    "title": "`s3` provider schema",
    "description": "The `s3` root schema comprises the entire provider databag for this interface.",
    "type": "object",
    "default": {},
    "required": ["bucket", "access-key", "secret-key", "endpoint"],
    "additionalProperties": "true",
    "properties": {
        "bucket": {
            "title": "Bucket name",
            "description": "The bucket/container name delivered by the provider.",
            "type": "string",
            "default": "",
            "examples": ["minio"],
        },
        "access-key": {
            "title": "Access Key ID",
            "description": "Access Key ID (account) for connecting to the object storage.",
            "type": "string",
            "default": "",
            "examples": ["username"],
        },
        "secret-key": {
            "title": "Access Secret Key ID",
            "description": "Access Key Secret ID (password) for connecting to the object storage.",
            "type": "string",
            "default": "",
            "examples": ["alphanum-32byte-random"],
        },
        "path": {
            "title": "Path",
            "description": "The path inside the bucket/container to store objects.",
            "type": "string",
            "default": "",
            "examples": ["relation-24"],
        },
        "endpoint": {
            "title": "Endpoint URL",
            "description": "The endpoint used to connect to the object storage.",
            "type": "string",
            "default": "",
            "examples": ["https://minio-endpoint/"],
        },
        "region": {
            "title": "Region",
            "description": "The region used to connect to the object storage.",
            "type": "string",
            "default": "",
            "examples": ["us-east-1"],
        },
        "s3-uri-style": {
            "title": "S3 URI Style",
            "description": "The S3 protocol specific bucket path lookup type.",
            "type": "string",
            "default": "",
            "examples": ["path", "host"],
        },
        "storage-class": {
            "title": "Storage Class",
            "description": "Storage Class for objects uploaded to the object storage.",
            "type": "string",
            "default": "",
            "examples": ["glacier"],
        },
        "tls-ca-chain": {
            "title": "TLS CA Chain",
            "description": "The complete CA chain, which can be used for HTTPS validation.",
            "type": "array",
            "items": {"type": "string"},
            "examples": [["base64-encoded-ca-chain=="]],
        },
        "s3-api-version": {
            "title": "S3 API signature",
            "description": "S3 protocol specific API signature.",
            "type": "integer",
            "default": "",
            "enum": [2, 4],
            "examples": [2, 4],
        },
        "attributes": {
            "title": "Custom metadata",
            "description": "The custom metadata (HTTP headers).",
            "type": "array",
            "items": {"type": "string"},
            "examples": [
                [
                    "Cache-Control=max-age=90000,min-fresh=9000",
                    "X-Amz-Server-Side-Encryption-Customer-Key=CuStoMerKey=",
                ]
            ],
        },
    },
    "examples": [
        {
            "bucket": "minio",
            "access-key": "RANDOM",
            "secret-key": "RANDOM",
            "path": "relation-68",
            "endpoint": "https://minio-endpoint/",
            "region": "us-east-1",
            "s3-uri-style": "path",
            "storage-class": "glacier",
            "tls-ca-chain": ["base64-encoded-ca-chain=="],
            "s3-api-version": 4,
            "attributes": [
                "Cache-Control=max-age=90000,min-fresh=9000",
                "X-Amz-Server-Side-Encryption-Customer-Key=CuStoMerKey=",
            ],
        }
    ],
}

ANONYMOUS_OBJECT_STORAGE_REQUIRES_APP_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2019-09/schema",
    "$id": "https://canonical.github.io/charm-relation-interfaces/interfaces/s3/schemas/requirer.json",
    "title": "`s3` provider schema",
    "description": "The `s3` root schema comprises the entire provider databag for this interface.",
    "type": "object",
    "default": {},
    "required": ["bucket"],
    "additionalProperties": "true",
    "properties": {
        "bucket": {
            "title": "Bucket Name",
            "description": "The bucket name requested by the requirer",
            "type": "string",
            "default": "",
            "examples": ["relation-17"],
        }
    },
    "examples": [{"bucket": "myapp"}],
}

# Model of the data a unit implementing the requirer will need to provide.
RequirerData = TypedDict(
    "RequirerData",
    {"bucket": str},
    total=True,
)

# Provider ingress data model.
ProviderData = TypedDict(
    "ProviderData",
    {
        "bucket": str,
        "access-key": str,
        "secret-key": str,
        "path": str,
        "endpoint": str,
        "s3-uri-style": str,
        "storage-class": str,
        "tls-ca-chain": str,
        "s3-api-version": Literal[2, 4],
        "attributes": List[str],
    },
    total=False,
)
# Provider application databag model.
ProviderApplicationData = TypedDict("ProviderApplicationData", {"ingress": ProviderData})  # type: ignore


def _validate_data(data, schema):
    """Checks whether `data` matches `schema`.

    Will raise DataValidationError if the data is not valid, else return None.
    """
    if not DO_VALIDATION:
        return
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        raise DataValidationError(data, schema) from e


class DataValidationError(RuntimeError):
    """Raised when data validation fails on IPU relation data."""


class _ObjectStorageBase(Object):
    """Base class for ObjectStorage interface classes."""

    def __init__(self, charm: CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)

        self.charm: CharmBase = charm
        self.relation_name = relation_name
        self.app = self.charm.app
        self.unit = self.charm.unit

        observe = self.framework.observe
        rel_events = charm.on[relation_name]
        observe(rel_events.relation_created, self._handle_relation)
        observe(rel_events.relation_joined, self._handle_relation)
        observe(rel_events.relation_changed, self._handle_relation)
        observe(rel_events.relation_broken, self._handle_relation_broken)
        observe(charm.on.leader_elected, self._handle_upgrade_or_leader)  # type: ignore
        observe(charm.on.upgrade_charm, self._handle_upgrade_or_leader)  # type: ignore

    @property
    def relations(self):
        """The list of Relation instances associated with this endpoint."""
        return list(self.charm.model.relations[self.relation_name])

    def _handle_relation(self, event):
        """Subclasses should implement this method to handle a relation update."""
        pass

    def _handle_relation_broken(self, event):
        """Subclasses should implement this method to handle a relation breaking."""
        pass

    def _handle_upgrade_or_leader(self, event):
        """Subclasses should implement this method to handle upgrades or leadership change."""
        pass


# Shamelessly taken from traefik_k8s.ingress -- it's a nice pattern!
class _ObjectStorageEvent(RelationEvent):
    __args__ = ()  # type: Tuple[str, ...]
    __optional_kwargs__ = {}  # type: Dict[str, Any]

    @classmethod
    def __attrs__(cls):
        return cls.__args__ + tuple(cls.__optional_kwargs__.keys())

    def __init__(self, handle, relation, *args, **kwargs):
        super().__init__(handle, relation)

        if not len(self.__args__) == len(args):
            raise TypeError("expected {} args, got {}".format(len(self.__args__), len(args)))

        for attr, obj in zip(self.__args__, args):
            setattr(self, attr, obj)
        for attr, default in self.__optional_kwargs__.items():
            obj = kwargs.get(attr, default)
            setattr(self, attr, obj)

    def snapshot(self) -> dict:
        dct = super().snapshot()
        for attr in self.__attrs__():
            obj = getattr(self, attr)
            try:
                dct[attr] = obj
            except ValueError as e:
                raise ValueError(
                    "cannot automagically serialize {}: "
                    "override this method and do it "
                    "manually.".format(obj)
                ) from e

        return dct  # type: ignore

    def restore(self, snapshot: dict) -> None:
        super().restore(snapshot)  # type: ignore
        for attr, obj in snapshot.items():
            setattr(self, attr, obj)


class ObjectStorageDataProvidedEvent(_ObjectStorageEvent):
    """Event representing that object storage data has been provided for an app."""

    __optional_kwargs__ = {"bucket": ""}  # type: ignore

    if typing.TYPE_CHECKING:
        bucket = None  # type: Optional[str]


class ObjectStorageDataRefreshEvent(HookEvent):
    """Request a refresh of data."""


class ObjectStorageProviderCharmEvents(ObjectEvents):
    """List of events that the auth provider charm can leverage."""

    requested = EventSource(ObjectStorageDataProvidedEvent)
    refresh = EventSource(ObjectStorageDataRefreshEvent)


class _ObjectStorageProviderBase(_ObjectStorageBase):
    """Base class for object storage provider classes.

    For now (with s3proxy), authentication details are the same for all
    clients, differing only in the bucket.
    """

    on = ObjectStorageProviderCharmEvents()  # type: ignore

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str,
        refresh_event: Optional[BoundEvent] = None,
    ):
        super().__init__(charm, relation_name)
        if not refresh_event:
            container = list(self.charm.meta.containers.values())[0]
            if len(self.charm.meta.containers) == 1:
                refresh_event = self.charm.on[container.name.replace("-", "_")].pebble_ready
            else:
                logger.warning(
                    "%d containers are present in metadata.yaml and "
                    "refresh_event was not specified. Defaulting to update_status. ",
                    len(self.charm.meta.containers),
                )
                refresh_event = self.charm.on.update_status

        self.framework.observe(refresh_event, self._handle_refresh)

    def _handle_refresh(self, event: Any):
        """Subclasses should handle this event in scenarios where an endpoint IP may change."""
        pass


class SingleAuthObjectStorageProvider(_ObjectStorageProviderBase):
    """Class for single authentication object storage providers.

    For now (with s3proxy), authentication details are the same for all
    clients, differing only in the bucket.
    """

    on = ObjectStorageProviderCharmEvents()

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str,
        refresh_event: Optional[BoundEvent] = None,
    ):
        super().__init__(charm, relation_name, refresh_event)

    def _handle_relation(self, event: Any):
        self._request_endpoints(event)

    def _handle_upgrade_or_leader(self, event):
        # We don't do anything on upgrades or leader-elected yet.
        self.on.refresh.emit()  # type: ignore

    def _handle_refresh(self, event):
        self.on.refresh.emit()  # type: ignore

    def _request_endpoints(self, event: Any) -> None:
        """Handler triggered on pretty much all events.

        Request an update from the workload charm.

        Args:
            event: Juju event

        Returns:
            None
        """
        if not self.charm.unit.is_leader():
            return

        if event.relation and event.relation.app:
            bucket = event.relation.data.get(event.relation.app, {}).get(
                "bucket", f"{event.relation.app.name}-{event.relation.id}"
            )
        else:
            bucket = "anonymous"
        self.on.requested.emit(event.relation, bucket=bucket)  # type: ignore

    def update_endpoints(self, data: Dict[str, str], relation_id: Optional[int] = None):
        """Update relation data bags with endpoint information."""
        if relation_id:
            for r in [rel for rel in self.relations if rel.id == relation_id]:
                if bucket := r.data.get(r.app, {}).get("bucket", ""):  # type: ignore
                    data["bucket"] = bucket
                    _validate_data(data, ANONYMOUS_OBJECT_STORAGE_REQUIRES_APP_SCHEMA)
                    r.data[self.charm.app].update(data)  # type: ignore
        else:
            for r in self.relations:
                if bucket := r.data.get(r.app, {}).get("bucket", ""):  # type: ignore
                    data["bucket"] = bucket
                    _validate_data(data, ANONYMOUS_OBJECT_STORAGE_REQUIRES_APP_SCHEMA)
                    r.data[self.charm.app].update(data)  # type: ignore


class ObjectStorageReadyEvent(_ObjectStorageEvent):
    """Event representing that object storage data has been provided for an app."""

    __args__ = ("bucket", "endpoint", "access_key", "secret_key")

    if typing.TYPE_CHECKING:
        access_key = None  # type: Optional[str]
        bucket = None  # type: Optional[str]
        endpoint = None  # type: Optional[str]
        secret_key = None  # type: Optional[str]


class ObjectStorageBrokenEvent(_ObjectStorageEvent):
    """Event representing that an object storage relation has been broken."""


class ObjectStorageRequirerCharmEvents(ObjectEvents):
    """List of events that the object storage requirer charm can leverage."""

    ready = EventSource(ObjectStorageReadyEvent)
    broken = EventSource(ObjectStorageBrokenEvent)


class ObjectStorageRequirer(_ObjectStorageBase):
    """Authentication configuration requirer class."""

    on = ObjectStorageRequirerCharmEvents()  # type: ignore

    # used to prevent spurious endpoints to be sent out if the event we're currently
    # handling is a relation-broken one.
    _stored = StoredState()

    def __init__(
        self,
        charm,
        relation_name: str = DEFAULT_RELATION_NAME,
        bucket: Optional[str] = None,
    ):
        """Constructs a requirer that consumes object storage.

        This class can be initialized as follows:

            self.object_storage = ObjectStorageRequirer(
            self,
            bucket="some-app"
            )

        Args:
            charm: CharmBase: the charm which manages this object.
            relation_name: str: name of the relation in `metadata.yaml` that has the
                `s3` interface.
            refresh_event: an optional bound event which will be observed to re-set
                authentication configuration.
            bucket: Optional[str]: bucket name to request on the endpoint. If not
                provided, {model.name}-{app.name} will be used.
        """
        super().__init__(charm, relation_name)
        self._stored.set_default(current_endpoints={})
        self.bucket = bucket or f"{charm.model.name}-{charm.app.name}"

    @property
    def relation(self) -> Optional[Relation]:
        """The established Relation instance, or None if still unrelated."""
        return self.relations[0] if self.relations else None

    def _handle_relation(self, event: RelationEvent):
        # we calculate the diff between the urls we were aware of
        # before and those we know now
        previous_endpoints = self._stored.current_endpoints or {}  # type: ignore
        current_endpoints = self._endpoints_from_relation_data
        self._stored.current_endpoints = current_endpoints  # type: ignore

        if isinstance(event, RelationBrokenEvent):
            self._stored.current_endpoints = {}
            return

        changed = previous_endpoints != current_endpoints
        if changed:
            self.on.ready.emit(  # type: ignore
                event.relation,
                current_endpoints["bucket"],
                current_endpoints["endpoint"],
                current_endpoints["access-key"],
                current_endpoints["secret-key"],
            )
            return
        event.relation.data[self.charm.app]["bucket"] = self.bucket

    def _handle_relation_broken(self, event):
        """Emit an event the parent charm can listen to."""
        self.on.broken.emit(event.relation)  # type: ignore

    @property
    def bucket_info(self):
        """Indicate whether a remote bucket is available."""
        return self._endpoints_from_relation_data

    @property
    def _endpoints_from_relation_data(self) -> Dict[str, str]:
        """Pull connection information out of relation data."""
        relation = self.relation
        if not relation:
            return {}

        if not relation.app and not relation.app.name:  # type: ignore
            # We must be in a relation_broken hook
            return {}
        assert isinstance(relation.app, Application)

        data = {}
        try:
            fields = ["access-key", "bucket", "endpoint", "secret-key"]

            for f in fields:
                data[f] = relation.data[relation.app].get(f, "")  # type: ignore
        except ModelError as e:
            logger.debug(
                "Error {} attempting to read remote app data; "
                "probably we are in a relation_departed hook".format(e)
            )
            return {}

        if not all([data[k] for k in data.keys()]):
            # incomplete relation data
            return {}

        _validate_data(data, ANONYMOUS_OBJECT_STORAGE_REQUIRES_APP_SCHEMA)
        return data
