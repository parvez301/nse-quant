#!/usr/bin/env python3
import os

import aws_cdk as cdk

from cert_stack import CertStack
from nse_quant_stack import NseQuantStack


app = cdk.App()

notificationEmail = app.node.try_get_context("notification_email") or os.environ.get("NOTIFICATION_EMAIL")
if not notificationEmail:
    raise SystemExit(
        "notification_email is required. Pass via:\n"
        "  cdk deploy -c notification_email=you@example.com\n"
        "  (or)  NOTIFICATION_EMAIL=you@example.com cdk deploy"
    )

# Custom domain config — optional. If you want CloudFront + cert + Route53 alias,
# pass all three via `-c`:
#   cdk deploy -c custom_domain=trade.example.com \
#              -c hosted_zone_id=Z0123456789ABCDEFGHIJ \
#              -c hosted_zone_name=example.com
# Skip them entirely to deploy with just the raw Lambda Function URL.
customDomain = app.node.try_get_context("custom_domain")
hostedZoneId = app.node.try_get_context("hosted_zone_id")
hostedZoneName = app.node.try_get_context("hosted_zone_name")

awsAccount = os.environ.get("CDK_DEFAULT_ACCOUNT")
primaryRegion = os.environ.get("CDK_DEFAULT_REGION", "ap-south-1")

certificate = None
if customDomain:
    certStack = CertStack(
        app,
        "NseQuantCertStack",
        env=cdk.Environment(account=awsAccount, region="us-east-1"),
        cross_region_references=True,
        domain_name=customDomain,
        hosted_zone_id=hostedZoneId,
        hosted_zone_name=hostedZoneName,
    )
    certificate = certStack.certificate

NseQuantStack(
    app,
    "NseQuantStack",
    env=cdk.Environment(account=awsAccount, region=primaryRegion),
    cross_region_references=True,
    notification_email=notificationEmail,
    custom_domain=customDomain or None,
    hosted_zone_id=hostedZoneId if customDomain else None,
    hosted_zone_name=hostedZoneName if customDomain else None,
    certificate=certificate,
)

app.synth()
