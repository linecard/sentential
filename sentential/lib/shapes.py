import re
from datetime import datetime
from enum import Enum
from pathlib import PosixPath
from typing import List, Union, Optional, Dict
from pydantic import BaseModel, Field, validator, Json
from sentential.support.shaper import Shaper
from sentential.lib.exceptions import ShapeError

#
# Global Constants
#
CURRENT_WORKING_IMAGE_TAG = "cwi"

#
# Internally Defined Shapes
#
class Image(BaseModel):
    id: str
    digest: Union[str, None]
    uri: Union[str, None]
    tags: List[str]
    arch: str
    versions: List[str]

    @validator("versions")
    def coerce_versions(cls, v):
        if v is not None:
            return list(set(v))
        else:
            return []

    @validator("tags")
    def coerce_tags(cls, v):
        if v is not None:
            return list(set(v))
        else:
            return []


class ImageView(Image):
    @validator("id")
    def humanize_id(cls, v):
        return v.replace("sha256:", "")[0:12]

    @validator("digest")
    def humanize_digest(cls, v):
        if v:
            return v.replace("sha256:", "")[0:12]


class Function(BaseModel):
    image: Image
    name: str
    role_arn: str
    role_name: str
    region: str
    arn: str
    web_console_url: Union[str, None]


class Provision(Shaper):
    storage: int = Field(default=512, description="ephemeral storage (mb)")
    memory: int = Field(default=128, description="allocated memory (mb)")
    timeout: int = Field(default=3, description="timeout (s)")
    subnet_ids: List[str] = Field(default=[], description="subnet ids")
    security_group_ids: List[str] = Field(default=[], description="security group ids")
    auth_type: str = Field(default="NONE", description="auth type")
    allow_headers: List[str] = Field(default=["*"], description="CORS AllowHeaders")
    allow_methods: List[str] = Field(default=["*"], description="CORS AllowMethods")
    allow_origins: List[str] = Field(default=["*"], description="CORS AllowOrigins")
    expose_headers: List[str] = Field(default=["*"], description="CORS ExposeHeaders")

    @validator("auth_type")
    def is_valid_auth_type(cls, v):
        valid_auth_types = ["NONE", "AWS"]
        if v not in valid_auth_types:
            raise ValueError(f"auth_type must be one of {', '.join(valid_auth_types)}")
        return v


#
# ECR
#

# describe_image()
class AwsImageDescription(BaseModel):
    imageDigest: str
    imageTags: Union[List[str], None]
    imageManifestMediaType: str


class AwsImageDescriptions(BaseModel):
    imageDetails: List[AwsImageDescription]


# Manifest List
# https://docs.docker.com/registry/spec/manifest-v2-2/
class AwsManifestListManifestPlatform(BaseModel):
    architecture: str
    os: str


class AwsManifestListManifest(BaseModel):
    mediaType: str
    size: int
    digest: str
    platform: AwsManifestListManifestPlatform


class AwsManifestList(BaseModel):
    schemaVersion: int
    mediaType: str
    manifests: List[AwsManifestListManifest]


# Image Manifest
# https://docs.docker.com/registry/spec/manifest-v2-2/
class AwsImageManifestLayer(BaseModel):
    mediaType: str
    size: int
    digest: str


class AwsImageManifest(BaseModel):
    schemaVersion: int
    mediaType: str
    config: AwsImageManifestLayer
    layers: List[AwsImageManifestLayer]


# batch_get_image()
class AwsImageDetailImageId(BaseModel):
    imageDigest: str
    imageTag: Optional[str]


class AwsImageDetail(BaseModel):
    registryId: str
    repositoryName: str
    imageId: AwsImageDetailImageId
    imageManifest: Union[Json[AwsImageManifest], Json[AwsManifestList]]


class AwsImageDetails(BaseModel):
    images: List[AwsImageDetail]


class AwsEcrAuthorizationData(BaseModel):
    authorizationToken: str
    expiresAt: datetime
    proxyEndpoint: str


class AwsEcrAuthorizationToken(BaseModel):
    authorizationData: List[AwsEcrAuthorizationData]


#
# IAM
#
class AWSPolicyStatement(BaseModel):
    """https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements_statement.html"""

    Effect: str
    Action: Union[str, List[str]]
    Principal: Optional[dict]
    Resource: Optional[Union[str, List[str]]]
    Condition: Optional[dict]


class AWSPolicyDocument(BaseModel):
    """https://docs.aws.amazon.com/IAM/latest/UserGuide/reference_policies_elements.html"""

    Version: str = "2012-10-17"
    Statement: List[AWSPolicyStatement]


class AWSCallerIdentity(BaseModel):
    UserId: str
    Account: str
    Arn: str
    type: Optional[bool]

    @validator("type", always=True)
    def derive_type(cls, value, values):
        if ":federated-user/" in values["Arn"]:
            return "federated-user"
        elif ":assumed-role/" in values["Arn"]:
            return "assumed-role"
        elif ":user/" in values["Arn"]:
            return "user"
        else:
            raise ShapeError(
                f"could not determine credential type of...\n{values['Arn']}"
            )


class AWSCredentials(BaseModel):
    AccessKeyId: str
    SecretAccessKey: str
    SessionToken: Optional[str]
    Expiration: Optional[datetime]


class AWSFederatedUser(BaseModel):
    FederatedUserId: str
    Arn: str


class AWSAssumedRoleUser(BaseModel):
    AssumedRoleId: str
    Arn: str


class AWSFederationToken(BaseModel):
    Credentials: AWSCredentials
    FederatedUser: AWSFederatedUser
    PackedPolicySize: int


class AWSAssumeRole(BaseModel):
    Credentials: AWSCredentials
    AssumedRoleUser: AWSAssumedRoleUser


#
# Lambda
#
class Runtimes(Enum):
    """https://gallery.ecr.aws/lambda?page=1"""

    python = "python"
    dotnet = "dotnet"
    java = "java"
    go = "go"
    nodejs = "nodejs"
    provided = "provided"
    ruby = "ruby"


LAMBDA_ROLE_POLICY_JSON = (
    AWSPolicyDocument(
        Statement=[
            AWSPolicyStatement(
                Effect="Allow",
                Principal={"Service": "lambda.amazonaws.com"},
                Action="sts:AssumeRole",
            )  # type: ignore
        ]
    )
).json(exclude_none=True)


class AwsFunctionVpcConfig(BaseModel):
    SubnetIds: List[str]
    SecurityGroupIds: List[str]
    VpcId: str


class AwsFunctionEnvironment(BaseModel):
    Variables: Dict[str, str]


class AwsFunctionEphemeralStorage(BaseModel):
    Size: int


class AwsFunctionConfiguration(BaseModel):
    FunctionName: str
    FunctionArn: str
    Role: str
    CodeSize: int
    Description: str
    Timeout: int
    MemorySize: int
    LastModified: datetime
    CodeSha256: str
    Version: str
    VpcConfig: AwsFunctionVpcConfig
    Environment: AwsFunctionEnvironment
    TracingConfig: Dict[str, str]
    RevisionId: str
    State: str
    StateReason: Optional[str]
    StateReasonCode: Optional[str]
    PackageType: str
    Architectures: List[str]
    EphemeralStorage: AwsFunctionEphemeralStorage


class AwsFunctionCode(BaseModel):
    RepositoryType: str
    ImageUri: str
    ResolvedImageUri: str


class AwsFunctionCors(BaseModel):
    AllowHeaders: List[str]
    AllowMethods: List[str]
    AllowOrigins: List[str]
    ExposeHeaders: List[str]


class AwsFunctionPublicUrl(BaseModel):
    FunctionUrl: str
    FunctionArn: str
    AuthType: str
    Cors: AwsFunctionCors
    CreationTime: datetime
    LastModifiedTime: datetime


class AwsFunction(BaseModel):
    Configuration: AwsFunctionConfiguration
    Code: AwsFunctionCode


#
# Pathing
#
class Paths(BaseModel):
    root: PosixPath
    sntl: PosixPath
    src: PosixPath
    bake: PosixPath
    runtime: PosixPath
    dockerfile: PosixPath
    wrapper: PosixPath
    policy: PosixPath
    shapes: PosixPath


def derive_paths(root: PosixPath = PosixPath(".")):
    return Paths(
        root=root,
        sntl=PosixPath(f"{root}/.sntl"),
        src=PosixPath(f"{root}/src"),
        bake=PosixPath(f"{root}/.sntl/docker-bake.hcl"),
        runtime=PosixPath(f"{root}/.sntl/Dockerfile"),
        dockerfile=PosixPath(f"{root}/Dockerfile"),
        wrapper=PosixPath(f"{root}/.sntl/wrapper.sh"),
        policy=PosixPath(f"{root}/policy.json"),
        shapes=PosixPath(f"{root}/shapes.py"),
    )


#
# API Gateway
#
class ApiGatewayIntegration(BaseModel):
    ConnectionType: str = "INTERNET"
    Description: str = "managed by sentential"
    IntegrationId: Optional[str] = None
    IntegrationMethod: str = "ANY"
    IntegrationType: str = "AWS_PROXY"
    IntegrationUri: str
    PayloadFormatVersion: str = "2.0"
    TimeoutInMillis: int = 30000
    RequestParameters: Optional[Dict[str, str]] = {}


class ApiGatewayRoute(BaseModel):
    ApiKeyRequired: bool
    AuthorizationType: str
    RouteId: str
    RouteKey: str
    Target: Optional[str]
    Integration: Optional[ApiGatewayIntegration]


class ApiGatewayMapping(BaseModel):
    ApiId: str
    ApiMappingId: str
    ApiMappingKey: str
    Stage: str
    Routes: List[ApiGatewayRoute] = []


class ApiGatewayDomain(BaseModel):
    DomainName: str
    DomainNameConfigurations: Optional[List[Dict]]
    Tags: Dict[str, str] = {}
    Mappings: List[ApiGatewayMapping] = []


class ApiGatewayParsedUrl(BaseModel):
    ApiId: str
    ApiMappingId: str
    ApiMappingKey: str
    RouteKey: str
    RouteId: Optional[str]
    Verb: str = "Any"
    Route: str
    FullPath: str


class LambdaPermission(BaseModel):
    FunctionName: str
    StatementId: str
    Action: str
    Principal: str
    SourceArn: str
    SourceAccount: str
    EventSourceToken: str
    Qualifier: str
    RevisionId: str
    PrincipalOrgID: str
    FunctionUrlAuthType: str = "None"
