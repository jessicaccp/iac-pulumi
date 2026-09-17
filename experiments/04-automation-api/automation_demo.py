"""Comanda uma implantação do Pulumi a partir do Python, em vez do CLI.

Útil quando um agente precisa executar uma atualização e analisar o resultado no
mesmo processo: os retornos são tipados, e não texto de terminal.

Verificação registrada em docs/01-verificacoes.md.
"""

import pulumi
import pulumi_docker as docker
from pulumi import automation as auto

PROJECT = "automation-api-demo"
STACK = "dev"
HOST_PORT = 9600


def program() -> None:
    # keep_locally: o daemon Docker é compartilhado, mas o estado do Pulumi é por
    # stack, então remover a imagem aqui pode quebrar containers de outro stack.
    image = docker.RemoteImage("nginx-image", name="nginx:1.27-alpine", keep_locally=True)
    container = docker.Container(
        "web",
        image=image.image_id,
        name="pulumi-auto-web",
        ports=[docker.ContainerPortArgs(internal=80, external=HOST_PORT)],
    )
    pulumi.export("url", pulumi.Output.concat("http://localhost:", str(HOST_PORT)))
    pulumi.export("container_id", container.id)


def on_event(event: auto.EngineEvent) -> None:
    if event.resource_pre_event is not None:
        metadata = event.resource_pre_event.metadata
        print(f"  [event] {metadata.op} {metadata.urn.split('::')[-1]}")
    elif event.diagnostic_event is not None and event.diagnostic_event.severity == "error":
        print(f"  [error] {event.diagnostic_event.message.strip()}")


def main() -> None:
    stack = auto.create_or_select_stack(stack_name=STACK, project_name=PROJECT, program=program)

    preview = stack.preview(on_event=on_event)
    print("resumo de mudanças do preview:", dict(preview.change_summary))

    update = stack.up(on_event=on_event)
    print("resultado da atualização:", update.summary.result)
    print("mudanças por recurso:", dict(update.summary.resource_changes))
    print("outputs (tipados):")
    for key, output in update.outputs.items():
        print(f"  {key} = {output.value} (secret={output.secret})")

    destroy = stack.destroy(on_event=on_event)
    print("resultado da remoção:", destroy.summary.result)


if __name__ == "__main__":
    main()
