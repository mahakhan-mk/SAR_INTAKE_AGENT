
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