"""Definition of the assessment question catalog.

The catalog drives the wizard UI, the scoring engine, and the recommendations
engine. It is intentionally defined as a plain Python data structure so that it
is trivial to inspect, version-control, and extend.

Each question has the following shape::

    {
        "key":     "iam_admin_mfa",         # stable identifier (DB-safe)
        "text":    "Do you enforce MFA ...", # prompt shown to the user
        "weight":  3,                        # criticality weight
        "options": [                         # displayed left-to-right in UI
            {"value": "yes",     "label": "Yes",     "score": 1.0},
            {"value": "partial", "label": "Partial", "score": 0.5},
            {"value": "no",      "label": "No",      "score": 0.0},
        ],
        # Optional: fixed remediation text used in the recommendations engine.
        "recommendation": "Enforce MFA for all administrative accounts ...",
    }

Score factors are between 0.0 and 1.0 - the scoring engine multiplies them by
the question weight to compute earned points.
"""
from __future__ import annotations

from typing import Dict, List, TypedDict


class Option(TypedDict):
    value: str
    label: str
    score: float


class Question(TypedDict, total=False):
    key: str
    text: str
    weight: int
    options: List[Option]
    recommendation: str


class Section(TypedDict):
    key: str
    name: str
    description: str
    questions: List[Question]


# Reusable option sets ----------------------------------------------------------

_YES_PARTIAL_NO: List[Option] = [
    {"value": "yes", "label": "Yes", "score": 1.0},
    {"value": "partial", "label": "Partial", "score": 0.5},
    {"value": "no", "label": "No", "score": 0.0},
]

_YES_NO: List[Option] = [
    {"value": "yes", "label": "Yes", "score": 1.0},
    {"value": "no", "label": "No", "score": 0.0},
]


# Section catalog --------------------------------------------------------------

SECTIONS: List[Section] = [
    {
        "key": "iam",
        "name": "Identity & Access Management",
        "description": (
            "Controls that govern how identities are created, authenticated, "
            "and authorised across the environment."
        ),
        "questions": [
            {
                "key": "iam_admin_mfa",
                "text": "Do you enforce MFA on all admin accounts?",
                "weight": 3,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Enforce phishing-resistant multi-factor authentication on every "
                    "administrative account, including break-glass and service-tier "
                    "admins, with conditional access policies that block legacy "
                    "authentication."
                ),
            },
            {
                "key": "iam_user_mfa",
                "text": "Do you enforce MFA on all end-user accounts?",
                "weight": 3,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Roll out multi-factor authentication to every end-user account "
                    "and remove any conditional exemptions that bypass MFA."
                ),
            },
            {
                "key": "iam_offboarding",
                "text": "Is there a formal offboarding process to revoke access within 24 hours?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "undocumented", "label": "Undocumented", "score": 0.5},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Document a joiner-mover-leaver workflow that revokes all access "
                    "within 24 hours of termination and validate it with HR triggers."
                ),
            },
            {
                "key": "iam_pam",
                "text": "Do you use a Privileged Access Management (PAM) solution?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "in_progress", "label": "In Progress", "score": 0.5},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Adopt a Privileged Access Management platform to vault privileged "
                    "credentials, enforce just-in-time elevation, and record privileged "
                    "sessions."
                ),
            },
            {
                "key": "iam_service_accounts",
                "text": "Are service accounts inventoried and reviewed quarterly?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "unknown", "label": "Unknown", "score": 0.0},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Establish a quarterly review of all service and machine accounts, "
                    "confirming ownership, scoped permissions, and credential rotation."
                ),
            },
            {
                "key": "iam_rbac",
                "text": "Do you enforce role-based access control (RBAC)?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Implement role-based access control with least-privilege role "
                    "definitions, and recertify role membership at least annually."
                ),
            },
        ],
    },
    {
        "key": "endpoint",
        "name": "Endpoint Security",
        "description": (
            "Controls that protect workstations, laptops, and servers from "
            "malware, exploitation, and policy bypass."
        ),
        "questions": [
            {
                "key": "ep_edr_coverage",
                "text": "Are all endpoints covered by an EDR/XDR solution?",
                "weight": 3,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Deploy a managed EDR/XDR agent to every endpoint and reconcile "
                    "the agent inventory with the asset inventory monthly to catch gaps."
                ),
            },
            {
                "key": "ep_edr_monitoring",
                "text": "Is EDR managed and monitored 24/7?",
                "weight": 2,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "business_hours", "label": "Business Hours Only", "score": 0.5},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Engage a 24x7 monitored detection and response service so EDR "
                    "alerts are triaged by analysts outside business hours."
                ),
            },
            {
                "key": "ep_patching",
                "text": "Is endpoint patching automated and completed within 30 days of release?",
                "weight": 2,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Automate operating system and third-party patch deployment with "
                    "a 30-day SLA for critical updates and reporting on patch latency."
                ),
            },
            {
                "key": "ep_usb_control",
                "text": "Are USB and removable media ports controlled or disabled?",
                "weight": 1,
                "options": _YES_NO,
                "recommendation": (
                    "Apply removable media controls via Group Policy or your endpoint "
                    "management platform, allowing approved encrypted devices only."
                ),
            },
            {
                "key": "ep_app_allowlist",
                "text": "Is application allowlisting or software restriction policy enforced?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Pilot application allowlisting on high-risk endpoints (servers, "
                    "finance workstations) and expand coverage based on telemetry."
                ),
            },
        ],
    },
    {
        "key": "network",
        "name": "Network Security",
        "description": (
            "Controls that segment, filter, and inspect traffic to limit lateral "
            "movement and block command-and-control activity."
        ),
        "questions": [
            {
                "key": "net_segmentation",
                "text": "Is network traffic segmented (VLANs/zones)?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Segment the network into trust zones using VLANs and inter-VLAN "
                    "firewall rules to constrain lateral movement."
                ),
            },
            {
                "key": "net_ngfw",
                "text": "Is there a next-gen firewall (NGFW) in place with active policy management?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "basic", "label": "Basic Firewall Only", "score": 0.5},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Replace any legacy stateful firewall with an actively managed NGFW "
                    "that performs deep packet inspection, IDS/IPS, and TLS inspection."
                ),
            },
            {
                "key": "net_remote_access",
                "text": "Is remote access limited to VPN or Zero Trust Network Access (ZTNA)?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "partial", "label": "Partial", "score": 0.5},
                    {"value": "no", "label": "No - Open RDP/Other", "score": 0.0},
                ],
                "recommendation": (
                    "Eliminate any direct exposure of management protocols (RDP, SSH, "
                    "SMB) to the internet and require MFA-protected VPN or ZTNA access."
                ),
            },
            {
                "key": "net_firewall_review",
                "text": "Are firewall rules reviewed at least annually?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "unknown", "label": "Unknown", "score": 0.0},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Schedule an annual firewall rule review to remove stale rules, "
                    "tighten any/any allows, and document business justification."
                ),
            },
            {
                "key": "net_dns_filter",
                "text": "Is DNS filtering enforced for all users including remote?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Deploy DNS filtering (e.g., protective DNS) to all users including "
                    "those off-network to block malware command-and-control domains."
                ),
            },
            {
                "key": "net_wifi_segmented",
                "text": "Is wireless network segmented from corporate resources?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "no_wireless", "label": "No Wireless", "score": 1.0},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Segregate guest and IoT wireless networks from the corporate "
                    "trust zone and require certificate-based 802.1X for staff Wi-Fi."
                ),
            },
        ],
    },
    {
        "key": "data",
        "name": "Data Protection & Backup",
        "description": (
            "Controls that classify, encrypt, retain, and recover business data."
        ),
        "questions": [
            {
                "key": "data_classification",
                "text": "Is sensitive data classified and inventoried?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Build a sensitive data inventory with classification labels and "
                    "owners, and apply DLP or labelling policies to enforce handling."
                ),
            },
            {
                "key": "data_encrypt_rest",
                "text": "Is data encrypted at rest on endpoints and servers?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Enforce full-disk encryption (BitLocker/FileVault/LUKS) on every "
                    "endpoint and enable native encryption on storage and databases."
                ),
            },
            {
                "key": "data_encrypt_transit",
                "text": "Is data encrypted in transit (TLS enforced)?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Require TLS 1.2 or higher for all internal and external services "
                    "and disable legacy ciphers and protocols."
                ),
            },
            {
                "key": "data_backup_freq",
                "text": "Are backups performed daily and tested quarterly?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Schedule daily backups for critical systems and complete a "
                    "documented restore test at least once per quarter."
                ),
            },
            {
                "key": "data_backup_immutable",
                "text": "Are backups stored offline or immutably (ransomware-protected)?",
                "weight": 3,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "unknown", "label": "Unknown", "score": 0.0},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Implement immutable or air-gapped backups (object lock, tape, or "
                    "tenant-isolated cloud) so ransomware cannot encrypt the backups."
                ),
            },
            {
                "key": "data_retention",
                "text": "Is there a documented data retention and destruction policy?",
                "weight": 1,
                "options": _YES_NO,
                "recommendation": (
                    "Publish a data retention and destruction policy aligned to "
                    "regulatory and contractual obligations and enforce it via tooling."
                ),
            },
        ],
    },
    {
        "key": "vuln",
        "name": "Vulnerability & Patch Management",
        "description": (
            "Controls that identify, prioritise, and remediate technical vulnerabilities."
        ),
        "questions": [
            {
                "key": "vm_program",
                "text": "Is there a formal vulnerability management program?",
                "weight": 2,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "informal", "label": "Informal", "score": 0.5},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Formalise the vulnerability management program with documented "
                    "scope, ownership, tooling, SLAs, and metrics reported to leadership."
                ),
            },
            {
                "key": "vm_quarterly_scan",
                "text": "Are internal systems scanned for vulnerabilities at least quarterly?",
                "weight": 2,
                "options": _YES_NO,
                "recommendation": (
                    "Run authenticated internal vulnerability scans at least quarterly "
                    "and feed the findings into the patch and remediation backlog."
                ),
            },
            {
                "key": "vm_critical_sla",
                "text": "Are critical vulnerabilities remediated within 72 hours?",
                "weight": 2,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "sla_defined", "label": "SLA Defined but Not Always Met", "score": 0.5},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Adopt a 72-hour remediation SLA for critical-severity vulnerabilities "
                    "and report exceptions to the executive risk committee."
                ),
            },
            {
                "key": "vm_patch_compliance",
                "text": "Is patch compliance tracked and reported?",
                "weight": 2,
                "options": _YES_NO,
                "recommendation": (
                    "Track patch compliance metrics by asset class and report monthly "
                    "to IT leadership, with remediation tickets for missed SLAs."
                ),
            },
        ],
    },
    {
        "key": "awareness",
        "name": "Security Awareness & Training",
        "description": (
            "Controls that prepare and test the workforce to resist social engineering."
        ),
        "questions": [
            {
                "key": "aw_annual_training",
                "text": "Do employees receive security awareness training at least annually?",
                "weight": 1,
                "options": _YES_NO,
                "recommendation": (
                    "Deliver mandatory security awareness training to every employee at "
                    "least annually and track completion at the manager level."
                ),
            },
            {
                "key": "aw_phishing_sim",
                "text": "Is phishing simulation testing conducted?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "planned", "label": "Planned", "score": 0.5},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Run quarterly phishing simulations targeting realistic lures and "
                    "deliver targeted retraining to repeat clickers."
                ),
            },
            {
                "key": "aw_role_based",
                "text": "Is there role-based training for IT and privileged users?",
                "weight": 1,
                "options": _YES_NO,
                "recommendation": (
                    "Provide role-based security training for IT administrators, "
                    "developers, and finance staff focused on threats relevant to them."
                ),
            },
            {
                "key": "aw_aup",
                "text": "Are acceptable use policies acknowledged annually by all staff?",
                "weight": 1,
                "options": _YES_NO,
                "recommendation": (
                    "Require all staff to acknowledge the Acceptable Use Policy on "
                    "hire and annually thereafter, retaining the records for audit."
                ),
            },
        ],
    },
    {
        "key": "ir",
        "name": "Incident Response & Business Continuity",
        "description": (
            "Controls that prepare, detect, and recover from disruptive incidents."
        ),
        "questions": [
            {
                "key": "ir_plan",
                "text": "Is there a documented Incident Response (IR) plan?",
                "weight": 2,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "untested", "label": "Exists but Untested", "score": 0.5},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Document a comprehensive Incident Response plan with roles, "
                    "escalation paths, evidence handling, and external partner contacts."
                ),
            },
            {
                "key": "ir_tabletop",
                "text": "Has the IR plan been tested via tabletop exercise in the last 12 months?",
                "weight": 1,
                "options": _YES_NO,
                "recommendation": (
                    "Conduct an annual tabletop exercise covering ransomware and BEC "
                    "scenarios with leadership and IT, and remediate the gaps found."
                ),
            },
            {
                "key": "ir_bcp_drp",
                "text": "Is there a Business Continuity Plan (BCP) and Disaster Recovery Plan (DRP)?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Develop and test a BCP and DRP covering critical business "
                    "processes, dependencies, and recovery sites or cloud failover."
                ),
            },
            {
                "key": "ir_rto_rpo",
                "text": "Is there a defined RTO/RPO for critical systems?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "informal", "label": "Informal", "score": 0.5},
                    {"value": "no", "label": "No", "score": 0.0},
                ],
                "recommendation": (
                    "Define and document Recovery Time and Recovery Point Objectives "
                    "for every critical system and validate them during DR tests."
                ),
            },
            {
                "key": "ir_ticketing",
                "text": "Is there a formal process to report and track security incidents?",
                "weight": 1,
                "options": _YES_NO,
                "recommendation": (
                    "Provide every employee with a clear channel for reporting "
                    "suspected incidents and track them through resolution in a ticketing tool."
                ),
            },
        ],
    },
    {
        "key": "compliance",
        "name": "Compliance & Governance",
        "description": (
            "Policies, third-party assessments, and asset governance."
        ),
        "questions": [
            {
                "key": "gov_regulatory",
                "text": "Is the organization subject to a regulatory framework (HIPAA, PCI-DSS, SOC 2, etc.)?",
                "weight": 1,
                "options": [
                    {"value": "yes", "label": "Yes", "score": 1.0},
                    {"value": "no", "label": "No", "score": 1.0},
                ],
                "recommendation": "",
            },
            {
                "key": "gov_infosec_policy",
                "text": "Is there a dedicated information security policy reviewed annually?",
                "weight": 1,
                "options": _YES_NO,
                "recommendation": (
                    "Adopt a board-approved information security policy reviewed and "
                    "signed off at least annually."
                ),
            },
            {
                "key": "gov_third_party_audit",
                "text": "Has a third-party security assessment or audit been performed in the last 2 years?",
                "weight": 1,
                "options": _YES_NO,
                "recommendation": (
                    "Engage a qualified third party to perform an independent security "
                    "assessment at least every two years."
                ),
            },
            {
                "key": "gov_vendor_risk",
                "text": "Is vendor/third-party risk assessed before granting access?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Implement a third-party risk programme that performs due diligence "
                    "before granting vendors access to data or systems."
                ),
            },
            {
                "key": "gov_asset_inventory",
                "text": "Is there a documented asset inventory (hardware and software)?",
                "weight": 1,
                "options": _YES_PARTIAL_NO,
                "recommendation": (
                    "Maintain an authoritative hardware and software asset inventory "
                    "reconciled at least monthly with discovery tooling."
                ),
            },
        ],
    },
]


def section_by_key(key: str) -> Section | None:
    """Return the section dictionary matching the given key, or None."""
    for section in SECTIONS:
        if section["key"] == key:
            return section
    return None


def question_lookup() -> Dict[str, Question]:
    """Return a flat mapping of question_key -> question dict."""
    out: Dict[str, Question] = {}
    for section in SECTIONS:
        for question in section["questions"]:
            out[question["key"]] = question
    return out


def section_for_question(question_key: str) -> Section | None:
    """Find which section a question key belongs to."""
    for section in SECTIONS:
        for q in section["questions"]:
            if q["key"] == question_key:
                return section
    return None
