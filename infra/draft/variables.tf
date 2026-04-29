variable "aws_region" {
  type        = string
  default     = "eu-central-1"
  description = "Frankfurt — keeps Bedrock invocations and (eventual) data in the EU."
}

variable "instance_type" {
  type        = string
  default     = "t3.small"
  description = "t3.small (~$15/mo) is enough for a few colleagues clicking through synthetic data."
}

variable "repo_url" {
  type        = string
  default     = "https://github.com/madrexler1/Clinic_Analysis_Project.git"
  description = "Public GitHub URL the user-data script clones at boot."
}

variable "repo_ref" {
  type        = string
  default     = "main"
  description = "Branch / tag / commit to deploy."
}

variable "bedrock_model_id" {
  type        = string
  default     = "eu.anthropic.claude-sonnet-4-6"
  description = "Cross-region inference profile in EU regions."
}

variable "basic_auth_username" {
  type        = string
  description = "HTTP basic auth username."
}

variable "basic_auth_password" {
  type        = string
  description = "HTTP basic auth password. Stored in Secrets Manager, NOT in TF state plaintext if you pass via TF_VAR_basic_auth_password env var."
  sensitive   = true
}
