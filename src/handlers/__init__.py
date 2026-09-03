"""AWS'e bağımlı ince adaptörler.

Bir handler 10-20 satırı geçiyorsa, muhtemelen içine `core/`'a ait bir karar
sızmıştır. Handler event'i parse eder, `core/`'u çağırır, sonucu yazar.
"""
