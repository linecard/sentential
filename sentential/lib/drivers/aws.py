import json
import os
from time import sleep
from typing import Dict, List, Optional
from sentential.lib.drivers.spec import Driver
from sentential.lib.ontology import Ontology
from sentential.lib.shapes import LAMBDA_ROLE_POLICY_JSON, Image
from sentential.lib.clients import clients
from sentential.lib.template import Policy

# TODO: figure out how to get boto3 typeshed to work, so functions can return types instead of Dict

class AwsDriverError(BaseException):
    pass

class AwsDriver(Driver):
    def __init__(self, ontology: Ontology) -> None:
        self.ontology = ontology
        self.context = self.ontology.context
        self.partition = self.context.partition
        self.region = self.context.region
        self.account_id = self.context.account_id
        self.repo_name = self.context.repository_name
        self.repo_url = self.context.repository_url
        self.envs = self.ontology.envs
        self.provision = self.ontology.configs
        self.resource_name = f"{self.partition}-{self.region}-{self.repo_name}"
        self.policy_arn = f"arn:aws:iam::{self.account_id}:policy/{self.resource_name}"

    def deployed(self) -> Image:
            function_name = self.resource_name
            try:
                function = clients.lmb.get_function(FunctionName=function_name)
                # tag = function["Code"]["ImageUri"].split("/")[1].split(":")[1]
                return Image(id="todo", digests=["todo"], tags=["todo"], versions=["todo"])
            except clients.lmb.exceptions.ResourceNotFoundException:
                raise AwsDriverError("could not find aws deployed function")

    def images(self) -> List[Image]:
        images = []
        describe_images = clients.ecr.describe_images(repositoryName=self.repo_name)['imageDetails']
        image_digests = [ {"imageDigest": image["imageDigest"]} for image in describe_images ]
        batch_get_images = clients.ecr.batch_get_image(repositoryName=self.repo_name, imageIds=image_digests)['images']
        image_config_digests = {}
        
        for image in batch_get_images:
            image_digest = image['imageId']['imageDigest']
            image_config_digest = json.loads(image['imageManifest'])['config']['digest']
            if image_digest not in image_config_digests:
                image_config_digests[image_digest] = []
            image_config_digests[image_digest].append(image_config_digest)

        for image in describe_images:
            image_digest = image['imageDigest']
            if 'imageTags' in image:
                tags = [f"{self.repo_url}:{tag}" for tag in image['imageTags'] ]
                versions = image['imageTags']
            else:
                tags = []
                versions= []

                
            images.append(Image(
                id=image['imageDigest'],
                digests=image_config_digests[image_digest],
                tags=tags,
                versions=versions
            ))
        
        return images


    def image(self, version: str) -> Image:
        for image in self.images():
            if version in image.versions:
                return image
        raise AwsDriverError(f"no image found with for version {version}")

    def deploy(self, image: Image, public_url: bool) -> str:
        self._put_role()
        clients.iam.attach_role_policy(
            RoleName=self._put_role()["Role"]["RoleName"],
            PolicyArn=self._put_policy()["Policy"]["Arn"],
        )

        function = self._put_lambda(image)

        if public_url:
            return self._put_url()["FunctionUrl"]
        else:
            return function["FunctionArn"]


    def destroy(self):
        role_name = self.resource_name
        function_name = self.resource_name
        try:
            clients.lmb.delete_function_url_config(FunctionName=function_name)
        except clients.lmb.exceptions.ResourceNotFoundException:
            pass

        try:
            clients.lmb.delete_function(FunctionName=function_name)
        except clients.lmb.exceptions.ResourceNotFoundException:
            pass

        try:
            clients.iam.detach_role_policy(
                PolicyArn=self.policy_arn, RoleName=role_name
            )

            policy_versions = clients.iam.list_policy_versions(
                PolicyArn=self.policy_arn
            )["Versions"]
            for policy_version in policy_versions:
                if not policy_version["IsDefaultVersion"]:
                    clients.iam.delete_policy_version(
                        PolicyArn=self.policy_arn, VersionId=policy_version["VersionId"]
                    )

            clients.iam.delete_policy(PolicyArn=self.policy_arn)
        except clients.iam.exceptions.NoSuchEntityException:
            pass

        try:
            clients.iam.delete_role(RoleName=role_name)
        except clients.iam.exceptions.NoSuchEntityException:
            pass

    def logs(self, follow: bool = False) -> None:
        cmd = ["aws", "logs", "tail", f"/aws/lambda/{self.resource_name}"]
        if follow:
            cmd.append("--follow")
        os.system(" ".join(cmd))

    def invoke(self, payload: str) -> None:
        raise AwsDriverError("invoke is not yet implemented")


    def _put_role(self, tags: Optional[Dict[str, str]] = None) -> Dict:
        role_name = self.resource_name
        try:
            clients.iam.create_role(
                RoleName=role_name,
                AssumeRolePolicyDocument=LAMBDA_ROLE_POLICY_JSON,
            )

            clients.iam.get_waiter("role_exists").wait(RoleName=role_name)

        except clients.iam.exceptions.EntityAlreadyExistsException:
            clients.iam.update_assume_role_policy(
                RoleName=role_name,
                PolicyDocument=LAMBDA_ROLE_POLICY_JSON,
            )

        clients.iam.get_waiter("role_exists").wait(RoleName=role_name)

        if tags:
            clients.iam.tag_role(
                RoleName=role_name,
                Tags=[
                    {"Key": key, "Value": value} for (key, value) in tags.items()
                ],
            )

        return clients.iam.get_role(RoleName=role_name)

    def _put_policy(self, tags: Optional[Dict[str, str]] = None) -> Dict:
        policy_json = Policy(self.ontology).render()
        policy_name = self.resource_name
        policy_arn = self.policy_arn
        
        try:
            policy = clients.iam.create_policy(
                PolicyName=policy_name,
                PolicyDocument=policy_json,
            )

        except clients.iam.exceptions.EntityAlreadyExistsException:
            policy = clients.iam.get_policy(PolicyArn=policy_arn)

            versions = clients.iam.list_policy_versions(PolicyArn=policy_arn)[
                "Versions"
            ]

            if len(versions) >= 5:
                clients.iam.delete_policy_version(
                    PolicyArn=policy_arn, VersionId=versions[-1]["VersionId"]
                )

            clients.iam.create_policy_version(
                PolicyArn=policy_arn,
                PolicyDocument=policy_json,
                SetAsDefault=True,
            )

        if tags:
            clients.iam.tag_policy(
                PolicyName=policy.name,
                Tags=[
                    {"Key": key, "Value": value} for (key, value) in tags.items()
                ],
            )

        clients.iam.get_waiter("policy_exists").wait(PolicyArn=policy_arn)
        return policy

    def _put_lambda(self, image: Image, tags: Optional[Dict[str, str]] = None) -> Dict:
        role_name = self.resource_name
        function_name = self.resource_name
        role_arn = clients.iam.get_role(RoleName=role_name)["Role"]["Arn"]
        image_uri = f"{self.repo_url}:{image.versions[0]}" # TODO: do we want to deploy latest version on image, or version declared?
        envs_path = self.envs.path
        sleep(10)
        try:
            function = clients.lmb.create_function(
                FunctionName=function_name,
                Role=role_arn,
                PackageType="Image",
                Code={"ImageUri": image_uri},
                Description=f"sententially deployed {image_uri}",
                Environment={"Variables": {"PARTITION": envs_path}},
                # Architectures=[self.image.arch], # TODO: figure out wtf is going on with fetching arch.
                EphemeralStorage={"Size": self.provision.parameters.storage},
                MemorySize=self.provision.parameters.memory,
                Timeout=self.provision.parameters.timeout,
                VpcConfig={
                    "SubnetIds": self.provision.parameters.subnet_ids,
                    "SecurityGroupIds": self.provision.parameters.security_group_ids,
                },
            )

            clients.lmb.add_permission(
                FunctionName=function_name,
                StatementId="FunctionURLAllowPublicAccess",
                Action="lambda:InvokeFunctionUrl",
                Principal="*",
                FunctionUrlAuthType=self.provision.parameters.auth_type,
            )

            return function
        except clients.lmb.exceptions.ResourceConflictException:
            function = clients.lmb.update_function_configuration(
                FunctionName=function_name,
                Role=role_arn,
                Description=f"sententially deployed {image_uri}",
                Environment={"Variables": {"PARTITION": envs_path}},
                EphemeralStorage={"Size": self.provision.parameters.storage},
                MemorySize=self.provision.parameters.memory,
                Timeout=self.provision.parameters.timeout,
                VpcConfig={
                    "SubnetIds": self.provision.parameters.subnet_ids,
                    "SecurityGroupIds": self.provision.parameters.security_group_ids,
                },
            )

            clients.lmb.get_waiter("function_updated_v2").wait(
                FunctionName=function_name
            )

            clients.lmb.update_function_code(
                FunctionName=function_name,
                ImageUri=image_uri,
                Publish=True,
            )

            try:
                clients.lmb.remove_permission(
                    FunctionName=function_name,
                    StatementId="FunctionURLAllowPublicAccess",
                )
            except clients.lmb.exceptions.ResourceNotFoundException:
                pass

            clients.lmb.add_permission(
                FunctionName=function_name,
                StatementId="FunctionURLAllowPublicAccess",
                Action="lambda:InvokeFunctionUrl",
                Principal="*",
                FunctionUrlAuthType=self.provision.parameters.auth_type,
            )

            if tags:
                clients.lmb.tag_resource(Resource=function.arn, Tags=tags)

            return function


    def _put_url(self) -> Dict:
        function_name = self.resource_name
        config = {
            "FunctionName": function_name,
            "AuthType": self.provision.parameters.auth_type,
            "Cors": {
                "AllowHeaders": self.provision.parameters.allow_headers,
                "AllowMethods": self.provision.parameters.allow_methods,
                "AllowOrigins": self.provision.parameters.allow_origins,
                "ExposeHeaders": self.provision.parameters.expose_headers,
            },
        }

        try:
            clients.lmb.create_function_url_config(**config)
        except clients.lmb.exceptions.ResourceConflictException:
            clients.lmb.update_function_url_config(**config)

        return clients.lmb.get_function_url_config(FunctionName=function_name)

