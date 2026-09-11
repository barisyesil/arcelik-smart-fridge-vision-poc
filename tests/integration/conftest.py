"""Entegrasyon testleri için ortak fixture'lar — gerçek AWS'e ASLA dokunmaz.

`moto` HTTP çağrılarını yakalayıp sahte yanıt döner; testler gerçek AWS
kimlik bilgileri olsa bile (geliştirici makinesinde olabilir) hiçbir gerçek
kaynağa erişmez. `aws_credentials` fixture'ı sahte kimlik bilgilerini de
zorunlu kılar — moto bazı SDK yollarında hâlâ credential resolution ister.
"""

from __future__ import annotations

import pytest
from moto import mock_aws

TABLE_NAME = "fridge-main-test"
BUCKET_NAME = "fridge-raw-test"
REGION = "eu-central-1"


@pytest.fixture
def aws_credentials(monkeypatch):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_SECURITY_TOKEN", "testing")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)


@pytest.fixture
def dynamo_table(aws_credentials):
    """`fridge-main` şemasıyla (PK/SK + sparse GSI1) sahte bir tablo kurar."""
    import boto3

    with mock_aws():
        resource = boto3.resource("dynamodb", region_name=REGION)
        table = resource.create_table(
            TableName=TABLE_NAME,
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                    "ProvisionedThroughput": {"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
                }
            ],
            ProvisionedThroughput={"ReadCapacityUnits": 5, "WriteCapacityUnits": 5},
        )
        table.wait_until_exists()
        yield table


@pytest.fixture
def aws_stack(dynamo_table):
    """Tablo + `fridge-raw-test` bucket'ı — handler uçtan uca testleri için."""
    import boto3

    s3 = boto3.client("s3", region_name=REGION)
    s3.create_bucket(
        Bucket=BUCKET_NAME,
        CreateBucketConfiguration={"LocationConstraint": REGION},
    )
    yield dynamo_table


@pytest.fixture
def s3_client(aws_stack):
    """Sahte S3 client — presigned POST akışını taklit eden testler için."""
    import boto3

    return boto3.client("s3", region_name=REGION)
