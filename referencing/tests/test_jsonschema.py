import pytest

from referencing import Registry, Resource, Specification
from referencing._core import Resolved
import referencing.jsonschema


@pytest.mark.parametrize(
    "uri, expected",
    [
        (
            "https://json-schema.org/draft/2020-12/schema",
            referencing.jsonschema.DRAFT202012,
        ),
        (
            "https://json-schema.org/draft/2019-09/schema",
            referencing.jsonschema.DRAFT201909,
        ),
        (
            "http://json-schema.org/draft-07/schema#",
            referencing.jsonschema.DRAFT7,
        ),
        (
            "http://json-schema.org/draft-06/schema#",
            referencing.jsonschema.DRAFT6,
        ),
        (
            "http://json-schema.org/draft-04/schema#",
            referencing.jsonschema.DRAFT4,
        ),
        (
            "http://json-schema.org/draft-03/schema#",
            referencing.jsonschema.DRAFT3,
        ),
    ],
)
def test_schemas_with_explicit_schema_keywords_are_detected(uri, expected):
    """
    The $schema keyword in JSON Schema is a dialect identifier.
    """
    contents = {"$schema": uri}
    resource = Resource.from_contents(contents)
    assert resource == Resource(contents=contents, specification=expected)


def test_unknown_dialect():
    dialect_id = "http://example.com/unknown-json-schema-dialect-id"
    with pytest.raises(referencing.jsonschema.UnknownDialect) as excinfo:
        Resource.from_contents({"$schema": dialect_id})
    assert excinfo.value.uri == dialect_id


@pytest.mark.parametrize(
    "id, specification",
    [
        ("$id", referencing.jsonschema.DRAFT202012),
        ("$id", referencing.jsonschema.DRAFT201909),
        ("$id", referencing.jsonschema.DRAFT7),
        ("$id", referencing.jsonschema.DRAFT6),
        ("id", referencing.jsonschema.DRAFT4),
        ("id", referencing.jsonschema.DRAFT3),
    ],
)
def test_id_of_mapping(id, specification):
    uri = "http://example.com/some-schema"
    assert specification.id_of({id: uri}) == uri


@pytest.mark.parametrize(
    "specification",
    [
        referencing.jsonschema.DRAFT202012,
        referencing.jsonschema.DRAFT201909,
        referencing.jsonschema.DRAFT7,
        referencing.jsonschema.DRAFT6,
    ],
)
@pytest.mark.parametrize("value", [True, False])
def test_id_of_bool(specification, value):
    assert specification.id_of(value) is None


@pytest.mark.parametrize(
    "specification",
    [
        referencing.jsonschema.DRAFT202012,
        referencing.jsonschema.DRAFT201909,
        referencing.jsonschema.DRAFT7,
        referencing.jsonschema.DRAFT6,
    ],
)
@pytest.mark.parametrize("value", [True, False])
def test_anchors_in_bool(specification, value):
    assert list(specification.anchors_in(value)) == []


@pytest.mark.parametrize(
    "specification",
    [
        referencing.jsonschema.DRAFT202012,
        referencing.jsonschema.DRAFT201909,
        referencing.jsonschema.DRAFT7,
        referencing.jsonschema.DRAFT6,
    ],
)
@pytest.mark.parametrize("value", [True, False])
def test_subresources_of_bool(specification, value):
    assert list(specification.subresources_of(value)) == []


@pytest.mark.parametrize(
    "uri, expected",
    [
        (
            "https://json-schema.org/draft/2020-12/schema",
            referencing.jsonschema.DRAFT202012,
        ),
        (
            "https://json-schema.org/draft/2019-09/schema",
            referencing.jsonschema.DRAFT201909,
        ),
        (
            "http://json-schema.org/draft-07/schema#",
            referencing.jsonschema.DRAFT7,
        ),
        (
            "http://json-schema.org/draft-06/schema#",
            referencing.jsonschema.DRAFT6,
        ),
        (
            "http://json-schema.org/draft-04/schema#",
            referencing.jsonschema.DRAFT4,
        ),
        (
            "http://json-schema.org/draft-03/schema#",
            referencing.jsonschema.DRAFT3,
        ),
    ],
)
def test_specification_with(uri, expected):
    assert referencing.jsonschema.specification_with(uri) == expected


@pytest.mark.parametrize(
    "uri, expected",
    [
        (
            "http://json-schema.org/draft-07/schema",
            referencing.jsonschema.DRAFT7,
        ),
        (
            "http://json-schema.org/draft-06/schema",
            referencing.jsonschema.DRAFT6,
        ),
        (
            "http://json-schema.org/draft-04/schema",
            referencing.jsonschema.DRAFT4,
        ),
        (
            "http://json-schema.org/draft-03/schema",
            referencing.jsonschema.DRAFT3,
        ),
    ],
)
def test_specification_with_no_empty_fragment(uri, expected):
    assert referencing.jsonschema.specification_with(uri) == expected


def test_specification_with_unknown_dialect():
    dialect_id = "http://example.com/unknown-json-schema-dialect-id"
    with pytest.raises(referencing.jsonschema.UnknownDialect) as excinfo:
        referencing.jsonschema.specification_with(dialect_id)
    assert excinfo.value.uri == dialect_id


def test_specification_with_default():
    dialect_id = "http://example.com/unknown-json-schema-dialect-id"
    specification = referencing.jsonschema.specification_with(
        dialect_id,
        default=Specification.OPAQUE,
    )
    assert specification is Specification.OPAQUE


# FIXME: The tests below should move to the referencing suite but I haven't yet
#        figured out how to represent dynamic (& recursive) ref lookups in it.
def test_lookup_trivial_dynamic_ref():
    one = referencing.jsonschema.DRAFT202012.create_resource(
        {"$dynamicAnchor": "foo"},
    )
    resolver = Registry().with_resource("http://example.com", one).resolver()
    resolved = resolver.lookup("http://example.com#foo")
    assert resolved.contents == one.contents


def test_multiple_lookup_trivial_dynamic_ref():
    TRUE = referencing.jsonschema.DRAFT202012.create_resource(True)
    root = referencing.jsonschema.DRAFT202012.create_resource(
        {
            "$id": "http://example.com",
            "$dynamicAnchor": "fooAnchor",
            "$defs": {
                "foo": {
                    "$id": "foo",
                    "$dynamicAnchor": "fooAnchor",
                    "$defs": {
                        "bar": True,
                        "baz": {
                            "$dynamicAnchor": "fooAnchor",
                        },
                    },
                },
            },
        },
    )
    resolver = (
        Registry()
        .with_resources(
            [
                ("http://example.com", root),
                ("http://example.com/foo/", TRUE),
                ("http://example.com/foo/bar", root),
            ],
        )
        .resolver()
    )

    first = resolver.lookup("http://example.com")
    second = first.resolver.lookup("foo/")
    resolver = second.resolver.lookup("bar").resolver
    fourth = resolver.lookup("#fooAnchor")
    assert fourth.contents == root.contents


def test_multiple_lookup_dynamic_ref_to_nondynamic_ref():
    one = referencing.jsonschema.DRAFT202012.create_resource(
        {"$anchor": "fooAnchor"},
    )
    two = referencing.jsonschema.DRAFT202012.create_resource(
        {
            "$id": "http://example.com",
            "$dynamicAnchor": "fooAnchor",
            "$defs": {
                "foo": {
                    "$id": "foo",
                    "$dynamicAnchor": "fooAnchor",
                    "$defs": {
                        "bar": True,
                        "baz": {
                            "$dynamicAnchor": "fooAnchor",
                        },
                    },
                },
            },
        },
    )
    resolver = (
        Registry()
        .with_resources(
            [
                ("http://example.com", two),
                ("http://example.com/foo/", one),
                ("http://example.com/foo/bar", two),
            ],
        )
        .resolver()
    )

    first = resolver.lookup("http://example.com")
    second = first.resolver.lookup("foo/")
    resolver = second.resolver.lookup("bar").resolver
    fourth = resolver.lookup("#fooAnchor")
    assert fourth.contents == two.contents


def test_lookup_trivial_recursive_ref():
    one = referencing.jsonschema.DRAFT201909.create_resource(
        {"$recursiveAnchor": True},
    )
    resolver = Registry().with_resource("http://example.com", one).resolver()
    first = resolver.lookup("http://example.com")
    resolved = referencing.jsonschema.lookup_recursive_ref(
        resolver=first.resolver,
    )
    assert resolved.contents == one.contents


def test_lookup_recursive_ref_to_bool():
    TRUE = referencing.jsonschema.DRAFT201909.create_resource(True)
    registry = Registry({"http://example.com": TRUE})
    resolved = referencing.jsonschema.lookup_recursive_ref(
        resolver=registry.resolver(base_uri="http://example.com"),
    )
    assert resolved.contents == TRUE.contents


def test_multiple_lookup_recursive_ref_to_bool():
    TRUE = referencing.jsonschema.DRAFT201909.create_resource(True)
    root = referencing.jsonschema.DRAFT201909.create_resource(
        {
            "$id": "http://example.com",
            "$recursiveAnchor": True,
            "$defs": {
                "foo": {
                    "$id": "foo",
                    "$recursiveAnchor": True,
                    "$defs": {
                        "bar": True,
                        "baz": {
                            "$recursiveAnchor": True,
                            "$anchor": "fooAnchor",
                        },
                    },
                },
            },
        },
    )
    resolver = (
        Registry()
        .with_resources(
            [
                ("http://example.com", root),
                ("http://example.com/foo/", TRUE),
                ("http://example.com/foo/bar", root),
            ],
        )
        .resolver()
    )

    first = resolver.lookup("http://example.com")
    second = first.resolver.lookup("foo/")
    resolver = second.resolver.lookup("bar").resolver
    fourth = referencing.jsonschema.lookup_recursive_ref(resolver=resolver)
    assert fourth.contents == root.contents


def test_multiple_lookup_recursive_ref_with_nonrecursive_ref():
    one = referencing.jsonschema.DRAFT201909.create_resource(
        {"$recursiveAnchor": True},
    )
    two = referencing.jsonschema.DRAFT201909.create_resource(
        {
            "$id": "http://example.com",
            "$recursiveAnchor": True,
            "$defs": {
                "foo": {
                    "$id": "foo",
                    "$recursiveAnchor": True,
                    "$defs": {
                        "bar": True,
                        "baz": {
                            "$recursiveAnchor": True,
                            "$anchor": "fooAnchor",
                        },
                    },
                },
            },
        },
    )
    three = referencing.jsonschema.DRAFT201909.create_resource(
        {"$recursiveAnchor": False},
    )
    resolver = (
        Registry()
        .with_resources(
            [
                ("http://example.com", three),
                ("http://example.com/foo/", two),
                ("http://example.com/foo/bar", one),
            ],
        )
        .resolver()
    )

    first = resolver.lookup("http://example.com")
    second = first.resolver.lookup("foo/")
    resolver = second.resolver.lookup("bar").resolver
    fourth = referencing.jsonschema.lookup_recursive_ref(resolver=resolver)
    assert fourth.contents == two.contents


def test_empty_registry():
    assert referencing.jsonschema.EMPTY_REGISTRY == Registry()


# A regression corpus for `$dynamicRef` resolution which makes the dynamic
# scope visible at every step.
#
# Three levels of resources share one `$dynamicAnchor` name ("node"):
#
#     entry-a --+                 each of entry-a / entry-b / mid / inner
#     entry-b --+--> mid --> inner    defines `$dynamicAnchor: "node"`
#
# plus a parallel chain (plain-entry --> plain-mid --> inner) where the
# outer two levels define *no* matching dynamic anchor, and plain `$anchor`
# targets which must never be resolved dynamically.
#
# Every step below asserts the fully-resolved target contents *and* the
# exact URIs on the resolver's dynamic scope, so a failure pinpoints the
# step whose stack diverged from the expected one.

_NODE_A = "https://example.com/entry-a"
_NODE_B = "https://example.com/entry-b"
_NODE_MID = "https://example.com/mid"
_NODE_INNER = "https://example.com/inner"
_PLAIN_ENTRY = "https://example.com/plain-entry"
_PLAIN_MID = "https://example.com/plain-mid"

_ENTRY_A_CONTENTS = {
    "$id": _NODE_A,
    "$dynamicAnchor": "node",
    "const": "entry-a",
    "$defs": {"plain": {"$anchor": "plain", "const": "plain-in-entry-a"}},
}
_ENTRY_B_CONTENTS = {
    "$id": _NODE_B,
    "$dynamicAnchor": "node",
    "const": "entry-b",
}
_MID_CONTENTS = {
    "$id": _NODE_MID,
    "$dynamicAnchor": "node",
    "const": "mid",
}
_INNER_CONTENTS = {
    "$id": _NODE_INNER,
    "$dynamicAnchor": "node",
    "const": "inner",
    "$defs": {"plain": {"$anchor": "plain", "const": "plain-in-inner"}},
}
_PLAIN_ENTRY_CONTENTS = {
    "$id": _PLAIN_ENTRY,
    "const": "plain-entry",
}
_PLAIN_MID_CONTENTS = {
    "$id": _PLAIN_MID,
    "const": "plain-mid",
}


def _dynamic_scope_corpus_registry():
    """
    A single registry holding all six corpus resources.
    """
    resources = [
        (_NODE_A, _ENTRY_A_CONTENTS),
        (_NODE_B, _ENTRY_B_CONTENTS),
        (_NODE_MID, _MID_CONTENTS),
        (_NODE_INNER, _INNER_CONTENTS),
        (_PLAIN_ENTRY, _PLAIN_ENTRY_CONTENTS),
        (_PLAIN_MID, _PLAIN_MID_CONTENTS),
    ]
    return Registry().with_resources(
        [
            (uri, referencing.jsonschema.DRAFT202012.create_resource(contents))
            for uri, contents in resources
        ],
    )


def _check_step(step, resolved, expected_contents, expected_scope):
    """
    Assert one corpus step, identifying the step on failure.
    """
    assert resolved.contents == expected_contents, (
        f"step {step}: resolved to the wrong target "
        f"(got {resolved.contents!r}, expected {expected_contents!r})"
    )
    scope = [uri for uri, _ in resolved.resolver.dynamic_scope()]
    assert scope == expected_scope, (
        f"step {step}: dynamic scope {scope!r} "
        f"!= expected {expected_scope!r}"
    )


def _run_dynamic_scope_corpus():
    """
    Drive the corpus, asserting target and dynamic scope at each step.
    """
    resolver = _dynamic_scope_corpus_registry().resolver()

    # Enter the shared mid -> inner chain once per entry schema,
    # interleaved through the *same* registry and root resolver.
    entry_a = resolver.lookup(_NODE_A)
    _check_step("enter entry-a", entry_a, _ENTRY_A_CONTENTS, [])
    entry_b = resolver.lookup(_NODE_B)
    _check_step("enter entry-b", entry_b, _ENTRY_B_CONTENTS, [])

    mid_via_a = entry_a.resolver.lookup("mid")
    _check_step("entry-a -> mid", mid_via_a, _MID_CONTENTS, [_NODE_A])
    mid_via_b = entry_b.resolver.lookup("mid")
    _check_step("entry-b -> mid", mid_via_b, _MID_CONTENTS, [_NODE_B])

    inner_via_a = mid_via_a.resolver.lookup("inner")
    _check_step(
        "entry-a -> mid -> inner",
        inner_via_a,
        _INNER_CONTENTS,
        [_NODE_MID, _NODE_A],
    )
    inner_via_b = mid_via_b.resolver.lookup("inner")
    _check_step(
        "entry-b -> mid -> inner",
        inner_via_b,
        _INNER_CONTENTS,
        [_NODE_MID, _NODE_B],
    )

    # The same `$dynamicRef: "#node"` at inner must land on *different*
    # outermost dynamic anchors depending on the entry schema.
    node_via_a = inner_via_a.resolver.lookup("#node")
    _check_step(
        "#node via entry-a",
        node_via_a,
        _ENTRY_A_CONTENTS,
        [_NODE_MID, _NODE_A],
    )
    node_via_b = inner_via_b.resolver.lookup("#node")
    _check_step(
        "#node via entry-b",
        node_via_b,
        _ENTRY_B_CONTENTS,
        [_NODE_MID, _NODE_B],
    )

    # Recursion: re-enter the chain from the resolved target. The scope
    # keeps growing and `#node` still resolves to the outermost entry.
    recur_mid = node_via_a.resolver.lookup("mid")
    _check_step(
        "recurse: entry-a -> mid",
        recur_mid,
        _MID_CONTENTS,
        [_NODE_A, _NODE_MID, _NODE_A],
    )
    recur_inner = recur_mid.resolver.lookup("inner")
    _check_step(
        "recurse: entry-a -> mid -> inner",
        recur_inner,
        _INNER_CONTENTS,
        [_NODE_MID, _NODE_A, _NODE_MID, _NODE_A],
    )
    recur_node = recur_inner.resolver.lookup("#node")
    _check_step(
        "recurse: #node still entry-a",
        recur_node,
        _ENTRY_A_CONTENTS,
        [_NODE_MID, _NODE_A, _NODE_MID, _NODE_A],
    )

    # Back at the outer levels, fresh lookups from the saved resolvers
    # are unaffected by the deeper ones above.
    again_from_a = entry_a.resolver.lookup("#node")
    _check_step(
        "outer #node from entry-a",
        again_from_a,
        _ENTRY_A_CONTENTS,
        [_NODE_A],
    )
    again_from_mid = mid_via_a.resolver.lookup("#node")
    _check_step(
        "outer #node from mid",
        again_from_mid,
        _ENTRY_A_CONTENTS,
        [_NODE_A],
    )
    again_from_inner = inner_via_a.resolver.lookup("#node")
    _check_step(
        "repeat #node via entry-a",
        again_from_inner,
        _ENTRY_A_CONTENTS,
        [_NODE_MID, _NODE_A],
    )

    # A chain whose outer resources define no matching `$dynamicAnchor`:
    # the `$dynamicRef` falls back to its statically resolved bookend.
    plain_entry = resolver.lookup(_PLAIN_ENTRY)
    _check_step("enter plain-entry", plain_entry, _PLAIN_ENTRY_CONTENTS, [])
    plain_mid = plain_entry.resolver.lookup("plain-mid")
    _check_step(
        "plain-entry -> plain-mid",
        plain_mid,
        _PLAIN_MID_CONTENTS,
        [_PLAIN_ENTRY],
    )
    inner_via_plain = plain_mid.resolver.lookup("inner")
    _check_step(
        "plain-entry -> plain-mid -> inner",
        inner_via_plain,
        _INNER_CONTENTS,
        [_PLAIN_MID, _PLAIN_ENTRY],
    )
    node_via_plain = inner_via_plain.resolver.lookup("#node")
    _check_step(
        "#node without outer dynamic anchors",
        node_via_plain,
        _INNER_CONTENTS,
        [_PLAIN_MID, _PLAIN_ENTRY],
    )

    # Control: a plain `$anchor` of the same name in two resources must
    # resolve statically to the inner one -- never dynamically outward.
    plain_anchor = inner_via_a.resolver.lookup("#plain")
    _check_step(
        "plain $anchor stays static",
        plain_anchor,
        {"$anchor": "plain", "const": "plain-in-inner"},
        [_NODE_MID, _NODE_A],
    )


def test_dynamic_ref_scope_corpus():
    _run_dynamic_scope_corpus()


def test_dynamic_ref_scope_corpus_detects_scope_ignoring_mutant(monkeypatch):
    """
    The corpus fails if `$dynamicRef` ignores the dynamic scope.

    A resolver which always returns the statically resolved bookend (and
    never walks the dynamic scope) must not pass the corpus.
    """

    def resolve_without_dynamic_scope(self, resolver):
        return Resolved(
            contents=self.resource.contents,
            resolver=resolver.in_subresource(self.resource),
        )

    monkeypatch.setattr(
        referencing.jsonschema.DynamicAnchor,
        "resolve",
        resolve_without_dynamic_scope,
    )
    with pytest.raises(AssertionError, match="step #node via entry-a"):
        _run_dynamic_scope_corpus()


def test_dynamic_ref_scope_corpus_detects_stale_target_mutant(monkeypatch):
    """
    The corpus fails if a `$dynamicRef` wrongly reuses its last target.

    A resolver which caches the first dynamically resolved target and
    reuses it for later lookups (regardless of the dynamic scope) must
    not pass the corpus.
    """
    original = referencing.jsonschema.DynamicAnchor.resolve
    cached = {}

    def resolve_reusing_last_target(self, resolver):
        if self.name not in cached:
            cached[self.name] = original(self, resolver)
        return cached[self.name]

    monkeypatch.setattr(
        referencing.jsonschema.DynamicAnchor,
        "resolve",
        resolve_reusing_last_target,
    )
    with pytest.raises(AssertionError, match="step #node via entry-b"):
        _run_dynamic_scope_corpus()
