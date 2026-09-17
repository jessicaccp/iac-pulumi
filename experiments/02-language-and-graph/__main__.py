"""Mecânica de linguagem que um documento declarativo não expressa.

Constrói uma frota com um laço, deriva valores de recursos que ainda não existem,
injeta um valor secreto de configuração e exporta uma lista calculada de
endpoints.

Verificação registrada em docs/01-verificacoes.md.
"""

import pulumi
import pulumi_docker as docker

config = pulumi.Config()
service_count = config.get_int("serviceCount") or 2
base_port = config.get_int("basePort") or 8090
image_name = config.get("imageName") or "nginx:1.27-alpine"
greeting = config.require_secret("greeting")

image = docker.RemoteImage("nginx-image", name=image_name)
network = docker.Network("study-net", name="pulumi-study-net")

containers = []
for index in range(service_count):
    container_name = f"pulumi-study-web-{index}"
    containers.append(
        docker.Container(
            container_name,
            image=image.image_id,
            name=container_name,
            networks_advanced=[docker.ContainerNetworksAdvancedArgs(name=network.name)],
            envs=[pulumi.Output.concat("GREETING=", greeting)],
            ports=[docker.ContainerPortArgs(internal=80, external=base_port + index)],
        )
    )


def render_endpoints(container_ids: list[str]) -> list[str]:
    return [
        f"http://localhost:{base_port + index} -> {container_id[:12]}"
        for index, container_id in enumerate(container_ids)
    ]


# Output.all transforma N valores pendentes em uma única lista pendente; apply é
# a única forma de rodar Python comum sobre eles, porque os valores ainda não são
# conhecidos neste ponto.
all_ids = pulumi.Output.all(*[container.id for container in containers])
pulumi.export("endpoints", all_ids.apply(render_endpoints))
pulumi.export("endpoint_count", len(containers))
pulumi.export("greeting_is_secret", greeting.is_secret())
