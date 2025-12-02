# Test Environment Setup

This guide explains how to set up and use the test environment for automatic deployments from the `feature-test` branch.

## Overview

The test environment is automatically deployed when you push to the `feature-test` branch. This allows you to test changes in a real AWS environment before merging to main.

## Branch-to-Environment Mapping

- **`feature-test`** → **`test`** environment
- **`main`** / **`render-deploy`** → **`dev`** environment
- Manual workflow dispatch → Choose environment (test/dev/staging/prod)

## Initial Setup

### 1. Create Test Environment Infrastructure

```bash
# Set required environment variables
export OPENAI_API_KEY="your-openai-api-key"
export SECRET_HEADER_KEY="your-secret-header"
export BASIC_AUTH_SECRET=$(echo -n "username:password" | base64)

# Deploy test environment infrastructure
./scripts/setup_aws_infrastructure.sh test
```

This creates:
- ECR repository: `cdk-ecr-stack-test-waterbot`
- ECS cluster: `cdk-app-stack-test-WaterbotFargateCluster`
- ECS service: `cdk-app-stack-test-FargateService`
- All supporting infrastructure (VPC, ALB, CloudFront, etc.)

### 2. Verify Infrastructure

```bash
# Check ECR repository
aws ecr describe-repositories --repository-names cdk-ecr-stack-test-waterbot --region us-west-2

# Check ECS cluster
aws ecs describe-clusters --clusters cdk-app-stack-test-WaterbotFargateCluster --region us-west-2

# Check CloudFormation stacks
aws cloudformation describe-stacks --stack-name cdk-app-stack-test --region us-west-2
```

## Automatic Deployment

### How It Works

1. **Push to `feature-test` branch**:
   ```bash
   git checkout -b feature-test
   # Make your changes
   git add .
   git commit -m "Test changes"
   git push origin feature-test
   ```

2. **GitHub Actions automatically**:
   - Detects the `feature-test` branch
   - Sets environment to `test`
   - Builds Docker image with ChromaDB
   - Pushes to test ECR repository
   - Deploys to test ECS service
   - Waits for service stability

3. **Check deployment status**:
   - Go to GitHub Actions tab
   - View the workflow run
   - See deployment summary with CloudFront URL

### Manual Deployment to Test

If you want to deploy manually to test environment:

```bash
./scripts/deploy_to_aws.sh test latest
```

## Test Environment Resources

### Resource Names

- **ECR Stack**: `cdk-ecr-stack-test`
- **App Stack**: `cdk-app-stack-test`
- **ECR Repository**: `cdk-ecr-stack-test-waterbot`
- **ECS Cluster**: `cdk-app-stack-test-WaterbotFargateCluster`
- **ECS Service**: `cdk-app-stack-test-FargateService`
- **Task Definition**: `cdk-app-stack-test-WaterbotTaskDefinition`

### Accessing the Test Environment

1. **Get CloudFront URL**:
   ```bash
   aws cloudformation describe-stacks \
     --stack-name cdk-app-stack-test \
     --query 'Stacks[0].Outputs[?OutputKey==`CloudFrontDistributionDomainName`].OutputValue' \
     --output text \
     --region us-west-2
   ```

2. **Access the application**:
   - URL: `https://<cloudfront-domain>`
   - Basic Auth: Use the credentials you set in `BASIC_AUTH_SECRET`
   - Custom Header: Set `X-Custom-Header` to your `SECRET_HEADER_KEY`

## Monitoring Test Environment

### View Logs

```bash
# View ECS service logs
aws logs tail /ecs/waterbot-test --follow --region us-west-2

# View recent logs
aws logs tail /ecs/waterbot-test --since 1h --region us-west-2
```

### Check Service Status

```bash
# Describe service
aws ecs describe-services \
  --cluster cdk-app-stack-test-WaterbotFargateCluster \
  --services cdk-app-stack-test-FargateService \
  --region us-west-2

# List running tasks
aws ecs list-tasks \
  --cluster cdk-app-stack-test-WaterbotFargateCluster \
  --service-name cdk-app-stack-test-FargateService \
  --region us-west-2
```

### View Deployment History

```bash
# List service deployments
aws ecs describe-services \
  --cluster cdk-app-stack-test-WaterbotFargateCluster \
  --services cdk-app-stack-test-FargateService \
  --region us-west-2 \
  --query 'services[0].deployments'
```

## Cost Considerations

The test environment uses the same resources as dev/staging:
- **Fargate**: ~$0.04/vCPU-hour, ~$0.004/GB-hour
- **ALB**: ~$0.0225/hour + data transfer
- **CloudFront**: Pay per data transfer
- **DynamoDB**: Pay per request (on-demand)

**Tip**: Consider stopping the test environment when not in use to save costs:
```bash
# Scale down to 0 tasks
aws ecs update-service \
  --cluster cdk-app-stack-test-WaterbotFargateCluster \
  --service cdk-app-stack-test-FargateService \
  --desired-count 0 \
  --region us-west-2

# Scale back up when needed
aws ecs update-service \
  --cluster cdk-app-stack-test-WaterbotFargateCluster \
  --service cdk-app-stack-test-FargateService \
  --desired-count 2 \
  --region us-west-2
```

## Cleanup

To remove the test environment:

```bash
cd iac/cdk
source .venv/bin/activate
cdk destroy cdk-app-stack-test --context env=test
cdk destroy cdk-ecr-stack-test --context env=test
```

**Note**: This will delete all resources. Make sure you don't need any data from the test environment.

## Troubleshooting

### Deployment Fails

1. **Check GitHub Actions logs** for specific errors
2. **Verify infrastructure exists**:
   ```bash
   aws cloudformation describe-stacks --stack-name cdk-app-stack-test
   ```
3. **Check ECR repository**:
   ```bash
   aws ecr describe-repositories --repository-names cdk-ecr-stack-test-waterbot
   ```

### Service Won't Start

1. **Check task definition**:
   ```bash
   aws ecs describe-task-definition --task-definition cdk-app-stack-test-WaterbotTaskDefinition
   ```
2. **Check service events**:
   ```bash
   aws ecs describe-services \
     --cluster cdk-app-stack-test-WaterbotFargateCluster \
     --services cdk-app-stack-test-FargateService \
     --query 'services[0].events[:5]'
   ```
3. **Check CloudWatch logs** for container errors

### Image Pull Errors

Ensure the ECS task role has permissions to pull from the test ECR repository.

## Best Practices

1. **Use feature branches**: Create feature branches from `feature-test` for testing
2. **Clean up old images**: Regularly clean up old ECR images to save storage costs
3. **Monitor costs**: Set up CloudWatch billing alarms
4. **Test before merge**: Always test in test environment before merging to main
5. **Use tags**: Tag your deployments with feature names or ticket numbers

## Next Steps

After testing in the test environment:
1. Merge changes to `main` branch (deploys to dev)
2. Create PR from `main` to `staging` (if you have staging)
3. Deploy to production when ready

