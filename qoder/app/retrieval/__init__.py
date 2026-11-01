"""Hybrid retrieval (S2).

Vector recall, full-text recall and structured filters are issued separately,
then fused with configurable weights (RRF by default). Every hit must carry
doc_id / doc_title / section / page / chunk_id so the UI can cite the source.
"""
