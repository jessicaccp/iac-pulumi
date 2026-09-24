"""Cria N modulos web em um namespace do cluster, para medir tempo.

Cada unidade e um ComponentResource com um Deployment e um Service, que e o
equivalente local de modulo do HCL. A contagem e os limites vem da configuracao
do stack. Explicado em docs/04-tempos.md.
"""

from __future__ import annotations

import pulumi
import pulumi_kubernetes as k8s

PREFIXO_DE_NAMESPACE = "bench-"


def validar_namespace(valor: str) -> str:
    """Recusa namespace que nao seja do experimento.

    O destroy remove tudo que o stack conhece, entao um namespace de terceiros na
    configuracao apagaria recursos que nao sao nossos.
    """
    if not valor.startswith(PREFIXO_DE_NAMESPACE):
        raise ValueError(
            f"namespace precisa comecar com {PREFIXO_DE_NAMESPACE!r}, veio {valor!r}"
        )
    return valor


def anotacoes_da_espera(skip_await: bool) -> dict[str, str] | None:
    """Anotacao que desliga a espera do provedor pelo recurso.

    A espera e por recurso, e o provedor espera o Service alem do Deployment: deixar
    so o Deployment sem espera ainda deixa o up preso na criacao do Service.
    """
    return {"pulumi.com/skipAwait": "true"} if skip_await else None


config = pulumi.Config()
namespace = validar_namespace(config.require("namespace"))
unit_count = config.get_int("unitCount") or 10
image = config.get("image") or "nginx:1.27-alpine"
name_prefix = config.get("namePrefix") or "bench-web"
cpu_request = config.get("cpuRequest") or "50m"
cpu_limit = config.get("cpuLimit") or "100m"
memory_request = config.get("memoryRequest") or "32Mi"
memory_limit = config.get("memoryLimit") or "64Mi"
anotacoes = anotacoes_da_espera(config.get_bool("skipAwait") or False)

nomes = [f"{name_prefix}-{indice:03d}" for indice in range(unit_count)]


class WebModule(pulumi.ComponentResource):
    """Unidade do experimento: um Deployment e um Service."""

    def __init__(self, nome: str, opts: pulumi.ResourceOptions | None = None) -> None:
        super().__init__("bench:index:WebModule", nome, None, opts)
        filhos = pulumi.ResourceOptions(parent=self)
        rotulos = {"app": nome}

        self.deployment = k8s.apps.v1.Deployment(
            f"{nome}-deployment",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name=nome,
                namespace=namespace,
                labels=rotulos,
                annotations=anotacoes,
            ),
            spec=k8s.apps.v1.DeploymentSpecArgs(
                replicas=1,
                selector=k8s.meta.v1.LabelSelectorArgs(match_labels=rotulos),
                template=k8s.core.v1.PodTemplateSpecArgs(
                    metadata=k8s.meta.v1.ObjectMetaArgs(labels=rotulos),
                    spec=k8s.core.v1.PodSpecArgs(
                        termination_grace_period_seconds=5,
                        containers=[
                            k8s.core.v1.ContainerArgs(
                                name="web",
                                image=image,
                                ports=[
                                    k8s.core.v1.ContainerPortArgs(container_port=80)
                                ],
                                resources=k8s.core.v1.ResourceRequirementsArgs(
                                    requests={
                                        "cpu": cpu_request,
                                        "memory": memory_request,
                                    },
                                    limits={"cpu": cpu_limit, "memory": memory_limit},
                                ),
                                readiness_probe=k8s.core.v1.ProbeArgs(
                                    http_get=k8s.core.v1.HTTPGetActionArgs(
                                        path="/", port=80
                                    ),
                                    initial_delay_seconds=1,
                                    period_seconds=2,
                                ),
                            )
                        ],
                    ),
                ),
            ),
            opts=filhos,
        )

        self.service = k8s.core.v1.Service(
            f"{nome}-service",
            metadata=k8s.meta.v1.ObjectMetaArgs(
                name=nome,
                namespace=namespace,
                labels=rotulos,
                annotations=anotacoes,
            ),
            spec=k8s.core.v1.ServiceSpecArgs(
                selector=rotulos,
                ports=[k8s.core.v1.ServicePortArgs(port=80, target_port=80)],
            ),
            opts=filhos,
        )

        self.register_outputs(
            {
                "deploymentName": self.deployment.metadata.name,
                "serviceName": self.service.metadata.name,
            }
        )


modules = [WebModule(nome) for nome in nomes]

pulumi.export("namespace", namespace)
pulumi.export("unitCount", unit_count)
pulumi.export("moduleNames", nomes)
