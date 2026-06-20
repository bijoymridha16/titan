"""Analytics data-capture layer.

Persists the full decision trail — every signal (incl. rejected), every order
attempt, every fill's realized slippage, and the feature vector at decision time
— so the paper→live call rests on complete evidence, not just filled trades.
All writes are best-effort: a logging failure must never break trading.
"""
