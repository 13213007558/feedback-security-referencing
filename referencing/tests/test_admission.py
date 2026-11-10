"""
Tests for `SpecificationAdmission` policies.

These tests describe the security-relevant behavior: an admission policy
follows resources through a `Registry` and `Resolver`, checking dialects
declared by both root and embedded resources, while leaving the default,
policy-free behavior unchanged.
"""

import pytest

import referencing.jsonschema
from referencing import (
    Registry,
    Resource,
    Specification,
    SpecificationAdmission,
    exceptions,
)
from referencing.jsonschema import (
    DRAFT3,
    DRAFT4,
    DRAFT6,
    DRAFT7,
    DRAFT201909,
    DRAFT202012,
)

D202012 = "https://json-schema.org/draft/2020-12/schema"
D201909 = "https://json-schema.org/draft/2019-09/schema"
D07 = "http://json-schema.org/draft-07/schema#"
D06 = "http://json-schema.org/draft-06/schema"
D04 = "http://json-schema.org/draft-04/schema"
D03 = "http://json-schema.org/draft-03/schema"
UNKNOWN = "https://example.com/unknown-dialect"


def admission_2020_7():
    return SpecificationAdmission.admitting(
        [DRAFT202012, DRAFT7],
        default=DRAFT202012,
    )


class TestSpecificationAdmission:
    def test_admitting_records_allowed_and_default(self):
        admission = admission_2020_7()
        assert admission.allowed == frozenset([DRAFT202012, DRAFT7])
        assert admission.default is DRAFT202012

    def test_admitting_accepts_any_iterable(self):
        admission = SpecificationAdmission.admitting(
            (each for each in [DRAFT202012, DRAFT7]),
        )
        assert admission.allowed == frozenset([DRAFT202012, DRAFT7])

    def test_admitting_defaults_to_one_of_the_admitted(self):
        allowed = [DRAFT7, DRAFT202012]
        admission = SpecificationAdmission.admitting(allowed)
        # Without an explicit default, some admitted specification is used.
        assert admission.default in frozenset(allowed)

    def test_admitting_requires_at_least_one_specification(self):
        with pytest.raises(ValueError, match="at least one"):
            SpecificationAdmission.admitting([])

    def test_default_must_be_admitted(self):
        with pytest.raises(ValueError, match="default specification"):
            SpecificationAdmission(
                allowed=[DRAFT202012],
                default=DRAFT7,
            )

    def test_equal_policies_are_equal(self):
        assert admission_2020_7() == admission_2020_7()

    def test_detect_explicit_allowed_dialect(self):
        admission = admission_2020_7()
        assert admission.detect({"$schema": D07}) is DRAFT7
        assert admission.detect({"$schema": D202012}) is DRAFT202012

    def test_detect_without_schema_uses_default(self):
        admission = admission_2020_7()
        assert admission.detect({"type": "integer"}) is DRAFT202012

    @pytest.mark.parametrize("contents", [True, False, 37, "a string", None])
    def test_detect_non_mapping_uses_default(self, contents):
        admission = admission_2020_7()
        assert admission.detect(contents) is DRAFT202012

    def test_detect_unknown_dialect_uri(self):
        admission = admission_2020_7()
        with pytest.raises(exceptions.UnknownDialect) as info:
            admission.detect({"$schema": UNKNOWN})
        assert info.value == exceptions.UnknownDialect(uri=UNKNOWN)

    def test_detect_known_but_disallowed_dialect(self):
        admission = admission_2020_7()
        with pytest.raises(exceptions.DisallowedDialect) as info:
            admission.detect({"$schema": D04})
        assert info.value == exceptions.DisallowedDialect(
            uri=D04,
            specification=DRAFT4,
        )

    def test_unknown_and_disallowed_are_distinct_errors(self):
        admission = admission_2020_7()
        with pytest.raises(exceptions.UnknownDialect):
            admission.detect({"$schema": UNKNOWN})
        with pytest.raises(exceptions.DisallowedDialect):
            admission.detect({"$schema": D04})
        assert (
            exceptions.UnknownDialect(uri=UNKNOWN)
            != exceptions.DisallowedDialect(uri=D04, specification=DRAFT4)
        )

    def test_detect_non_string_schema_identifier(self):
        admission = admission_2020_7()
        with pytest.raises(exceptions.CannotDetermineSpecification):
            admission.detect({"$schema": 37})

    def test_unknown_dialect_is_not_treated_as_latest_draft(self):
        admission = admission_2020_7()
        with pytest.raises(exceptions.UnknownDialect):
            Resource.from_contents({"$schema": UNKNOWN}, admission)


class TestResourceFromContents:
    def test_root_with_allowed_explicit_dialect(self):
        contents = {"$schema": D07}
        resource = Resource.from_contents(contents, admission_2020_7())
        assert resource == Resource(contents=contents, specification=DRAFT7)

    def test_root_without_dialect_uses_policy_default(self):
        resource = Resource.from_contents(
            {"type": "integer"},
            admission_2020_7(),
        )
        assert resource == DRAFT202012.create_resource({"type": "integer"})

    def test_root_unknown_dialect(self):
        with pytest.raises(exceptions.UnknownDialect):
            Resource.from_contents(
                {"$schema": UNKNOWN},
                admission_2020_7(),
            )

    def test_root_disallowed_dialect(self):
        with pytest.raises(exceptions.DisallowedDialect) as info:
            Resource.from_contents(
                {"$schema": D04},
                admission_2020_7(),
            )
        assert info.value.uri == D04
        assert info.value.specification is DRAFT4

    def test_subresources_detect_under_admission(self):
        root = DRAFT202012.create_resource(
            {
                "$id": "urn:root",
                "$defs": {
                    "legacy": {"$schema": D07, "$id": "urn:legacy"},
                },
            },
        )
        subresources = list(root.subresources(admission_2020_7()))
        assert subresources == [
            DRAFT7.create_resource({"$schema": D07, "$id": "urn:legacy"}),
        ]

    def test_subresources_reject_disallowed_dialect(self):
        root = DRAFT202012.create_resource(
            {"$defs": {"old": {"$schema": D04}}},
        )
        with pytest.raises(exceptions.DisallowedDialect):
            list(root.subresources(admission_2020_7()))

    def test_subresources_without_admission_keep_original_behavior(self):
        root = DRAFT202012.create_resource(
            {"$defs": {"child": {"type": "integer"}}},
        )
        assert list(root.subresources()) == [
            DRAFT202012.create_resource({"type": "integer"}),
        ]


class TestRegistryAdmission:
    def test_registry_exposes_its_admission(self):
        admission = admission_2020_7()
        registry = Registry(admission=admission)
        assert registry.admission is admission

    def test_registry_without_admission(self):
        assert Registry().admission is None

    def test_with_contents_applies_policy_to_root(self):
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("urn:example", {"$schema": D07})],
        )
        assert registry["urn:example"] == DRAFT7.create_resource(
            {"$schema": D07},
        )

    def test_with_contents_default_when_no_dialect(self):
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("urn:example", {"type": "integer"})],
        )
        assert registry["urn:example"] == DRAFT202012.create_resource(
            {"type": "integer"},
        )

    def test_with_contents_rejects_disallowed_root(self):
        registry = Registry(admission=admission_2020_7())
        with pytest.raises(exceptions.DisallowedDialect):
            registry.with_contents([("urn:example", {"$schema": D04})])

    def test_with_contents_rejects_unknown_root(self):
        registry = Registry(admission=admission_2020_7())
        with pytest.raises(exceptions.UnknownDialect):
            registry.with_contents([("urn:example", {"$schema": UNKNOWN})])

    def test_explicit_resource_is_not_rechecked(self):
        # A directly constructed Resource is trusted even for a dialect the
        # policy would not admit via autodetection.
        resource = DRAFT4.create_resource({"id": "urn:legacy"})
        registry = Registry(admission=admission_2020_7()).with_resource(
            "urn:legacy",
            resource,
        )
        assert registry["urn:legacy"] is resource

    def test_explicit_default_specification_overrides_policy(self):
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("urn:example", {"type": "integer"})],
            default_specification=DRAFT7,
        )
        assert registry["urn:example"] == DRAFT7.create_resource(
            {"type": "integer"},
        )

    def test_crawl_checks_embedded_resource(self):
        root = {
            "$id": "https://example.com/root",
            "$schema": D202012,
            "$defs": {
                "legacy": {
                    "$schema": D07,
                    "$id": "legacy",
                    "type": "integer",
                },
            },
        }
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("https://example.com/root", root)],
        )
        crawled = registry.crawl()
        assert crawled["https://example.com/legacy"] == DRAFT7.create_resource(
            root["$defs"]["legacy"],
        )

    def test_crawl_rejects_embedded_disallowed_dialect(self):
        root = {
            "$id": "https://example.com/root",
            "$schema": D202012,
            "$defs": {"old": {"$schema": D04, "type": "integer"}},
        }
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("https://example.com/root", root)],
        )
        with pytest.raises(exceptions.DisallowedDialect) as info:
            registry.crawl()
        assert info.value.uri == D04
        assert info.value.specification is DRAFT4

    def test_crawl_rejects_embedded_unknown_dialect(self):
        root = {
            "$id": "https://example.com/root",
            "$schema": D202012,
            "$defs": {"mystery": {"$schema": UNKNOWN}},
        }
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("https://example.com/root", root)],
        )
        with pytest.raises(exceptions.UnknownDialect) as info:
            registry.crawl()
        assert info.value.uri == UNKNOWN

    def test_crawl_rejects_embedded_non_string_schema_identifier(self):
        root = {
            "$id": "https://example.com/root",
            "$schema": D202012,
            "$defs": {"broken": {"$schema": 123}},
        }
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("https://example.com/root", root)],
        )
        with pytest.raises(exceptions.CannotDetermineSpecification):
            registry.crawl()

    def test_bool_subresource_uses_policy_default(self):
        root = DRAFT202012.create_resource({"$defs": {"enabled": True}})
        assert list(root.subresources(admission_2020_7())) == [
            DRAFT202012.create_resource(True),
        ]

    def test_const_data_schema_keyword_does_not_switch_resource(self):
        root = {
            "$id": "urn:root",
            "$schema": D202012,
            "properties": {
                "payload": {"const": {"$schema": UNKNOWN}},
            },
        }
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("urn:root", root)],
        )
        # Crawling only enters real subschemas; the const value is opaque.
        assert list(registry.crawl()) == ["urn:root"]
        resolved = registry.resolver().lookup(
            "urn:root#/properties/payload/const",
        )
        assert resolved.contents == {"$schema": UNKNOWN}

    def test_combining_equal_admissions_preserves_policy(self):
        admission = admission_2020_7()
        combined = Registry(admission=admission).combine(
            Registry(admission=admission_2020_7()),
        )
        assert combined.admission == admission

    def test_combining_with_a_policy_free_registry(self):
        admission = admission_2020_7()
        combined = Registry(admission=admission).combine(Registry())
        assert combined.admission is admission
        combined = Registry().combine(Registry(admission=admission))
        assert combined.admission is admission

    def test_combining_conflicting_admissions_fails(self):
        strict = SpecificationAdmission.admitting([DRAFT7], default=DRAFT7)
        with pytest.raises(ValueError, match="admission"):
            Registry(admission=admission_2020_7()).combine(
                Registry(admission=strict),
            )

    def test_retrieved_resource_admission_error_is_not_wrapped(self):
        def retrieve(uri):
            return Resource.from_contents(
                {"$schema": D04},
                admission_2020_7(),
            )

        registry = Registry(
            retrieve=retrieve,
            admission=admission_2020_7(),
        )
        with pytest.raises(exceptions.DisallowedDialect):
            registry.get_or_retrieve("urn:retrieved")

    def test_retrieved_unknown_dialect_error_is_not_wrapped(self):
        def retrieve(uri):
            return Resource.from_contents(
                {"$schema": UNKNOWN},
                admission_2020_7(),
            )

        registry = Registry(
            retrieve=retrieve,
            admission=admission_2020_7(),
        )
        with pytest.raises(exceptions.UnknownDialect):
            registry.get_or_retrieve("urn:retrieved")


class TestResolverAdmission:
    def test_resolver_carries_admission(self):
        admission = admission_2020_7()
        resolver = Registry(admission=admission).resolver(base_uri="urn:base")
        assert resolver.admission is admission

    def test_resolver_without_admission(self):
        assert Registry().resolver().admission is None

    def test_resolver_with_root_keeps_admission(self):
        admission = admission_2020_7()
        registry = Registry(admission=admission)
        resolver = registry.resolver_with_root(
            DRAFT202012.create_resource({"$id": "urn:root"}),
        )
        assert resolver.admission is admission

    def test_lookup_legal_cross_draft_relative_reference(self):
        root = {
            "$id": "https://example.com/schemas/root",
            "$schema": D202012,
            "$ref": "legacy/child#/definitions/node",
            "$defs": {
                "legacy": {
                    "$schema": D07,
                    "$id": "legacy/child",
                    "definitions": {"node": {"type": "integer"}},
                },
            },
        }
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("https://example.com/schemas/root", root)],
        )
        resolver = registry.resolver(
            base_uri="https://example.com/schemas/root",
        )
        resolved = resolver.lookup("legacy/child#/definitions/node")
        assert resolved.contents == {"type": "integer"}
        # The policy follows the resolver into the embedded resource.
        assert resolved.resolver.admission == admission_2020_7()

    def test_lookup_resolves_embedded_resource_by_relative_id(self):
        root = {
            "$id": "https://example.com/schemas/root",
            "$schema": D202012,
            "$defs": {
                "legacy": {
                    "$schema": D07,
                    "$id": "legacy/child",
                    "type": "string",
                },
            },
        }
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("https://example.com/schemas/root", root)],
        )
        resolver = registry.resolver(
            base_uri="https://example.com/schemas/root",
        )
        resolved = resolver.lookup("legacy/child")
        assert resolved.contents == root["$defs"]["legacy"]

    def test_lookup_surfaces_embedded_disallowed_dialect_location(self):
        root = {
            "$id": "https://example.com/root",
            "$schema": D202012,
            "$defs": {"old": {"$schema": D04, "$id": "old"}},
        }
        registry = Registry(admission=admission_2020_7()).with_contents(
            [("https://example.com/root", root)],
        )
        # Resolving the embedded resource forces a crawl through the public
        # Resolver interface, surfacing the offending dialect identifier.
        with pytest.raises(exceptions.DisallowedDialect) as info:
            registry.resolver().lookup("https://example.com/old")
        assert info.value.uri == D04
        assert info.value.specification is DRAFT4

    def test_different_anchor_rules_are_respected_per_dialect(self):
        # Draft 7 defines plain-name anchors via a fragment-only $id.
        draft7 = {"$schema": D07, "$id": "#named", "type": "string"}
        draft7_registry = Registry(admission=admission_2020_7()).with_resource(
            "https://example.com/draft7",
            DRAFT7.create_resource(draft7),
        )
        resolved = draft7_registry.resolver().lookup(
            "https://example.com/draft7#named",
        )
        assert resolved.contents == draft7

        # Draft 2020-12 instead defines them via $anchor.
        modern = {
            "$schema": D202012,
            "$id": "https://example.com/modern",
            "$defs": {"named": {"$anchor": "named", "type": "number"}},
        }
        modern_registry = Registry(
            admission=admission_2020_7(),
        ).with_contents([("https://example.com/modern", modern)])
        resolved = modern_registry.resolver().lookup(
            "https://example.com/modern#named",
        )
        assert resolved.contents == {"$anchor": "named", "type": "number"}


class TestPolicyIsolation:
    def test_two_policies_in_one_process_do_not_interfere(self):
        draft7_only = SpecificationAdmission.admitting(
            [DRAFT7],
            default=DRAFT7,
        )
        modern = admission_2020_7()

        strict = Registry(admission=draft7_only).with_contents(
            [("urn:strict", {"$schema": D07})],
        )
        loose = Registry(admission=modern).with_contents(
            [("urn:loose", {"$schema": D202012})],
        )

        assert strict["urn:strict"]._specification is DRAFT7
        assert loose["urn:loose"]._specification is DRAFT202012

        with pytest.raises(exceptions.DisallowedDialect):
            Registry(admission=draft7_only).with_contents(
                [("urn:rejected", {"$schema": D202012})],
            )
        # The looser policy still admits 2020-12 in the same process.
        assert (
            Registry(admission=modern)
            .with_contents([("urn:accepted", {"$schema": D202012})])[
                "urn:accepted"
            ]
            ._specification
            is DRAFT202012
        )

    def test_policies_do_not_mutate_global_specification_registry(self):
        dialect_ids = [D202012, D201909, D07, D06, D04, D03]
        before = [
            referencing.jsonschema.specification_with(each)
            for each in dialect_ids
        ]
        SpecificationAdmission.admitting([DRAFT7], default=DRAFT7).detect(
            {"$schema": D07},
        )
        with pytest.raises(exceptions.DisallowedDialect):
            admission_2020_7().detect({"$schema": D04})
        with pytest.raises(exceptions.UnknownDialect):
            admission_2020_7().detect({"$schema": UNKNOWN})
        after = [
            referencing.jsonschema.specification_with(each)
            for each in dialect_ids
        ]
        assert before == after
        # A disallowed dialect remains resolvable outside of any policy.
        assert referencing.jsonschema.specification_with(D04) is DRAFT4
        assert referencing.jsonschema.specification_with(D03) is DRAFT3
        assert referencing.jsonschema.specification_with(D06) is DRAFT6
        assert (
            referencing.jsonschema.specification_with(D201909)
            is DRAFT201909
        )


class TestDefaultBehaviorUnchanged:
    def test_policy_free_registry_falls_back_to_default(self):
        registry = Registry().with_contents(
            [("urn:example", {"foo": "bar"})],
            default_specification=Specification.OPAQUE,
        )
        assert registry["urn:example"] == Resource.opaque({"foo": "bar"})

    def test_unknown_dialect_with_default_specification_falls_back(self):
        resource = Resource.from_contents(
            {"$schema": UNKNOWN},
            DRAFT202012,
        )
        assert resource == DRAFT202012.create_resource({"$schema": UNKNOWN})

    def test_policy_free_registry_detects_any_known_dialect(self):
        registry = Registry().with_contents(
            [
                ("urn:modern", {"$schema": D202012}),
                ("urn:legacy", {"$schema": D04}),
            ],
        )
        assert registry["urn:modern"]._specification is DRAFT202012
        assert registry["urn:legacy"]._specification is DRAFT4

    def test_policy_free_embedded_unknown_dialect_falls_back(self):
        root = DRAFT202012.create_resource(
            {"$defs": {"child": {"$schema": UNKNOWN}}},
        )
        subresources = list(root.subresources())
        assert subresources == [
            DRAFT202012.create_resource({"$schema": UNKNOWN}),
        ]

    def test_jsonschema_unknown_dialect_alias_is_core_exception(self):
        assert (
            referencing.jsonschema.UnknownDialect
            is exceptions.UnknownDialect
        )
