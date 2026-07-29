from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from app.api.schemas import AIAnalysisQuestionRowDTO, AIAnalysisResponseDTO
from app.assemblers.ai_analysis_assembler import AIAnalysisAssembler
from app.models.ai_analysis import AIAnalysisQuestionRowRecord, AIAnalysisRunRecord, AIAnalysisViewRecord
from app.models.enums import AnalysisRunStatus


def _payload(result) -> dict[str, object]:
    return AIAnalysisResponseDTO.model_validate(result).model_dump(mode="json")


def _row_payload(row) -> dict[str, object]:
    return AIAnalysisQuestionRowDTO.model_validate(row).model_dump(mode="json")


def build_view(
    *,
    latest_run: AIAnalysisRunRecord | None = None,
    questions: list[AIAnalysisQuestionRowRecord] | None = None,
) -> AIAnalysisViewRecord:
    return AIAnalysisViewRecord(
        assessment_id=UUID("00000000-0000-0000-0000-000000000100"),
        latest_run=latest_run,
        questions=questions or [],
    )


def build_run() -> AIAnalysisRunRecord:
    return AIAnalysisRunRecord(
        analysis_run_id=UUID("00000000-0000-0000-0000-000000000200"),
        status=AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS,
        created_at=datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc),
    )


def build_question_row(
    *,
    question_id: str,
    question_number: str,
    result_risk_level: str | None = "high",
    result_risk_score: float | None = 3.0,
    result_risk_impact: str | None = "Result impact should stay separate.",
    result_explanation: str | None = "AI explanation text.",
    result_confidence: float | None = 0.85,
    selected_option_id: str | None = "00000000-0000-0000-0000-000000000300",
    answer_value: object | None = "Yes",
    option_risk_band: str | None = "medium",
    option_risk_weight: float | None = 2.0,
    option_why_it_matters: str | None = "Configured rationale.",
    option_risk_signal: str | None = "Configured signal.",
    reviewer_remarks: str | None = "Needs manual follow-up.",
    domain: str | None = "Security",
) -> AIAnalysisQuestionRowRecord:
    return AIAnalysisQuestionRowRecord(
        question_id=UUID(question_id),
        question_number=question_number,
        question_text=f"Question text for {question_number}",
        domain=domain,
        response_id=UUID("00000000-0000-0000-0000-000000000400"),
        selected_option_id=UUID(selected_option_id) if selected_option_id is not None else None,
        answer_value=answer_value,
        option_risk_band=option_risk_band,
        option_risk_weight=option_risk_weight,
        option_why_it_matters=option_why_it_matters,
        option_risk_signal=option_risk_signal,
        result_risk_level=result_risk_level,
        result_risk_score=result_risk_score,
        result_risk_impact=result_risk_impact,
        result_explanation=result_explanation,
        result_confidence=result_confidence,
        reviewer_remarks=reviewer_remarks,
    )


def test_complete_view_maps_to_expected_dto():
    assembler = AIAnalysisAssembler()
    view = build_view(
        latest_run=build_run(),
        questions=[
            build_question_row(
                question_id="00000000-0000-0000-0000-000000000001",
                question_number="TRIAGE-001",
            )
        ],
    )

    dto = assembler.to_dto(view)

    assert _payload(dto) == {
        "assessmentId": "00000000-0000-0000-0000-000000000100",
        "latestAnalysisRun": {
            "analysisRunId": "00000000-0000-0000-0000-000000000200",
            "status": "completed_with_limitations",
            "createdAt": "2026-07-21T12:00:00Z",
        },
        "questions": [
            {
                "questionId": "00000000-0000-0000-0000-000000000001",
                "questionNumber": "TRIAGE-001",
                "questionText": "Question text for TRIAGE-001",
                "domain": "Security",
                "selectedOptionId": "00000000-0000-0000-0000-000000000300",
                "answerValue": "Yes",
                "riskBand": "high",
                "riskScore": 3.0,
                "riskSignal": "Configured signal.",
                "whyItMatters": "Configured rationale.",
                "reviewerRemarks": "Needs manual follow-up.",
            }
        ],
    }
    assert dto.questions[0].aiExplanation == "AI explanation text."
    assert dto.questions[0].confidence == 0.85
    assert "aiExplanation" not in _payload(dto)["questions"][0]
    assert "confidence" not in _payload(dto)["questions"][0]


def test_run_metadata_maps_correctly():
    assembler = AIAnalysisAssembler()
    dto = assembler.to_dto(build_view(latest_run=build_run()))

    assert dto.latestAnalysisRun.analysisRunId == UUID("00000000-0000-0000-0000-000000000200")
    assert dto.latestAnalysisRun.status == AnalysisRunStatus.COMPLETED_WITH_LIMITATIONS
    assert dto.latestAnalysisRun.createdAt == datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def test_question_fields_map_correctly():
    assembler = AIAnalysisAssembler()
    dto = assembler.to_dto(
        build_view(
            questions=[
                build_question_row(
                    question_id="00000000-0000-0000-0000-000000000010",
                    question_number="TRIAGE-010",
                    selected_option_id=None,
                    answer_value="No",
                    domain="Operations",
                )
            ]
        )
    )

    row = dto.questions[0]
    assert row.questionId == UUID("00000000-0000-0000-0000-000000000010")
    assert row.questionNumber == "TRIAGE-010"
    assert row.questionText == "Question text for TRIAGE-010"
    assert row.domain == "Operations"
    assert row.selectedOptionId is None
    assert row.answerValue == "No"


def test_option_risk_metadata_maps_correctly():
    assembler = AIAnalysisAssembler()
    dto = assembler.to_dto(
        build_view(
            questions=[
                build_question_row(
                    question_id="00000000-0000-0000-0000-000000000020",
                    question_number="TRIAGE-020",
                    option_risk_band="critical",
                    option_risk_weight=4.0,
                    option_why_it_matters="Option rationale only.",
                    option_risk_signal="Option signal only.",
                    result_risk_level="low",
                    result_risk_score=1.0,
                )
            ]
        )
    )

    row = dto.questions[0]
    assert row.riskSignal == "Option signal only."
    assert row.whyItMatters == "Option rationale only."
    assert row.riskBand.value == "low"
    assert row.riskScore == 1.0


def test_ai_result_fields_map_correctly():
    assembler = AIAnalysisAssembler()
    dto = assembler.to_dto(
        build_view(
            questions=[
                build_question_row(
                    question_id="00000000-0000-0000-0000-000000000030",
                    question_number="TRIAGE-030",
                    result_risk_level="critical",
                    result_risk_score=4.0,
                    result_risk_impact="AI impact text.",
                    result_explanation="AI narrative.",
                    result_confidence=0.97,
                    option_why_it_matters="Configured rationale remains separate.",
                )
            ]
        )
    )

    row = dto.questions[0]
    assert row.riskBand.value == "critical"
    assert row.riskScore == 4.0
    assert row.whyItMatters == "Configured rationale remains separate."
    assert row.aiExplanation == "AI narrative."
    assert row.confidence == 0.97
    assert "aiExplanation" not in _row_payload(row)
    assert "confidence" not in _row_payload(row)


def test_reviewer_remarks_are_preserved():
    assembler = AIAnalysisAssembler()
    dto = assembler.to_dto(
        build_view(
            questions=[
                build_question_row(
                    question_id="00000000-0000-0000-0000-000000000040",
                    question_number="TRIAGE-040",
                    reviewer_remarks="Reviewed and accepted.",
                )
            ]
        )
    )

    assert dto.questions[0].reviewerRemarks == "Reviewed and accepted."


def test_reviewer_remarks_supports_null():
    assembler = AIAnalysisAssembler()
    dto = assembler.to_dto(
        build_view(
            questions=[
                build_question_row(
                    question_id="00000000-0000-0000-0000-000000000041",
                    question_number="TRIAGE-041",
                    reviewer_remarks=None,
                )
            ]
        )
    )

    assert dto.questions[0].reviewerRemarks is None


def test_nullable_run_and_analysis_fields_are_handled():
    assembler = AIAnalysisAssembler()
    dto = assembler.to_dto(
        build_view(
            latest_run=None,
            questions=[
                build_question_row(
                    question_id="00000000-0000-0000-0000-000000000050",
                    question_number="TRIAGE-050",
                    result_risk_level=None,
                    result_risk_score=None,
                    result_risk_impact=None,
                    result_explanation=None,
                    result_confidence=None,
                    selected_option_id=None,
                    answer_value=None,
                    reviewer_remarks=None,
                )
            ],
        )
    )

    assert dto.latestAnalysisRun.analysisRunId is None
    assert dto.latestAnalysisRun.status is None
    assert dto.latestAnalysisRun.createdAt is None
    row = dto.questions[0]
    assert row.selectedOptionId is None
    assert row.answerValue is None
    assert row.riskBand is None
    assert row.riskScore is None
    assert row.reviewerRemarks is None
    assert row.aiExplanation is None
    assert row.confidence is None
    assert "aiExplanation" not in _row_payload(row)
    assert "confidence" not in _row_payload(row)


def test_row_ordering_is_preserved():
    assembler = AIAnalysisAssembler()
    dto = assembler.to_dto(
        build_view(
            questions=[
                build_question_row(
                    question_id="00000000-0000-0000-0000-000000000061",
                    question_number="TRIAGE-002",
                ),
                build_question_row(
                    question_id="00000000-0000-0000-0000-000000000060",
                    question_number="TRIAGE-001",
                ),
            ]
        )
    )

    assert [row.questionId for row in dto.questions] == [
        UUID("00000000-0000-0000-0000-000000000061"),
        UUID("00000000-0000-0000-0000-000000000060"),
    ]
