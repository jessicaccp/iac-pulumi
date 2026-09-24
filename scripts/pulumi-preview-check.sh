#!/usr/bin/env bash
# Smoke test: proves that the Pulumi Kubernetes provider reaches the cluster,
# without creating anything. Only "preview" is used, never "up" or "destroy".
#
# Usage: ./scripts/pulumi-preview-check.sh [namespace]

set -uo pipefail

NAMESPACE="${1:-bench-preview}"
ARQUIVO_DE_AMBIENTE="${PULUMI_BENCH_ENV:-$HOME/.pulumi/bench-env.sh}"

if [ ! -f "$ARQUIVO_DE_AMBIENTE" ]; then
  echo "ambiente nao encontrado em $ARQUIVO_DE_AMBIENTE"
  echo "rode antes: ./scripts/setup-pulumi.sh"
  exit 1
fi
# shellcheck disable=SC1090
source "$ARQUIVO_DE_AMBIENTE"

if ! command -v kubectl >/dev/null 2>&1; then
  echo "kubectl nao esta no PATH"
  exit 1
fi
echo "contexto atual: $(kubectl config current-context 2>/dev/null || echo nenhum)"
echo "namespace do teste: $NAMESPACE (so leitura, nada e criado)"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Estado em diretorio temporario: a serie do experimento nao e tocada.
export PULUMI_BACKEND_URL="file://$TMP/state"
mkdir -p "$TMP/state"

cat > "$TMP/Pulumi.yaml" <<'EOF'
name: preview-check
runtime:
  name: python
description: provider connectivity check
EOF

cat > "$TMP/__main__.py" <<'EOF'
"""Declares one ConfigMap so the provider has something to plan."""
import pulumi
import pulumi_kubernetes as k8s

namespace = pulumi.Config().get("namespace") or "bench-preview"

k8s.core.v1.ConfigMap(
    "preview-check",
    metadata=k8s.meta.v1.ObjectMetaArgs(name="preview-check", namespace=namespace),
    data={"aviso": "somente preview, nada e criado no cluster"},
)
EOF

cd "$TMP" || exit 1
pulumi stack init check >/dev/null 2>&1
pulumi config set namespace "$NAMESPACE" >/dev/null

echo
echo "== preview (primeira vez baixa o plugin do provider)"
if pulumi preview --stack check --non-interactive 2>&1 | tail -20; then
  echo
  echo "resultado: o provider alcançou o cluster e o plano foi calculado."
else
  echo
  echo "resultado: falhou. causas comuns:"
  echo "  - kubeconfig sem permissao para o namespace $NAMESPACE"
  echo "  - API do cluster inalcancavel desta maquina (teste: kubectl get nodes)"
  echo "  - plugin do provider nao baixou (sem saida de rede)"
  exit 1
fi
