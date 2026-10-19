from datetime import UTC, datetime

from sum_service.common.contracts import generated
from sum_service.observer.domain.observation import Observation
from sum_service.observer.message import PUBLISHED_BY, observed_envelope, subject_of

NOW = datetime(2026, 10, 15, 14, 0, tzinfo=UTC)
RESOURCE = "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1b"


def test_the_observed_envelope_matches_the_contract_and_carries_the_roles() -> None:
    envelope = observed_envelope(
        message_id="0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1c",
        resource_id=RESOURCE,
        observation=Observation("present", {"serviceRoles": ["ipm.organization.get"]}),
        correlation_id="0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1d",
        causation_id="0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1e",
        now=NOW,
    )
    generated.MessageEnvelope.model_validate(envelope)
    assert envelope["messageType"] == "observed" and envelope["emitter"] == "observer"
    assert envelope["presence"] == "present" and envelope["publishedBy"] == PUBLISHED_BY
    assert envelope["data"] == {"serviceRoles": ["ipm.organization.get"]}


def test_the_subject_follows_the_observer_pattern() -> None:
    assert subject_of(RESOURCE) == f"observer.observed.sum.service.{RESOURCE}.changed"
