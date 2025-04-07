from __future__ import annotations

import base64
import logging
import os
import zlib
from collections import Counter, namedtuple
from collections.abc import Sequence
from functools import cached_property
from typing import Any, Literal, NotRequired, TypedDict

import msgpack
import sentry_sdk
import zstandard
from sentry_ophio.enhancers import Cache as RustCache
from sentry_ophio.enhancers import Component as RustComponent
from sentry_ophio.enhancers import Enhancements as RustEnhancements

from sentry import projectoptions
from sentry.grouping.component import FrameGroupingComponent, StacktraceGroupingComponent
from sentry.stacktraces.functions import set_in_app
from sentry.utils.safe import get_path, set_path, setdefault_path

from .exceptions import InvalidEnhancerConfig
from .matchers import create_match_frame
from .parser import parse_enhancements
from .rules import EnhancementRule, EnhancementRuleDict

logger = logging.getLogger(__name__)

# NOTE: The 1_000 here is pretty arbitrary. Our builtin base enhancements have about ~300 rules,
# So this leaves quite a bit of headroom for custom enhancement rules as well.
RUST_CACHE = RustCache(1_000)

# TODO: Move 3 to the end when we're ready for it to be the default
VERSIONS = [3, 2]
LATEST_VERSION = VERSIONS[-1]

DEFAULT_GROUPING_ENHANCEMENTS_ID = "newstyle:2023-01-11"


VALID_PROFILING_MATCHER_PREFIXES = (
    "stack.abs_path",
    "path",  # stack.abs_path alias
    "stack.module",
    "module",  # stack.module alias
    "stack.function",
    "function",  # stack.function alias
    "stack.package",
    "package",  # stack.package
)
VALID_PROFILING_ACTIONS_SET = frozenset(["+app", "-app"])

StructuredEnhancementsConfig = namedtuple(
    "StructuredEnhancementsConfig", ["version", "classifier_rules", "contributes_rules"]
)


def merge_rust_enhancements(
    bases: list[str], rust_enhancements: RustEnhancements
) -> RustEnhancements:
    """
    This will merge the parsed enhancements together with the `bases`.
    It pretty much concatenates all the rules in `bases` (in order) together
    with all the rules in the incoming `rust_enhancements`.
    """
    merged_rust_enhancements = RustEnhancements.empty()
    for base_id in bases:
        base = ENHANCEMENT_BASES.get(base_id)
        if base:
            merged_rust_enhancements.extend_from(base.rust_enhancements)
    merged_rust_enhancements.extend_from(rust_enhancements)
    return merged_rust_enhancements


def parse_rust_enhancements(
    source: Literal["config_structure", "config_string"], input: str | bytes
) -> RustEnhancements:
    """
    Parses ``RustEnhancements`` from either a msgpack-encoded `config_structure`,
    or from the text representation called `config_string`.
    """
    try:
        if source == "config_structure":
            rules = Enhancements._from_config_structure(
                msgpack.loads(input, raw=False),
                RustEnhancements.from_config_structure(input, RUST_CACHE),
            ).rules
            bases = Enhancements._from_config_structure(
                msgpack.loads(input, raw=False),
                RustEnhancements.from_config_structure(input, RUST_CACHE),
            ).bases
            # if rules:
            #     breakpoint()
            assert isinstance(input, bytes)
            return RustEnhancements.from_config_structure(input, RUST_CACHE)
        else:
            assert isinstance(input, str)
            return RustEnhancements.parse(input, RUST_CACHE)
    except RuntimeError as e:  # Rust bindings raise parse errors as `RuntimeError`
        raise InvalidEnhancerConfig(str(e))


# TODO: Convert this into a typeddict in ophio
RustExceptionData = dict[str, bytes | None]


def make_rust_exception_data(
    exception_data: dict[str, Any] | None,
) -> RustExceptionData:
    exception_data = exception_data or {}
    rust_data = {
        "ty": exception_data.get("type"),
        "value": exception_data.get("value"),
        "mechanism": get_path(exception_data, "mechanism", "type"),
    }

    # Convert string values to bytes
    for key, value in rust_data.items():
        if isinstance(value, str):
            rust_data[key] = value.encode("utf-8")

    return RustExceptionData(
        ty=rust_data["ty"],
        value=rust_data["value"],
        mechanism=rust_data["mechanism"],
    )


def is_valid_profiling_matcher(matchers: list[str]) -> bool:
    for matcher in matchers:
        if not matcher.startswith(VALID_PROFILING_MATCHER_PREFIXES):
            return False
    return True


def is_valid_profiling_action(action: str) -> bool:
    return action in VALID_PROFILING_ACTIONS_SET


def keep_profiling_rules(config: str) -> str:
    filtered_rules = []
    if config is None or config == "":
        return ""
    for rule in config.splitlines():
        rule = rule.strip()
        if rule == "" or rule.startswith("#"):  # ignore comment lines
            continue
        *matchers, action = rule.split()
        if is_valid_profiling_matcher(matchers) and is_valid_profiling_action(action):
            filtered_rules.append(rule)
    return "\n".join(filtered_rules)


class EnhancementsDict(TypedDict):
    id: str | None
    bases: list[str]
    latest: bool
    rules: NotRequired[list[EnhancementRuleDict]]
    classifier_rules: NotRequired[list[EnhancementRuleDict]]
    contributes_rules: NotRequired[list[EnhancementRuleDict]]


class Enhancements:
    # NOTE: You must add a version to ``VERSIONS`` any time attributes are added
    # to this class, s.t. no enhancements lacking these attributes are loaded
    # from cache.
    # See ``GroupingConfigLoader._get_enhancements`` in src/sentry/grouping/api.py.

    def __init__(
        self,
        rules: list[EnhancementRule] | tuple[list[EnhancementRule], list[EnhancementRule]],
        rust_enhancements: RustEnhancements,
        version: int | None = None,
        bases: list[str] | None = None,
        id: str | None = None,
    ):
        self.id = id
        self.version = version or LATEST_VERSION
        self.bases = bases or []

        # TODO: Once we're satisfied that versions 2 and 3 produce the same results, and we make 3
        # the default, we can get rid of the version 2 code (here and in other methods) because
        # version is included as part of the base64 string we stick in the cache and into the event
        # (meaning any version 2 )
        if self.version <= 2:
            assert isinstance(rules, list)
            self.rules = rules
            self.rust_enhancements = merge_rust_enhancements(self.bases, rust_enhancements)
        else:
            # If we land here while loading rules from project options, they won't yet have been
            # split up by type, so do it now. Note that rules which as originally written have both
            # classifier and contributes actions will be split in two.
            if isinstance(rules, list):
                # Rules which set `in_app` or `category` on frames
                self.classifier_rules = [
                    rule.as_classifier_rule()  # Only include classifier actions
                    for rule in rules
                    if rule._has_classifier_actions
                ]
                # Rules which set `contributes` on frames and/or the stacktrace
                self.contributes_rules = [
                    rule._as_contributes_rule()  # Only include contributes actions
                    for rule in rules
                    if rule._has_contributes_actions
                ]
            # If we're loading rules from a base64 string (either from the cache or from an event)
            else:
                classifier_rules, contributes_rules = rules
                self.classifier_rules = classifier_rules
                self.contributes_rules = contributes_rules

            classifier_rules_text = "\n".join(rule.text for rule in self.classifier_rules)
            self.rust_classifier_enhancements = parse_rust_enhancements(
                "config_string", classifier_rules_text
            )
            contributes_rules_text = "\n".join(rule.text for rule in self.contributes_rules)
            self.rust_contributes_enhancements = parse_rust_enhancements(
                "config_string", contributes_rules_text
            )

    # answer = (
    #     custom_server_answer
    #     or custom_client_answer
    #     or derived_server_answer
    #     or default_server_answer
    #     or default_answer
    # )

    """
    split rules up by family

    do default and derived rules together, then

    split +/-group rules into separate rules from other rules since they're applied separately
        category/app rules
            run both functions, all hints will be app hints since grouping rules have been split off
            run defaults, derived, custom separately -> store results, hints separately
            adapt hints based on source
            run precedence, apply final answer
        group rules
            only run second function, all hints will be grouping hints since app rules have been split off
            there's no client answer so can just jam defaults + derived + custom rules all together


    3x Enhancements objects/None
    each object has classifier rules, contribution rules
    no more bases




    """

    def get_category_and_in_app_for_frame(
        self,
        frame: dict[str, Any],
        platform: str,
        rust_exception_data: RustExceptionData,
    ) -> tuple[str | None, bool | None]:
        match_frame = create_match_frame(frame, platform)
        category, in_app = self.rust_enhancements.apply_modifications_to_frames(
            [match_frame], rust_exception_data
        )[0]

    # ModificationResult = tuple[str | None, bool | None]

    def apply_category_and_updated_in_app_to_frames(
        self,
        frames: Sequence[dict[str, Any]],
        platform: str,
        exception_data: dict[str, Any],
    ) -> None:
        """
        Apply enhancement rules to each frame, adding a category (if any) and updating the `in_app`
        value if necessary.

        Both the category and `in_app` data will be used during grouping. The `in_app` values will
        also be persisted in the saved event, so they can be used in the UI and when determining
        things like suspect commits and suggested assignees.
        """
        # TODO: Fix this type to list[MatchFrame] once it's fixed in ophio
        match_frames: list[Any] = [create_match_frame(frame, platform) for frame in frames]
        rust_exception_data = make_rust_exception_data(exception_data)

        # breakpoint()

        category_and_in_app_results = self.rust_enhancements.apply_modifications_to_frames(
            match_frames, rust_exception_data
        )

        for frame, (category, in_app) in zip(frames, category_and_in_app_results):
            # Track the incoming `in_app` value, before we make any changes. This is different from
            # the `orig_in_app` value which may be set below, because it's not tied to the value
            # changing as a result of stacktrace rules.
            setdefault_path(frame, "data", "client_in_app", value=frame.get("in_app"))

            if in_app is not None:
                # If the `in_app` value changes as a result of this call, the original value (in
                # integer form) will be added to `frame.data` under the key "orig_in_app"
                set_in_app(frame, in_app)
            if category is not None:
                set_path(frame, "data", "category", value=category)

    def assemble_stacktrace_component(
        self,
        variant_name: str,
        frame_components: list[FrameGroupingComponent],
        frames: list[dict[str, Any]],
        platform: str | None,
        exception_data: dict[str, Any] | None = None,
    ) -> StacktraceGroupingComponent:
        """
        This assembles a `stacktrace` grouping component out of the given
        `frame` components and source frames.

        This also handles cases where the entire stacktrace should be discarded.
        """
        # TODO: Fix this type to list[MatchFrame] once it's fixed in ophio
        match_frames: list[Any] = [create_match_frame(frame, platform) for frame in frames]

        rust_frame_components = [RustComponent(contributes=c.contributes) for c in frame_components]

        # Modify the rust components by applying +group/-group rules and getting hints for both
        # those changes and the `in_app` changes applied by earlier in the ingestion process by
        # `apply_category_and_updated_in_app_to_frames`. Also, get `hint` and `contributes` values
        # for the overall stacktrace (returned in `rust_results`).
        rust_results = self.rust_enhancements.assemble_stacktrace_component(
            match_frames, make_rust_exception_data(exception_data), rust_frame_components
        )

        # Tally the number of each type of frame in the stacktrace. Later on, this will allow us to
        # both collect metrics and use the information in decisions about whether to send the event
        # to Seer
        frame_counts: Counter[str] = Counter()

        # Update frame components with results from rust
        for py_component, rust_component in zip(frame_components, rust_frame_components):
            # TODO: Remove the first condition once we get rid of the legacy config
            if (
                not (self.bases and self.bases[0].startswith("legacy"))
                and variant_name == "app"
                and not py_component.in_app
            ):
                # System frames should never contribute in the app variant, so force
                # `contribtues=False`, regardless of the rust results. Use the rust hint if it
                # explains the `in_app` value (but not if it explains the `contributing` value,
                # because we're ignoring that)
                #
                # TODO: Right now, if stacktrace rules have modified both the `in_app` and
                # `contributes` values, then the hint you get back from the rust enhancers depends
                # on the order in which those changes happened, which in turn depends on both the
                # order of stacktrace rules and the order of the actions within a stacktrace rule.
                # Ideally we'd get both hints back.
                hint = (
                    rust_component.hint
                    if rust_component.hint and rust_component.hint.startswith("marked out of app")
                    else py_component.hint
                )
                py_component.update(contributes=False, hint=hint)
            elif variant_name == "system":
                # We don't need hints about marking frames in or out of app in the system stacktrace
                # because such changes don't actually have an effect there
                hint = (
                    rust_component.hint
                    if rust_component.hint
                    and not rust_component.hint.startswith("marked in-app")
                    and not rust_component.hint.startswith("marked out of app")
                    else py_component.hint
                )
                py_component.update(contributes=rust_component.contributes, hint=hint)
            else:
                py_component.update(
                    contributes=rust_component.contributes, hint=rust_component.hint
                )

            # Add this frame to our tally
            key = f"{"in_app" if py_component.in_app else "system"}_{"contributing" if py_component.contributes else "non_contributing"}_frames"
            frame_counts[key] += 1

        # Because of the special case above, in which we ignore the rust-derived `contributes` value
        # for certain frames, it's possible for the rust-derived `contributes` value for the overall
        # stacktrace to be wrong, too (if in the process of ignoring rust we turn a stacktrace with
        # at least one contributing frame into one without any). So we need to special-case here as
        # well.
        #
        # TODO: Remove the first condition once we get rid of the legacy config
        if (
            not (self.bases and self.bases[0].startswith("legacy"))
            and variant_name == "app"
            and frame_counts["in_app_contributing_frames"] == 0
        ):
            stacktrace_contributes = False
            stacktrace_hint = None
        else:
            stacktrace_contributes = rust_results.contributes
            stacktrace_hint = rust_results.hint

        stacktrace_component = StacktraceGroupingComponent(
            values=frame_components,
            hint=stacktrace_hint,
            contributes=stacktrace_contributes,
            frame_counts=frame_counts,
        )

        return stacktrace_component

    # TODO: This used to be used in the /grouping-enhancements endpoint, which no longer exists.
    # (See https://github.com/getsentry/sentry/pull/12679) We can probably get rid of it, and the
    # `EnhancementsDict` type.
    def as_dict(self, with_rules: bool = False) -> EnhancementsDict:
        rv: EnhancementsDict = {
            "id": self.id,
            "bases": self.bases,
            "latest": projectoptions.lookup_well_known_key(
                "sentry:grouping_enhancements_base"
            ).get_default(epoch=projectoptions.LATEST_EPOCH)
            == self.id,
        }
        if with_rules:
            rv["rules"] = [x.as_dict() for x in self.rules]
            rv["classifier_rules"] = [x.as_dict() for x in self.classifier_rules]
            rv["contributes_rules"] = [x.as_dict() for x in self.contributes_rules]
        return rv

    def _to_config_structure(self) -> list[Any] | StructuredEnhancementsConfig:
        if self.version <= 2:
            return [
                self.version,
                self.bases,
                [rule._to_config_structure(self.version) for rule in self.rules],
            ]
        else:
            return StructuredEnhancementsConfig(
                self.version,
                [rule._to_config_structure(self.version) for rule in self.classifier_rules],
                [rule._to_config_structure(self.version) for rule in self.contributes_rules],
            )

    @cached_property
    def base64_string(self) -> str:
        """A base64 string representation of the enhancements object"""
        pickled = msgpack.dumps(self._to_config_structure())
        compressed_pickle = zstandard.compress(pickled)
        base64_bytes = base64.urlsafe_b64encode(compressed_pickle).strip(b"=")
        base64_str = base64_bytes.decode("ascii")
        return base64_str

    @classmethod
    def _from_config_structure(
        cls,
        data: list[Any],
        rust_enhancements: RustEnhancements,
    ) -> Enhancements:
        version, bases, rule_config_structures = data
        if version not in VERSIONS:
            raise ValueError("Unknown version")
        return cls(
            rules=[
                EnhancementRule._from_config_structure(rule_config_structure, version=version)
                for rule_config_structure in rule_config_structures
            ],
            rust_enhancements=rust_enhancements,
            version=version,
            bases=bases,
        )

    @classmethod
    def _from_config_structure_split(
        cls,
        data: list[Any] | StructuredEnhancementsConfig,
        rust_enhancements: RustEnhancements,
    ) -> Enhancements:
        if isinstance(data, list):
            version, bases, rules = data
            if version not in VERSIONS:
                raise ValueError("Unknown version")
            assert version <= 2
            return cls(
                rules=[
                    EnhancementRule._from_config_structure(rule, version=version) for rule in rules
                ],
                rust_enhancements=rust_enhancements,
                version=version,
                bases=bases,
            )
        else:
            version, classifier_rules, contributes_rules = data
            if version not in VERSIONS:
                raise ValueError("Unknown version")
            return cls(
                rules=[
                    EnhancementRule._from_config_structure(rule, version=version) for rule in rules
                ],
                rust_enhancements=rust_enhancements,
                version=version,
                bases=bases,
            )

    @classmethod
    def from_base64_string(cls, base64_string: str | bytes) -> Enhancements:
        """Convert a base64 string into an `Enhancements` object"""
        bytes_str = (
            base64_string.encode("ascii", "ignore")
            if isinstance(base64_string, str)
            else base64_string
        )
        padded_bytes = bytes_str + b"=" * (4 - (len(bytes_str) % 4))
        try:
            compressed_pickle = base64.urlsafe_b64decode(padded_bytes)

            if compressed_pickle.startswith(b"\x28\xb5\x2f\xfd"):
                pickled = zstandard.decompress(compressed_pickle)
            else:
                pickled = zlib.decompress(compressed_pickle)

            config_structure = msgpack.loads(pickled, raw=False)
            version = config_structure[0]
            if version <= 2:
                rust_enhancements = parse_rust_enhancements("config_structure", pickled)

            return cls._from_config_structure(config_structure, rust_enhancements)
        except (LookupError, AttributeError, TypeError, ValueError) as e:
            raise ValueError("invalid stacktrace rule config: %s" % e)

    @classmethod
    @sentry_sdk.tracing.trace
    def from_rules_text(
        cls,
        s: str,
        bases: list[str] | None = None,
        id: str | None = None,
        version: int | None = None,
    ) -> Enhancements:
        """Create an `Enhancements` object from a text blob containing stacktrace rules"""
        rust_enhancements = parse_rust_enhancements("config_string", s)

        rules = parse_enhancements(s)

        # Rules which set `in_app` or `category` on frames
        classifier_rules = [
            rule.as_classifier_rule()  # Only include classifier actions
            for rule in rules
            if rule._has_classifier_actions
        ]
        # Rules which set `contributes` on frames and/or the stacktrace
        contributes_rules = [
            rule._as_contributes_rule()  # Only include contributes actions
            for rule in rules
            if rule._has_contributes_actions
        ]
        classifier_rules_text = "\n".join(rule.text for rule in classifier_rules)
        rust_classifier_enhancements = parse_rust_enhancements(
            "config_string", classifier_rules_text
        )
        contributes_rules_text = "\n".join(rule.text for rule in contributes_rules)
        rust_contributes_enhancements = parse_rust_enhancements(
            "config_string", contributes_rules_text
        )

        return Enhancements(
            rules,
            rust_enhancements=rust_enhancements,
            version=version,
            bases=bases,
            id=id,
        )

    @classmethod
    def get_default_enhancements(cls, grouping_config_id: str | None = None) -> Enhancements:
        from sentry.grouping.strategies.configurations import STRATEGY_CONFIG_CLASSES_BY_ID

        enhancements_id = DEFAULT_GROUPING_ENHANCEMENTS_ID
        if grouping_config_id is not None:
            strategy_config = STRATEGY_CONFIG_CLASSES_BY_ID[grouping_config_id]
            enhancements_id = strategy_config.enhancements_base or DEFAULT_GROUPING_ENHANCEMENTS_ID

        old = cls.from_rules_text("", bases=[enhancements_id] if enhancements_id else [])
        new = DEFAULT_GROUPING_ENHANCEMENTS_BY_ID[enhancements_id]
        if new.base64_string != old.base64_string:
            breakpoint()

        return DEFAULT_GROUPING_ENHANCEMENTS_BY_ID[enhancements_id]


def _load_configs() -> dict[str, Enhancements]:
    enhancement_bases = {}
    configs_dir = os.path.join(os.path.abspath(os.path.dirname(__file__)), "enhancement-configs")
    for filename in os.listdir(configs_dir):
        if filename.endswith(".txt"):
            with open(os.path.join(configs_dir, filename), encoding="utf-8") as f:
                # Strip the extension
                filename = filename.replace(".txt", "")
                # We cannot use `:` in filenames on Windows but we already have ids with
                # `:` in their names hence this trickery.
                filename = filename.replace("@", ":")
                enhancements = Enhancements.from_rules_text(f.read(), id=filename)
                enhancement_bases[filename] = enhancements
    return enhancement_bases


# A map of config ids to `Enhancement` objects
ENHANCEMENT_BASES: dict[str, Enhancements] = _load_configs()
DEFAULT_GROUPING_ENHANCEMENTS_BY_ID = ENHANCEMENT_BASES
DEFAULT_BASE64_ENHANCEMENTS_BY_ID = {
    config_id: enhancements.base64_string
    for config_id, enhancements in DEFAULT_GROUPING_ENHANCEMENTS_BY_ID.items()
}

del _load_configs
