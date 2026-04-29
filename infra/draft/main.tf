###############################################################################
# Smartemis — DRAFT environment (synthetic data only).
#
# Single EC2 in eu-central-1, public IP, nginx + basic auth + self-signed TLS,
# uvicorn behind it, SQLite + synthetic CSV. Bedrock via the EC2 instance role.
# SSM Session Manager for shell access — no SSH, no key pair to manage.
#
# This is intentionally NOT the production architecture. For real Smartemis
# customer data we still need Phase 2: VPC + RDS + KMS CMK + VPC endpoints +
# CloudTrail + DPA/DPIA. See infra/prod/ when that's built.
###############################################################################

terraform {
  required_version = ">= 1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
  }
}

provider "aws" {
  region = var.aws_region
  default_tags {
    tags = {
      Project     = "smartemis"
      Environment = "draft"
      Owner       = "smartemis-consulting"
      DataClass   = "synthetic"
      ManagedBy   = "terraform"
    }
  }
}

###############################################################################
# Networking — use the default VPC. For draft / synthetic data this is fine.
# Production rebuilds with private subnets + VPC endpoints; not here.
###############################################################################
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default_public" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

###############################################################################
# Basic-auth credentials → Secrets Manager. The instance role reads them at
# boot and writes /etc/nginx/.htpasswd. Creds never sit in user-data plaintext.
###############################################################################
resource "aws_secretsmanager_secret" "basic_auth" {
  name                    = "smartemis-draft/basic-auth"
  description             = "HTTP basic auth credentials for the Smartemis draft env"
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "basic_auth" {
  secret_id = aws_secretsmanager_secret.basic_auth.id
  secret_string = jsonencode({
    username = var.basic_auth_username
    password = var.basic_auth_password
  })
}

###############################################################################
# IAM role for the EC2 instance.
#   - SSM Session Manager (shell access, no SSH)
#   - Bedrock invoke on the EU Sonnet 4.6 inference profile + the underlying FM
#   - Read the basic-auth secret
###############################################################################
data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "instance" {
  name               = "smartemis-draft-instance"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json
}

resource "aws_iam_role_policy_attachment" "ssm" {
  role       = aws_iam_role.instance.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "bedrock_invoke" {
  statement {
    sid     = "BedrockInvokeSonnet46EU"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = [
      "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6*",
      "arn:aws:bedrock:*:*:inference-profile/eu.anthropic.claude-sonnet-4-6",
    ]
  }
}

data "aws_iam_policy_document" "secrets_read" {
  statement {
    sid       = "ReadBasicAuthSecret"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = [aws_secretsmanager_secret.basic_auth.arn]
  }
}

resource "aws_iam_role_policy" "bedrock" {
  name   = "bedrock-invoke"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.bedrock_invoke.json
}

resource "aws_iam_role_policy" "secrets" {
  name   = "secrets-read"
  role   = aws_iam_role.instance.id
  policy = data.aws_iam_policy_document.secrets_read.json
}

resource "aws_iam_instance_profile" "instance" {
  name = "smartemis-draft-instance"
  role = aws_iam_role.instance.name
}

###############################################################################
# Security group: 443 from anywhere (basic auth + TLS in front of uvicorn).
# 80 only redirects to 443. NO port 22 — shell access is via SSM only.
###############################################################################
resource "aws_security_group" "web" {
  name        = "smartemis-draft-web"
  description = "Smartemis draft env - HTTPS in, all out"
  vpc_id      = data.aws_vpc.default.id

  ingress {
    description = "HTTPS"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP (redirects to HTTPS)"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "All egress (Bedrock, GitHub, dnf, Secrets Manager, etc.)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

###############################################################################
# AMI — latest Amazon Linux 2023 x86_64.
###############################################################################
data "aws_ami" "al2023" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

###############################################################################
# EC2 instance.
###############################################################################
locals {
  user_data = templatefile("${path.module}/user-data.sh", {
    aws_region        = var.aws_region
    bedrock_model_id  = var.bedrock_model_id
    repo_url          = var.repo_url
    repo_ref          = var.repo_ref
    basic_auth_secret = aws_secretsmanager_secret.basic_auth.id
  })
}

resource "aws_instance" "app" {
  ami                         = data.aws_ami.al2023.id
  instance_type               = var.instance_type
  subnet_id                   = data.aws_subnets.default_public.ids[0]
  vpc_security_group_ids      = [aws_security_group.web.id]
  iam_instance_profile        = aws_iam_instance_profile.instance.name
  associate_public_ip_address = true

  user_data                   = local.user_data
  user_data_replace_on_change = true

  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_size           = 30
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = true
  }

  tags = {
    Name = "smartemis-draft"
  }
}
