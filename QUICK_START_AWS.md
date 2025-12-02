# Quick Start: AWS Deployment

## 🚀 Fastest Path to Deploy

### 1. Set Environment Variables

```bash
export OPENAI_API_KEY="sk-..."
export SECRET_HEADER_KEY="your-secret-header"
export BASIC_AUTH_SECRET=$(echo -n "username:password" | base64)
export AWS_ACCESS_KEY_ID="AKIA..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_REGION="us-west-2"
```

### 2. Deploy Infrastructure (First Time Only)

```bash
./scripts/setup_aws_infrastructure.sh dev
```

### 3. Deploy Application

```bash
./scripts/deploy_to_aws.sh dev latest
```

That's it! 🎉

## 🔄 CI/CD Setup (GitHub Actions)

### 1. Add GitHub Secrets

Go to: `Settings > Secrets and variables > Actions`

Add:
- `AWS_ACCESS_KEY_ID`
- `AWS_SECRET_ACCESS_KEY`
- `OPENAI_API_KEY`

### 2. Push to Trigger Deployment

**Automatic deployments:**
- **`feature-test` branch** → Deploys to **test** environment
- **`main` branch** → Deploys to **dev** environment

```bash
# Deploy to test environment
git checkout -b feature-test
git push origin feature-test

# Deploy to dev environment
git push origin main
```

The workflow will automatically:
- Detect branch and set environment
- Build Docker image
- Push to ECR
- Deploy to ECS

## 📋 What Gets Deployed

- **ECR**: Docker image repository
- **ECS Fargate**: Container service (2-4 tasks, auto-scaling)
- **ALB**: Application Load Balancer
- **CloudFront**: CDN with HTTPS
- **DynamoDB**: Message storage
- **S3**: Transcript storage
- **VPC**: Isolated network

## 🧪 Test Environment

For automatic test deployments from `feature-test` branch:

```bash
# First time: Set up test infrastructure
./scripts/setup_aws_infrastructure.sh test

# Then push to feature-test branch for auto-deployment
git checkout -b feature-test
git push origin feature-test
```

See [TEST_ENVIRONMENT_SETUP.md](./TEST_ENVIRONMENT_SETUP.md) for details.

## 🔍 Check Deployment Status

```bash
# View ECS service
aws ecs describe-services \
  --cluster cdk-app-stack-dev-WaterbotFargateCluster \
  --services cdk-app-stack-dev-FargateService \
  --region us-west-2

# View logs
aws logs tail /ecs/waterbot-dev --follow --region us-west-2
```

## 🆘 Troubleshooting

**Build fails?**
- Check `application/newData/` has PDF files
- Verify `OPENAI_API_KEY` is set

**ECS won't start?**
- Check CloudWatch logs
- Verify ECR image exists
- Check IAM permissions

**Can't access app?**
- Get CloudFront URL from stack outputs
- Check security groups allow traffic
- Verify basic auth credentials

## 📚 More Details

See [AWS_DEPLOYMENT.md](./AWS_DEPLOYMENT.md) for complete documentation.

