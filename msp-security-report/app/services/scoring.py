"""Assessment scoring logic.

Scoring rules
-------------
Each question has a *weight* (criticality) and a list of options. Each option
has a *score* factor between 0.0 and 1.0. Earned points = weight * score.

Risk rating bands (after Nessus deductions):
    >= 85%  -> Low Risk
    70-84%  -> Medium Risk
    50-69%  -> High Risk
    < 50%   -> Critical Risk

Nessus deductions are computed in nessus_parser and applied here so that the
final percentage reflects the on-the-ground reality of unpatched
vulnerabilities.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.models import (
    Assessment,
    AssessmentAnswer,
    RiskRating,
)
from app.services.questions import (
    SECTIONS,
    Question,
    Section,
    question_lookup,
    section_for_question,
)


# --- Score band thresholds ----------------------------------------------------

_BANDS: List[tuple[float, RiskRating]] = [
    (85.0, RiskRating.low),
    (70.0, RiskRating.medium),
    (50.0, RiskRating.high),
    (0.0, RiskRating.critical),
]


@dataclass
class QuestionResult:
    """Per-question result included in the section/overall breakdown."""

    key: str
    text: str
    answer_value: str
    answer_label: str
    weight: int
    earned: float
    possible: int
    section_key: str
    section_name: str

    @property
    def percentage(self) -> float:
        return (self.earned / self.possible) * 100.0 if self.possible else 0.0


@dataclass
class SectionResult:
    """Aggregated result for one section."""

    key: str
    name: str
    description: str
    earned: float = 0.0
    possible: int = 0
    questions: List[QuestionResult] = field(default_factory=list)
    answered: int = 0
    total: int = 0

    @property
    def percentage(self) -> float:
        return (self.earned / self.possible) * 100.0 if self.possible else 0.0

    @property
    def is_low_scoring(self) -> bool:
        return self.percentage < 60.0


@dataclass
class ScoringResult:
    """The full scoring result for an assessment."""

    raw_score: float
    max_score: int
    base_percentage: float
    nessus_deduction: float
    adjusted_score: float
    percentage: float
    risk_rating: RiskRating
    sections: List[SectionResult]

    @property
    def percentage_int(self) -> int:
        return int(round(self.percentage))


# --- Public helpers -----------------------------------------------------------

def get_option_score(question: Question, answer_value: str) -> float:
    """Return the 0..1 score factor of the chosen option."""
    for opt in question["options"]:
        if opt["value"] == answer_value:
            return opt["score"]
    return 0.0


def determine_risk_rating(percentage: float) -> RiskRating:
    """Map a percentage score to a RiskRating using the configured bands."""
    for threshold, rating in _BANDS:
        if percentage >= threshold:
            return rating
    return RiskRating.critical


def score_answer(answer: AssessmentAnswer) -> tuple[float, int]:
    """Compute (earned, possible) for one answer using the question catalog."""
    catalog = question_lookup()
    question = catalog.get(answer.question_key)
    if question is None:
        # Fall back to the stored weight if the question definition has been
        # changed since the answer was saved.
        return 0.0, answer.weight
    factor = get_option_score(question, answer.answer_value)
    return factor * answer.weight, question["weight"]


def compute_nessus_deduction(nessus_summary: Optional[Dict]) -> float:
    """Compute the score deduction (in raw points) from a Nessus summary.

    Each Critical vuln deducts 1.5 pts, each High deducts 0.5, capped at 15
    and 10 points respectively. Medium/Low/Info do not deduct.
    """
    if not nessus_summary:
        return 0.0
    counts = nessus_summary.get("severity_counts", {}) or {}
    critical = int(counts.get("Critical", 0) or 0)
    high = int(counts.get("High", 0) or 0)
    crit_deduct = min(critical * 1.5, 15.0)
    high_deduct = min(high * 0.5, 10.0)
    return crit_deduct + high_deduct


def score_assessment(assessment: Assessment) -> ScoringResult:
    """Compute the full scoring breakdown for an assessment."""
    catalog = question_lookup()

    # Initialise a section bucket for every catalog section, so empty sections
    # still appear in the report (with an "unanswered" indicator).
    section_buckets: Dict[str, SectionResult] = {}
    for sec in SECTIONS:
        section_buckets[sec["key"]] = SectionResult(
            key=sec["key"],
            name=sec["name"],
            description=sec["description"],
            total=len(sec["questions"]),
        )

    for ans in assessment.answers:
        question = catalog.get(ans.question_key)
        if question is None:
            continue
        section = section_for_question(ans.question_key)
        if section is None:
            continue
        bucket = section_buckets[section["key"]]
        factor = get_option_score(question, ans.answer_value)
        earned = factor * question["weight"]
        possible = question["weight"]
        bucket.earned += earned
        bucket.possible += possible
        bucket.answered += 1
        bucket.questions.append(
            QuestionResult(
                key=ans.question_key,
                text=ans.question_text,
                answer_value=ans.answer_value,
                answer_label=ans.answer_label,
                weight=question["weight"],
                earned=earned,
                possible=possible,
                section_key=section["key"],
                section_name=section["name"],
            )
        )

    sections = list(section_buckets.values())

    raw_score = sum(s.earned for s in sections)
    max_score = sum(q["weight"] for sec in SECTIONS for q in sec["questions"])

    base_percentage = (raw_score / max_score) * 100.0 if max_score else 0.0

    deduction = compute_nessus_deduction(assessment.nessus_summary)
    adjusted_score = max(0.0, raw_score - deduction)
    adjusted_percentage = (adjusted_score / max_score) * 100.0 if max_score else 0.0

    return ScoringResult(
        raw_score=raw_score,
        max_score=max_score,
        base_percentage=base_percentage,
        nessus_deduction=deduction,
        adjusted_score=adjusted_score,
        percentage=adjusted_percentage,
        risk_rating=determine_risk_rating(adjusted_percentage),
        sections=sections,
    )


# --- Recommendations ----------------------------------------------------------

@dataclass
class Recommendation:
    priority: str  # "Critical" | "High" | "Medium"
    section_name: str
    question_text: str
    answer_label: str
    text: str  # the recommendation body
    rationale: str


def _priority_for(question: Question, factor: float) -> str:
    """Map a question/answer to a remediation priority."""
    weight = question.get("weight", 1)
    if factor == 0.0 and weight >= 3:
        return "Critical"
    if factor == 0.0 and weight == 2:
        return "High"
    if factor == 0.0:
        return "High"
    # Partial answers
    if weight >= 3:
        return "High"
    if weight == 2:
        return "Medium"
    return "Medium"


_PRIORITY_ORDER = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}


def generate_recommendations(result: ScoringResult) -> List[Recommendation]:
    """Generate prioritised remediation recommendations from a ScoringResult."""
    catalog = question_lookup()
    recs: List[Recommendation] = []

    for section in result.sections:
        for q in section.questions:
            question_def = catalog.get(q.key)
            if question_def is None:
                continue
            factor = q.earned / q.weight if q.weight else 0.0
            # Only emit a recommendation for failed or partial answers.
            if factor >= 1.0:
                continue
            rec_text = question_def.get("recommendation", "").strip()
            if not rec_text:
                continue
            priority = _priority_for(question_def, factor)
            rationale = (
                f"Current state: '{q.answer_label}'. This control carries a "
                f"weight of {q.weight} reflecting its impact on overall risk."
            )
            recs.append(
                Recommendation(
                    priority=priority,
                    section_name=section.name,
                    question_text=q.text,
                    answer_label=q.answer_label,
                    text=rec_text,
                    rationale=rationale,
                )
            )

    recs.sort(key=lambda r: (_PRIORITY_ORDER.get(r.priority, 99), r.section_name))
    return recs


# --- Executive summary narrative ---------------------------------------------

def generate_executive_findings(
    result: ScoringResult, recommendations: List[Recommendation]
) -> List[str]:
    """Return 3-5 plain-English narrative bullet points for the exec summary.

    The narrative is deterministic (no LLM) and drawn from the assessment data:
    overall posture, weakest sections, and the most critical open gaps.
    """
    findings: List[str] = []

    # 1) Overall posture statement.
    posture_phrase = {
        RiskRating.low: "a strong overall security posture",
        RiskRating.medium: "a moderate overall security posture with notable gaps",
        RiskRating.high: "a weak overall security posture with material control gaps",
        RiskRating.critical: "a critical exposure level requiring immediate remediation",
    }[result.risk_rating]
    findings.append(
        f"The assessment indicates {posture_phrase}, with an overall score of "
        f"{result.percentage_int} percent and a risk rating of "
        f"{result.risk_rating.value}."
    )

    # 2) Weakest sections.
    answered_sections = [s for s in result.sections if s.possible > 0]
    weakest = sorted(answered_sections, key=lambda s: s.percentage)[:3]
    if weakest:
        names = ", ".join(s.name for s in weakest if s.percentage < 80.0)
        if names:
            findings.append(
                "The lowest-scoring control domains are "
                f"{names}. These areas should be prioritised in the remediation roadmap."
            )

    # 3) Critical recommendations.
    critical = [r for r in recommendations if r.priority == "Critical"]
    if critical:
        topics = []
        for r in critical[:3]:
            topics.append(r.question_text.rstrip("?"))
        joined = "; ".join(topics)
        findings.append(
            "Critical-severity gaps were identified relating to: "
            f"{joined}. These represent the highest residual risk and should "
            "be addressed within the next 30 days."
        )

    # 4) Nessus impact, if present.
    if result.nessus_deduction > 0:
        findings.append(
            "Vulnerability scan data adjusted the posture score downward by "
            f"{result.nessus_deduction:.1f} points, reflecting unpatched "
            "Critical and High severity findings on in-scope hosts."
        )

    # 5) Strengths, if any.
    strong_sections = [s for s in answered_sections if s.percentage >= 85.0]
    if strong_sections and len(findings) < 5:
        names = ", ".join(s.name for s in strong_sections[:3])
        findings.append(
            f"Mature controls were observed in {names}, which provide a defensible baseline "
            "to build on."
        )

    return findings[:5]
