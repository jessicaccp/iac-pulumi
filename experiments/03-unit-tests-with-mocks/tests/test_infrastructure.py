"""Testes unitários do infrastructure.py, sem daemon Docker e sem CLI.

Fora do CLI do Pulumi, o runtime informa project="project" e stack="stack", então
as chaves do PULUMI_CONFIG precisam usar o prefixo "project:".

O registro de recursos é assíncrono, e uma asserção que lê o registrador de mocks
a partir de um método de teste comum roda antes de qualquer recurso existir e passa
sem verificar nada. Por isso toda asserção aqui está dentro de
@pulumi.runtime.test e retorna um future que só resolve depois do registro dos
recursos de interesse.
"""

import json
import os
import unittest

import pulumi
from pulumi.runtime import MockCallArgs, MockResourceArgs, Mocks, set_mocks

CONFIG = {
    "project:serviceCount": "3",
    "project:basePort": "9500",
    "project:imageName": "nginx:1.27-alpine",
}

IMAGE = "docker:index/remoteImage:RemoteImage"
NETWORK = "docker:index/network:Network"
CONTAINER = "docker:index/container:Container"


class RecordingMocks(Mocks):
    """Registra todo recurso pedido pelo programa e devolve identificadores sintéticos."""

    def __init__(self) -> None:
        self.resources: list[tuple[str, str, dict]] = []

    def new_resource(self, args: MockResourceArgs) -> tuple[str, dict]:
        self.resources.append((args.typ, args.name, args.inputs))
        identifier = f"{args.name}-id"
        outputs = {"id": identifier}
        if args.typ == IMAGE:
            # O programa lê image_id deste recurso. O mock precisa devolver toda
            # output property que o programa consome: o que faltar continua
            # desconhecido e é descartado em silêncio dos inputs registrados.
            outputs["imageId"] = identifier
        return identifier, outputs

    def call(self, args: MockCallArgs) -> dict:
        return {}

    def of_type(self, typ: str) -> list[tuple[str, str, dict]]:
        return [r for r in self.resources if r[0] == typ]


mocks = RecordingMocks()
os.environ["PULUMI_CONFIG"] = json.dumps(CONFIG)
set_mocks(mocks)

import infrastructure  # noqa: E402  -- precisa vir depois do set_mocks


def settled() -> "pulumi.Output[list[str]]":
    """Resolve quando a imagem, a rede e todos os containers foram registrados."""
    return pulumi.Output.all(*[container.id for container in infrastructure.containers])


class InfrastructureTest(unittest.TestCase):
    @pulumi.runtime.test
    def test_registers_the_expected_resource_count(self) -> None:
        def check(_: list[str]) -> None:
            # Protege contra asserção vácua: falha alto se nada foi registrado.
            self.assertEqual(len(mocks.resources), 5)

        return settled().apply(check)

    @pulumi.runtime.test
    def test_creates_one_container_per_service(self) -> None:
        def check(_: list[str]) -> None:
            self.assertEqual(len(mocks.of_type(CONTAINER)), 3)

        return settled().apply(check)

    @pulumi.runtime.test
    def test_creates_exactly_one_network(self) -> None:
        def check(_: list[str]) -> None:
            self.assertEqual(len(mocks.of_type(NETWORK)), 1)

        return settled().apply(check)

    @pulumi.runtime.test
    def test_container_ports_follow_base_port(self) -> None:
        def check(_: list[str]) -> None:
            # O registro roda em paralelo, então a ordem do registrador não é a do
            # programa, e inteiros voltam como float na serialização.
            ports = sorted(
                int(inputs["ports"][0]["external"])
                for _, _, inputs in mocks.of_type(CONTAINER)
            )
            self.assertEqual(ports, [9500, 9501, 9502])

        return settled().apply(check)

    @pulumi.runtime.test
    def test_every_container_is_attached_to_the_network(self) -> None:
        def check(_: list[str]) -> None:
            for _, _, inputs in mocks.of_type(CONTAINER):
                self.assertEqual(len(inputs["networksAdvanced"]), 1)

        return settled().apply(check)

    @pulumi.runtime.test
    def test_container_image_comes_from_the_image_resource(self) -> None:
        def check(_: list[str]) -> None:
            for _, _, inputs in mocks.of_type(CONTAINER):
                self.assertEqual(inputs["image"], "nginx-image-id")

        return settled().apply(check)
    @pulumi.runtime.test
    def test_exported_ids_resolve(self) -> None:
        def check(ids: list[str]) -> None:
            self.assertEqual(ids, ["web-0-id", "web-1-id", "web-2-id"])

        return settled().apply(check)


if __name__ == "__main__":
    unittest.main()
