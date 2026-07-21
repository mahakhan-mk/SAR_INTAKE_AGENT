
# Architecture

## Overview

The SAR Assessment Service is responsible for Intake, Inherent Risk, AI Analysis, HITL, Document Checklist, and Report generation.

Vendor Reputation is implemented in a separate service and consumed through its APIs.

---

# High Level Flow

Assessment
        │
        ▼
Assessment Responses
        │
        ▼
Analysis Service
        │
        ├──────────────► Question Analysis
        │                     │
        │                     ▼
        │              question_risk_results
        │
        ├──────────────► Executive Summary
        │                     │
        │                     ▼
        │             question_analysis_runs
        │
        ▼
Assemblers
        │
        ├──────────────► Inherent Risk DTO
        ├──────────────► AI Analysis DTO
        ├──────────────► Checklist DTO
        └──────────────► Report DTO

---

# Layers

HTTP API

Responsible only for:

- validation
- authentication
- calling services

No business logic.

---

Repositories

Responsible only for:

- SELECT
- INSERT
- UPDATE
- DELETE

No DTO construction.

---

Services

Responsible for:

- orchestration
- scoring
- LLM calls
- checklist rules
- report generation

---

Assemblers

Responsible only for converting domain objects into React DTOs.

---

# AI Analysis Flow

Assessment Responses
        │
        ▼
Question Analysis Service
        │
        ▼
question_analysis_runs

        │
        ▼
question_risk_results

Each analysed question contains:

- selected response
- why_it_matters (database)
- risk_signal (database)
- AI explanation
- AI confidence
- reviewer override

---

# Executive Summary

Input

- assessment context
- calculated inherent risk
- highest risk drivers
- top domains

The LLM does not calculate risk.

It explains the deterministic assessment.

The generated summary is stored in:

question_analysis_runs.executive_summary

---

# Document Checklist

Consumes

- assessment responses
- inherent risk
- AI analysis

Produces

- checklist items
- missing documents
- reviewer overrides

---

# Report Preview

Consumes

- Intake
- Inherent Risk
- AI Analysis
- Document Checklist

Produces one assembled DTO.

The report does not rerun AI analysis.

---

# Database Ownership

question_definitions

- question
- why_it_matters

question_options

- option
- risk_weight
- risk_band
- risk_signal

assessment_responses

- selected answers

question_analysis_runs

- overall analysis
- executive summary

question_risk_results

- AI explanation
- confidence
- AI risk

Reviewer overrides are stored separately and never overwrite AI output.

---

# Shared Analysis Run

The Inherent Risk page and AI Analysis page use the same analysis run.

Only one analysis pipeline exists.

The pages are different projections of the same stored results.

---

# Development Responsibilities

Developer 1

- Intake
- AI Analysis
- HITL

Developer 2

- Inherent Risk
- Executive Summary
- Document Checklist
- Report Preview
- Report Generation

## Implemented Inherent Risk Foundation

- `GET /api/v1/assessments/{assessment_id}/inherent-risk` is implemented as a deterministic read-or-calculate flow.
- `POST /api/v1/assessments/{assessment_id}/analysis-runs` now creates a synchronous deterministic run and preserves prior runs.
- The API layer validates inputs and delegates only to the service.
- Repository queries are split into small indexed reads:
  - assessment header
  - active triage questionnaire version
  - triage question definitions
  - assessment responses
  - question options
  - latest successful analysis run
  - persisted question risk results
- The service calculates per-question risk strictly from `question_options.risk_weight` and `question_options.risk_band`.
- The service persists exactly one `question_analysis_runs` row plus `question_risk_results` rows in the same transaction.
- The Inherent Risk and AI Analysis pages share the same `question_analysis_runs` record.
- Vendor Reputation is excluded from the inherent-risk workflow and top-risk-driver output.
- `question_analysis_runs` stores `triage_score`, `inherent_score`, `inherent_risk_level`, run status, and scoring rule version.
- `question_risk_results` stores deterministic explanation text, confidence, and a constrained input snapshot for each answered triage response.

## Implemented Scoring Policy

- No stronger authoritative aggregation rule or seeded weight configuration was present in the repository as of July 21, 2026, so the backend uses explicit scoring rule version `inherent-risk-v1-percentage`.
- Overall inherent risk is derived from triage questions only.
- The service calculates:
  - `total_score = sum(selected option risk_weight)`
  - `max_score = sum(max option risk_weight for each answered triage question)`
  - `score_percentage = total_score / max_score * 100`
- Percentage mapping:
  - `low`: `0 <= percentage < 25`
  - `medium`: `25 <= percentage < 50`
  - `high`: `50 <= percentage < 75`
  - `critical`: `75 <= percentage <= 100`
- If no triage responses exist, the page returns `not_assessed`.
- If active triage questions exist but some are unanswered, the run status is `completed_with_limitations` and scoring uses available responses only.
- Because the current schema does not expose an explicit required flag, the implementation treats all active non-Vendor-Reputation triage questions as required for limitation detection.
