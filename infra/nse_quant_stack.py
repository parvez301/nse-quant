from pathlib import Path

from aws_cdk import (
    BundlingOptions,
    CfnOutput,
    Duration,
    RemovalPolicy,
    Stack,
    aws_certificatemanager as acm,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as cloudfront_origins,
    aws_ec2 as ec2,
    aws_ecr_assets as ecr_assets,
    aws_ecs as ecs,
    aws_events as events,
    aws_events_targets as events_targets,
    aws_iam as iam,
    aws_lambda as lambda_,
    aws_logs as logs,
    aws_route53 as route53,
    aws_route53_targets as route53_targets,
    aws_s3 as s3,
    aws_secretsmanager as secretsmanager,
    aws_sns as sns,
    aws_sns_subscriptions as sns_subs,
)
from constructs import Construct


REPO_ROOT = Path(__file__).resolve().parent.parent


class NseQuantStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        notification_email: str,
        custom_domain: str | None = None,
        hosted_zone_id: str | None = None,
        hosted_zone_name: str | None = None,
        certificate: acm.ICertificate | None = None,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # ------------------------------------------------------------------
        # State bucket: qlib data + outputs (decisions, portfolio, equity)
        # ------------------------------------------------------------------
        stateBucket = s3.Bucket(
            self,
            "StateBucket",
            bucket_name=None,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            versioned=True,
            removal_policy=RemovalPolicy.RETAIN,
            lifecycle_rules=[
                s3.LifecycleRule(
                    id="expire-noncurrent",
                    noncurrent_version_expiration=Duration.days(30),
                    abort_incomplete_multipart_upload_after=Duration.days(7),
                ),
            ],
        )

        # ------------------------------------------------------------------
        # SNS topic for notifications + email subscription
        # ------------------------------------------------------------------
        notifyTopic = sns.Topic(self, "NotifyTopic", display_name="NSE Quant Notifications")
        notifyTopic.add_subscription(sns_subs.EmailSubscription(notification_email))

        # ------------------------------------------------------------------
        # Container image — built locally, pushed to CDK-managed ECR
        # ------------------------------------------------------------------
        cronImage = ecr_assets.DockerImageAsset(
            self,
            "CronImage",
            directory=str(REPO_ROOT),
            file="docker/Dockerfile",
            platform=ecr_assets.Platform.LINUX_ARM64,
            exclude=[
                ".venv",
                ".git",
                "infra",
                "ui_lambda",
                "data/qlib_data",
                "outputs/walkforward_backtest",
                "outputs/processed_datasets",
                "outputs/daily.log",
                "outputs/alerts.log",
                "outputs/HALT",
                "outputs/*.png",
                "docs",
                "**/__pycache__",
            ],
        )

        # ------------------------------------------------------------------
        # ECS cluster on default VPC; Fargate Spot task scheduled by EventBridge
        # ------------------------------------------------------------------
        vpc = ec2.Vpc.from_lookup(self, "DefaultVpc", is_default=True)
        cluster = ecs.Cluster(
            self,
            "Cluster",
            vpc=vpc,
            enable_fargate_capacity_providers=True,
        )
        cluster.add_default_capacity_provider_strategy([
            ecs.CapacityProviderStrategy(capacity_provider="FARGATE_SPOT", weight=1),
        ])

        taskDefinition = ecs.FargateTaskDefinition(
            self,
            "DailyTaskDef",
            cpu=512,
            memory_limit_mib=2048,
            ephemeral_storage_gib=21,
            runtime_platform=ecs.RuntimePlatform(
                cpu_architecture=ecs.CpuArchitecture.ARM64,
                operating_system_family=ecs.OperatingSystemFamily.LINUX,
            ),
        )

        stateBucket.grant_read_write(taskDefinition.task_role)
        notifyTopic.grant_publish(taskDefinition.task_role)

        cronLogGroup = logs.LogGroup(
            self,
            "CronLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )

        taskDefinition.add_container(
            "Daily",
            image=ecs.ContainerImage.from_docker_image_asset(cronImage),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="daily", log_group=cronLogGroup),
            environment={
                "STATE_BUCKET": stateBucket.bucket_name,
                "SNS_TOPIC_ARN": notifyTopic.topic_arn,
                "AWS_DEFAULT_REGION": self.region,
            },
        )

        # 02:30 UTC Mon-Fri = 08:00 IST Mon-Fri
        # Default container CMD = /app/run_daily_cloud.sh (set in Dockerfile),
        # so we don't need a containerOverrides command here.
        scheduleRule = events.Rule(
            self,
            "DailyCron",
            schedule=events.Schedule.cron(minute="30", hour="2", week_day="MON-FRI"),
        )
        scheduleRule.add_target(
            events_targets.EcsTask(
                cluster=cluster,
                task_definition=taskDefinition,
                assign_public_ip=True,
                subnet_selection=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            )
        )

        # 10:30 UTC Mon-Fri = 16:00 IST Mon-Fri — post-NSE-close run that
        # fires Tier 3 (live IC) + Tier 4 (token re-probe) when Kite quotes
        # actually reflect intraday movement. Reuses the same task definition
        # and image; container_overrides points it at the post-close entry.
        postCloseRule = events.Rule(
            self,
            "PostCloseCron",
            schedule=events.Schedule.cron(minute="30", hour="10", week_day="MON-FRI"),
        )
        postCloseRule.add_target(
            events_targets.EcsTask(
                cluster=cluster,
                task_definition=taskDefinition,
                assign_public_ip=True,
                subnet_selection=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
                container_overrides=[
                    events_targets.ContainerOverride(
                        container_name="Daily",
                        command=["/app/run_postclose_cloud.sh"],
                    )
                ],
            )
        )

        # Catch infrastructure failures (image pull, ENI alloc, OOM kill) — cases
        # where the script never reached its own SNS notify path. Successful runs
        # exit with stopCode=EssentialContainerExited which we deliberately ignore.
        events.Rule(
            self,
            "TaskFailureAlarm",
            event_pattern=events.EventPattern(
                source=["aws.ecs"],
                detail_type=["ECS Task State Change"],
                detail={
                    "clusterArn": [cluster.cluster_arn],
                    "lastStatus": ["STOPPED"],
                    "stopCode": ["TaskFailedToStart", "SpotInterruption"],
                },
            ),
            targets=[events_targets.SnsTopic(notifyTopic)],
        )

        # ------------------------------------------------------------------
        # UI Lambda — Function URL, single handler, lit-html UI
        # ------------------------------------------------------------------
        uiLogGroup = logs.LogGroup(
            self,
            "UiLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        # Kite Connect credentials live in Secrets Manager. Seeded with empty
        # api_key/api_secret/access_token; populate via `aws secretsmanager
        # put-secret-value` after the first deploy. The UI Lambda reads it for
        # the daily OAuth callback flow and writes the resulting access_token
        # back into the same secret.
        kiteSecret = secretsmanager.Secret(
            self,
            "KiteSecret",
            secret_name="nse-quant/kite",
            description="Zerodha Kite Connect credentials + daily access token",
            secret_string_value=None,
            generate_secret_string=secretsmanager.SecretStringGenerator(
                secret_string_template='{"api_key":"","api_secret":"","client_id":"","access_token":"","access_token_set_at":""}',
                generate_string_key="_seed",
            ),
        )

        uiLambda = lambda_.Function(
            self,
            "UiHandler",
            runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(REPO_ROOT / "ui_lambda")),
            memory_size=256,
            timeout=Duration.seconds(15),
            environment={
                "STATE_BUCKET": stateBucket.bucket_name,
                "KITE_SECRET_NAME": kiteSecret.secret_name,
            },
            log_group=uiLogGroup,
        )
        stateBucket.grant_read(uiLambda)
        kiteSecret.grant_read(uiLambda)
        kiteSecret.grant_write(uiLambda)

        uiUrl = uiLambda.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.GET],
            ),
        )

        # ------------------------------------------------------------------
        # Analytics Lambda — DuckDB on S3 Parquet, mounted at /api/analytics/*
        # ------------------------------------------------------------------
        analyticsLogGroup = logs.LogGroup(
            self,
            "AnalyticsLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        analyticsLambda = lambda_.Function(
            self,
            "AnalyticsHandler",
            runtime=lambda_.Runtime.PYTHON_3_12,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(
                str(REPO_ROOT / "analytics_lambda"),
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_12.bundling_image,
                    command=[
                        "bash", "-c",
                        "set -e; "
                        # Install lightgbm without its scipy dep — we only use
                        # `predict(dense_array, pred_contrib=True)`, which never
                        # touches scipy. Saves ~140 MB of bundle size.
                        "pip install --no-cache-dir --no-deps "
                        "lightgbm==4.5.0 "
                        "--platform manylinux2014_aarch64 --only-binary=:all: "
                        "-t /asset-output; "
                        "pip install --no-cache-dir "
                        "pyarrow==18.1.0 numpy==2.1.3 "
                        "--platform manylinux2014_aarch64 --only-binary=:all: "
                        "-t /asset-output; "
                        # lightgbm needs libgomp at runtime; AL2023 Lambda image
                        # doesn't preinstall it. Copy from the build image and
                        # surface it via LD_LIBRARY_PATH below.
                        "mkdir -p /asset-output/lib; "
                        "cp /usr/lib64/libgomp.so.1 /asset-output/lib/; "
                        "cp handler.py scipy_stub.py /asset-output/",
                    ],
                ),
            ),
            memory_size=2048,
            timeout=Duration.seconds(30),
            environment={
                "STATE_BUCKET": stateBucket.bucket_name,
                "ANALYTICS_PREFIX": "outputs/analytics",
                # lightgbm dlopens libgomp at predict-time; we ship it in /lib
                "LD_LIBRARY_PATH": "/var/task/lib:/var/lang/lib:/lib64:/usr/lib64",
            },
            log_group=analyticsLogGroup,
        )
        stateBucket.grant_read(analyticsLambda)

        analyticsUrl = analyticsLambda.add_function_url(
            auth_type=lambda_.FunctionUrlAuthType.NONE,
            cors=lambda_.FunctionUrlCorsOptions(
                allowed_origins=["*"],
                allowed_methods=[lambda_.HttpMethod.GET],
            ),
        )

        # ------------------------------------------------------------------
        # Custom domain (CloudFront in front of the Function URL + Route53 alias).
        # Optional: only built if `custom_domain` was passed in.
        # The raw Function URL keeps working alongside; this is purely additive.
        # ------------------------------------------------------------------
        if custom_domain and certificate and hosted_zone_id and hosted_zone_name:
            distribution = cloudfront.Distribution(
                self,
                "UiDistribution",
                comment=f"NSE Quant UI ({custom_domain})",
                domain_names=[custom_domain],
                certificate=certificate,
                default_behavior=cloudfront.BehaviorOptions(
                    origin=cloudfront_origins.FunctionUrlOrigin(uiUrl),
                    viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                    allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                    cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                    origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                ),
                additional_behaviors={
                    # /api/analytics/* gets routed to the analytics Lambda; everything
                    # else (including /api/*) falls through to the UI Lambda above.
                    "/api/analytics/*": cloudfront.BehaviorOptions(
                        origin=cloudfront_origins.FunctionUrlOrigin(analyticsUrl),
                        viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                        allowed_methods=cloudfront.AllowedMethods.ALLOW_GET_HEAD,
                        cache_policy=cloudfront.CachePolicy.CACHING_DISABLED,
                        origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER_EXCEPT_HOST_HEADER,
                    ),
                },
                price_class=cloudfront.PriceClass.PRICE_CLASS_100,  # NA + EU only — cheapest
            )
            zone = route53.HostedZone.from_hosted_zone_attributes(
                self,
                "UiZone",
                hosted_zone_id=hosted_zone_id,
                zone_name=hosted_zone_name,
            )
            recordName = custom_domain.removesuffix("." + hosted_zone_name).removesuffix(hosted_zone_name).rstrip(".")
            route53.ARecord(
                self,
                "UiAlias",
                zone=zone,
                record_name=recordName or None,
                target=route53.RecordTarget.from_alias(
                    route53_targets.CloudFrontTarget(distribution)
                ),
            )
            CfnOutput(self, "CustomDomainUrl", value=f"https://{custom_domain}/")

        # ------------------------------------------------------------------
        # Kite token monitor — pages operator before 08:00 IST cron if the
        # daily access token has expired or will expire within 90 minutes.
        # Kite tokens cannot be programmatically refreshed (Zerodha mandates
        # fresh OAuth + 2FA daily), so the best we can do is alert early.
        # ------------------------------------------------------------------
        tokenMonitorLogGroup = logs.LogGroup(
            self,
            "KiteTokenMonitorLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        kiteLoginUrl = (
            f"https://{custom_domain}/kite-login"
            if custom_domain
            else f"{uiUrl.url}kite-login"
        )
        tokenMonitorLambda = lambda_.Function(
            self,
            "KiteTokenMonitor",
            runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(REPO_ROOT / "kite_token_monitor_lambda")),
            memory_size=128,
            timeout=Duration.seconds(15),
            environment={
                "KITE_SECRET_NAME": kiteSecret.secret_name,
                "SNS_TOPIC_ARN": notifyTopic.topic_arn,
                "KITE_LOGIN_URL": kiteLoginUrl,
                "WARN_MINUTES": "90",
            },
            log_group=tokenMonitorLogGroup,
        )
        kiteSecret.grant_read(tokenMonitorLambda)
        notifyTopic.grant_publish(tokenMonitorLambda)

        # 01:00 UTC Mon-Fri = 06:30 IST Mon-Fri. Token expires at 06:00 IST,
        # so this fires 30 min after expiry — gives operator 90 min runway
        # before the 08:00 IST decision cron needs the token.
        events.Rule(
            self,
            "KiteTokenMonitorSchedule",
            schedule=events.Schedule.cron(minute="0", hour="1", week_day="MON-FRI"),
            targets=[events_targets.LambdaFunction(tokenMonitorLambda)],
        )

        # ------------------------------------------------------------------
        # Intraday MTM Lambda — every 15 min during market hours, pulls
        # live last-prices from Kite for the paper portfolio and writes
        # outputs/intraday_mtm.json. Dashboard polls it behind an opt-in
        # toggle (default OFF — daily kill-switch P&L stays the source of
        # truth; intraday is informational only).
        # ------------------------------------------------------------------
        intradayMtmLogGroup = logs.LogGroup(
            self,
            "IntradayMtmLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        intradayMtmLambda = lambda_.Function(
            self,
            "IntradayMtm",
            runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            # Bundle kiteconnect via Docker — 'requests' + 'kiteconnect'
            # are the only runtime deps; everything else is stdlib.
            code=lambda_.Code.from_asset(
                str(REPO_ROOT / "intraday_mtm_lambda"),
                bundling=BundlingOptions(
                    image=lambda_.Runtime.PYTHON_3_11.bundling_image,
                    command=[
                        "bash", "-c",
                        "set -e; "
                        "pip install --no-cache-dir "
                        "kiteconnect==5.0.1 "
                        "--platform manylinux2014_aarch64 --only-binary=:all: "
                        "-t /asset-output; "
                        "cp handler.py /asset-output/",
                    ],
                ),
            ),
            memory_size=256,
            timeout=Duration.seconds(20),
            environment={
                "STATE_BUCKET": stateBucket.bucket_name,
                "KITE_SECRET_NAME": kiteSecret.secret_name,
            },
            log_group=intradayMtmLogGroup,
        )
        stateBucket.grant_read(intradayMtmLambda)
        stateBucket.grant_put(intradayMtmLambda)
        kiteSecret.grant_read(intradayMtmLambda)

        # Every 15 min Mon-Fri 03:45-09:45 UTC (= 09:15-15:15 IST), plus
        # 10:00 UTC (= 15:30 IST close print). Cron syntax: `*/15` over
        # hours 03-09 gives 24 fires; we add an explicit 10:00 below so
        # the close print is captured.
        events.Rule(
            self,
            "IntradayMtmSchedule",
            schedule=events.Schedule.cron(
                minute="*/15", hour="3-9", week_day="MON-FRI"
            ),
            targets=[events_targets.LambdaFunction(intradayMtmLambda)],
        )
        events.Rule(
            self,
            "IntradayMtmCloseSchedule",
            schedule=events.Schedule.cron(
                minute="0", hour="10", week_day="MON-FRI"
            ),
            targets=[events_targets.LambdaFunction(intradayMtmLambda)],
        )

        # ------------------------------------------------------------------
        # Dead-man's-switch Lambda — alerts if cron didn't write last_run.json
        # ------------------------------------------------------------------
        deadManLogGroup = logs.LogGroup(
            self,
            "DeadManLogs",
            retention=logs.RetentionDays.ONE_MONTH,
            removal_policy=RemovalPolicy.DESTROY,
        )
        deadManLambda = lambda_.Function(
            self,
            "DeadManSwitch",
            runtime=lambda_.Runtime.PYTHON_3_11,
            architecture=lambda_.Architecture.ARM_64,
            handler="handler.handler",
            code=lambda_.Code.from_asset(str(REPO_ROOT / "dead_man_lambda")),
            memory_size=128,
            timeout=Duration.seconds(15),
            environment={
                "STATE_BUCKET": stateBucket.bucket_name,
                "SNS_TOPIC_ARN": notifyTopic.topic_arn,
                "STALE_AFTER_MINUTES": "120",
            },
            log_group=deadManLogGroup,
        )
        stateBucket.grant_read(deadManLambda)
        notifyTopic.grant_publish(deadManLambda)

        # 04:00 UTC = 09:30 IST (cron expected to finish by ~02:45 UTC)
        deadManRule = events.Rule(
            self,
            "DeadManSchedule",
            schedule=events.Schedule.cron(minute="0", hour="4", week_day="MON-FRI"),
        )
        deadManRule.add_target(events_targets.LambdaFunction(deadManLambda))

        # ------------------------------------------------------------------
        # Outputs
        # ------------------------------------------------------------------
        CfnOutput(self, "StateBucketName", value=stateBucket.bucket_name)
        CfnOutput(self, "NotifyTopicArn", value=notifyTopic.topic_arn)
        CfnOutput(self, "ClusterName", value=cluster.cluster_name)
        CfnOutput(self, "TaskDefinitionArn", value=taskDefinition.task_definition_arn)
        CfnOutput(
            self,
            "UiUrl",
            value=uiUrl.url,
            description="Open in browser, paste UI_TOKEN when prompted",
        )
        CfnOutput(
            self,
            "AnalyticsUrl",
            value=analyticsUrl.url,
            description="Direct Function URL for the analytics Lambda (debug only)",
        )
        CfnOutput(
            self,
            "KiteSecretArn",
            value=kiteSecret.secret_arn,
            description="Secrets Manager ARN for Zerodha Kite credentials",
        )
