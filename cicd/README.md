# AWS Native CI/CD

This folder adds an AWS-native pipeline without removing existing GitHub Actions.

## What gets created

- CodePipeline (Source -> CI -> Deploy)
- CodeBuild project for CI (`buildspec-ci.yml`)
- CodeBuild project for deploy (`buildspec-deploy.yml`)
- Artifact S3 bucket
- IAM roles for CodePipeline and CodeBuild

## Deploy

```bash
aws cloudformation deploy \
  --template-file cicd/codepipeline.yaml \
  --stack-name aiagentcore-cicd \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
    RepositoryName=aiAgentCore \
    BranchName=main \
    PipelineName=aiAgentCore-pipeline \
    StackName=InfraStack \
    RuntimeEcrRepositoryName=ai-agentcore-runtime \
    ModelId=amazon.nova-lite-v1:0
```

## Notes

- This template intentionally keeps permissions broad for quick bring-up.
- `CodeBuildServiceRole` currently attaches `AdministratorAccess`.
- After the pipeline is stable, tighten permissions to least privilege.
- Existing `.github/workflows/*` are untouched.
