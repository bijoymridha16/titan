"""Decision layer — automated, rule-based strategy selection.

This package is what makes TITAN *decision-driven* instead of human-toggled.
It reads the market, classifies the regime with deterministic rules, and
arms/disarms the validated strategy set accordingly — every decision logged
with the exact features that produced it (the "no hallucination" guarantee).
"""
