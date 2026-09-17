"""Mede a rede e os containers criados por este experimento.

O Pulumi não participa daqui: ele construiu a rede, mas as métricas de execução
vivem no sistema. Quatro fontes, cada uma respondendo a uma pergunta:

  1. /sys/class/net/<iface>/statistics  -> contadores exatos de bytes e pacotes por container
  2. docker stats                       -> CPU e memória por container
  3. log de acesso do nginx             -> requisições efetivamente atendidas, contadas pela aplicação
  4. docker network inspect             -> quem está ligado à rede, e com qual endereço

Duas amostras separadas por um intervalo produzem taxas, em vez de totais acumulados.

Uso: python metrics.py [--interval 5] [--json]
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from typing import Any

SERVER = "pulumi-study-metrics-server"
CLIENT = "pulumi-study-metrics-client"
NETWORK = "pulumi-study-metrics-net"
INTERFACE = "eth0"
COUNTERS = ("rx_bytes", "tx_bytes", "rx_packets", "tx_packets", "rx_errors", "tx_errors")
# As mensagens de inicialização do próprio nginx vão para o mesmo fluxo de log,
# então uma requisição é reconhecida pelo formato dos primeiros campos do log
# combinado.
ACCESS_LOG_LINE = re.compile(r"^\S+ - - \[")


def run(*args: str) -> str:
    """Executa um comando e devolve sua saída padrão, falhando com o stderr."""
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {result.stderr.strip()}")
    return result.stdout


def interface_counters(container: str) -> dict[str, int]:
    counters = {}
    for name in COUNTERS:
        path = f"/sys/class/net/{INTERFACE}/statistics/{name}"
        counters[name] = int(run("docker", "exec", container, "cat", path).strip())
    return counters


def container_stats() -> dict[str, dict[str, str]]:
    raw = run("docker", "stats", "--no-stream", "--format", "json", SERVER, CLIENT)
    return {row["Name"]: row for row in (json.loads(line) for line in raw.splitlines() if line.strip())}


def requests_served() -> int:
    """Conta as linhas do log de acesso do nginx, que tem uma linha por requisição."""
    lines = run("docker", "logs", SERVER).splitlines()
    return sum(1 for line in lines if ACCESS_LOG_LINE.match(line))


def network_members() -> list[dict[str, str]]:
    inspect = json.loads(run("docker", "network", "inspect", NETWORK))[0]
    return [
        {"name": entry["Name"], "ipv4": entry.get("IPv4Address", ""), "mac": entry.get("MacAddress", "")}
        for entry in inspect.get("Containers", {}).values()
    ]


def sample() -> tuple[float, dict[str, Any]]:
    """Lê cada contador uma vez e informa em que instante fez isso.

    O instante é registrado antes dos contadores porque ler todos eles custa cerca
    de dois segundos, com uma dúzia de chamadas "docker exec", e uma taxa dividida
    pelo intervalo pedido, em vez do tempo realmente decorrido, sai errada.
    """
    timestamp = time.monotonic()
    counters = {name: interface_counters(name) for name in (SERVER, CLIENT)}
    return timestamp, {
        "counters": counters,
        "requests": requests_served(),
        "stats": container_stats(),
    }


def rates(before: dict[str, Any], after: dict[str, Any], seconds: float) -> dict[str, Any]:
    report: dict[str, Any] = {"interval_seconds": seconds, "containers": {}, "requests": {}}
    for name in (SERVER, CLIENT):
        first, second = before["counters"][name], after["counters"][name]
        delta = {key: second[key] - first[key] for key in COUNTERS}
        report["containers"][name] = {
            "total": second,
            "delta": delta,
            "per_second": {key: round(value / seconds, 2) for key, value in delta.items()},
            "cpu_percent": after["stats"][name]["CPUPerc"],
            "memory_usage": after["stats"][name]["MemUsage"],
            "network_io_reported_by_docker": after["stats"][name]["NetIO"],
        }
    served = after["requests"] - before["requests"]
    report["requests"] = {
        "total_served": after["requests"],
        "served_in_interval": served,
        "per_second": round(served / seconds, 2),
    }
    return report


def render(report: dict[str, Any], members: list[dict[str, str]]) -> str:
    lines = [f"Rede {NETWORK}, {len(members)} membros:"]
    for member in members:
        lines.append(f"  {member['name']:30} {member['ipv4']:20} {member['mac']}")
    lines.append("")
    lines.append(f"Janela real medida: {report['interval_seconds']:.2f}s (o intervalo pedido mais o custo de ler os contadores)")
    lines.append("")
    header = f"{'container':30} {'rx B/s':>10} {'tx B/s':>10} {'rx pkt/s':>9} {'tx pkt/s':>9} {'erros':>6} {'cpu':>7} {'mem':>16}"
    lines.append(header)
    for name, data in report["containers"].items():
        rate = data["per_second"]
        errors = data["delta"]["rx_errors"] + data["delta"]["tx_errors"]
        lines.append(
            f"{name:30} {rate['rx_bytes']:10.1f} {rate['tx_bytes']:10.1f} "
            f"{rate['rx_packets']:9.2f} {rate['tx_packets']:9.2f} {errors:6d} "
            f"{data['cpu_percent']:>7} {data['memory_usage']:>16}"
        )
    requests = report["requests"]
    lines.append("")
    lines.append(
        f"Requisições servidas pelo nginx: {requests['served_in_interval']} no intervalo "
        f"({requests['per_second']}/s), {requests['total_served']} desde que o container subiu"
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", type=float, default=5.0, help="segundos entre as duas amostras")
    parser.add_argument("--json", action="store_true", help="imprime o resultado em JSON")
    args = parser.parse_args()

    try:
        members = network_members()
        started, before = sample()
        first_members = {member["name"] for member in members}
        if {SERVER, CLIENT} - first_members:
            missing = ", ".join(sorted({SERVER, CLIENT} - first_members))
            raise RuntimeError(f"containers fora da rede: {missing}")
    except RuntimeError as error:
        print(f"não consegui medir: {error}", file=sys.stderr)
        print("rode 'pulumi up' neste diretório primeiro.", file=sys.stderr)
        return 1

    time.sleep(args.interval)
    finished, after = sample()
    report = rates(before, after, finished - started)

    if args.json:
        print(json.dumps({"network": NETWORK, "members": members, **report}, indent=2))
    else:
        print(render(report, members))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
