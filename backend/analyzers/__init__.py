"""Deterministic project analyzers (Phase 6).

These produce FACTS — no LLM calls, fully unit-testable. The LLM later
interprets the facts into the migration report; it never invents them.

Safety: uploaded repositories are untrusted input. We only READ text files
(manifests, configs, source) with stdlib parsers — uploaded code is never
executed, and ZIP extraction is path-traversal protected (see api/migration).
"""
