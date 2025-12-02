# AWS Deployment Guide

This guide covers deploying Waterbot to AWS ECS using CDK infrastructure and CI/CD pipelines.

## Prerequisites

1. **AWS Account** with appropriate permissions
2. **AWS CLI** configured with credentials
3. **Docker** installed and running
4. **Node.js** and **npm** (for CDK)
5. **Python 3.11+** (for CDK Python dependencies)

## Required Environment Variables

Set these environment variables before deployment:

```bash
export OPENAI_API_KEY="your-openai-api-key"
export SECRET_HEADER_KEY="your-secret-header-value"
export BASIC_AUTH_SECRET="base64-encoded-username:password"
export AWS_ACCESS_KEY_ID="your-aws-access-key"
export AWS_SECRET_ACCESS_KEY="your-aws-secret-key"
export AWS_REGION="us-west-2"  # or your preferred region
```

To generate `BASIC_AUTH_SECRET`:
```bash
echo -n "username:password" | base64
```

## Infrastructure Setup

### 1. Initial Infrastructure Deployment

Deploy the AWS infrastructure (ECR, ECS, VPC, etc.) using CDK:

```bash
# Make script executable
chmod +x scripts/setup_aws_infrastructure.sh

# Deploy infrastructure for dev environment
./scripts/setup_aws_infrastructure.sh dev
```

This will:
- Create ECR repository for Docker images
- Set up ECS Fargate cluster
- Create VPC, ALB, CloudFront distribution
- Set up DynamoDB tables and S3 buckets
- Configure IAM roles and permissions

### 2. Verify Infrastructure

Check that resources were created:

```bash
# List ECR repositories
aws ecr describe-repositories --region us-west-2

# List ECS clusters
aws ecs list-clusters --region us-west-2

# List CloudFormation stacks
aws cloudformation list-stacks --region us-west-2
```

## Manual Deployment

### Build and Deploy to AWS

```bash
# Make script executable
chmod +x scripts/deploy_to_aws.sh

# Deploy to dev environment
./scripts/deploy_to_aws.sh dev latest

# Deploy to staging
./scripts/deploy_to_aws.sh staging latest

# Deploy to production
./scripts/deploy_to_aws.sh prod latest
```

The script will:
1. Build Docker image (including frontend and ChromaDB)
2. Push image to ECR
3. Update ECS service to use new image
4. Wait for service to stabilize

## CI/CD Pipeline Setup

### GitHub Actions

The repository includes a GitHub Actions workflow (`.github/workflows/deploy-aws.yml`) that automatically deploys on push to `main` or `render-deploy` branches.

### Required GitHub Secrets

Configure these secrets in your GitHub repository settings:

1. **AWS_ACCESS_KEY_ID** - AWS access key with ECS/ECR permissions
2. **AWS_SECRET_ACCESS_KEY** - AWS secret key
3. **OPENAI_API_KEY** - OpenAI API key for building ChromaDB

### Workflow Triggers

The workflow triggers on:
- Push to `main` or `render-deploy` branches
- Manual workflow dispatch (with environment selection)
- Changes to application code, frontend, or Dockerfile

### Workflow Steps

1. Checkout code
2. Configure AWS credentials
3. Login to ECR
4. Build Docker image (with ChromaDB)
5. Push to ECR
6. Update ECS task definition
7. Deploy to ECS service
8. Wait for service stability

## Environment Configuration

### Development Environment

- **ECR Repository**: `cdk-ecr-stack-dev-waterbot`
- **ECS Cluster**: `cdk-app-stack-dev-WaterbotFargateCluster`
- **ECS Service**: `cdk-app-stack-dev-FargateService`

### Staging Environment

- **ECR Repository**: `cdk-ecr-stack-staging-waterbot`
- **ECS Cluster**: `cdk-app-stack-staging-WaterbotFargateCluster`
- **ECS Service**: `cdk-app-stack-staging-FargateService`

### Production Environment

- **ECR Repository**: `cdk-ecr-stack-prod-waterbot`
- **ECS Cluster**: `cdk-app-stack-prod-WaterbotFargateCluster`
- **ECS Service**: `cdk-app-stack-prod-FargateService`

## Updating Infrastructure

To update infrastructure after code changes:

```bash
cd iac/cdk
source .venv/bin/activate
cdk deploy --context env=dev --all
```

## Monitoring and Logs

### View ECS Service Logs

```bash
# Get log group name
aws logs describe-log-groups --log-group-name-prefix "/ecs/waterbot" --region us-west-2

# View recent logs
aws logs tail /ecs/waterbot-dev --follow --region us-west-2
```

### Check Service Status

```bash
# Describe service
aws ecs describe-services \
  --cluster cdk-app-stack-dev-WaterbotFargateCluster \
  --services cdk-app-stack-dev-FargateService \
  --region us-west-2

# List running tasks
aws ecs list-tasks \
  --cluster cdk-app-stack-dev-WaterbotFargateCluster \
  --service-name cdk-app-stack-dev-FargateService \
  --region us-west-2
```

### CloudFront Distribution

The application is served through CloudFront. Get the distribution URL:

```bash
aws cloudformation describe-stacks \
  --stack-name cdk-app-stack-dev \
  --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDistributionDomainName`].OutputValue' \
  --output text
```

## Troubleshooting

### Build Fails - Missing newData

If the Docker build fails because `newData` directory is missing:

```bash
# Ensure newData directory exists with PDF files
ls -la application/newData/

# Or download PDFs first
python download_pdfs.py
```

### ECS Service Won't Start

1. Check task definition:
   ```bash
   aws ecs describe-task-definition \
     --task-definition cdk-app-stack-dev-WaterbotTaskDefinition \
     --region us-west-2
   ```

2. Check service events:
   ```bash
   aws ecs describe-services \
     --cluster cdk-app-stack-dev-WaterbotFargateCluster \
     --services cdk-app-stack-dev-FargateService \
     --region us-west-2 \
     --query 'services[0].events[:5]'
   ```

3. Check CloudWatch logs for errors

### Image Pull Errors

Ensure the ECS task role has permissions to pull from ECR:

```bash
# Verify ECR repository exists
aws ecr describe-repositories --repository-names cdk-ecr-stack-dev-waterbot --region us-west-2
```

### ChromaDB Build Issues

If ChromaDB fails to build during Docker build:

1. Ensure `OPENAI_API_KEY` is set as build arg
2. Check that `application/newData/` contains PDF/TXT files
3. Review build logs for specific errors

## Cost Optimization

- **Fargate**: Pay per vCPU and memory used
- **ALB**: Pay per hour and per LCU
- **CloudFront**: Pay per data transfer
- **DynamoDB**: Pay per request (on-demand mode)
- **S3**: Pay per storage and requests

Consider:
- Using reserved capacity for production
- Setting up auto-scaling policies
- Using CloudFront caching for static assets
- Monitoring costs in AWS Cost Explorer

## Security Best Practices

1. **Secrets Management**: Use AWS Secrets Manager (already configured)
2. **IAM Roles**: Follow principle of least privilege
3. **VPC**: Application runs in private subnets
4. **CloudFront**: Basic auth protection configured
5. **HTTPS**: All traffic encrypted via CloudFront
6. **Image Scanning**: Enable ECR image scanning

## Next Steps

1. Set up monitoring and alerting (CloudWatch alarms)
2. Configure auto-scaling based on metrics
3. Set up backup strategies for DynamoDB
4. Configure custom domain with SSL certificate
5. Set up staging and production environments
6. Implement blue/green deployments

