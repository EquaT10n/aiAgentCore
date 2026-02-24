from __future__ import annotations

# CDK 主模块
import aws_cdk as cdk

# 常用 CDK 基础构件
from aws_cdk import CfnOutput, Duration, Stack

# Bedrock AgentCore 资源
from aws_cdk import aws_bedrockagentcore as bedrockagentcore

# DynamoDB 资源
from aws_cdk import aws_dynamodb as dynamodb

# ECR 资源
from aws_cdk import aws_ecr as ecr

# IAM 资源
from aws_cdk import aws_iam as iam

# S3 资源
from aws_cdk import aws_s3 as s3

# CDK 构造树基类
from constructs import Construct


# 基础设施主栈：定义运行时所需云资源
class InfraStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # 从 CDK context 读取可选参数
        existing_ecr_repository_name = self.node.try_get_context("existing_ecr_repository_name")
        runtime_image_tag = self.node.try_get_context("runtime_image_tag") or "latest"
        # 如果传了不可变镜像引用（repo@sha256:...），优先使用它
        runtime_image_ref = self.node.try_get_context("runtime_image_ref")
        model_id = self.node.try_get_context("model_id") or "amazon.nova-lite-v1:0"
        # 可选：直接指定模型 ARN（优先级高于 model_id）
        model_arn = self.node.try_get_context("model_arn")
        pdf_url_expires = str(self.node.try_get_context("pdf_url_expires") or "600")

        # S3：保存生成的 PDF 文件
        pdf_bucket = s3.Bucket(
            self,
            "PdfBucket",
            enforce_ssl=True,
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            versioned=False,
            # 30 天自动过期，控制存储成本
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
        )

        # DynamoDB：保存问答元数据
        qa_table = dynamodb.Table(
            self,
            "QaRecordsTable",
            partition_key=dynamodb.Attribute(name="record_id", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery=True,
        )

        # ECR：复用已有仓库或新建仓库
        if existing_ecr_repository_name:
            runtime_repo = ecr.Repository.from_repository_name(
                self, "RuntimeImageRepoImported", existing_ecr_repository_name
            )
            ecr_repository_name = existing_ecr_repository_name
        else:
            runtime_repo = ecr.Repository(
                self,
                "RuntimeImageRepo",
                repository_name="ai-agentcore-runtime",
                image_scan_on_push=True,
            )
            ecr_repository_name = runtime_repo.repository_name

        # Runtime 执行角色（由 Bedrock AgentCore 服务扮演）
        runtime_role = iam.Role(
            self,
            "AgentRuntimeExecutionRole",
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            description="Execution role for AgentCore runtime container.",
        )

        # 允许调用指定模型
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    str(model_arn)
                    if model_arn
                    else (
                        "arn:"
                        f"{cdk.Aws.PARTITION}:bedrock:{cdk.Aws.REGION}"
                        f"::foundation-model/{model_id}"
                    )
                ],
            )
        )

        # 拉取容器镜像所需权限
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["ecr:GetAuthorizationToken"],
                resources=["*"],
            )
        )
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "ecr:BatchGetImage",
                    "ecr:GetDownloadUrlForLayer",
                    "ecr:BatchCheckLayerAvailability",
                ],
                resources=[runtime_repo.repository_arn],
            )
        )
        runtime_repo.grant_pull(runtime_role)

        # 允许写 CloudWatch Logs（便于诊断）
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=[
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:DescribeLogGroups",
                    "logs:DescribeLogStreams",
                    "logs:PutLogEvents",
                ],
                resources=["*"],
            )
        )

        # 允许写 DynamoDB 问答记录
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:PutItem"],
                resources=[qa_table.table_arn],
            )
        )

        # 允许读写 S3 的 pdf/ 前缀
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject", "s3:GetObject"],
                resources=[f"{pdf_bucket.bucket_arn}/pdf/*"],
            )
        )

        # 计算容器镜像 URI（优先不可变引用）
        container_image_uri = (
            str(runtime_image_ref)
            if runtime_image_ref
            else f"{runtime_repo.repository_uri}:{runtime_image_tag}"
        )

        # 通过描述中的 marker 让 endpoint 在镜像变化时触发更新
        endpoint_deploy_marker = (str(runtime_image_tag) if runtime_image_tag else "latest")[:48]
        if runtime_image_ref:
            endpoint_deploy_marker = str(runtime_image_ref).split("@")[-1][:48]
        endpoint_description = (
            "Primary endpoint for ai-agentcore runtime. "
            f"marker={endpoint_deploy_marker}"
        )

        # 定义 AgentCore Runtime
        runtime = bedrockagentcore.CfnRuntime(
            self,
            "AgentRuntime",
            agent_runtime_name="ai_agentcore_runtime",
            role_arn=runtime_role.role_arn,
            network_configuration=bedrockagentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            agent_runtime_artifact=bedrockagentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=bedrockagentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=container_image_uri
                )
            ),
            # 运行时环境变量会被应用代码读取
            environment_variables={
                "MODEL_ID": model_id,
                "TABLE_NAME": qa_table.table_name,
                "BUCKET_NAME": pdf_bucket.bucket_name,
                "PDF_URL_EXPIRES": pdf_url_expires,
                "AWS_REGION": self.region,
                "AWS_DEFAULT_REGION": self.region,
            },
        )

        # 显式依赖默认策略，避免权限还未落地就创建 runtime
        default_policy = runtime_role.node.try_find_child("DefaultPolicy")
        if default_policy is not None and default_policy.node.default_child is not None:
            runtime.add_dependency(default_policy.node.default_child)

        # 定义 Runtime Endpoint
        runtime_endpoint = bedrockagentcore.CfnRuntimeEndpoint(
            self,
            "AgentRuntimeEndpoint",
            agent_runtime_id=runtime.attr_agent_runtime_id,
            name="prod",
            description=endpoint_description,
        )
        runtime_endpoint.add_dependency(runtime)

        # 组装调用路径与完整调用 URL
        invoke_path = cdk.Fn.join(
            "",
            [
                "/runtimes/",
                runtime.attr_agent_runtime_arn,
                "/invocations?accountId=",
                self.account,
                "&qualifier=",
                runtime_endpoint.name,
            ],
        )
        invoke_url = cdk.Fn.join(
            "",
            [
                "https://bedrock-agentcore.",
                self.region,
                ".amazonaws.com/runtimes/",
                runtime.attr_agent_runtime_arn,
                "/invocations?accountId=",
                self.account,
                "&qualifier=",
                runtime_endpoint.name,
            ],
        )

        # CloudFormation 输出，便于部署后查询
        CfnOutput(self, "PdfBucketName", value=pdf_bucket.bucket_name)
        CfnOutput(self, "PdfBucketArn", value=pdf_bucket.bucket_arn)
        CfnOutput(self, "QaTableName", value=qa_table.table_name)
        CfnOutput(self, "QaTableArn", value=qa_table.table_arn)
        CfnOutput(self, "RuntimeImageRepositoryName", value=ecr_repository_name)
        CfnOutput(self, "RuntimeImageRepositoryUri", value=runtime_repo.repository_uri)
        CfnOutput(self, "RuntimeContainerImageUri", value=container_image_uri)
        CfnOutput(self, "AgentRuntimeArn", value=runtime.attr_agent_runtime_arn)
        CfnOutput(self, "AgentRuntimeId", value=runtime.attr_agent_runtime_id)
        CfnOutput(
            self,
            "AgentRuntimeEndpointArn",
            value=runtime_endpoint.attr_agent_runtime_endpoint_arn,
        )
        CfnOutput(self, "AgentRuntimeEndpointId", value=runtime_endpoint.attr_id)
        CfnOutput(self, "AgentRuntimeEndpointName", value=runtime_endpoint.name)
        CfnOutput(self, "AgentRuntimeEndpointOutput", value=runtime_endpoint.name)
        CfnOutput(self, "AgentRuntimeEndpointInvokeUrl", value=invoke_url)
        CfnOutput(self, "InvokePath", value=invoke_path)


# CDK 应用入口
app = cdk.App()
InfraStack(app, "InfraStack")
app.synth()
