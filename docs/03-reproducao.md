# Reprodução

Configuração usada nas verificações, comandos de instalação e execução dos experimentos.

## 1. Configuração de referência

| Item | Valor |
| --- | --- |
| CLI do Pulumi | 3.263.0 |
| Docker | 29.8.0, rootless, socket em `/run/user/1000/docker.sock` |
| Python | 3.13.14, com `pulumi`, `pulumi-docker` e `pytest` |
| Credenciais de nuvem | nenhuma |
| Backend de estado | Pulumi Cloud, em conta individual; backend de arquivo nos testes locais |
| OpenTofu | 1.11.5, no experimento 07 |
| Terraform | 1.16.3, no experimento 07 |

Os comandos e as saídas dos documentos deste repositório foram produzidos nessa configuração. Onde o
comportamento depende de uma característica específica, o documento correspondente indica.

## 2. Instalação

```bash
curl -fsSL https://get.pulumi.com | sh
export PATH="$PATH:$HOME/.pulumi/bin"
pulumi version                             # 3.263.0 na versão utilizada aqui

pyenv install 3.13.14
pyenv local 3.13.14
python3 -m venv .venv
.venv/bin/pip install pulumi pulumi-docker pytest
```

Versões esperadas: `pulumi==3.263.0`, `pulumi_docker==5.2.0`, `pytest==9.1.1`.

### 2.1 Docker em modo rootless

O daemon escuta em um socket por usuário, e o provedor do Pulumi não consulta o `docker context`, de modo que o
endpoint precisa ser informado:

```bash
docker context ls                          # confirma se o contexto ativo é rootless
export DOCKER_HOST=unix:///run/user/1000/docker.sock
curl -sS --unix-socket /run/user/1000/docker.sock http://localhost/_ping   # imprime OK
```

### 2.2 Ferramentas do lado HCL

O OpenTofu é um binário único, obtido em `get.opentofu.org`. O Terraform também, em
`releases.hashicorp.com`, com o hash conferido contra o arquivo `SHA256SUMS` da versão:

```bash
V=1.16.3
curl -sSO "https://releases.hashicorp.com/terraform/$V/terraform_${V}_linux_amd64.zip"
curl -sSO "https://releases.hashicorp.com/terraform/$V/terraform_${V}_SHA256SUMS"
grep linux_amd64 terraform_${V}_SHA256SUMS | sha256sum -c -
unzip -o terraform_${V}_linux_amd64.zip -d ~/.local/bin
```

## 3. Backend de estado

| Backend | Como usar | Estado |
| --- | --- | --- |
| Pulumi Cloud | `pulumi login` | no serviço, com a chave dos segredos no serviço |
| Arquivo local | `export PULUMI_BACKEND_URL=file:///caminho` e `export PULUMI_CONFIG_PASSPHRASE=...` | JSON no disco, com a chave derivada da passphrase |

O diretório do backend de arquivo precisa existir antes. Com ele, `pulumi login` não é necessário e o
`pulumi whoami` devolve o usuário do sistema operacional. A estrutura criada é:

```
.pulumi/stacks/<projeto>/<stack>.json           checkpoint atual, mais .bak
.pulumi/history/<projeto>/<stack>-<id>.checkpoint.json
.pulumi/history/<projeto>/<stack>-<id>.history.json
.pulumi/backups/<projeto>/<stack>/<stack>.<id>.json
```

## 4. Experimentos

| Experimento | O que contém |
| --- | --- |
| `01-docker-python` | Imagem e container, com configuração e outputs |
| `02-language-and-graph` | Laços, valor secreto na configuração, `Output.apply` e grafo de dependências |
| `03-unit-tests-with-mocks` | Programa testado em processo, sem daemon e sem CLI |
| `04-automation-api` | `preview`, `up` e `destroy` chamados de dentro do Python |
| `05-local-backend-and-state` | Backend de arquivo, segredo por passphrase e formato do estado |
| `06-network-and-metrics` | Rede com servidor e gerador de tráfego, e o coletor de métricas |
| `07-docker-hcl` | A mesma topologia escrita em HCL, para OpenTofu e Terraform |

```bash
export DOCKER_HOST=unix:///run/user/1000/docker.sock

cd experiments/01-docker-python
pulumi stack init dev && pulumi config set hostPort 8080 && pulumi up
docker ps --filter name=pulumi-study-nginx

cd ../02-language-and-graph
pulumi stack init dev
pulumi config set serviceCount 2 && pulumi config set basePort 8090
pulumi config set --secret greeting "hello from a secret config"
pulumi up

cd ../03-unit-tests-with-mocks && ../../.venv/bin/python -m pytest tests/ -q

cd ../04-automation-api && ../../.venv/bin/python automation_demo.py

cd ../06-network-and-metrics
pulumi stack init dev && pulumi up
../../.venv/bin/python metrics.py --interval 5

cd ../07-docker-hcl
tofu init && tofu apply -auto-approve      # ou: terraform init && terraform apply
```

Cada projeto tem stack próprio. Dois recursos são compartilhados: o daemon Docker, e as portas do host, sendo
que o experimento 01 publica a 8080 e o 02 publica a 8090 e acima. Um stack adicional precisa de portas próprias
por `hostPort` ou `basePort`.

## 5. Lista de verificação

```bash
pulumi version                                             # 3.263.0 ou superior
pulumi plugin ls                                           # docker 5.2.0 após o primeiro uso
curl -sS --unix-socket "${DOCKER_HOST#unix://}" http://localhost/_ping   # OK
.venv/bin/python -c 'import pulumi, pulumi_docker'          # sem saída
cd experiments/03-unit-tests-with-mocks && ../../.venv/bin/python -m pytest tests/ -q   # 7 passed
cd ../01-docker-python && pulumi preview                    # "3 to create" em backend novo
cd ../02-language-and-graph && pulumi preview               # "5 to create" em backend novo
cd ../04-automation-api && ../../.venv/bin/python automation_demo.py                     # termina com succeeded
```

Depois da aplicação dos stacks, os previews informam `3 unchanged` e `5 unchanged`. A suíte de testes é a única
verificação que dispensa CLI, login e daemon: foi executada em diretório limpo, com `PATH=/usr/bin:/bin` e todas
as variáveis `PULUMI_*` e `DOCKER_HOST` removidas.

## 6. Limpeza

```bash
pulumi destroy                       # em cada diretório de experimento
pulumi stack rm dev
rm -rf /tmp/pulumi-study-backend
rm -rf ~/.pulumi/plugins             # libera o espaço dos plugins, 87 MB o do Docker
docker ps --filter name=pulumi-study # não deve listar nada
```

A ordem importa quando vários stacks compartilham o mesmo alvo: o experimento 01 é proprietário do recurso de
imagem do nginx e o 04 consome a mesma imagem. A remoção do 01 precede a do 04, ou o recurso de imagem é
declarado com `keep_locally=True` (item 9 de `01-verificacoes.md`).

## 7. Problemas conhecidos

A lista de falhas encontradas na primeira execução, com causa e correção, está no item 17 de
`01-verificacoes.md`.
