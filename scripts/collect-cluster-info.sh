#!/usr/bin/env bash
# Read-only collection of what the benchmark design needs from the cluster.
# Nothing here creates, changes, restarts or deletes a resource.
#
# Usage: ./scripts/collect-cluster-info.sh [arquivo-de-saida]

set -u

OUT="${1:-$HOME/bench/cluster-info-$(date +%F-%H%M).txt}"
mkdir -p "$(dirname "$OUT")"

{
  echo "=== cluster em $(hostname), $(date -Is)"

  echo; echo "== ferramentas desta maquina"
  for c in kubectl pulumi python3 curl; do printf '%s=%s ' "$c" "$(command -v "$c" || echo ausente)"; done; echo
  kubectl version 2>/dev/null | grep -E "Version" | head -2
  python3 -V 2>&1
  df -h "$HOME" | tail -1

  echo; echo "== acesso"
  kubectl config current-context 2>/dev/null || echo "sem contexto"
  kubectl config view --minify -o jsonpath='{.contexts[0].context.namespace}{"\n"}' 2>/dev/null
  kubectl auth can-i --list 2>/dev/null | head -4

  echo; echo "== nos"
  kubectl get nodes 2>/dev/null
  kubectl get nodes -o custom-columns='NODE:.metadata.name,CPU:.status.allocatable.cpu,MEM:.status.allocatable.memory,PODS:.status.allocatable.pods,TAINTS:.spec.taints[*].key' 2>/dev/null

  echo; echo "== o que terceiros ja reservaram por no"
  kubectl describe nodes 2>/dev/null | grep -A9 "Allocated resources" | head -60

  echo; echo "== relogio desta maquina"
  echo "local: $(date -Is)"
  echo "externa: $(curl -sI https://get.pulumi.com 2>/dev/null | grep -i '^date:' | head -1)"
  timedatectl 2>/dev/null | head -3

  echo; echo "== uso real por no"
  for N in $(kubectl get nodes --no-headers -o custom-columns=':.metadata.name' 2>/dev/null); do
    echo "--- $N"
    kubectl get --raw "/api/v1/nodes/$N/proxy/stats/summary" 2>/dev/null | python3 -c '
import json, sys
try:
    dados = json.load(sys.stdin)
except Exception:
    print("  sem resposta do kubelet"); raise SystemExit
no = dados.get("node", {})
def gib(valor):
    return round(valor / 1024**3, 1)
print("  cpu em uso: %.2f nucleos" % (no.get("cpu", {}).get("usageNanoCores", 0) / 1e9))
print("  memoria em uso: %.1f GiB" % gib(no.get("memory", {}).get("workingSetBytes", 0)))
print("  disco raiz: %.1f GiB usados de %.1f GiB" % (gib(no.get("fs", {}).get("usedBytes", 0)), gib(no.get("fs", {}).get("capacityBytes", 0))))
'
  done

  echo; echo "== namespaces e quem ocupa o cluster"
  kubectl get ns 2>/dev/null
  kubectl get pods -A --no-headers 2>/dev/null | awk '{print $1}' | sort | uniq -c | sort -rn | head -20

  echo; echo "== teto por namespace"
  kubectl get resourcequota,limitrange -A 2>/dev/null

  echo; echo "== storage e entrada"
  kubectl get storageclass 2>/dev/null
  kubectl get ingressclass 2>/dev/null
  kubectl get svc -n traefik 2>/dev/null

  echo; echo "== registry interno"
  kubectl get svc,endpoints -n registry -o wide 2>/dev/null
  kubectl get pods -n registry 2>/dev/null

  echo; echo "== metrics-server"
  kubectl get deploy -n kube-system 2>/dev/null

  echo; echo "== saida de rede desta maquina"
  for u in https://get.pulumi.com https://pypi.org/simple/ https://registry-1.docker.io/v2/; do
    printf '%s -> %s\n' "$u" "$(timeout 8 curl -s -o /dev/null -w '%{http_code}' "$u" 2>/dev/null || echo falha)"
  done
  env | grep -i proxy || echo "sem proxy no ambiente"

  echo; echo "=== fim"
} 2>&1 | tee "$OUT"

echo
echo "saida salva em: $OUT"
