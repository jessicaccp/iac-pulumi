"""Menor programa possível, pequeno de propósito: o interesse deste experimento
é o arquivo de estado, e não a infraestrutura.

Verificação registrada em docs/01-verificacoes.md.
"""

import pulumi
import pulumi_docker as docker

config = pulumi.Config()
token = config.require_secret("token")

network = docker.Network("study-net", name="pulumi-local-backend-net")

pulumi.export("network_id", network.id)
pulumi.export("token_length", token.apply(len))
