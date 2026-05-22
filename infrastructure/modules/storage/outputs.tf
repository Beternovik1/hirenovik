# infrastructure/modules/storage/outputs.tf

output "raw_bucket_name" {
  value = aws_s3_bucket.raw.id
}

output "curated_bucket_name" {
  value = aws_s3_bucket.curated.id
}

output "models_bucket_name" {
  value = aws_s3_bucket.models.id
}

output "outputs_bucket_name" {
  value = aws_s3_bucket.outputs.id
}

output "input_bucket_name" {
  value = aws_s3_bucket.input.id
}

output "input_bucket_arn" {
  value = aws_s3_bucket.input.arn
}

output "raw_bucket_arn" {
  value = aws_s3_bucket.raw.arn
}

output "curated_bucket_arn" {
  value = aws_s3_bucket.curated.arn
}

output "models_bucket_arn" {
  value = aws_s3_bucket.models.arn
}

output "outputs_bucket_arn" {
  value = aws_s3_bucket.outputs.arn
}
