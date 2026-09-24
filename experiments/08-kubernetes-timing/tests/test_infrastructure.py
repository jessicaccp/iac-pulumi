"""Testes do programa, sem cluster e sem CLI.

Fora do CLI do Pulumi o runtime informa project="project", e por isso as chaves do
PULUMI_CONFIG levam esse prefixo. As assercoes ficam dentro de
@pulumi.runtime.test porque o registro de recursos e assincrono: uma leitura do
registrador fora dele roda antes de existir qualquer recurso e passa sem verificar
nada.

O valor maior destes testes e a garantia de seguranca: nenhum recurso fora do
namespace do experimento, nenhum recurso de escopo de cluster e nenhum pod sem
limite de CPU e memoria. Verificado em docs/04-tempos.md.
"""

import asyncio
import json
import os
import unittest

import pulumi
from pulumi.runtime import MockCallArgs, MockResourceArgs, Mocks, set_mocks

CONFIG = {
    "project:namespace": "bench-teste",
    "project:unitCount": "3",
    "project:namePrefix": "bench-web",
    "project:skipAwait": "true",
}

DEPLOYMENT = "kubernetes:apps/v1:Deployment"
SERVICE = "kubernetes:core/v1:Service"
NAMESPACE = "bench-teste"


class RecordingMocks(Mocks):
    """Registra os recursos pedidos pelo programa e devolve identificadores sinteticos."""

    def __init__(self) -> None:
        self.resources: list[tuple[str, str, dict, bool]] = []

    def new_resource(self, args: MockResourceArgs) -> tuple[str, dict]:
        self.resources.append((args.typ, args.name, args.inputs, args.custom))
        metadados = dict(args.inputs.get("metadata") or {})
        metadados["name"] = metadados.get("name") or args.name
        return f"{args.name}-id", {"id": f"{args.name}-id", "metadata": metadados}

    def call(self, args: MockCallArgs) -> dict:
        return {}

    def custom(self) -> list[tuple[str, str, dict]]:
        """Recursos que existem no provedor, sem os componentes do proprio programa."""
        return [r for r in self.resources if r[3]]

    def of_type(self, typ: str) -> list[tuple[str, str, dict]]:
        return [r for r in self.custom() if r[0] == typ]


mocks = RecordingMocks()
os.environ["PULUMI_CONFIG"] = json.dumps(CONFIG)

# O Python 3.14 deixou de criar event loop implicitamente, e o runtime do Pulumi
# registra a stack na importacao esperando um loop corrente nesta thread.
asyncio.set_event_loop(asyncio.new_event_loop())

set_mocks(mocks)

import infrastructure  # noqa: E402  -- precisa vir depois do set_mocks


def settled() -> "pulumi.Output[list[str]]":
    """Resolve quando todos os deployments foram registrados."""
    return pulumi.Output.all(*[modulo.deployment.id for modulo in infrastructure.modules])


class SegurancaTest(unittest.TestCase):
    @pulumi.runtime.test
    def test_registra_os_recursos_esperados(self) -> None:
        def check(_: list[str]) -> None:
            # Protege contra assercao vacua: falha alto se nada foi registrado.
            self.assertEqual(len(mocks.of_type(DEPLOYMENT)), 3)
            self.assertEqual(len(mocks.of_type(SERVICE)), 3)

        return settled().apply(check)

    @pulumi.runtime.test
    def test_nenhum_recurso_de_escopo_de_cluster(self) -> None:
        def check(_: list[str]) -> None:
            tipos = {typ for typ, _, _, _ in mocks.custom()}
            self.assertEqual(tipos, {DEPLOYMENT, SERVICE})

        return settled().apply(check)

    @pulumi.runtime.test
    def test_todo_recurso_esta_no_namespace_do_experimento(self) -> None:
        def check(_: list[str]) -> None:
            for typ, nome, inputs, _ in mocks.custom():
                metadados = inputs["metadata"]
                self.assertEqual(
                    metadados["namespace"], NAMESPACE, f"{typ} {nome} fora do namespace"
                )

        return settled().apply(check)

    @pulumi.runtime.test
    def test_todo_container_declara_limites_e_pedidos(self) -> None:
        def check(_: list[str]) -> None:
            for _, nome, inputs, _ in mocks.of_type(DEPLOYMENT):
                container = inputs["spec"]["template"]["spec"]["containers"][0]
                recursos = container["resources"]
                for chave in ("cpu", "memory"):
                    self.assertIn(chave, recursos["limits"], f"{nome} sem limite de {chave}")
                    self.assertIn(
                        chave, recursos["requests"], f"{nome} sem pedido de {chave}"
                    )

        return settled().apply(check)

    @pulumi.runtime.test
    def test_a_remocao_nao_espera_o_periodo_padrao_de_graca(self) -> None:
        def check(_: list[str]) -> None:
            for _, nome, inputs, _ in mocks.of_type(DEPLOYMENT):
                segundo = inputs["spec"]["template"]["spec"][
                    "terminationGracePeriodSeconds"
                ]
                self.assertEqual(segundo, 5, f"{nome} com periodo de graca diferente")

        return settled().apply(check)


    @pulumi.runtime.test
    def test_a_espera_desligada_vale_para_deployment_e_service(self) -> None:
        def check(_: list[str]) -> None:
            for typ, nome, inputs, _ in mocks.custom():
                anotacoes = inputs["metadata"].get("annotations") or {}
                self.assertEqual(
                    anotacoes.get("pulumi.com/skipAwait"),
                    "true",
                    f"{typ} {nome} ainda espera o provedor",
                )

        return settled().apply(check)


class NamespaceTest(unittest.TestCase):
    def test_a_anotacao_da_espera_so_existe_quando_desligada(self) -> None:
        self.assertIsNone(infrastructure.anotacoes_da_espera(False))
        self.assertEqual(
            infrastructure.anotacoes_da_espera(True),
            {"pulumi.com/skipAwait": "true"},
        )
    def test_recusa_namespace_de_terceiros(self) -> None:
        for proibido in ("default", "kube-system", "teste", "bench", "Bench-teste"):
            with self.assertRaises(ValueError, msg=f"aceitou {proibido!r}"):
                infrastructure.validar_namespace(proibido)

    def test_aceita_namespace_do_experimento(self) -> None:
        self.assertEqual(infrastructure.validar_namespace("bench-larces"), "bench-larces")

    def test_o_namespace_em_uso_foi_validado(self) -> None:
        self.assertEqual(infrastructure.namespace, NAMESPACE)


if __name__ == "__main__":
    unittest.main()
