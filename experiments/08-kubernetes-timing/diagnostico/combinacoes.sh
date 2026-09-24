#!/usr/bin/env bash
# Testa a ultima diferenca entre o diagnostico e o experimento: o paralelismo.
#
# O diagnostico com os campos todos, componentes e varias unidades passa em 12
# segundos quando nao recebe --parallel, e o experimento travou com --parallel 2 e
# com --parallel 10. Estes casos variam o paralelismo com a mesma topologia.
#
# Uso: ./combinacoes.sh [namespace]
#
# Precisa da credencial de administrador e de um stack ja criado no projeto.

set -uo pipefail

NAMESPACE="${1:-bench-larces}"
LIMITE=90

if [ -n "${KUBECONFIG:-}" ]; then
  echo "aviso: KUBECONFIG esta definido e sera usado: $KUBECONFIG"
  echo "para este diagnostico, o esperado e a credencial de administrador."
  echo
fi

limpar() {
  kubectl delete deploy,svc --all -n "$NAMESPACE" >/dev/null 2>&1
  pulumi destroy --skip-preview --yes >/dev/null 2>&1
}

rodar() {
  local nome="$1" unidades="$2" componente="$3" paralelismo="$4"
  local inicio fim extra=()

  pulumi config set namespace "$NAMESPACE" >/dev/null
  pulumi config set sonda true >/dev/null
  pulumi config set limites true >/dev/null
  pulumi config set graca true >/dev/null
  pulumi config set servico true >/dev/null
  pulumi config set quantidade "$unidades" >/dev/null
  pulumi config set componente "$componente" >/dev/null
  [ -n "$paralelismo" ] && extra=(--parallel "$paralelismo")

  limpar
  inicio=$(date +%s)
  if timeout "$LIMITE" pulumi up --skip-preview --yes --color never "${extra[@]}" \
      >"/tmp/diag-$nome.log" 2>&1; then
    fim=$(date +%s)
    printf 'unidades=%-2s componente=%-5s paralelismo=%-4s -> %ss\n' \
      "$unidades" "$componente" "${paralelismo:-padrao}" "$((fim - inicio))"
  else
    printf 'unidades=%-2s componente=%-5s paralelismo=%-4s -> TRAVOU (log /tmp/diag-%s.log)\n' \
      "$unidades" "$componente" "${paralelismo:-padrao}" "$nome"
  fi
  limpar
}

rodar controle            2  false "" 
rodar soltas-paralelo-2   2  false 2
rodar comp-2-padrao       2  true  ""
rodar comp-2-paralelo-2   2  true  2
rodar comp-2-paralelo-1   2  true  1
rodar comp-10-paralelo-10 10 true  10

echo
echo "logs em /tmp/diag-*.log"
