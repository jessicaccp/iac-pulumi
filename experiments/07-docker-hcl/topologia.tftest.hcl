mock_provider "docker" {}

run "topologia" {
  command = plan

  assert {
    condition     = docker_network.metrics_net.name == "tofu-study-metrics-net"
    error_message = "nome da rede inesperado"
  }

  assert {
    condition     = docker_container.server.name == "tofu-study-metrics-server"
    error_message = "nome do servidor inesperado"
  }

  assert {
    condition     = length(docker_container.client.command) == 3
    error_message = "comando do cliente inesperado"
  }
}
