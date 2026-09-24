"""Deployments com os campos do experimento, variando quantidade e componente.

O Deployment minimo passa pela espera do provedor, e a combinacao de campos igual
a do experimento tambem passa, em 12 segundos. Este projeto existe para separar as
duas diferencas que restam entre o experimento e o diagnostico:

  pulumi config set quantidade 2          # mais de uma unidade na mesma execucao
  pulumi config set componente true       # unidade dentro de um ComponentResource

Os campos do Deployment seguem as chaves sonda, limites, graca e servico, iguais
as do diagnostico anterior. Explicado em docs/04-tempos.md.
"""

from __future__ import annotations

import pulumi
import pulumi_kubernetes as k8s

config = pulumi.Config()
namespace = config.require("namespace")
quantidade = config.get_int("quantidade") or 1
usar_componente = config.get_bool("componente") or False
usar_sonda = config.get_bool("sonda") or False
usar_limites = config.get_bool("limites") or False
usar_graca = config.get_bool("graca") or False
usar_servico = config.get_bool("servico") or False

if not namespace.startswith("bench-"):
    raise ValueError(f"namespace precisa comecar com 'bench-', veio {namespace!r}")

sonda = None
if usar_sonda:
    sonda = k8s.core.v1.ProbeArgs(
        http_get=k8s.core.v1.HTTPGetActionArgs(path="/", port=80),
        initial_delay_seconds=1,
        period_seconds=2,
    )

limites = None
if usar_limites:
    limites = k8s.core.v1.ResourceRequirementsArgs(
        requests={"cpu": "50m", "memory": "32Mi"},
        limits={"cpu": "100m", "memory": "64Mi"},
    )


def criar_par(nome: str, opts: pulumi.ResourceOptions | None = None) -> tuple:
    """Um Deployment e um Service, iguais aos do experimento."""
    rotulos = {"app": nome}
    deployment = k8s.apps.v1.Deployment(
        f"{nome}-deployment",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name=nome, namespace=namespace, labels=rotulos
        ),
        spec=k8s.apps.v1.DeploymentSpecArgs(
            replicas=1,
            selector=k8s.meta.v1.LabelSelectorArgs(match_labels=rotulos),
            template=k8s.core.v1.PodTemplateSpecArgs(
                metadata=k8s.meta.v1.ObjectMetaArgs(labels=rotulos),
                spec=k8s.core.v1.PodSpecArgs(
                    termination_grace_period_seconds=5 if usar_graca else None,
                    containers=[
                        k8s.core.v1.ContainerArgs(
                            name="web",
                            image="nginx:1.27-alpine",
                            ports=[k8s.core.v1.ContainerPortArgs(container_port=80)]
                            if usar_sonda
                            else None,
                            resources=limites,
                            readiness_probe=sonda,
                        )
                    ],
                ),
            ),
        ),
        opts=opts,
    )
    servico = k8s.core.v1.Service(
        f"{nome}-service",
        metadata=k8s.meta.v1.ObjectMetaArgs(
            name=nome, namespace=namespace, labels=rotulos
        ),
        spec=k8s.core.v1.ServiceSpecArgs(
            selector=rotulos,
            ports=[k8s.core.v1.ServicePortArgs(port=80, target_port=80)],
        ),
        opts=opts,
    )
    return deployment, servico


class Unidade(pulumi.ComponentResource):
    """A unidade do experimento, dentro de um componente."""

    def __init__(self, nome: str, opts: pulumi.ResourceOptions | None = None) -> None:
        super().__init__("diagnostico:index:Unidade", nome, None, opts)
        filhos = pulumi.ResourceOptions(parent=self)
        self.deployment, self.servico = criar_par(nome, filhos)
        self.register_outputs(
            {
                "deploymentName": self.deployment.metadata.name,
                "serviceName": self.servico.metadata.name,
            }
        )


nomes = [f"await-check-{indice:03d}" for indice in range(quantidade)]

if usar_componente:
    unidades = [Unidade(nome) for nome in nomes]
else:
    unidades = [criar_par(nome) for nome in nomes]

pulumi.export("quantidade", quantidade)
pulumi.export("componente", usar_componente)
pulumi.export("nomes", nomes)
