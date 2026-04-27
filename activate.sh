# Run with `source ./activate.sh` to apply this project's AWS profile/region
# to your current shell. Override AWS_PROFILE in your environment or in
# .envrc.local to point at your own AWS account. Mirrors what .envrc does for
# direnv users.

export AWS_PROFILE=${AWS_PROFILE:-default}
unset AWS_DEFAULT_PROFILE
export AWS_REGION=${AWS_REGION:-ap-south-1}
export AWS_DEFAULT_REGION=${AWS_REGION}

# Per-machine overrides
[[ -f .envrc.local ]] && source ./.envrc.local

echo "AWS profile -> ${AWS_PROFILE}  (region: ${AWS_REGION})"
aws sts get-caller-identity --query "[Account,Arn]" --output text 2>/dev/null || echo "(profile not yet configured locally)"
