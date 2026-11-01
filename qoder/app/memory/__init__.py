"""Memory layer (S3).

PowerContext owns what cannot be computed: preferences, error attribution,
session summaries, plans and task progress. It is deliberately separate from
seekdb, which owns the corpus and the numeric mastery scores. ``client.py``
talks HTTP; ``kinds.py`` defines the memory taxonomy.
"""
