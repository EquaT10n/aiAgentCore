from __future__ import annotations

import aws_cdk as cdk
from constructs import Construct


class InfraStack(cdk.Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: object) -> None:
        super().__init__(scope, construct_id, **kwargs)


app = cdk.App()
InfraStack(app, "InfraStack")
app.synth()
