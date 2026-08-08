"""
Prompt-injection guard for untrusted email content.

Runs entirely locally, BEFORE any content is sent to OpenRouter:
1. sanitize_text: Unicode normalization plus stripping of invisible
   characters that can hide instructions from human review.
2. HeuristicDetector: deterministic regex patterns for known injection
   markers (instruction overrides, role spoofing, output planting).
3. MLDetector: a local transformer classifier (no API calls) that scores
   text for prompt-injection intent.
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Zero-width, soft-hyphen, and bidi-control characters: invisible to a human
# reader but still tokenized by the model, a common carrier for hidden
# instructions.
_HIDDEN_CHARS = re.compile(
    "[\u200b-\u200f\u2028\u2029\u202a-\u202e" "\u2060-\u2064\u2066-\u2069\u00ad\ufeff]"
)

# C0/C1 control characters except tab and newline.
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")

# Spoofed prompt-boundary markers. The real markers include a per-request
# random token an attacker cannot predict, but strip lookalikes anyway.
_BOUNDARY_SPOOF = re.compile(r"(?:BEGIN|END)_EMAIL_\S*", re.IGNORECASE)


def sanitize_text(text: Optional[str]) -> str:
    """
    Normalize and clean untrusted text before scanning or prompting.

    Args:
        text: Raw text from an email field (may be None)

    Returns:
        Sanitized text safe for inclusion in a prompt
    """
    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _HIDDEN_CHARS.sub("", text)
    text = _CONTROL_CHARS.sub("", text)
    text = _BOUNDARY_SPOOF.sub("", text)
    return text


class HeuristicDetector:
    """Deterministic regex detection of known prompt-injection markers."""

    PATTERNS = {
        "instruction_override": re.compile(
            r"\b(?:ignore|disregard|forget|bypass|override)\b"
            r"(?:\W+\w+){0,4}?\W+"
            r"(?:instructions?|prompts?|rules?|directives?)\b",
            re.IGNORECASE,
        ),
        "new_instructions": re.compile(
            r"\b(?:new|updated|revised|real|actual)\s+"
            r"(?:instructions?|system\s+prompt|task)\s*(?::|\bare\b|\bis\b)",
            re.IGNORECASE,
        ),
        "role_spoofing": re.compile(
            r"^\s*(?:system|assistant|developer)\s*:",
            re.IGNORECASE | re.MULTILINE,
        ),
        "special_tokens": re.compile(
            r"<\|[a-z_]+\|>|\[/?INST\]|<<SYS>>|###\s*(?:system|instruction)",
            re.IGNORECASE,
        ),
        "prompt_extraction": re.compile(
            r"\b(?:reveal|show|print|repeat|output|display)\b"
            r"(?:\W+\w+){0,3}?\W+"
            r"(?:system\s+prompt|your\s+instructions?)\b",
            re.IGNORECASE,
        ),
        "output_planting": re.compile(
            r"\"labels\"\s*:"
            r"|\b(?:respond|reply|answer)\s+(?:with\s+)?only\b"
            r"|\byour\s+(?:response|output|answer)\s+must\b",
            re.IGNORECASE,
        ),
        # Direct address to the classifier: legitimate human email never
        # opens with "dear AI" or "attention classification model"
        "model_addressing": re.compile(
            r"\b(?:dear|hello|hey|attention)[,:]?\s+"
            r"(?:ai\b|assistant\b|classifier\b|llm\b"
            r"|classification\s+(?:model|system|assistant)"
            r"|language\s+model)",
            re.IGNORECASE,
        ),
        # Telling the classifier to disregard the email's actual content
        "content_override": re.compile(
            r"\bregardless\s+of\b(?:\W+\w+){0,3}?\W+content\b"
            r"|\bno\s+matter\s+what\b(?:\W+\w+){0,3}?\W+(?:says|contains?)\b",
            re.IGNORECASE,
        ),
    }

    def scan(self, text: str) -> List[str]:
        """
        Scan text for injection markers.

        Args:
            text: Sanitized text to scan

        Returns:
            Names of matched patterns (empty list if clean)
        """
        return [name for name, pattern in self.PATTERNS.items() if pattern.search(text)]


class MLDetector:
    """Local ML prompt-injection classifier (lazy-loaded, CPU-only)."""

    # ~1500 chars is well under the model's 512-token limit for typical text;
    # overlap ensures an injection spanning a chunk boundary is still seen.
    CHUNK_SIZE = 1500
    CHUNK_OVERLAP = 200

    # Default calibrated against the efficacy corpus: real attacks the
    # heuristics miss score ~1.0, while benign-but-imperative emails
    # (itineraries, product announcements) can score 0.91-0.98
    DEFAULT_THRESHOLD = 0.98

    def __init__(self, model_name: str, threshold: float = DEFAULT_THRESHOLD):
        """
        Args:
            model_name: HuggingFace model ID for text classification
            threshold: Injection probability at or above which text is flagged
        """
        self.model_name = model_name
        self.threshold = threshold
        self._pipeline = None
        self._load_failed = False

    def _load(self):
        """Load the classification pipeline once; disable on failure."""
        if self._pipeline is None and not self._load_failed:
            try:
                from transformers import pipeline

                self._pipeline = pipeline(
                    "text-classification",
                    model=self.model_name,
                    truncation=True,
                    max_length=512,
                )
                logger.info(f"Loaded injection detection model: {self.model_name}")
            except Exception as e:
                self._load_failed = True
                logger.error(
                    f"Failed to load injection detection model "
                    f"'{self.model_name}': {e}. "
                    f"Continuing with heuristic detection only."
                )
        return self._pipeline

    @classmethod
    def _chunk(cls, text: str) -> List[str]:
        """Split text into overlapping chunks that fit the model's context."""
        if len(text) <= cls.CHUNK_SIZE:
            return [text]

        chunks = []
        step = cls.CHUNK_SIZE - cls.CHUNK_OVERLAP
        for start in range(0, len(text), step):
            chunk = text[start : start + cls.CHUNK_SIZE]
            chunks.append(chunk)
            if start + cls.CHUNK_SIZE >= len(text):
                break
        return chunks

    def scan(self, text: str) -> Optional[float]:
        """
        Score text for prompt-injection intent.

        Args:
            text: Sanitized text to score

        Returns:
            Maximum injection probability across chunks, or None if the
            model is unavailable
        """
        pipe = self._load()
        if pipe is None or not text.strip():
            return None

        try:
            max_score = 0.0
            for chunk in self._chunk(text):
                result = pipe(chunk)[0]
                label = result.get("label", "").upper()
                score = float(result.get("score", 0.0))
                injection_score = score if label == "INJECTION" else 1.0 - score
                max_score = max(max_score, injection_score)
            return max_score
        except Exception as e:
            logger.error(f"Error running injection detection model: {e}")
            return None


@dataclass
class ScanResult:
    """Result of scanning an email for prompt injection."""

    flagged: bool
    reasons: List[str]
    sanitized_email: Dict


class InjectionGuard:
    """Combined sanitization and detection pipeline for incoming emails."""

    SCANNED_FIELDS = ("subject", "from", "body", "snippet")

    def __init__(
        self,
        ml_enabled: bool = True,
        ml_model: str = "protectai/deberta-v3-base-prompt-injection-v2",
        ml_threshold: float = MLDetector.DEFAULT_THRESHOLD,
    ):
        """
        Args:
            ml_enabled: Whether to run the local ML detector
            ml_model: HuggingFace model ID for the ML detector
            ml_threshold: Injection probability at or above which to flag
        """
        self.heuristics = HeuristicDetector()
        self.ml = MLDetector(ml_model, ml_threshold) if ml_enabled else None

    def scan(self, email: Dict) -> ScanResult:
        """
        Sanitize an email and scan it for prompt-injection attempts.

        Args:
            email: Email dictionary with subject, from, body/snippet fields

        Returns:
            ScanResult with flagged status, reasons, and the sanitized email
        """
        sanitized = dict(email)
        for field_name in self.SCANNED_FIELDS:
            if field_name in sanitized:
                sanitized[field_name] = sanitize_text(sanitized[field_name])

        combined = "\n".join(
            sanitized.get(field_name, "") for field_name in self.SCANNED_FIELDS
        )

        reasons = [f"heuristic:{name}" for name in self.heuristics.scan(combined)]

        # Skip the ML pass when heuristics already flagged the email
        if not reasons and self.ml is not None:
            score = self.ml.scan(combined)
            if score is not None and score >= self.ml.threshold:
                reasons.append(f"ml:score={score:.3f}")

        return ScanResult(
            flagged=bool(reasons), reasons=reasons, sanitized_email=sanitized
        )
