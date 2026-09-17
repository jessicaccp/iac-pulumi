variable "greeting" {
  type      = string
  sensitive = true
  default   = "hello from a sensitive variable"
}

resource "docker_network" "metrics_net" {
  name = "tofu-study-metrics-net"
}

resource "docker_image" "server" {
  name         = "nginx:1.27-alpine"
  keep_locally = true
}

resource "docker_image" "client" {
  name         = "busybox:1.37"
  keep_locally = true
}

resource "docker_container" "server" {
  name  = "tofu-study-metrics-server"
  image = docker_image.server.image_id

  networks_advanced {
    name = docker_network.metrics_net.name
  }

  env = ["GREETING=${var.greeting}"]
}

resource "docker_container" "client" {
  name  = "tofu-study-metrics-client"
  image = docker_image.client.image_id

  networks_advanced {
    name = docker_network.metrics_net.name
  }

  command = [
    "sh", "-c",
    "while true; do wget -q -O /dev/null http://tofu-study-metrics-server/; sleep 0.2; done"
  ]
}

output "network_name" {
  value = docker_network.metrics_net.name
}

output "server_name" {
  value = docker_container.server.name
}

output "client_name" {
  value = docker_container.client.name
}
