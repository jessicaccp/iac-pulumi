"""Coloca uma rede no ar: uma rede, um servidor e um gerador de tráfego.

O Pulumi cria a rede e os containers. Ele não coleta métricas de execução; o
metrics.py lê essas métricas do sistema depois.

Verificação registrada em docs/01-verificacoes.md.
"""

import pulumi
import pulumi_docker as docker

config = pulumi.Config()
network_name = config.get("networkName") or "pulumi-study-metrics-net"
server_name = config.get("serverName") or "pulumi-study-metrics-server"
client_name = config.get("clientName") or "pulumi-study-metrics-client"

network = docker.Network("metrics-net", name=network_name)

# keep_locally porque o daemon Docker é compartilhado com os outros experimentos:
# remover uma imagem compartilhada aqui quebraria containers de outro stack.
server_image = docker.RemoteImage("nginx-image", name="nginx:1.27-alpine", keep_locally=True)
client_image = docker.RemoteImage("busybox-image", name="busybox:1.37", keep_locally=True)

# Sem porta publicada: o servidor só é alcançável de dentro da rede, e é isso que
# torna esta rede privada em vez de exposta ao host.
server = docker.Container(
    "server",
    image=server_image.image_id,
    name=server_name,
    networks_advanced=[docker.ContainerNetworksAdvancedArgs(name=network.name)],
)

# Uma requisição a cada 0,2s, indefinidamente, o que mantém a taxa constante em
# vez de em rajadas. O DNS interno do Docker resolve o servidor pelo nome do
# container, então nenhum endereço IP aparece aqui.
traffic_script = (
    "while true; do "
    f"wget -q -O /dev/null http://{server_name}/; "
    "sleep 0.2; "
    "done"
)

client = docker.Container(
    "client",
    image=client_image.image_id,
    name=client_name,
    networks_advanced=[docker.ContainerNetworksAdvancedArgs(name=network.name)],
    command=["sh", "-c", traffic_script],
)

pulumi.export("network_name", network.name)
pulumi.export("network_id", network.id)
pulumi.export("server_name", server_name)
pulumi.export("client_name", client_name)
pulumi.export("server_is_running", server.name)
