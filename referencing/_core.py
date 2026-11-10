from __future__ import annotations

from collections.abc import Iterable, Iterator, Sequence
from enum import Enum
from typing import Any, Callable, ClassVar, Generic, Protocol, Union
from urllib.parse import unquote, urldefrag, urljoin

from attrs import evolve, field
from rpds import HashTrieMap, HashTrieSet, List

try:
    from typing_extensions import TypeVar
except ImportError:  # pragma: no cover
    from typing import TypeVar

from referencing import exceptions
from referencing._attrs import frozen
from referencing.typing import URI, Anchor as AnchorType, D, Mapping, Retrieve

EMPTY_UNCRAWLED: HashTrieSet[URI] = HashTrieSet()
EMPTY_PREVIOUS_RESOLVERS: List[URI] = List()


class _Unset(Enum):
    """
    What sillyness...
    """

    SENTINEL = 1


_UNSET = _Unset.SENTINEL


class _MaybeInSubresource(Protocol[D]):
    def __call__(
        self,
        segments: Sequence[int | str],
        resolver: Resolver[D],
        subresource: Resource[D],
    ) -> Resolver[D]: ...


def _detect_or_error(contents: D) -> Specification[D]:
    if not isinstance(contents, Mapping):
        raise exceptions.CannotDetermineSpecification(contents)

    jsonschema_dialect_id = contents.get("$schema")  # type: ignore[reportUnknownMemberType]
    if not isinstance(jsonschema_dialect_id, str):
        raise exceptions.CannotDetermineSpecification(contents)

    from referencing.jsonschema import specification_with

    return specification_with(jsonschema_dialect_id)


def _detect_or_default(
    default: Specification[D],
) -> Callable[[D], Specification[D]]:
    def _detect(contents: D) -> Specification[D]:
        if not isinstance(contents, Mapping):
            return default

        jsonschema_dialect_id = contents.get("$schema")  # type: ignore[reportUnknownMemberType]
        if jsonschema_dialect_id is None:
            return default

        from referencing.jsonschema import specification_with

        return specification_with(
            jsonschema_dialect_id,  # type: ignore[reportUnknownArgumentType]
            default=default,
        )

    return _detect


class _SpecificationDetector:
    def __get__(
        self,
        instance: Specification[D] | None,
        cls: type[Specification[D]],
    ) -> Callable[[D], Specification[D]]:
        if instance is None:
            return _detect_or_error
        else:
            return _detect_or_default(instance)


#: Either a concrete `Specification` (used directly as the default) or a
#: `SpecificationAdmission` policy describing both the default and the set of
#: admitted specifications.
DefaultSpecificationOrAdmission = Union[
    "Specification[D]",
    "SpecificationAdmission[D]",
    type["Specification[D]"],
]


@frozen
class SpecificationAdmission(Generic[D]):
    """
    An admission policy controlling which specifications resources may use.

    Policies constrain the dialects that referenced (root or embedded)
    resources are allowed to identify as, so that a subresource declaring its
    own :kw:`$schema` cannot silently switch interpretation to a dialect that
    was not approved.

    A resource which explicitly declares a dialect is checked against the
    policy:

        * a dialect URI unknown to the library raises
          `referencing.exceptions.UnknownDialect` (rather than being treated
          as the latest draft or any other dialect),

        * a known dialect which is not part of the admitted specifications
          raises `referencing.exceptions.DisallowedDialect`.

    A resource which does not declare a dialect is interpreted using the
    policy's explicit ``default`` specification.

    An admission is a callable-like object exposing the same ``detect``
    interface as a `Specification`, which allows it to be threaded through
    `Resource.from_contents`, `Registry` and `Resolver` alongside the
    resources it governs.
    """

    #: The specifications resources are allowed to identify as.
    allowed: frozenset[Specification[D]] = field(  # type: ignore[reportGeneralTypeIssues]
        converter=frozenset,
    )

    #: The specification used for resources which do not declare one.
    default: Specification[D]

    def __attrs_post_init__(self) -> None:
        if self.default not in self.allowed:
            raise ValueError(  # noqa: TRY003
                "The default specification must itself be an admitted "
                f"specification, but {self.default!r} is not among "
                f"{sorted(self.allowed, key=lambda each: each.name)!r}.",
            )

    @classmethod
    def admitting(
        cls,
        specifications: Iterable[Specification[D]],
        default: Specification[D] | None = None,
    ) -> SpecificationAdmission[D]:
        """
        Create an admission allowing the given specifications.

        If no explicit ``default`` is given, one of the admitted
        specifications is used as the default for resources without a
        declared dialect. Pass ``default`` explicitly to choose which.
        """
        allowed = frozenset(specifications)
        if not allowed:
            raise ValueError(  # noqa: TRY003
                "An admission policy must admit at least one specification.",
            )
        if default is None:
            default = next(iter(allowed))
        return cls(allowed=allowed, default=default)

    def detect(self, contents: D) -> Specification[D]:
        """
        Detect the specification of the given contents under this policy.

        Raises:

            `referencing.exceptions.CannotDetermineSpecification`

                if the contents declare a non-string dialect identifier

            `referencing.exceptions.UnknownDialect`

                if the contents declare a dialect no specification recognizes

            `referencing.exceptions.DisallowedDialect`

                if the contents declare a known but non-admitted dialect

        """
        if not isinstance(contents, Mapping):
            return self.default

        jsonschema_dialect_id = contents.get(  # type: ignore[reportUnknownMemberType]
            "$schema",
        )
        if jsonschema_dialect_id is None:
            return self.default
        if not isinstance(jsonschema_dialect_id, str):
            raise exceptions.CannotDetermineSpecification(contents)

        from referencing.jsonschema import specification_with

        specification = specification_with(jsonschema_dialect_id)
        if specification not in self.allowed:
            raise exceptions.DisallowedDialect(
                uri=jsonschema_dialect_id,
                specification=specification,
            )
        return specification


@frozen
class Specification(Generic[D]):
    """
    A specification which defines referencing behavior.

    The various methods of a `Specification` allow for varying referencing
    behavior across JSON Schema specification versions, etc.
    """

    #: A short human-readable name for the specification, used for debugging.
    name: str

    #: Find the ID of a given document.
    id_of: Callable[[D], URI | None]

    #: Retrieve the subresources of the given document (without traversing into
    #: the subresources themselves).
    subresources_of: Callable[[D], Iterable[D]]

    #: While resolving a JSON pointer, conditionally enter a subresource
    #: (if e.g. we have just entered a keyword whose value is a subresource)
    maybe_in_subresource: _MaybeInSubresource[D]

    #: Retrieve the anchors contained in the given document.
    _anchors_in: Callable[
        [Specification[D], D],
        Iterable[AnchorType[D]],
    ] = field(alias="anchors_in")

    #: An opaque specification where resources have no subresources
    #: nor internal identifiers.
    OPAQUE: ClassVar[Specification[Any]]

    #: Attempt to discern which specification applies to the given contents.
    #:
    #: May be called either as an instance method or as a class method, with
    #: slightly different behavior in the following case:
    #:
    #: Recall that not all contents contains enough internal information about
    #: which specification it is written for -- the JSON Schema ``{}``,
    #: for instance, is valid under many different dialects and may be
    #: interpreted as any one of them.
    #:
    #: When this method is used as an instance method (i.e. called on a
    #: specific specification), that specification is used as the default
    #: if the given contents are unidentifiable.
    #:
    #: On the other hand when called as a class method, an error is raised.
    #:
    #: To reiterate, ``DRAFT202012.detect({})`` will return ``DRAFT202012``
    #: whereas the class method ``Specification.detect({})`` will raise an
    #: error.
    #:
    #: (Note that of course ``DRAFT202012.detect(...)`` may return some other
    #: specification when given a schema which *does* identify as being for
    #: another version).
    #:
    #: Raises:
    #:
    #:     `CannotDetermineSpecification`
    #:
    #:         if the given contents don't have any discernible
    #:         information which could be used to guess which
    #:         specification they identify as
    detect = _SpecificationDetector()

    def __repr__(self) -> str:
        return f"<Specification name={self.name!r}>"

    def anchors_in(self, contents: D):
        """
        Retrieve the anchors contained in the given document.
        """
        return self._anchors_in(self, contents)

    def create_resource(self, contents: D) -> Resource[D]:
        """
        Create a resource which is interpreted using this specification.
        """
        return Resource(contents=contents, specification=self)


Specification.OPAQUE = Specification(
    name="opaque",
    id_of=lambda contents: None,
    subresources_of=lambda contents: [],
    anchors_in=lambda specification, contents: [],
    maybe_in_subresource=lambda segments, resolver, subresource: resolver,
)


@frozen
class Resource(Generic[D]):
    r"""
    A document (deserialized JSON) with a concrete interpretation under a spec.

    In other words, a Python object, along with an instance of `Specification`
    which describes how the document interacts with referencing -- both
    internally (how it refers to other `Resource`\ s) and externally (how it
    should be identified such that it is referenceable by other documents).
    """

    contents: D
    _specification: Specification[D] = field(alias="specification")

    @classmethod
    def from_contents(
        cls,
        contents: D,
        default_specification: (
            DefaultSpecificationOrAdmission[D]
        ) = Specification,
    ) -> Resource[D]:
        """
        Create a resource guessing which specification applies to the contents.

        ``default_specification`` may be a `Specification` (or the
        `Specification` class itself) or else a `SpecificationAdmission`
        policy. When given an admission, the policy both provides the default
        specification for contents which don't declare a dialect and checks
        any explicitly declared dialect against the admitted specifications.

        Raises:

            `CannotDetermineSpecification`

                if the given contents don't have any discernible
                information which could be used to guess which
                specification they identify as

            `referencing.exceptions.UnknownDialect`

                if an admission policy is in effect and the contents declare
                a dialect which no known specification recognizes

            `referencing.exceptions.DisallowedDialect`

                if an admission policy is in effect and the contents declare
                a known, but non-admitted, dialect

        """
        specification = default_specification.detect(contents)
        return specification.create_resource(contents=contents)

    @classmethod
    def opaque(cls, contents: D) -> Resource[D]:
        """
        Create an opaque `Resource` -- i.e. one with opaque specification.

        See `Specification.OPAQUE` for details.
        """
        return Specification.OPAQUE.create_resource(contents=contents)

    def id(self) -> URI | None:
        """
        Retrieve this resource's (specification-specific) identifier.
        """
        id = self._specification.id_of(self.contents)
        if id is None:
            return
        return id.rstrip("#")

    def subresources(
        self,
        default_specification: (
            DefaultSpecificationOrAdmission[D] | _Unset
        ) = _UNSET,
    ) -> Iterable[Resource[D]]:
        """
        Retrieve this resource's subresources.

        By default each subresource is detected using this resource's own
        specification as the default (in case a subresource doesn't declare
        one). If given a `SpecificationAdmission`, the policy is used to
        detect every subresource instead, checking any dialect they declare.
        """
        if default_specification is _UNSET:
            default_specification = self._specification
        return (
            Resource.from_contents(
                each,
                default_specification=default_specification,
            )
            for each in self._specification.subresources_of(self.contents)
        )

    def anchors(self) -> Iterable[AnchorType[D]]:
        """
        Retrieve this resource's (specification-specific) identifier.
        """
        return self._specification.anchors_in(self.contents)

    def pointer(self, pointer: str, resolver: Resolver[D]) -> Resolved[D]:
        """
        Resolve the given JSON pointer.

        Raises:

            `exceptions.PointerToNowhere`

                if the pointer points to a location not present in the document

        """
        if not pointer:
            return Resolved(contents=self.contents, resolver=resolver)

        contents = self.contents
        segments: list[int | str] = []
        for segment in unquote(pointer[1:]).split("/"):
            if isinstance(contents, Sequence):
                segment = int(segment)
            else:
                segment = segment.replace("~1", "/").replace("~0", "~")
            try:
                contents = contents[segment]  # type: ignore[reportUnknownArgumentType]
            except LookupError as lookup_error:
                error = exceptions.PointerToNowhere(ref=pointer, resource=self)
                raise error from lookup_error

            segments.append(segment)
            last = resolver
            resolver = self._specification.maybe_in_subresource(
                segments=segments,
                resolver=resolver,
                subresource=self._specification.create_resource(contents),
            )
            if resolver is not last:
                segments = []
        return Resolved(contents=contents, resolver=resolver)  # type: ignore[reportUnknownArgumentType]


def _fail_to_retrieve(uri: URI):
    raise exceptions.NoSuchResource(ref=uri)


@frozen
class Registry(Mapping[URI, Resource[D]]):
    r"""
    A registry of `Resource`\ s, each identified by their canonical URIs.

    Registries store a collection of in-memory resources, and optionally
    enable additional resources which may be stored elsewhere (e.g. in a
    database, a separate set of files, over the network, etc.).

    They also lazily walk their known resources, looking for subresources
    within them. In other words, subresources contained within any added
    resources will be retrievable via their own IDs (though this discovery of
    subresources will be delayed until necessary).

    Registries are immutable, and their methods return new instances of the
    registry with the additional resources added to them.

    The ``retrieve`` argument can be used to configure retrieval of resources
    dynamically, either over the network, from a database, or the like.
    Pass it a callable which will be called if any URI not present in the
    registry is accessed. It must either return a `Resource` or else raise a
    `NoSuchResource` exception indicating that the resource does not exist
    even according to the retrieval logic.
    """

    _resources: HashTrieMap[URI, Resource[D]] = field(
        default=HashTrieMap(),
        converter=HashTrieMap.convert,  # type: ignore[reportGeneralTypeIssues]
        alias="resources",
    )
    _anchors: HashTrieMap[tuple[URI, str], AnchorType[D]] = HashTrieMap()
    _uncrawled: HashTrieSet[URI] = EMPTY_UNCRAWLED
    _retrieve: Retrieve[D] = field(default=_fail_to_retrieve, alias="retrieve")
    _admission: SpecificationAdmission[D] | None = field(
        default=None,
        alias="admission",
    )

    @property
    def admission(self) -> SpecificationAdmission[D] | None:
        """
        The `SpecificationAdmission` policy governing this registry, if any.
        """
        return self._admission

    def __getitem__(self, uri: URI) -> Resource[D]:
        """
        Return the (already crawled) `Resource` identified by the given URI.
        """
        try:
            return self._resources[uri.rstrip("#")]
        except KeyError:
            raise exceptions.NoSuchResource(ref=uri) from None

    def __iter__(self) -> Iterator[URI]:
        """
        Iterate over all crawled URIs in the registry.
        """
        return iter(self._resources)

    def __len__(self) -> int:
        """
        Count the total number of fully crawled resources in this registry.
        """
        return len(self._resources)

    def __rmatmul__(
        self,
        new: Resource[D] | Iterable[Resource[D]],
    ) -> Registry[D]:
        """
        Create a new registry with resource(s) added using their internal IDs.

        Resources must have a internal IDs (e.g. the :kw:`$id` keyword in
        modern JSON Schema versions), otherwise an error will be raised.

        Both a single resource as well as an iterable of resources works, i.e.:

            * ``resource @ registry`` or

            * ``[iterable, of, multiple, resources] @ registry``

        which -- again, assuming the resources have internal IDs -- is
        equivalent to calling `Registry.with_resources` as such:

        .. code:: python

            registry.with_resources(
                (resource.id(), resource) for resource in new_resources
            )

        Raises:

            `NoInternalID`

                if the resource(s) in fact do not have IDs

        """
        if isinstance(new, Resource):
            new = (new,)

        resources = self._resources
        uncrawled = self._uncrawled
        for resource in new:
            id = resource.id()
            if id is None:
                raise exceptions.NoInternalID(resource=resource)
            uncrawled = uncrawled.insert(id)
            resources = resources.insert(id, resource)
        return evolve(self, resources=resources, uncrawled=uncrawled)

    def __repr__(self) -> str:
        size = len(self)
        pluralized = "resource" if size == 1 else "resources"
        if self._uncrawled:
            uncrawled = len(self._uncrawled)
            if uncrawled == size:
                summary = f"uncrawled {pluralized}"
            else:
                summary = f"{pluralized}, {uncrawled} uncrawled"
        else:
            summary = f"{pluralized}"
        return f"<Registry ({size} {summary})>"

    def get_or_retrieve(self, uri: URI) -> Retrieved[D, Resource[D]]:
        """
        Get a resource from the registry, crawling or retrieving if necessary.

        May involve crawling to find the given URI if it is not already known,
        so the returned object is a `Retrieved` object which contains both the
        resource value as well as the registry which ultimately contained it.
        """
        resource = self._resources.get(uri)
        if resource is not None:
            return Retrieved(registry=self, value=resource)

        registry = self.crawl()
        resource = registry._resources.get(uri)
        if resource is not None:
            return Retrieved(registry=registry, value=resource)

        try:
            resource = registry._retrieve(uri)
        except (
            exceptions.CannotDetermineSpecification,
            exceptions.DisallowedDialect,
            exceptions.NoSuchResource,
            exceptions.UnknownDialect,
        ):
            raise
        except Exception as error:
            raise exceptions.Unretrievable(ref=uri) from error
        else:
            registry = registry.with_resource(uri, resource)
            return Retrieved(registry=registry, value=resource)

    def remove(self, uri: URI):
        """
        Return a registry with the resource identified by a given URI removed.
        """
        if uri not in self._resources:
            raise exceptions.NoSuchResource(ref=uri)

        return evolve(
            self,
            resources=self._resources.remove(uri),
            uncrawled=self._uncrawled.discard(uri),
            anchors=HashTrieMap(
                (k, v) for k, v in self._anchors.items() if k[0] != uri
            ),
        )

    def anchor(self, uri: URI, name: str):
        """
        Retrieve a given anchor from a resource which must already be crawled.
        """
        value = self._anchors.get((uri, name))
        if value is not None:
            return Retrieved(value=value, registry=self)

        registry = self.crawl()
        value = registry._anchors.get((uri, name))
        if value is not None:
            return Retrieved(value=value, registry=registry)

        resource = self[uri]
        canonical_uri = resource.id()
        if canonical_uri is not None:
            value = registry._anchors.get((canonical_uri, name))
            if value is not None:
                return Retrieved(value=value, registry=registry)

        if "/" in name:
            raise exceptions.InvalidAnchor(
                ref=uri,
                resource=resource,
                anchor=name,
            )
        raise exceptions.NoSuchAnchor(ref=uri, resource=resource, anchor=name)

    def contents(self, uri: URI) -> D:
        """
        Retrieve the (already crawled) contents identified by the given URI.
        """
        return self[uri].contents

    def crawl(self) -> Registry[D]:
        """
        Crawl all added resources, discovering subresources.
        """
        resources = self._resources
        anchors = self._anchors
        uncrawled = [(uri, resources[uri]) for uri in self._uncrawled]
        while uncrawled:
            uri, resource = uncrawled.pop()

            id = resource.id()
            if id is not None:
                uri = urljoin(uri, id)
                resources = resources.insert(uri, resource)
            for each in resource.anchors():
                anchors = anchors.insert((uri, each.name), each)
            if self._admission is None:
                subresources = resource.subresources()
            else:
                subresources = resource.subresources(self._admission)
            uncrawled.extend((uri, each) for each in subresources)
        return evolve(
            self,
            resources=resources,
            anchors=anchors,
            uncrawled=EMPTY_UNCRAWLED,
        )

    def with_resource(self, uri: URI, resource: Resource[D]):
        """
        Add the given `Resource` to the registry, without crawling it.
        """
        return self.with_resources([(uri, resource)])

    def with_resources(
        self,
        pairs: Iterable[tuple[URI, Resource[D]]],
    ) -> Registry[D]:
        r"""
        Add the given `Resource`\ s to the registry, without crawling them.
        """
        resources = self._resources
        uncrawled = self._uncrawled
        for uri, resource in pairs:
            # Empty fragment URIs are equivalent to URIs without the fragment.
            # TODO: Is this true for non JSON Schema resources? Probably not.
            uri = uri.rstrip("#")
            uncrawled = uncrawled.insert(uri)
            resources = resources.insert(uri, resource)
        return evolve(self, resources=resources, uncrawled=uncrawled)

    def with_contents(
        self,
        pairs: Iterable[tuple[URI, D]],
        default_specification: (
            DefaultSpecificationOrAdmission[D] | _Unset
        ) = _UNSET,
    ) -> Registry[D]:
        r"""
        Add the given contents to the registry, autodetecting when necessary.

        If no ``default_specification`` is given and the registry has a
        `SpecificationAdmission` policy, the policy is used to detect (and
        check) each document's specification.
        """
        if default_specification is _UNSET:
            if self._admission is not None:
                default_specification = self._admission
            else:
                default_specification = Specification
        return self.with_resources(
            (uri, Resource.from_contents(each, default_specification))
            for uri, each in pairs
        )

    def combine(self, *registries: Registry[D]) -> Registry[D]:
        """
        Combine together one or more other registries, producing a unified one.
        """
        if registries == (self,):
            return self
        resources = self._resources
        anchors = self._anchors
        uncrawled = self._uncrawled
        retrieve = self._retrieve
        admission = self._admission
        for registry in registries:
            resources = resources.update(registry._resources)
            anchors = anchors.update(registry._anchors)
            uncrawled = uncrawled.update(registry._uncrawled)

            if registry._retrieve is not _fail_to_retrieve:  # type: ignore[reportUnnecessaryComparison] ???
                if registry._retrieve is not retrieve is not _fail_to_retrieve:  # type: ignore[reportUnnecessaryComparison] ???
                    raise ValueError(  # noqa: TRY003
                        "Cannot combine registries with conflicting retrieval "
                        "functions.",
                    )
                retrieve = registry._retrieve

            if registry._admission is not None:
                if (
                    admission is not None
                    and registry._admission != admission
                ):
                    raise ValueError(  # noqa: TRY003
                        "Cannot combine registries with conflicting "
                        "specification admission policies.",
                    )
                admission = registry._admission
        return evolve(
            self,
            anchors=anchors,
            resources=resources,
            uncrawled=uncrawled,
            retrieve=retrieve,
            admission=admission,
        )

    def resolver(self, base_uri: URI = "") -> Resolver[D]:
        """
        Return a `Resolver` which resolves references against this registry.
        """
        return Resolver(base_uri=base_uri, registry=self)

    def resolver_with_root(self, resource: Resource[D]) -> Resolver[D]:
        """
        Return a `Resolver` with a specific root resource.
        """
        uri = resource.id() or ""
        return Resolver(
            base_uri=uri,
            registry=self.with_resource(uri, resource),
        )


#: An anchor or resource.
AnchorOrResource = TypeVar(
    "AnchorOrResource",
    AnchorType[Any],
    Resource[Any],
    default=Resource[Any],
)


@frozen
class Retrieved(Generic[D, AnchorOrResource]):
    """
    A value retrieved from a `Registry`.
    """

    value: AnchorOrResource
    registry: Registry[D]


@frozen
class Resolved(Generic[D]):
    """
    A reference resolved to its contents by a `Resolver`.
    """

    contents: D
    resolver: Resolver[D]


@frozen
class Resolver(Generic[D]):
    """
    A reference resolver.

    Resolvers help resolve references (including relative ones) by
    pairing a fixed base URI with a `Registry`.

    This object, under normal circumstances, is expected to be used by
    *implementers of libraries* built on top of `referencing` (e.g. JSON Schema
    implementations or other libraries resolving JSON references),
    not directly by end-users populating registries or while writing
    schemas or other resources.

    References are resolved against the base URI, and the combined URI
    is then looked up within the registry.

    The process of resolving a reference may itself involve calculating
    a *new* base URI for future reference resolution (e.g. if an
    intermediate resource sets a new base URI), or may involve encountering
    additional subresources and adding them to a new registry.
    """

    _base_uri: URI = field(alias="base_uri")
    _registry: Registry[D] = field(alias="registry")
    _previous: List[URI] = field(default=List(), repr=False, alias="previous")

    @property
    def admission(self) -> SpecificationAdmission[D] | None:
        """
        The `SpecificationAdmission` policy governing this resolver, if any.

        The policy is carried by the underlying registry and therefore
        follows the resolver across root and embedded resources.
        """
        return self._registry.admission

    def lookup(self, ref: URI) -> Resolved[D]:
        """
        Resolve the given reference to the resource it points to.

        Raises:

            `exceptions.Unresolvable`

                or a subclass thereof (see below) if the reference isn't
                resolvable

            `exceptions.NoSuchAnchor`

                if the reference is to a URI where a resource exists but
                contains a plain name fragment which does not exist within
                the resource

            `exceptions.PointerToNowhere`

                if the reference is to a URI where a resource exists but
                contains a JSON pointer to a location within the resource
                that does not exist

        """
        if ref.startswith("#"):
            uri, fragment = self._base_uri, ref[1:]
        else:
            uri, fragment = urldefrag(urljoin(self._base_uri, ref))
        try:
            retrieved = self._registry.get_or_retrieve(uri)
        except exceptions.NoSuchResource:
            raise exceptions.Unresolvable(ref=ref) from None
        except exceptions.Unretrievable as error:
            raise exceptions.Unresolvable(ref=ref) from error

        if fragment.startswith("/"):
            resolver = self._evolve(registry=retrieved.registry, base_uri=uri)
            return retrieved.value.pointer(pointer=fragment, resolver=resolver)

        if fragment:
            retrieved = retrieved.registry.anchor(uri, fragment)
            resolver = self._evolve(registry=retrieved.registry, base_uri=uri)
            return retrieved.value.resolve(resolver=resolver)

        resolver = self._evolve(registry=retrieved.registry, base_uri=uri)
        return Resolved(contents=retrieved.value.contents, resolver=resolver)

    def in_subresource(self, subresource: Resource[D]) -> Resolver[D]:
        """
        Create a resolver for a subresource (which may have a new base URI).
        """
        id = subresource.id()
        if id is None:
            return self
        return evolve(self, base_uri=urljoin(self._base_uri, id))

    def dynamic_scope(self) -> Iterable[tuple[URI, Registry[D]]]:
        """
        In specs with such a notion, return the URIs in the dynamic scope.
        """
        for uri in self._previous:
            yield uri, self._registry

    def _evolve(self, base_uri: URI, **kwargs: Any):
        """
        Evolve, appending to the dynamic scope.
        """
        previous = self._previous
        if self._base_uri and (not previous or base_uri != self._base_uri):
            previous = previous.push_front(self._base_uri)
        return evolve(self, base_uri=base_uri, previous=previous, **kwargs)


@frozen
class Anchor(Generic[D]):
    """
    A simple anchor in a `Resource`.
    """

    name: str
    resource: Resource[D]

    def resolve(self, resolver: Resolver[D]):
        """
        Return the resource for this anchor.
        """
        return Resolved(contents=self.resource.contents, resolver=resolver)
