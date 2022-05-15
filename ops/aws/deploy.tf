resource "aws_iam_role" "api" {
  name               = "${var.api}_lambda_role"

  assume_role_policy = <<-EOT
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Action": "sts:AssumeRole",
        "Principal": {
          "Service": "lambda.amazonaws.com"
        },
        "Effect": "Allow",
        "Sid": ""
      }
    ]
  }
  EOT
}

resource "aws_iam_policy" "combined" {
  name   = "${var.api}-access"
  path   = "/"
  policy = data.aws_iam_policy_document.combined.json
}

resource "aws_iam_role_policy_attachment" "allow_combined" {
  role       = aws_iam_role.api.name
  policy_arn = aws_iam_policy.combined.arn
}

resource "aws_lambda_function" "deploy" {
  depends_on    = [null_resource.build, null_resource.release]
  function_name = var.api
  package_type  = "Image"
  image_uri     = "${data.aws_ecr_repository.api.repository_url}:${local.code_sha}"
  role          = aws_iam_role.api.arn

  environment {
    variables = local.compose["services"][var.api]["environment"]
  }
}

resource "aws_lambda_function_url" "deploy" {
  function_name      = aws_lambda_function.deploy.function_name
  authorization_type = "NONE"
}

output "function_url" {
  value = aws_lambda_function_url.deploy.function_url
}
