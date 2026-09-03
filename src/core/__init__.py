"""Saf iş mantığı katmanı.

Bu paketin içinde `import boto3` veya herhangi bir AWS importu bulunamaz;
`tests/unit/test_core_purity.py` bunu zorlar. Böylece iş mantığı AWS olmadan
test edilir ve altyapıdan bağımsız kalır.
"""
