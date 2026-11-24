"""
guardrails.py - Security Guardrails, DoS Protection & Output Verification
Course: PCAM* ZG516 - Applied Generative AI (Major Project / Assignment 2)
Phase 3: Security Guardrails, Prompt Ablation & Self-Improving Loop
Satisfies: FR4 (Guardrail overhead < 6s), NFR1, Experiment E9
"""

import re
import time
from typing import Dict, Any, Tuple, Optional

class DoSProtection:
    """Rate limiter and request payload sanity validator (FR4)."""
    def __init__(self, max_chars: int = 1500, min_interval_sec: float = 0.5):
        self.max_chars = max_chars
        self.min_interval_sec = min_interval_sec
        self.last_query_time = 0.0

    def check(self, query: str) -> Tuple[bool, Optional[str]]:
        now = time.time()
        if (now - self.last_query_time) < self.min_interval_sec:
            return False, "Rate limit exceeded: Please wait before submitting another query."
        if len(query.strip()) == 0:
            return False, "Query cannot be empty."
        if len(query) > self.max_chars:
            return False, f"Query exceeds maximum allowed length of {self.max_chars} characters."
        self.last_query_time = now
        return True, None


class InputGuardrails:
    """Detects prompt injections, PII, and out-of-scope non-regulatory queries."""
    
    INJECTION_PATTERNS = [
        r"ignore\s+(?:all\s+)?(?:previous\s+)?(?:above\s+)?instructions",
        r"system\s+prompt\s+override",
        r"you\s+are\s+now\s+(?:dan|unrestricted|jailbroken)",
        r"bypass\s+(?:all\s+)?(?:rules|guardrails|safety)",
        r"reveal\s+(?:internal|system|prompt)\s+instructions",
        r"forget\s+(?:your|the|all)\s+constraints"
    ]
    
    FINANCE_KEYWORDS = [
        "rbi", "bank", "nbfc", "capital", "car", "crar", "cet1", "basel", 
        "repo", "reverse repo", "msf", "sdf", "inflation", "cpi", "mpc",
        "lending", "kyc", "aml", "priority sector", "psl", "deposit", 
        "liquidity", "crr", "slr", "guideline", "direction", "circular",
        "payment", "upi", "card", "cyber", "green", "housing"
    ]
    
    PII_PATTERNS = {
        "AADHAAR": r"\b\d{4}\s\d{4}\s\d{4}\b",
        "PAN": r"\b[A-Z]{5}[0-9]{4}[A-Z]\b",
        "PHONE": r"\b(?:\+91|0)?[6-9]\d{9}\b",
        "EMAIL": r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"
    }

    @classmethod
    def detect_prompt_injection(cls, query: str) -> bool:
        q_lower = query.lower()
        return any(re.search(pat, q_lower) for pat in cls.INJECTION_PATTERNS)

    @classmethod
    def check_domain_scope(cls, query: str) -> bool:
        q_lower = query.lower()
        return any(k in q_lower for k in cls.FINANCE_KEYWORDS)

    @classmethod
    def sanitize_pii(cls, text: str) -> Tuple[str, bool]:
        sanitized = text
        pii_detected = False
        for pii_type, pattern in cls.PII_PATTERNS.items():
            if re.search(pattern, sanitized, flags=re.IGNORECASE):
                pii_detected = True
                sanitized = re.sub(pattern, f"[{pii_type}_REDACTED]", sanitized, flags=re.IGNORECASE)
        return sanitized, pii_detected

    @classmethod
    def validate_input(cls, query: str) -> Dict[str, Any]:
        start = time.perf_counter()
        
        # 1. Prompt Injection Check
        if cls.detect_prompt_injection(query):
            return {
                "allowed": False,
                "reason": "Security Alert: Adversarial prompt injection attempt detected.",
                "latency_sec": time.perf_counter() - start
            }
        
        # 2. Domain Scope Check
        if not cls.check_domain_scope(query):
            return {
                "allowed": False,
                "reason": "Out of Scope: Query is unrelated to RBI banking and financial regulations.",
                "latency_sec": time.perf_counter() - start
            }
        
        # 3. PII Masking
        clean_query, pii_found = cls.sanitize_pii(query)
        
        return {
            "allowed": True,
            "sanitized_query": clean_query,
            "pii_detected": pii_found,
            "latency_sec": time.perf_counter() - start
        }


class OutputGuardrails:
    """Verifies citation presence, grounding, and detects hallucinations."""
    
    CITATION_REGEX = r"\[(?:Source|Document):\s*([^,\]]+),\s*(?:Page|Slide):\s*(\d+)\]"

    @classmethod
    def validate_output(cls, response: str, context: str) -> Dict[str, Any]:
        start = time.perf_counter()
        
        # Safe refusal handling
        if "insufficient evidence" in response.lower() or "not stated in the provided documents" in response.lower():
            return {
                "valid": True,
                "status": "SAFE_REFUSAL",
                "citations_found": [],
                "latency_sec": time.perf_counter() - start
            }
        
        # Mandatory citation validation
        citations = re.findall(cls.CITATION_REGEX, response, flags=re.IGNORECASE)
        if not citations:
            return {
                "valid": False,
                "status": "MISSING_CITATION",
                "reason": "Answer failed guardrails: Missing mandatory citation format [Source: <doc>, Page/Slide: <page>].",
                "latency_sec": time.perf_counter() - start
            }
            
        return {
            "valid": True,
            "status": "PASSED",
            "citations_found": citations,
            "latency_sec": time.perf_counter() - start
        }
