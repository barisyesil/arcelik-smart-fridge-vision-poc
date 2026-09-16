#!/usr/bin/env python3
"""CDK giriş noktası.

Çalıştırma (infra dizininden):
    cdk synth
    cdk deploy -c budget_alert_email=ekip@ornek.com

`cdk.json` bu dizindedir; CDK CLI onu çalışma dizininde arar, böylece `cdk.out/`
repo kökünü kirletmez.
"""

import os

import aws_cdk as cdk
from stacks.fridge_stack import FridgeStack

app = cdk.App()
stage = str(app.node.try_get_context("stage") or "dev").lower()
if stage not in {"dev", "staging", "prod"}:
    raise ValueError("stage must be one of: dev, staging, prod")

stack_id = "FridgeStack" if stage == "dev" else f"FridgeStack{stage.title()}"
FridgeStack(
    app,
    stack_id,
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        # Bölge sabit: eu-central-1. Ücretsiz katman hesaplamaları buna göre.
        region="eu-central-1",
    ),
    stage=stage,
)

cdk.Tags.of(app).add("project", "smartfridge")
cdk.Tags.of(app).add("stage", stage)

app.synth()
