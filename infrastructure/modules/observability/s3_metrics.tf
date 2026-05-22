resource "aws_s3_bucket_metric" "curated_objects" {
  bucket = var.curated_bucket_name
  name   = "CuratedBucketObjectCount"
}
