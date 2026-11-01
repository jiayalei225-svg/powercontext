"""Ingestion (S2).

Turns markdown / txt / pdf into heading-aware chunks and writes both the
embedding and the full-text index. Kept separate from retrieval because the
failure modes are different: ingestion fails on parsing and chunk boundaries,
retrieval fails on ranking and filters.
"""
