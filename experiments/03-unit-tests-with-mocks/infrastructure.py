"""Programa sob teste.

Mantido importável e sem efeitos fora do Pulumi, para que os testes possam
executá-lo em processo, com provedores simulados, sem daemon e sem CLI.

Verificação registrada em docs/01-verificacoes.md.
"""

import pulumi
import pulumi_docker as docker

config = pulumi.Config()
service_count = config.get_int("serviceCount") or 2
base_port = config.get_int("basePort") or 9000
image_name = config.get("imageName") or "nginx:1.27-alpine"

image = docker.RemoteImage("nginx-image", name=image_name)
network = docker.Network("study-net", name="pulumi-study-net")

containers = [
    docker.Container(
        f"web-{index}",
        image=image.image_id,
        name=f"pulumi-study-web-{index}",
        networks_advanced=[docker.ContainerNetworksAdvancedArgs(name=network.name)],
        ports=[docker.ContainerPortArgs(internal=80, external=base_port + index)],
    )
    for index in range(service_count)
]

container_ports = [base_port + index for index in range(service_count)]

pulumi.export("ports", container_ports)
pulumi.export("container_ids", pulumi.Output.all(*[c.id for c in containers]))
