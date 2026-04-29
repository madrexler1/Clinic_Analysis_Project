output "public_ip" {
  value       = aws_instance.app.public_ip
  description = "EC2 public IPv4."
}

output "public_dns" {
  value       = aws_instance.app.public_dns
  description = "EC2 public DNS (works once boot finishes)."
}

output "url" {
  value       = "https://${aws_instance.app.public_dns}/"
  description = "Share this with colleagues. Browser will warn about the self-signed cert — they accept once."
}

output "ssm_command" {
  value       = "aws ssm start-session --target ${aws_instance.app.id} --region ${var.aws_region}"
  description = "Shell into the instance for debugging — no SSH needed."
}

output "tail_bootstrap_log" {
  value       = "aws ssm start-session --target ${aws_instance.app.id} --region ${var.aws_region} --document-name AWS-StartInteractiveCommand --parameters command='sudo tail -f /var/log/cloud-init-output.log'"
  description = "Tail the user-data bootstrap log from your laptop."
}
