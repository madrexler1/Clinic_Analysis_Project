# Smartemis — DRAFT environment (Terraform)

Single-EC2 deployment of the Smartemis app for **synthetic data only**, behind nginx + HTTP basic auth + self-signed TLS, with Bedrock invoked via the EC2 instance role. SSM Session Manager for shell access — no SSH key to manage.

> **Not for real customer data.** This module skips RDS, KMS CMK, VPC endpoints, CloudTrail, and other GDPR Phase-2 controls. When you point the app at real Smartemis data, build `infra/prod/` first.

## Cost (rough)

| Item | $/month |
|---|---|
| EC2 t3.small (`eu-central-1`) | ~15 |
| EBS 20 GB gp3, encrypted | ~2 |
| Public IP, data transfer (low) | ~2 |
| Bedrock | pay-per-call |
| **Total** | **~$20** |

`terraform destroy` when you're done; the secret in Secrets Manager has a 0-day recovery window so it disappears with everything else.

## Prerequisites

- Terraform ≥ 1.6
- AWS CLI configured with credentials that can create EC2, IAM roles, Secrets Manager, security groups in `eu-central-1`
- Bedrock model access for Claude Sonnet 4.6 already enabled in your account (you did this earlier — invoking from the instance won't re-prompt)

## Deploy

From inside `infra/draft/`:

```bash
# 1. Set the basic-auth password as an env var so it doesn't land in tfvars on disk:
export TF_VAR_basic_auth_username="smartemis"
export TF_VAR_basic_auth_password='<your password>'

# 2. Init + plan
terraform init
terraform plan

# 3. Review the plan. Should be ~12 resources, no destroys.
#    When it looks right:
terraform apply

# 4. Note the outputs:
#    - url           → share with colleagues
#    - ssm_command   → shell into the box for debugging
#    - tail_bootstrap_log → tail user-data progress
```

Bootstrap takes about **3-5 minutes** after `apply` returns. Watch it:

```bash
$(terraform output -raw tail_bootstrap_log)
# wait for: "Smartemis draft env bootstrap complete."
```

Then open the URL. Browser will warn once about the self-signed cert — colleagues click "Advanced" → "Proceed". Basic auth prompt follows; they enter the username + password you set.

## Updating the app

Two ways to push new code:

**A. Recreate the instance** (cleanest — pulls fresh from `main`, regenerates synthetic data):

```bash
terraform taint aws_instance.app
terraform apply
```

The public IP changes; reshare the URL. Cost: ~$0 — terminate + create on a t3.small is free under hourly billing if you're <1h.

**B. Pull on the running instance** (faster, keeps the IP and any feedback rows):

```bash
aws ssm start-session --target $(terraform output -raw ec2_id 2>/dev/null) \
    --region eu-central-1
# then on the box:
sudo -u ec2-user bash -lc 'cd /opt/smartemis && git pull && .venv/bin/pip install -e .'
sudo systemctl restart smartemis
```

## Tearing it down

```bash
terraform destroy
```

Confirms then deletes the EC2, IAM role, security group, and the basic-auth secret. ~$0 monthly cost after.

## What's intentionally **not** here

- No RDS — SQLite on the instance's EBS volume. Lost on `taint` / re-create.
- No KMS CMK — EBS uses default `aws/ebs` key.
- No VPC endpoints — Bedrock and Secrets Manager calls go over the public internet.
- No CloudTrail data events on Bedrock.
- No DPIA / DPA wiring.

All of these get added in `infra/prod/` for the GDPR-compliant production environment.
