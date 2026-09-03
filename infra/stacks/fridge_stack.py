"""Tüm altyapı tek stack.

Kaynaklar bağımlılık sırasına göre tanımlanır:
    1. Log grupları  2. DynamoDB  3. SQS DLQ  4. SSM parametre (referans)
    5. Lambda'lar    6. S3 + olay bildirimi  7. HTTP API  8. Budget  9. IAM
"""

from __future__ import annotations

from pathlib import Path

from aws_cdk import Aws, CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_apigatewayv2 as apigatewayv2
from aws_cdk import aws_apigatewayv2_integrations as apigatewayv2_integrations
from aws_cdk import aws_budgets as budgets
from aws_cdk import aws_dynamodb as dynamodb
from aws_cdk import aws_iam as iam
from aws_cdk import aws_lambda as lambda_
from aws_cdk import aws_lambda_destinations as lambda_destinations
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_sqs as sqs
from aws_cdk import aws_ssm as ssm
from constructs import Construct


class FridgeStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, *, stage: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        self.stage = stage

        # ------------------------------------------------------------------
        # 1) CloudWatch Log Grupları
        # Lambda kendi log grubunu yaratırsa retention "asla silme" olur ve
        # ücretsiz katman sessizce dolar. Grupları burada tanımlayıp Lambda'ya
        # `log_group=` olarak geçiyoruz; retention 7 gün.
        # ------------------------------------------------------------------
        self.api_log_group = logs.LogGroup(
            self,
            "ApiLogGroup",
            log_group_name="/aws/lambda/fridge-api",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.extractor_log_group = logs.LogGroup(
            self,
            "ExtractorLogGroup",
            log_group_name="/aws/lambda/fridge-extractor",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------
        # 2) DynamoDB `fridge-main`
        # Provisioned 5/5 (on-demand ücretsiz katmanda değil). GSI1 projection ALL.
        # TTL attribute "expires_at". Streams şimdi açılır: sonradan açınca geçmiş
        # değişiklikler gelmez.
        # ------------------------------------------------------------------
        self.table = dynamodb.Table(
            self,
            "MainTable",
            table_name="fridge-main",
            partition_key=dynamodb.Attribute(
                name="PK",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="SK",
                type=dynamodb.AttributeType.STRING,
            ),
            billing_mode=dynamodb.BillingMode.PROVISIONED,
            read_capacity=5,
            write_capacity=5,
            time_to_live_attribute="expires_at",
            stream=dynamodb.StreamViewType.NEW_AND_OLD_IMAGES,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.table.add_global_secondary_index(
            index_name="GSI1",
            partition_key=dynamodb.Attribute(
                name="GSI1PK",
                type=dynamodb.AttributeType.STRING,
            ),
            sort_key=dynamodb.Attribute(
                name="GSI1SK",
                type=dynamodb.AttributeType.STRING,
            ),
            projection_type=dynamodb.ProjectionType.ALL,
            read_capacity=5,
            write_capacity=5,
        )

        # ------------------------------------------------------------------
        # 3) SQS `fridge-extractor-dlq` — retention 14 gün
        # ------------------------------------------------------------------
        self.extractor_dlq = sqs.Queue(
            self,
            "ExtractorDlq",
            queue_name="fridge-extractor-dlq",
            retention_period=Duration.days(14),
            encryption=sqs.QueueEncryption.SQS_MANAGED,
            removal_policy=RemovalPolicy.DESTROY,
        )

        # ------------------------------------------------------------------
        # 4) SSM Parametre `/smartfridge/dev/gemini-api-key`
        # SecureString CDK ile oluşturulamaz (değer şifreli olarak state'e düşmesin
        # diye CloudFormation desteklemiyor). Parametre elle oluşturulur:
        #   aws ssm put-parameter --name /smartfridge/dev/gemini-api-key \
        #       --type SecureString --value <ANAHTAR> --region eu-central-1
        # Stack sadece referans alır ve extractor rolüne okuma izni verir.
        # ------------------------------------------------------------------
        self.gemini_api_key = ssm.StringParameter.from_secure_string_parameter_attributes(
            self,
            "GeminiApiKey",
            parameter_name="/smartfridge/dev/gemini-api-key",
        )

        # ------------------------------------------------------------------
        # 5) Lambda'lar — VPC yok.
        #
        # fridge-api        : handler="handlers.inventory_api.handler"
        #                     256 MB, 10 sn, arm64. presign.py ayrı bir Lambda
        #                     değil — inventory_api "POST /v1/uploads" rotasında
        #                     onu içeriden çağırır.
        # fridge-extractor  : handler="handlers.extractor.handler"
        #                     512 MB, 60 sn, arm64, reserved_concurrent_executions=5,
        #                     on_failure -> SqsDestination(dlq)
        #
        # Kod, build_lambda_packages.py ile önceden paketlenir (handlers/, core/,
        # adapters/ ve extractor için ARM64 wheel'ler).
        # ------------------------------------------------------------------
        build_root = Path(__file__).resolve().parents[1] / "build"
        api_package = build_root / "fridge-api"
        extractor_package = build_root / "fridge-extractor"
        missing_packages = [
            str(package) for package in (api_package, extractor_package) if not package.is_dir()
        ]
        if missing_packages:
            raise FileNotFoundError(
                "Lambda deployment paketleri bulunamadi. Once "
                "`python infra/scripts/build_lambda_packages.py` calistirin: "
                + ", ".join(missing_packages)
            )

        self.api_function = lambda_.Function(
            self,
            "ApiFunction",
            function_name="fridge-api",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handlers.inventory_api.handler",
            code=lambda_.Code.from_asset(str(api_package)),
            memory_size=256,
            timeout=Duration.seconds(10),
            log_group=self.api_log_group,
            environment={
                "TABLE_NAME": self.table.table_name,
                "LOG_LEVEL": "INFO",
                "DEFAULT_USER_ID": "u_demo",
            },
        )

        self.extractor_function = lambda_.Function(
            self,
            "ExtractorFunction",
            function_name="fridge-extractor",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handlers.extractor.handler",
            code=lambda_.Code.from_asset(str(extractor_package)),
            memory_size=512,
            timeout=Duration.seconds(60),
            reserved_concurrent_executions=5,
            on_failure=lambda_destinations.SqsDestination(self.extractor_dlq),
            log_group=self.extractor_log_group,
            environment={
                "TABLE_NAME": self.table.table_name,
                "GEMINI_PARAM_NAME": self.gemini_api_key.parameter_name,
                "VISION_PROVIDER": "gemini",
                "LOG_LEVEL": "INFO",
            },
        )

        # ------------------------------------------------------------------
        # 6) S3 `fridge-raw-{hesap}`
        # BLOCK_ALL public access, SSE-S3, 30 gün lifecycle, CORS sadece
        # localhost:5173. Olay bildirimi ObjectCreated -> extractor; prefix
        # "uploads/" filtresi şart — filtresiz bildirim sonsuz döngü riski taşır.
        # ------------------------------------------------------------------
        raw_bucket_name = f"fridge-raw-{Aws.ACCOUNT_ID}"
        self.raw_bucket = s3.Bucket(
            self,
            "RawBucket",
            bucket_name=raw_bucket_name,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="ExpireRawUploadsAfter30Days",
                    prefix="uploads/",
                    expiration=Duration.days(30),
                )
            ],
            cors=[
                s3.CorsRule(
                    allowed_methods=[s3.HttpMethods.GET, s3.HttpMethods.POST],
                    allowed_origins=["http://localhost:5173"],
                    allowed_headers=["*"],
                )
            ],
            removal_policy=RemovalPolicy.DESTROY,
        )
        s3_invoke_permission = lambda_.CfnPermission(
            self,
            "AllowS3ToInvokeExtractor",
            action="lambda:InvokeFunction",
            function_name=self.extractor_function.function_arn,
            principal="s3.amazonaws.com",
            source_account=Aws.ACCOUNT_ID,
            source_arn=f"arn:{Aws.PARTITION}:s3:::{raw_bucket_name}",
        )
        raw_bucket_resource = self.raw_bucket.node.default_child
        if not isinstance(raw_bucket_resource, s3.CfnBucket):
            raise TypeError("RawBucket icin beklenen CloudFormation kaynagi bulunamadi")
        raw_bucket_resource.notification_configuration = (
            s3.CfnBucket.NotificationConfigurationProperty(
                lambda_configurations=[
                    s3.CfnBucket.LambdaConfigurationProperty(
                        event="s3:ObjectCreated:*",
                        function=self.extractor_function.function_arn,
                        filter=s3.CfnBucket.NotificationFilterProperty(
                            s3_key=s3.CfnBucket.S3KeyFilterProperty(
                                rules=[
                                    s3.CfnBucket.FilterRuleProperty(
                                        name="prefix",
                                        value="uploads/",
                                    )
                                ]
                            )
                        ),
                    )
                ]
            )
        )
        raw_bucket_resource.add_dependency(s3_invoke_permission)
        self.api_function.add_environment("BUCKET_NAME", self.raw_bucket.bucket_name)

        # ------------------------------------------------------------------
        # 7) HTTP API `fridge-api-gw`
        # Auth yok. Throttle: rate 5 rps, burst 10. CORS sadece localhost:5173.
        # Rotalar (API kontratı v1, path'ler dondurulmuş):
        #   POST /v1/uploads, GET /v1/uploads/{upload_id}, GET /v1/items,
        #   PATCH /v1/items/{item_id}, DELETE /v1/items/{item_id}
        # ------------------------------------------------------------------
        self.api_access_log_group = logs.LogGroup(
            self,
            "ApiAccessLogGroup",
            log_group_name="/aws/apigateway/fridge-api-gw",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        self.http_api = apigatewayv2.HttpApi(
            self,
            "HttpApi",
            api_name="fridge-api-gw",
            cors_preflight=apigatewayv2.CorsPreflightOptions(
                allow_origins=["http://localhost:5173"],
                allow_headers=["content-type", "x-user-id"],
                allow_methods=[
                    apigatewayv2.CorsHttpMethod.GET,
                    apigatewayv2.CorsHttpMethod.POST,
                    apigatewayv2.CorsHttpMethod.PATCH,
                    apigatewayv2.CorsHttpMethod.DELETE,
                ],
            ),
        )
        api_integration = apigatewayv2_integrations.HttpLambdaIntegration(
            "ApiIntegration",
            self.api_function,
        )
        routes = (
            (apigatewayv2.HttpMethod.POST, "/v1/uploads"),
            (apigatewayv2.HttpMethod.GET, "/v1/uploads/{upload_id}"),
            (apigatewayv2.HttpMethod.GET, "/v1/items"),
            (apigatewayv2.HttpMethod.PATCH, "/v1/items/{item_id}"),
            (apigatewayv2.HttpMethod.DELETE, "/v1/items/{item_id}"),
        )
        for method, path in routes:
            self.http_api.add_routes(
                path=path,
                methods=[method],
                integration=api_integration,
            )

        default_stage = self.http_api.default_stage
        if default_stage is None:
            raise RuntimeError("HTTP API default stage olusturulamadi")
        default_stage_resource = default_stage.node.default_child
        if not isinstance(default_stage_resource, apigatewayv2.CfnStage):
            raise TypeError("HTTP API icin beklenen default stage kaynagi bulunamadi")
        default_stage_resource.default_route_settings = apigatewayv2.CfnStage.RouteSettingsProperty(
            throttling_burst_limit=10,
            throttling_rate_limit=5,
        )
        default_stage_resource.access_log_settings = (
            apigatewayv2.CfnStage.AccessLogSettingsProperty(
                destination_arn=self.api_access_log_group.log_group_arn,
                format=(
                    '{"requestId":"$context.requestId","routeKey":"$context.routeKey",'
                    '"status":"$context.status","responseLength":"$context.responseLength",'
                    '"integrationError":"$context.integrationErrorMessage"}'
                ),
            )
        )

        # ------------------------------------------------------------------
        # 8) Budget 5 USD — e-posta alarmı (ACTUAL %80 ve %100 eşikleri)
        # E-posta adresi koda gömülmez; CDK context'ten okunur:
        #   cdk deploy -c budget_alert_email=ekip@ornek.com
        # ------------------------------------------------------------------
        alert_email = self.node.try_get_context("budget_alert_email")
        if not alert_email:
            raise ValueError("Synth/deploy icin `-c budget_alert_email=ekip@ornek.com` gerekli")
        budgets.CfnBudget(
            self,
            "MonthlyBudget",
            budget=budgets.CfnBudget.BudgetDataProperty(
                budget_name="smartfridge-monthly-budget",
                budget_type="COST",
                time_unit="MONTHLY",
                budget_limit=budgets.CfnBudget.SpendProperty(
                    amount=5,
                    unit="USD",
                ),
            ),
            notifications_with_subscribers=[
                budgets.CfnBudget.NotificationWithSubscribersProperty(
                    notification=budgets.CfnBudget.NotificationProperty(
                        comparison_operator="GREATER_THAN",
                        notification_type="ACTUAL",
                        threshold=threshold,
                        threshold_type="PERCENTAGE",
                    ),
                    subscribers=[
                        budgets.CfnBudget.SubscriberProperty(
                            address=alert_email,
                            subscription_type="EMAIL",
                        )
                    ],
                )
                for threshold in (80, 100)
            ],
        )

        # ------------------------------------------------------------------
        # 9) IAM — kaynak bazlı, wildcard yok.
        # api rolü       : tabloya read/write, bucket'a s3:PutObject (uploads/*)
        # extractor rolü : tabloya read/write + dynamodb:TransactWriteItems
        #                  (commit_extraction tek transaction'da yazdığı için bu
        #                  izin şart), bucket'a s3:GetObject (uploads/*), SSM
        #                  parametresine okuma + kms:Decrypt, DLQ'ya SendMessage.
        #
        # Bucket izinlerinde `grant_put/grant_read` KULLANILMAZ: bu helper'lar
        # policy statement'ına bucket'a Fn::GetAtt referansı gömer. RawBucket zaten
        # (S3 bildirimi için) ExtractorFunction'a bağımlı; extractor'ın policy'si
        # de bucket'a bağımlı olursa "Circular dependency between resources" ile
        # deploy patlar (cdk synth bunu yakalamaz, sadece changeset aşamasında
        # çıkar). Bucket adı zaten sadece hesap kimliğinden türediği için ARN elle
        # kurulup döngü kaynağı referansı atlanır.
        # ------------------------------------------------------------------
        raw_bucket_arn = f"arn:{Aws.PARTITION}:s3:::{raw_bucket_name}"

        self.table.grant_read_write_data(self.api_function)
        self.api_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject"],
                resources=[f"{raw_bucket_arn}/uploads/*"],
            )
        )

        self.table.grant_read_write_data(self.extractor_function)
        self.table.grant(self.extractor_function, "dynamodb:TransactWriteItems")
        self.extractor_function.add_to_role_policy(
            iam.PolicyStatement(
                actions=["s3:GetObject"],
                resources=[f"{raw_bucket_arn}/uploads/*"],
            )
        )
        self.gemini_api_key.grant_read(self.extractor_function)

        # Web arayüzünün .env'i için gerekli çıktılar.
        CfnOutput(self, "ApiUrl", value=self.http_api.api_endpoint)
        CfnOutput(self, "BucketName", value=self.raw_bucket.bucket_name)
        CfnOutput(self, "TableName", value=self.table.table_name)
