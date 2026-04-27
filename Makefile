# Override these on the command line for your environment, e.g.:
#   make deploy AWS_PROFILE=myprofile NOTIFICATION_EMAIL=you@example.com
AWS_PROFILE   ?= default
AWS_REGION    ?= ap-south-1
NOTIFICATION_EMAIL ?= you@example.com

# All AWS-touching targets export the profile + region so child processes inherit.
export AWS_PROFILE
unexport AWS_DEFAULT_PROFILE
export AWS_REGION
export AWS_DEFAULT_REGION = $(AWS_REGION)
export JSII_SILENCE_WARNING_UNTESTED_NODE_VERSION = 1
export CDK_DOCKER ?= $(shell command -v docker >/dev/null 2>&1 && echo docker || echo podman)

CDK = ./node_modules/.bin/cdk

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-22s\033[0m %s\n",$$1,$$2}'

# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------
.PHONY: setup
setup: ## Install Python + Node CDK deps locally inside infra/
	cd infra && python3 -m venv .venv && ./.venv/bin/pip install -q -r requirements.txt
	cd infra && npm install --no-save aws-cdk@2

# ---------------------------------------------------------------------------
# CDK
# ---------------------------------------------------------------------------
.PHONY: bootstrap
bootstrap: ## One-time CDK bootstrap for this account/region
	cd infra && PATH="$$PWD/.venv/bin:$$PATH" $(CDK) bootstrap \
		aws://$$(aws sts get-caller-identity --query Account --output text)/$(AWS_REGION) \
		-c notification_email=$(NOTIFICATION_EMAIL)

.PHONY: synth
synth: ## Synthesize CloudFormation template
	cd infra && PATH="$$PWD/.venv/bin:$$PATH" $(CDK) synth -c notification_email=$(NOTIFICATION_EMAIL)

.PHONY: deploy
deploy: ## Build image, push, deploy stack
	cd infra && PATH="$$PWD/.venv/bin:$$PATH" $(CDK) deploy --all --require-approval never \
		-c notification_email=$(NOTIFICATION_EMAIL)

.PHONY: diff
diff: ## Show pending changes
	cd infra && PATH="$$PWD/.venv/bin:$$PATH" $(CDK) diff -c notification_email=$(NOTIFICATION_EMAIL)

.PHONY: destroy
destroy: ## Tear down everything (S3 bucket retained — empty + delete by hand)
	cd infra && PATH="$$PWD/.venv/bin:$$PATH" $(CDK) destroy -c notification_email=$(NOTIFICATION_EMAIL)

# ---------------------------------------------------------------------------
# State seeding
# ---------------------------------------------------------------------------
.PHONY: seed
seed: ## Upload local data/qlib_data + outputs to the state bucket (first-run only)
	@bucket=$$(aws cloudformation describe-stacks --stack-name NseQuantStack --query "Stacks[0].Outputs[?OutputKey=='StateBucketName'].OutputValue" --output text); \
	echo "Seeding s3://$$bucket"; \
	aws s3 sync data/qlib_data s3://$$bucket/data/qlib_data --no-progress; \
	aws s3 sync outputs       s3://$$bucket/outputs       --no-progress \
	    --exclude "HALT" --exclude "daily.log" --exclude "alerts.log" \
	    --exclude "walkforward_backtest/*" --exclude "processed_datasets/*"

# ---------------------------------------------------------------------------
# Operational
# ---------------------------------------------------------------------------
.PHONY: run-now
run-now: ## Trigger today's daily task immediately (overrides cron)
	@cluster=$$(aws cloudformation describe-stacks --stack-name NseQuantStack --query "Stacks[0].Outputs[?OutputKey=='ClusterName'].OutputValue" --output text); \
	taskdef=$$(aws cloudformation describe-stacks --stack-name NseQuantStack --query "Stacks[0].Outputs[?OutputKey=='TaskDefinitionArn'].OutputValue" --output text); \
	subnet=$$(aws ec2 describe-subnets --filters "Name=default-for-az,Values=true" --query "Subnets[0].SubnetId" --output text); \
	sg=$$(aws ec2 describe-security-groups --filters "Name=group-name,Values=default" --query "SecurityGroups[0].GroupId" --output text); \
	echo "Running task on $$cluster (subnet=$$subnet, sg=$$sg)"; \
	aws ecs run-task --cluster "$$cluster" --task-definition "$$taskdef" \
		--capacity-provider-strategy capacityProvider=FARGATE_SPOT,weight=1 \
		--network-configuration "awsvpcConfiguration={subnets=[$$subnet],securityGroups=[$$sg],assignPublicIp=ENABLED}"

.PHONY: logs
logs: ## Tail the most recent cron-task log stream
	@group=$$(aws logs describe-log-groups --log-group-name-prefix "/aws/ecs/" --query "logGroups[?contains(logGroupName,'CronLogs')].logGroupName | [0]" --output text); \
	stream=$$(aws logs describe-log-streams --log-group-name "$$group" --order-by LastEventTime --descending --max-items 1 --query "logStreams[0].logStreamName" --output text); \
	echo "Group: $$group  Stream: $$stream"; \
	aws logs tail "$$group" --log-stream-names "$$stream" --follow

.PHONY: ui-url
ui-url: ## Print the UI Function URL
	@aws cloudformation describe-stacks --stack-name NseQuantStack --query "Stacks[0].Outputs[?OutputKey=='UiUrl'].OutputValue" --output text

.PHONY: halt-clear
halt-clear: ## Remove the HALT object from S3
	@bucket=$$(aws cloudformation describe-stacks --stack-name NseQuantStack --query "Stacks[0].Outputs[?OutputKey=='StateBucketName'].OutputValue" --output text); \
	aws s3 rm s3://$$bucket/outputs/HALT && echo "HALT cleared"
