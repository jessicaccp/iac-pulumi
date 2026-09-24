#!/usr/bin/env bash
# Instala o CLI do Pulumi e o ambiente Python do experimento, sem sudo.
# O CLI, os plugins e o estado ficam em ~/.pulumi; o venv fica no projeto.
#
# Uso: ./scripts/setup-pulumi.sh [caminho-do-venv]
#
# Depois de rodar, em cada shell novo:
#   source ~/.pulumi/bench-env.sh

set -uo pipefail

PULUMI_DIR="$HOME/.pulumi"
VENV="${1:-$HOME/workspace/pulumi/.venv}"
ARQUIVO_DE_AMBIENTE="$PULUMI_DIR/bench-env.sh"
ARQUIVO_DE_SENHA="$PULUMI_DIR/passphrase"
DIRETORIO_DE_ESTADO="$PULUMI_DIR/state"
CLI_VERSION="3.263.0"
SDK_VERSION="3.263.0"
K8S_SDK_VERSION="4.34.2"
PYTEST_VERSION="9.1.1"

echo "CLI e plugins: $PULUMI_DIR"
echo "venv:          $VENV"
mkdir -p "$DIRETORIO_DE_ESTADO" || exit 1

echo
echo "== 1. CLI do Pulumi"
if [ -x "$PULUMI_DIR/bin/pulumi" ]; then
  echo "ja instalado: $PULUMI_DIR/bin/pulumi"
elif command -v pulumi >/dev/null 2>&1; then
  echo "ja instalado: $(command -v pulumi)"
else
  if ! curl -fsSL https://get.pulumi.com | sh -s -- --version "$CLI_VERSION"; then
    echo "nao consegui fixar a versao $CLI_VERSION, instalando a ultima disponivel"
    curl -fsSL https://get.pulumi.com | sh || {
      echo "falha ao baixar de get.pulumi.com."
      echo "sem saida de rede, copie o pacote do CLI e os plugins para esta maquina e use:"
      echo "  pulumi plugin install resource kubernetes v$K8S_SDK_VERSION --file <arquivo>"
      exit 1
    }
  fi
fi
export PATH="$PULUMI_DIR/bin:$PATH"

echo
echo "== 2. arquivos de ambiente"
if [ ! -f "$ARQUIVO_DE_SENHA" ]; then
  head -c 32 /dev/urandom | base64 > "$ARQUIVO_DE_SENHA"
  chmod 600 "$ARQUIVO_DE_SENHA"
  echo "passphrase do estado criada em $ARQUIVO_DE_SENHA"
fi

cat > "$ARQUIVO_DE_AMBIENTE" <<EOF
# Gerado por scripts/setup-pulumi.sh. Carregue com: source $ARQUIVO_DE_AMBIENTE
export PATH="\$HOME/.pulumi/bin:\$PATH"
export PULUMI_BACKEND_URL="file://$DIRETORIO_DE_ESTADO"
export PULUMI_CONFIG_PASSPHRASE_FILE="$ARQUIVO_DE_SENHA"
export PULUMI_PYTHON_CMD="$VENV/bin/python"
EOF
chmod 600 "$ARQUIVO_DE_AMBIENTE"
echo "ambiente gravado em $ARQUIVO_DE_AMBIENTE"

# shellcheck disable=SC1090
source "$ARQUIVO_DE_AMBIENTE"
pulumi version || exit 1

echo
echo "== 3. ambiente Python"
if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv "$VENV" || {
    echo "falha ao criar o venv em $VENV"
    exit 1
  }
fi
"$VENV/bin/pip" install --quiet --upgrade pip
if ! "$VENV/bin/pip" install --quiet \
    "pulumi==$SDK_VERSION" \
    "pulumi-kubernetes==$K8S_SDK_VERSION" \
    "pytest==$PYTEST_VERSION"; then
  echo "falha ao instalar os pacotes do PyPI"
  exit 1
fi
"$VENV/bin/python" -c 'from importlib.metadata import version; print("pulumi", version("pulumi"), "| pulumi-kubernetes", version("pulumi-kubernetes"), "| pytest", version("pytest"))'

echo
echo "== pronto"
echo "carregue o ambiente em cada shell novo:"
echo "  source $ARQUIVO_DE_AMBIENTE"
echo "o primeiro preview baixa o plugin do provider em $PULUMI_DIR/plugins"
