import logging
from typing import Any

from sentry.api.exceptions import ResourceDoesNotExist
from sentry.eventstore.models import Event, GroupEvent
from sentry.grouping.api import GroupingConfigNotFound
from sentry.grouping.variants import BaseVariant
from sentry.models.project import Project
from sentry.utils import metrics

logger = logging.getLogger(__name__)


def get_grouping_info(
    config_name: str | None, project: Project, event: Event | GroupEvent
) -> dict[str, dict[str, Any]]:
    # We always fetch the stored hashes here. The reason for this is
    # that we want to show in the UI if the forced grouping algorithm
    # produced hashes that would normally also appear in the event.
    hashes = event.get_hashes()

    try:
        if event.get_event_type() == "transaction":
            # TODO: Test proving the front end doesn't call this endpoint for performance issues
            # https://github.com/getsentry/sentry/blob/599a484808fa6bd04df41fc165496d5d85cdcb33/static/app/components/events/groupingInfo/index.spec.tsx#L54
            variants = {}
            # TODO: It's not clear we ever land in this branch. Check back in on this metric and if
            # it hasn't fired, we can probably get rid of this and the accompanying test.
            metrics.incr("grouping.get_grouping_info.called_on_transaction_event")
        else:
            variants = event.get_grouping_variants(
                force_config=config_name, normalize_stacktraces=True
            )

    except GroupingConfigNotFound:
        raise ResourceDoesNotExist(detail="Unknown grouping config")

    grouping_info = get_grouping_info_from_variants(variants)

    # One place we use this info is in the grouping info section of the event details page, and for
    # that we recalculate hashes/variants on the fly since we don't store the variants as part of
    # event data. If the grouping config has been changed since the event was ingested, we may get
    # different hashes here than the ones stored on the event.
    _check_for_mismatched_hashes(event, project, grouping_info, hashes)

    return grouping_info


def _check_for_mismatched_hashes(
    event: Event | GroupEvent,
    project: Project,
    grouping_info: dict[str, dict[str, Any]],
    hashes: list[str],
) -> None:
    """
    Given a dictionary of variant data, check each variant's hash value to make sure it is `hashes`.

    The result is stored with each variant and recorded as a metric.
    """

    for variant_dict in grouping_info.values():
        hash_value = variant_dict["hash"]

        # Since the hashes are generated on the fly and might no
        # longer match the stored ones we indicate if the hash
        # generation caused the hash to mismatch.
        variant_dict["hashMismatch"] = hash_mismatch = (
            hash_value is not None and hash_value not in hashes
        )

        if hash_mismatch:
            metrics.incr("event_grouping_info.hash_mismatch")
            logger.error(
                "event_grouping_info.hash_mismatch",
                extra={"project_id": project.id, "event_id": event.event_id},
            )
        else:
            metrics.incr("event_grouping_info.hash_match")


def get_grouping_info_from_variants(
    variants: dict[str, BaseVariant],
) -> dict[str, dict[str, Any]]:
    """
    Given a dictionary of variant objects, create and return a copy of the dictionary in which each
    variant object value has been transformed into an equivalent dictionary value, which knows the
    key under which it lives.
    """

    return {key: {"key": key, **variant.as_dict()} for key, variant in variants.items()}
