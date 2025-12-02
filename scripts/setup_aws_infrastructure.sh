#!/bin/bash
set -e

# Script to set up AWS infrastructure using CDK
# Usage: ./scripts/setup_aws_infrastructure.sh [environment]

ENVIRONMENT="${1:-dev}"

echo "🏗️  Setting up AWS infrastructure for environment: $ENVIRONMENT"

# Check if required environment variables are set
if [ -z "$OPENAI_API_KEY" ]; then
    echo "❌ OPENAI_API_KEY must be set"
    exit 1
fi

if [ -z "$SECRET_HEADER_KEY" ]; then
    echo "❌ SECRET_HEADER_KEY must be set"
    exit 1
fi

if [ -z "$BASIC_AUTH_SECRET" ]; then
    echo "❌ BASIC_AUTH_SECRET must be set (base64 encoded username:password)"
    exit 1
fi

# Check if CDK is installed
if ! command -v cdk &> /dev/null; then
    echo "❌ AWS CDK is not installed"
    echo "   Install with: npm install -g aws-cdk"
    exit 1
fi

cd iac/cdk

# Install CDK dependencies
if [ ! -d "node_modules" ]; then
    echo "📦 Installing CDK dependencies..."
    npm install
fi

# Install Python dependencies
if [ ! -d ".venv" ]; then
    echo "📦 Creating Python virtual environment..."
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
else
    source .venv/bin/activate
fi

# Bootstrap CDK (only needed once per account/region)
echo "🚀 Bootstrapping CDK (if needed)..."
cdk bootstrap --context env=$ENVIRONMENT || echo "CDK already bootstrapped"

# Deploy ECR stack first
echo "📦 Deploying ECR stack..."
cdk deploy cdk-ecr-stack --context env=$ENVIRONMENT --require-approval never

# Deploy App stack
echo "🚀 Deploying App stack..."
cdk deploy cdk-app-stack --context env=$ENVIRONMENT --require-approval never

echo ""
echo "✅ Infrastructure deployment complete!"
echo ""
echo "📝 Next steps:"
echo "   1. Build and push Docker image: ./scripts/deploy_to_aws.sh $ENVIRONMENT"
echo "   2. Or use GitHub Actions for automated deployments"

