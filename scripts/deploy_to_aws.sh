#!/bin/bash
set -e

# Script to build Docker image and deploy to AWS ECS
# Usage: ./scripts/deploy_to_aws.sh [environment] [tag]

ENVIRONMENT="${1:-dev}"
TAG="${2:-latest}"
AWS_REGION="${AWS_REGION:-us-west-2}"

echo "🚀 Deploying Waterbot to AWS ECS..."
echo "   Environment: $ENVIRONMENT"
echo "   Tag: $TAG"
echo "   Region: $AWS_REGION"

# Check if required environment variables are set
if [ -z "$AWS_ACCESS_KEY_ID" ] || [ -z "$AWS_SECRET_ACCESS_KEY" ]; then
    echo "❌ AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY must be set"
    exit 1
fi

if [ -z "$OPENAI_API_KEY" ]; then
    echo "⚠️  OPENAI_API_KEY not set. RAG ingestion (Add_files_to_db.py) can be run later with DB_* set."
    BUILD_ARGS=""
else
    BUILD_ARGS="--build-arg OPENAI_API_KEY=$OPENAI_API_KEY"
    echo "✅ OPENAI_API_KEY is set"
fi

# Get stack names based on environment
if [ "$ENVIRONMENT" = "test" ]; then
    ECR_STACK="cdk-ecr-stack-test"
    APP_STACK="cdk-app-stack-test"
    ECS_CLUSTER="cdk-app-stack-test-WaterbotFargateCluster"
    ECS_SERVICE="cdk-app-stack-test-FargateService"
elif [ "$ENVIRONMENT" = "dev" ]; then
    ECR_STACK="cdk-ecr-stack-dev"
    APP_STACK="cdk-app-stack-dev"
    ECS_CLUSTER="cdk-app-stack-dev-WaterbotFargateCluster"
    ECS_SERVICE="cdk-app-stack-dev-FargateService"
elif [ "$ENVIRONMENT" = "staging" ]; then
    ECR_STACK="cdk-ecr-stack-staging"
    APP_STACK="cdk-app-stack-staging"
    ECS_CLUSTER="cdk-app-stack-staging-WaterbotFargateCluster"
    ECS_SERVICE="cdk-app-stack-staging-FargateService"
elif [ "$ENVIRONMENT" = "prod" ]; then
    ECR_STACK="cdk-ecr-stack-prod"
    APP_STACK="cdk-app-stack-prod"
    ECS_CLUSTER="cdk-app-stack-prod-WaterbotFargateCluster"
    ECS_SERVICE="cdk-app-stack-prod-FargateService"
else
    echo "❌ Unknown environment: $ENVIRONMENT"
    echo "   Use: test, dev, staging, or prod"
    exit 1
fi

# Get AWS account ID
AWS_ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)

# Get ECR repository name from CloudFormation stack
echo "🔍 Looking up ECR repository from stack: $ECR_STACK"
ECR_REPO=$(aws cloudformation describe-stacks \
    --stack-name $ECR_STACK \
    --query 'Stacks[0].Outputs[?OutputKey==`RepositoryName`].OutputValue' \
    --output text \
    --region $AWS_REGION 2>/dev/null)

# If not found in outputs, try to find by listing repositories
if [ -z "$ECR_REPO" ] || [ "$ECR_REPO" = "None" ]; then
    echo "⚠️  Repository not found in stack outputs, searching ECR..."
    ECR_REPO=$(aws ecr describe-repositories \
        --region $AWS_REGION \
        --query "repositories[?contains(repositoryName, 'waterbot')].repositoryName" \
        --output text | head -1)
fi

# If still not found, try default naming convention
if [ -z "$ECR_REPO" ] || [ "$ECR_REPO" = "None" ]; then
    echo "⚠️  Using default repository naming convention..."
    ECR_REPO="${ECR_STACK}-waterbot"
fi

ECR_URI="${AWS_ACCOUNT_ID}.dkr.ecr.${AWS_REGION}.amazonaws.com/${ECR_REPO}"

echo "📦 ECR Repository: $ECR_URI"

# Login to ECR
echo "🔐 Logging into ECR..."
aws ecr get-login-password --region $AWS_REGION | docker login --username AWS --password-stdin $ECR_URI

# Build Docker image
echo "🔨 Building Docker image..."
docker build \
    --platform linux/amd64 \
    $BUILD_ARGS \
    -t ${ECR_URI}:${TAG} \
    -t ${ECR_URI}:latest \
    .

# Push to ECR
echo "⬆️  Pushing image to ECR..."
docker push ${ECR_URI}:${TAG}
docker push ${ECR_URI}:latest

# Update ECS service
echo "🔄 Updating ECS service..."
aws ecs update-service \
    --cluster $ECS_CLUSTER \
    --service $ECS_SERVICE \
    --force-new-deployment \
    --region $AWS_REGION \
    > /dev/null

echo ""
echo "✅ Deployment initiated!"
echo ""
echo "📝 Image: ${ECR_URI}:${TAG}"
echo "📝 ECS Service: $ECS_SERVICE"
echo "📝 ECS Cluster: $ECS_CLUSTER"
echo ""
echo "⏳ Waiting for service to stabilize..."
aws ecs wait services-stable \
    --cluster $ECS_CLUSTER \
    --services $ECS_SERVICE \
    --region $AWS_REGION

echo ""
echo "✅ Deployment complete! Service is stable."

