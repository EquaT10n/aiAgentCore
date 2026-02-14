from __future__ import annotations

import aws_cdk as cdk
from aws_cdk import (
    CfnOutput,
    Duration,
    Stack,
)
from aws_cdk import (
    aws_bedrockagentcore as bedrockagentcore,
)
from aws_cdk import (
    aws_dynamodb as dynamodb,
)
from aws_cdk import (
    aws_ecr as ecr,
)
from aws_cdk import (
    aws_iam as iam,
)
from aws_cdk import (
    aws_s3 as s3,
)
from constructs import Construct

# 引入 AWS CDK 主模块（包含 App/Fn/Aws 等核心构件）
# 从 CDK 中按需导入会用到的资源构件
# CDK 构造树中的基础节点类型

# 基础设施主栈：定义运行时所需全部云资源
class InfraStack(Stack):
    # 栈初始化入口
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        # 先初始化父类 Stack
        super().__init__(scope, construct_id, **kwargs)

        # 读取上下文参数：外部 ECR 仓库名（可选）
        existing_ecr_repository_name = self.node.try_get_context("existing_ecr_repository_name")
        # 读取镜像 tag，默认 latest
        runtime_image_tag = self.node.try_get_context("runtime_image_tag") or "latest"
        # 读取模型 ID，未传则使用默认 Claude 模型
        model_id = self.node.try_get_context("model_id") or (
            "anthropic.claude-3-5-sonnet-20241022-v2:0"
        )
        # 读取模型 ARN（可选，优先级高于 model_id 拼 ARN）
        model_arn = self.node.try_get_context("model_arn")
        # 读取 PDF 预签名 URL 过期时间（秒），统一转字符串传入环境变量
        pdf_url_expires = str(self.node.try_get_context("pdf_url_expires") or "600")

        # 创建 S3 Bucket：用于保存生成的 PDF
        pdf_bucket = s3.Bucket(
            self,
            "PdfBucket",
            # 强制 HTTPS 访问
            enforce_ssl=True,
            # 阻断全部公共访问
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            # 关闭对象版本化（当前场景不需要）
            versioned=False,
            # 生命周期：30 天后自动过期删除
            lifecycle_rules=[s3.LifecycleRule(expiration=Duration.days(30))],
        )

        # 创建 DynamoDB 表：保存问答记录元数据
        qa_table = dynamodb.Table(
            self,
            "QaRecordsTable",
            # 主键为 record_id（字符串）
            partition_key=dynamodb.Attribute(name="record_id", type=dynamodb.AttributeType.STRING),
            # 按量计费，避免固定预置吞吐
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            # 开启 PITR，支持按时间点恢复
            point_in_time_recovery=True,
        )

        # 若传入了已有 ECR 仓库名，则复用已有仓库
        if existing_ecr_repository_name:
            runtime_repo = ecr.Repository.from_repository_name(
                self, "RuntimeImageRepoImported", existing_ecr_repository_name
            )
            # 输出值使用外部仓库名
            ecr_repository_name = existing_ecr_repository_name
        else:
            # 否则在栈中创建新 ECR 仓库
            runtime_repo = ecr.Repository(
                self,
                "RuntimeImageRepo",
                # 仓库名固定，便于 CI/CD 查找
                repository_name="ai-agentcore-runtime",
                # 推送时自动扫描镜像漏洞
                image_scan_on_push=True,
            )
            # 输出值使用新建仓库名
            ecr_repository_name = runtime_repo.repository_name

        # 创建运行时执行角色：由 Bedrock AgentCore 服务扮演
        runtime_role = iam.Role(
            self,
            "AgentRuntimeExecutionRole",
            # 信任主体：Bedrock AgentCore 服务
            assumed_by=iam.ServicePrincipal("bedrock-agentcore.amazonaws.com"),
            # 角色说明
            description="Execution role for AgentCore runtime container.",
        )
        # 授予调用大模型权限
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                # 允许普通调用与流式调用
                actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                resources=[
                    # 若显式传入 model_arn，则只授权该 ARN
                    str(model_arn)
                    if model_arn
                    # 否则按 model_id 在当前分区/区域拼出基础模型 ARN
                    else (
                        "arn:"
                        f"{cdk.Aws.PARTITION}:bedrock:{cdk.Aws.REGION}"
                        f"::foundation-model/{model_id}"
                    )
                ],
            )
        )
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
        # 授予写入 DynamoDB 权限（保存问答记录）
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["dynamodb:PutItem"],
                resources=[qa_table.table_arn],
            )
        )
        # 授予 S3 读写 PDF 权限（限定到 pdf/ 前缀）
        runtime_role.add_to_policy(
            iam.PolicyStatement(
                actions=["s3:PutObject", "s3:GetObject"],
                resources=[f"{pdf_bucket.bucket_arn}/pdf/*"],
            )
        )

        # 创建 AgentCore Runtime 资源（容器运行时定义）
        runtime = bedrockagentcore.CfnRuntime(
            self,
            "AgentRuntime",
            # 运行时名称（全局可识别）
            agent_runtime_name="ai_agentcore_runtime",
            # 绑定执行角色
            role_arn=runtime_role.role_arn,
            # 网络模式：公网访问
            network_configuration=bedrockagentcore.CfnRuntime.NetworkConfigurationProperty(
                network_mode="PUBLIC"
            ),
            # 指定容器镜像来源（ECR URI + tag）
            agent_runtime_artifact=bedrockagentcore.CfnRuntime.AgentRuntimeArtifactProperty(
                container_configuration=bedrockagentcore.CfnRuntime.ContainerConfigurationProperty(
                    container_uri=f"{runtime_repo.repository_uri}:{runtime_image_tag}"
                )
            ),
            # 注入运行时环境变量（应用代码读取）
            environment_variables={
                "MODEL_ID": model_id,
                "TABLE_NAME": qa_table.table_name,
                "BUCKET_NAME": pdf_bucket.bucket_name,
                "PDF_URL_EXPIRES": pdf_url_expires,
            },
        )
        default_policy = runtime_role.node.try_find_child("DefaultPolicy")
        if default_policy is not None and default_policy.node.default_child is not None:
            runtime.add_dependency(default_policy.node.default_child)

        # 创建 Runtime Endpoint：提供实际调用入口
        runtime_endpoint = bedrockagentcore.CfnRuntimeEndpoint(
            self,
            "AgentRuntimeEndpoint",
            # 绑定到上面创建的 runtime
            agent_runtime_id=runtime.attr_agent_runtime_id,
            # 端点名称，用作 qualifier
            name="prod",
            # 端点说明
            description="Primary endpoint for ai-agentcore runtime.",
        )
        # 显式依赖：确保先创建 runtime 再创建 endpoint
        runtime_endpoint.add_dependency(runtime)

        # 生成相对调用路径（便于调试或网关拼接）
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
        # 生成完整调用 URL（输出给部署后 smoke test 使用）
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

        # 以下为 CloudFormation 输出，方便部署后查询资源信息
        CfnOutput(self, "PdfBucketName", value=pdf_bucket.bucket_name)
        CfnOutput(self, "PdfBucketArn", value=pdf_bucket.bucket_arn)
        CfnOutput(self, "QaTableName", value=qa_table.table_name)
        CfnOutput(self, "QaTableArn", value=qa_table.table_arn)
        CfnOutput(self, "RuntimeImageRepositoryName", value=ecr_repository_name)
        CfnOutput(self, "RuntimeImageRepositoryUri", value=runtime_repo.repository_uri)
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
# 实例化基础设施栈
InfraStack(app, "InfraStack")
# 合成 CloudFormation 模板
app.synth()
