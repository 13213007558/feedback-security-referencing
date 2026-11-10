import pytest

from referencing import (
    OnConflict,
    Registry,
    Resource,
    ResourcePolicy,
    exceptions,
)
from referencing.jsonschema import DRAFT202012

VENDOR = "https://vendor.example/schemas/"
RESERVED = "https://schema.ours.internal/"
SPEC = DRAFT202012


def policy(allowed=(VENDOR,), **kwargs):
    return ResourcePolicy(allowed=allowed, **kwargs)


def resource(contents):
    return SPEC.create_resource(contents)


def registry(*pairs, **kwargs):
    return Registry(policy=policy(**kwargs)).with_resources(list(pairs))


class TestResourcePolicy:
    def test_allows_exact_and_prefix(self):
        scope = policy(
            allowed=("https://vendor.example/schemas/", "urn:fixed"),
        )
        assert scope.allows("https://vendor.example/schemas/a.json")
        assert scope.allows("urn:fixed")
        assert not scope.allows("https://vendor.example/other")
        assert not scope.allows("https://evil.example/schemas/a.json")

    def test_out_of_scope_carries_uri_source_and_ranges(self):
        scope = policy()
        error = exceptions.URIOutsideScope(
            uri=RESERVED + "admin.json",
            source=VENDOR + "root.json",
            allowed=(VENDOR,),
        )
        with pytest.raises(exceptions.URIOutsideScope) as caught:
            scope.check_scope(RESERVED + "admin.json", VENDOR + "root.json")
        assert caught.value == error
        message = str(caught.value)
        assert RESERVED + "admin.json" in message
        assert VENDOR + "root.json" in message
        assert VENDOR in message

    def test_conflict_message_never_contains_contents(self):
        secret = {"$id": VENDOR + "a.json", "password": "hunter2"}
        scope = policy()
        with pytest.raises(exceptions.ConflictingResource) as caught:
            scope.check_conflict(
                uri=VENDOR + "a.json",
                existing=resource(secret),
                resource=resource({"$id": VENDOR + "a.json", "v": 2}),
                source=VENDOR + "b.json",
            )
        message = str(caught.value)
        assert VENDOR + "a.json" in message
        assert VENDOR + "b.json" in message
        assert "hunter2" not in message
        assert "password" not in message


class TestRegistration:
    def test_root_resource_must_be_in_scope(self):
        with pytest.raises(exceptions.URIOutsideScope) as caught:
            registry((RESERVED + "root.json", resource({"type": "object"})))
        assert caught.value.uri == RESERVED + "root.json"
        assert caught.value.source == RESERVED + "root.json"

    def test_self_reported_id_must_be_in_scope(self):
        root = resource({"$id": RESERVED + "root.json"})
        with pytest.raises(exceptions.URIOutsideScope) as caught:
            root @ Registry(policy=policy())
        assert caught.value.uri == RESERVED + "root.json"

    def test_in_scope_registration_succeeds(self):
        root = resource({"$id": VENDOR + "root.json", "type": "object"})
        reg = root @ Registry(policy=policy())
        assert reg[VENDOR + "root.json"] == root

    def test_failure_does_not_half_register(self):
        original = registry(
            (VENDOR + "keep.json", resource({"type": "object"})),
        )
        before = set(original)
        with pytest.raises(exceptions.URIOutsideScope):
            original.with_resources(
                [
                    (VENDOR + "new.json", resource({})),
                    (RESERVED + "bad.json", resource({})),
                ],
            )
        assert set(original) == before

    def test_identical_reregistration_is_idempotent(self):
        uri = VENDOR + "same.json"
        contents = {"$id": uri, "type": "object"}
        reg = registry((uri, resource(contents)))
        again = reg.with_resource(uri, resource(dict(contents)))
        assert len(again) == 1
        assert again[uri] == resource(contents)

    def test_different_contents_at_same_uri_rejected(self):
        uri = VENDOR + "dup.json"
        reg = registry((uri, resource({"$id": uri, "v": 1})))
        with pytest.raises(exceptions.ConflictingResource) as caught:
            reg.with_resource(uri, resource({"$id": uri, "v": 2}))
        assert caught.value.uri == uri
        assert caught.value.source == uri

    def test_replace_policy_keeps_lenient_overwrite(self):
        uri = VENDOR + "dup.json"
        reg = registry(
            (uri, resource({"$id": uri, "v": 1})),
            on_conflict=OnConflict.REPLACE,
        )
        replaced = reg.with_resource(uri, resource({"$id": uri, "v": 2}))
        assert replaced[uri].contents == {"$id": uri, "v": 2}


class TestCrawl:
    def test_nested_relative_ids_resolve_within_scope(self):
        root = {
            "$id": VENDOR + "root.json",
            "$defs": {
                "child": {"$id": "child.json", "type": "object"},
                "nested": {
                    "$id": "nested/",
                    "$defs": {"deep": {"$id": "deep.json"}},
                },
            },
        }
        crawled = registry((VENDOR + "root.json", resource(root))).crawl()
        assert set(crawled) == {
            VENDOR + "root.json",
            VENDOR + "child.json",
            VENDOR + "nested/",
            VENDOR + "nested/deep.json",
        }

    def test_cross_namespace_absolute_id_rejected(self):
        root = {
            "$id": VENDOR + "evil.json",
            "$defs": {
                "escape": {"$id": RESERVED + "admin.json"},
            },
        }
        reg = registry((VENDOR + "evil.json", resource(root)))
        with pytest.raises(exceptions.URIOutsideScope) as caught:
            reg.crawl()
        assert caught.value.uri == RESERVED + "admin.json"
        assert caught.value.source == VENDOR + "evil.json"

    def test_relative_id_resolving_outside_scope_rejected(self):
        root = {
            "$id": VENDOR + "root.json",
            "$defs": {
                # Resolves against the root URI and escapes the prefix.
                "escape": {"$id": "../escape.json"},
            },
        }
        reg = registry((VENDOR + "root.json", resource(root)))
        with pytest.raises(exceptions.URIOutsideScope) as caught:
            reg.crawl()
        assert caught.value.uri == "https://vendor.example/escape.json"

    def test_same_root_different_alias_conflicts(self):
        owner = {"$id": VENDOR + "shared.json", "v": 1}
        importer = {
            "$id": VENDOR + "other.json",
            "$defs": {"dup": {"$id": "shared.json", "v": 2}},
        }
        reg = registry(
            (VENDOR + "shared.json", resource(owner)),
            (VENDOR + "other.json", resource(importer)),
        )
        with pytest.raises(exceptions.ConflictingResource) as caught:
            reg.crawl()
        assert caught.value.uri == VENDOR + "shared.json"
        assert caught.value.source == VENDOR + "other.json"

    def test_same_alias_identical_contents_are_idempotent(self):
        shared = {"$id": VENDOR + "shared.json", "v": 1}
        importer = {
            "$id": VENDOR + "other.json",
            "$defs": {"dup": dict(shared)},
        }
        reg = registry(
            (VENDOR + "shared.json", resource(dict(shared))),
            (VENDOR + "other.json", resource(importer)),
        )
        crawled = reg.crawl()
        assert crawled[VENDOR + "shared.json"].contents == shared
        # Re-crawling an already fully crawled registry stays idempotent.
        assert crawled.crawl() == crawled

    @pytest.mark.parametrize("reversed_order", [False, True])
    def test_conflict_is_independent_of_import_order(self, reversed_order):
        first = {"$id": VENDOR + "m.json", "v": "m"}
        second = {
            "$id": VENDOR + "n.json",
            "$defs": {"dup": {"$id": "m.json", "v": "n"}},
        }
        pairs = [
            (VENDOR + "m.json", resource(first)),
            (VENDOR + "n.json", resource(second)),
        ]
        if reversed_order:
            pairs.reverse()
        reg = registry(*pairs)
        with pytest.raises(exceptions.ConflictingResource) as caught:
            reg.crawl()
        assert caught.value.uri == VENDOR + "m.json"
        assert caught.value.source == VENDOR + "n.json"

    def test_failed_crawl_keeps_original_registry(self):
        root = {
            "$id": VENDOR + "root.json",
            "$defs": {"escape": {"$id": RESERVED + "admin.json"}},
        }
        reg = registry((VENDOR + "root.json", resource(root)))
        uncrawled = set(reg._uncrawled)
        with pytest.raises(exceptions.URIOutsideScope):
            reg.crawl()
        assert set(reg._uncrawled) == uncrawled
        assert set(reg) == {VENDOR + "root.json"}


class TestRetrieval:
    def test_out_of_scope_uri_never_calls_retriever(self):
        calls = []

        def retrieve(uri):  # pragma: no cover
            calls.append(uri)
            return resource({"$id": uri})

        reg = Registry(policy=policy(), retrieve=retrieve)
        with pytest.raises(exceptions.URIOutsideScope):
            reg.get_or_retrieve(RESERVED + "secret.json")
        assert calls == []

    def test_in_scope_retrieval_is_allowed(self):
        fetched = resource({"$id": VENDOR + "fetched.json"})
        reg = Registry(policy=policy(), retrieve=lambda uri: fetched)
        assert reg.get_or_retrieve(VENDOR + "fetched.json").value == fetched


class TestDefaultCompatibility:
    def test_registry_without_policy_keeps_lenient_overwrite(self):
        uri = "urn:example:dup"
        reg = Registry().with_resource(uri, Resource.opaque({"v": 1}))
        reg = reg.with_resource(uri, Resource.opaque({"v": 2}))
        assert reg[uri].contents == {"v": 2}

    def test_registry_without_policy_allows_any_namespace(self):
        reg = Registry().with_resource(
            RESERVED + "root.json",
            resource({"type": "object"}),
        )
        assert RESERVED + "root.json" in reg
