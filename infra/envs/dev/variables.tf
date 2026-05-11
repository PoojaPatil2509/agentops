variable "project_name" {
  description = "Project name, used as prefix for all resources"
  type        = string
  default     = "agentops"
}

variable "environment" {
  description = "Environment name (dev, staging, prod)"
  type        = string
  default     = "dev"
}

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "eu-central-1"
}

variable "aws_account_id" {
  description = "AWS account ID, used in IAM and KMS policies"
  type        = string
  default     = "504110891823"
}

variable "bucket_suffix" {
  description = "Unique suffix appended to globally-unique resources like S3 buckets"
  type        = string
  default     = "pooja"
}

variable "common_tags" {
  description = "Tags applied to every resource"
  type        = map(string)
  default = {
    Project     = "agentops"
    Environment = "dev"
    ManagedBy   = "terraform"
    Owner       = "pooja"
  }
}