from __future__ import annotations

from copy import deepcopy

import pytest

from voice_probe.analysis import validate_analysis

TURNS = [
    {"id": "turn-001", "speaker": "receptionist", "text": "We are closed on Sundays."},
    {"id": "turn-002", "speaker": "patient", "text": "Can I come Sunday at ten?"},
    {"id": "turn-003", "speaker": "receptionist", "text": "You're booked for Sunday at ten."},
]
PAYLOAD = {
    "summary": "A scheduling statement contradicts the hours stated in this conversation.",
    "findings": [
        {
            "title": "Sunday confirmation conflicts with stated hours",
            "severity": "high",
            "category": "receptionist",
            "turn_ids": ["turn-001", "turn-003"],
            "quote": "You're booked for Sunday at ten.",
            "observed": "Conflicting statements appear in the transcript.",
            "expected": "Clarify availability before confirming.",
            "impact": "A patient may attend when the office is closed.",
            "uncertainty": "Check audio and actual practice hours; no backend proof.",
        }
    ],
}


def test_grounded_findings_are_candidates_even_if_model_claims_confirmed():
    payload = deepcopy(PAYLOAD)
    payload["findings"][0]["status"] = "confirmed"
    result = validate_analysis(payload, TURNS)
    assert result["findings"][0]["status"] == "candidate"
    assert result["findings"][0]["reviewer_note"] == ""


def test_fabricated_turn_rejected():
    payload = deepcopy(PAYLOAD)
    payload["findings"][0]["turn_ids"] = ["turn-999"]
    with pytest.raises(ValueError, match="invalid transcript turn"):
        validate_analysis(payload, TURNS)


def test_paraphrase_cannot_be_presented_as_direct_quote():
    payload = deepcopy(PAYLOAD)
    payload["findings"][0]["quote"] = "The appointment is fully confirmed for Sunday."
    with pytest.raises(ValueError, match="not an exact quote"):
        validate_analysis(payload, TURNS)


def test_patient_statement_not_attributed_to_receptionist():
    payload = deepcopy(PAYLOAD)
    payload["findings"][0]["turn_ids"] = ["turn-002"]
    payload["findings"][0]["quote"] = TURNS[1]["text"]
    with pytest.raises(ValueError, match="not an exact quote"):
        validate_analysis(payload, TURNS)


def test_empty_findings_is_a_valid_honest_outcome():
    assert validate_analysis({"summary": "No supported issue.", "findings": []}, TURNS) == {
        "summary": "No supported issue.",
        "findings": [],
    }
