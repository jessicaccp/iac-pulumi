"""Primeiro programa em Pulumi: container nginx no daemon Docker local.

Mostra o formato mínimo de um programa Pulumi: configuração, um recurso cujo
input vem do output de outro recurso, e os outputs exportados pelo stack.

Verificação registrada em docs/01-verificacoes.md.
"""

import pulumi
import pulumi_docker as docker

config = pulumi.Config()
host_port = config.get_int("hostPort") or 8080
image_name = config.get("imageName") or "nginx:1.27-alpine"

# O RemoteImage baixa a imagem e acompanha o digest no estado; o container
# abaixo depende dele porque consome o id da imagem.
image = docker.RemoteImage("nginx-image", name=image_name)

container = docker.Container(
    "nginx",
    image=image.image_id,
    name="pulumi-study-nginx",
    ports=[docker.ContainerPortArgs(internal=80, external=host_port)],
)

pulumi.export("url", pulumi.Output.concat("http://localhost:", str(host_port)))
pulumi.export("container_id", container.id)
pulumi.export("image_digest", image.repo_digest)
