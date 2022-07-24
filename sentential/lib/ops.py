import ast
from uuid import uuid4

from python_on_whales import DockerException

from sentential.lib.facts import Facts
from sentential.lib.infra import Infra
from sentential.lib.clients import clients
from sentential.lib.shapes.internal import Spec
from sentential.lib.store import SecretStore, ConfigStore
from sentential.lib.template import BuildTime as Template
from sentential.lib.shapes.aws import AWSPolicyDocument, ECREvent


def retry_after_docker_login(func):
    def wrap(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (DockerException) as e:
            print("retrying after ecr login")
            clients.docker.login_ecr()
            return func(self, *args, **kwargs)

    return wrap


class Ops:
    def __init__(self, repository_name: str) -> None:
        self.facts = Facts(repository_name=repository_name)
        self.config = ConfigStore(self.facts.repository_name)
        self.secret = SecretStore(self.facts.repository_name, self.facts.kms_key_id)

    def build(self, tag: str = "latest"):
        spec = Spec(
            prefix=self.facts.repository_name,
            policy=Template(self.facts).policy(),
            role_name=self.facts.repository_name,
            policy_name=self.facts.repository_name,
        )

        clients.docker.build(
            f"{self.facts.path.root}",
            labels={
                "spec": spec.json(exclude_none=True, exclude={"store"}, by_alias=True)
            },
            load=True,
            tags=[f"{self.facts.repository_name}:{tag}"],
        )

    @retry_after_docker_login
    def publish(self, tag: str = "latest"):
        clients.docker.image.tag(
            f"{self.facts.repository_name}:{tag}", f"{self.facts.repository_url}:{tag}"
        )
        clients.docker.image.push(f"{self.facts.repository_url}:{tag}")

    def deploy(self, tag: str = "latest"):
        event = self._generate_ecr_event(tag)
        Infra(event).ensure()

    def destroy(self, tag: str = "latest"):
        event = self._generate_ecr_event(tag)
        Infra(event).destroy()

    def emulate(self, tag: str = "latest"):
        event = self._generate_ecr_event(tag)
        clients.docker.remove(["sentential"], force=True, volumes=True)
        clients.docker.remove(["sentential-gw"], force=True, volumes=True)
        try:
            clients.docker.network.remove(["sentential-bridge"])
        except:
            print("no docker network to remove")

        clients.docker.network.create("sentential-bridge")

        image = clients.docker.image.inspect(
            f"{event.detail.repository_name}:{event.detail.image_tag}"
        )
        spec = Spec.parse_obj(ast.literal_eval(image.config.labels["spec"]))
        credentials = self._get_federation_token(spec.policy)
        default_env = {
            "AWS_REGION": event.region,
            "PREFIX": event.detail.repository_name,
        }

        clients.docker.run(
            f"{event.detail.repository_name}:{event.detail.image_tag}",
            name="sentential",
            hostname="sentential",
            networks=["sentential-bridge"],
            detach=True,
            remove=False,
            publish=[("9000", "8080")],
            envs={**default_env, **credentials},
        )

        clients.docker.run(
            "ghcr.io/wheegee/sentential-gw:latest",
            name="sentential-gw",
            hostname="sentential-gw",
            networks=["sentential-bridge"],
            detach=True,
            remove=False,
            publish=[("8081", "8081")],
            envs={"LAMBDA_ENDPOINT": "http://sentential:8080"},
        )
        print("http://localhost:8081")

    def _get_federation_token(self, policy: AWSPolicyDocument):
        token = clients.sts.get_federation_token(
            Name=f"{self.facts.repository_name}-spec-policy",
            Policy=policy.json(exclude_none=True, by_alias=True),
        )["Credentials"]

        return {
            "AWS_ACCESS_KEY_ID": token["AccessKeyId"],
            "AWS_SECRET_ACCESS_KEY": token["SecretAccessKey"],
            "AWS_SESSION_TOKEN": token["SessionToken"],
        }

    def _generate_ecr_event(self, tag: str = "latest") -> ECREvent:
        return ECREvent.parse_obj(
            {
                "version": 0,
                "id": str(uuid4()),
                "account": self.facts.account_id,
                "region": self.facts.region,
                "detail": {
                    "repository-name": self.facts.repository_name,
                    "image-tag": tag,
                },
            }
        )
