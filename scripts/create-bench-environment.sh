#!/usr/bin/env bash
# Prepara o namespace do experimento no cluster: quota, limites e acesso restrito.
#
# Uso:
#   ./scripts/create-bench-environment.sh bench-larces              # valida, nao cria nada
#   ./scripts/create-bench-environment.sh bench-larces --only-yaml  # so mostra o arquivo do pedido
#   ./scripts/create-bench-environment.sh bench-larces --apply      # cria de verdade
#   ./scripts/create-bench-environment.sh bench-larces --renew-token # so renova o kubeconfig restrito
#   ./scripts/create-bench-environment.sh bench-larces --remove     # desfaz tudo o que criou
#
# Todos os modos que falam com o cluster precisam da credencial de administrador.
# Com o KUBECONFIG restrito exportado eles falham, e o script avisa antes de tentar.
#
# Por padrao o modo e a validacao do lado do servidor, que responde o que seria
# criado sem criar. A aplicacao de verdade e decisao de quem administra o cluster.
#
# Requer credencial de administrador, porque cria Namespace, ServiceAccount, Role
# e RoleBinding. Nada fora do namespace do experimento e criado, e nada existente
# e alterado.

set -uo pipefail

PREFIXO="bench-"
NAMESPACE="${1:-}"
MODO="${2:-}"

uso() {
  echo "uso: $0 <namespace comecando com $PREFIXO> [--only-yaml|--apply|--renew-token|--remove]"
  exit 1
}

exigir_credencial_de_administracao() {
  local resposta
  # A ultima linha e a resposta: o kubectl avisa antes que o recurso nao tem escopo
  # de namespace, e comparar a saida inteira reprovaria uma credencial valida.
  resposta="$(kubectl auth can-i create namespaces 2>&1 | tail -n1)"
  if [ "$resposta" = "yes" ]; then
    return 0
  fi
  echo "esta etapa precisa da credencial de administrador do cluster."
  echo "a credencial ativa respondeu: $resposta"
  echo "se o KUBECONFIG restrito do experimento esta exportado, volte para a sua:"
  echo "  unset KUBECONFIG"
  exit 1
}

remover() {
  local so_namespace resto kubeconfig
  so_namespace="$(mktemp)"
  resto="$(mktemp)"
  kubeconfig="$HOME/bench/kubeconfig-$NAMESPACE.yaml"

  # Ordem inversa: primeiro o conteudo, depois o namespace. O delete do namespace
  # levaria tudo junto, mas assim a saida fica limpa e sem NotFound.
  awk '/^---$/{exit} {print}' "$ARQUIVO" > "$so_namespace"
  awk 'feito{print} /^---$/{feito=1}' "$ARQUIVO" > "$resto"

  echo "== removendo o conteudo do namespace"
  kubectl delete -f "$resto" --ignore-not-found=true || true
  echo
  echo "== removendo o namespace"
  kubectl delete -f "$so_namespace" --ignore-not-found=true || true
  rm -f "$so_namespace" "$resto"

  if [ -f "$kubeconfig" ]; then
    rm -f "$kubeconfig"
    echo
    echo "kubeconfig local removido: $kubeconfig"
  fi
  echo
  echo "conferir que nada sobrou do experimento:"
  echo "  kubectl get ns | grep $PREFIXO || echo 'nenhum namespace do experimento'"
  echo "  kubectl get pods -A | grep $PREFIXO || echo 'nenhum pod do experimento'"
}

gerar_kubeconfig() {
  local destino="$HOME/bench/kubeconfig-$NAMESPACE.yaml"
  local servidor ca token
  servidor="$(kubectl config view --minify -o jsonpath='{.clusters[0].cluster.server}')"
  ca="$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')"
  if ! token="$(kubectl create token bench-runner -n "$NAMESPACE" --duration=24h)"; then
    echo "nao consegui criar o token da ServiceAccount"
    return 1
  fi
  cat > "$destino" <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: cluster
    cluster:
      server: $servidor
      certificate-authority-data: $ca
contexts:
  - name: $NAMESPACE
    context:
      cluster: cluster
      user: bench-runner
      namespace: $NAMESPACE
current-context: $NAMESPACE
users:
  - name: bench-runner
    user:
      token: $token
EOF
  chmod 600 "$destino"
  echo
  echo "kubeconfig restrito ao namespace: $destino"
  echo "use na serie com: export KUBECONFIG=$destino"
  echo "o token vale 24 horas, depois e preciso gerar outro"

  echo
  echo "== alcance da credencial restrita"
  printf '  fora do namespace:   '
  KUBECONFIG="$destino" kubectl auth can-i create pods --all-namespaces
  printf '  dentro do namespace: '
  KUBECONFIG="$destino" kubectl auth can-i create deployments -n "$NAMESPACE"
  echo "  esperado: no fora, yes dentro"
}

[ -n "$NAMESPACE" ] || uso
case "$NAMESPACE" in
  "$PREFIXO"*) ;;
  *) echo "o namespace precisa comecar com $PREFIXO"; exit 1 ;;
esac

ARQUIVO="$HOME/bench/ambiente-$NAMESPACE.yaml"
mkdir -p "$HOME/bench"

cat > "$ARQUIVO" <<EOF
apiVersion: v1
kind: Namespace
metadata:
  name: $NAMESPACE
  labels:
    purpose: iac-timing-benchmark
---
apiVersion: v1
kind: ResourceQuota
metadata:
  name: bench-quota
  namespace: $NAMESPACE
spec:
  hard:
    pods: "150"
    requests.cpu: "8"
    requests.memory: 6Gi
    limits.cpu: "16"
    limits.memory: 12Gi
---
apiVersion: v1
kind: LimitRange
metadata:
  name: bench-limits
  namespace: $NAMESPACE
spec:
  limits:
    - type: Container
      defaultRequest:
        cpu: 50m
        memory: 32Mi
      default:
        cpu: 100m
        memory: 64Mi
      max:
        cpu: "1"
        memory: 512Mi
---
apiVersion: v1
kind: ServiceAccount
metadata:
  name: bench-runner
  namespace: $NAMESPACE
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: bench-runner
  namespace: $NAMESPACE
rules:
  # endpoints: o provedor do Pulumi le os Endpoints para saber se o Service ficou
  # pronto. Sem esta permissao o up fica preso na criacao do Service, sem erro.
  - apiGroups: [""]
    resources: ["pods", "services", "configmaps", "events", "endpoints"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
  - apiGroups: ["apps"]
    resources: ["deployments", "replicasets"]
    verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: bench-runner
  namespace: $NAMESPACE
subjects:
  - kind: ServiceAccount
    name: bench-runner
    namespace: $NAMESPACE
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: bench-runner
EOF

echo "arquivo do pedido: $ARQUIVO"
echo

if [ "$MODO" = "--only-yaml" ]; then
  cat "$ARQUIVO"
  exit 0
fi

if [ "$MODO" = "--apply" ]; then
  exigir_credencial_de_administracao
  kubectl apply -f "$ARQUIVO" || exit 1
  gerar_kubeconfig
  exit 0
fi

if [ "$MODO" = "--renew-token" ]; then
  exigir_credencial_de_administracao
  gerar_kubeconfig
  exit 0
fi

if [ "$MODO" = "--remove" ]; then
  exigir_credencial_de_administracao
  remover
  exit 0
fi

echo "modo de validacao: nada sera criado"
exigir_credencial_de_administracao
if ! kubectl apply -f "$ARQUIVO" --dry-run=client >/dev/null; then
  echo "  sintaxe do arquivo: falhou"
  exit 1
fi
echo "  sintaxe do arquivo: ok"

# O Namespace e o unico objeto que o servidor consegue validar antes de existir:
# o kubectl valida cada objeto contra o estado atual do cluster, e um dry run nao
# cria namespace, entao os objetos de dentro dele dariam NotFound.
SO_NAMESPACE="$(mktemp)"
awk '/^---$/{exit} {print}' "$ARQUIVO" > "$SO_NAMESPACE"
if kubectl apply -f "$SO_NAMESPACE" --dry-run=server; then
  echo "  validacao do namespace pelo servidor: ok"
else
  echo "  validacao do namespace pelo servidor: falhou"
  echo "  causas comuns: credencial sem permissao de criar Namespace, ou sem acesso a API"
  rm -f "$SO_NAMESPACE"
  exit 1
fi
rm -f "$SO_NAMESPACE"

echo
echo "os outros cinco objetos nao podem ser validados no servidor antes de o namespace"
echo "existir, por limitacao do dry run. A permissao da ServiceAccount e conferida"
echo "depois de aplicar, junto com a geracao do kubeconfig restrito."
echo
echo "se o administrador concordar, aplique com:"
echo "  $0 $NAMESPACE --apply"
