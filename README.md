# sentential

![CI](https://github.com/bkeane/sentential/actions/workflows/main.yml/badge.svg)
## Todo

- [ ] Configuration of shared TF state for AWS deployments
- [ ] Dependabot
  - Docker
  - Python
  - Terraform
- [ ] SSM parameters via Terraform
  - Auth0
  - RDS
- [ ] Further scope `rds-db` and `describe` actions in policies
- [ ] Security groups for RDS and Lambda
- [ ] Connection pooling for Lambda -> RDS

## Requirements

### ECR repository

```sh
aws ecr create-repository \
  --region <region> \
  --image-scanning-configuration scanOnPush=true \
  --repository-name <app_name>
```

### Auth0

In your Auth0 tenant, create a `Custom API`, and the populate the following _secure_ SSM parameters in AWS:
- `/<app_name>/domain`
- `/<app_name>/audience`
  - Usually the `Identifier` for the API

### KMS key

If needed, create a KMS key and alias:
```sh
KEYID=$(aws kms create-key | jq -r '.KeyMetadata.KeyId')
aws kms create-alias \
  --alias-name alias/<key_name> \
  --target-key-id $KEYID
```

### RDS

Populate the following _secure_ SSM parameters in AWS:
- `/<app_name>/db_user`
- `/<app_name>/db_root_cert`
  - Base64 encoded

Grant your Postgres user permission to use IAM authentication:
```sql
GRANT rds_iam TO <user>;
```

## Usage

## Project structure 

- `ops/local` - Local Lambda environment via Terraform
- `ops/aws` - Creates AWS Lambda environment and URL via Terraform
- `app/src` - `python3 main.py` runs application locally
- `gateway/src` - `python3 main.py` runs Lambda gateway locally
