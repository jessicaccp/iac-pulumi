# Tempos

Desenho da medição de tempo do Pulumi no cluster do laboratório e o procedimento para executá-la. A medição cobre
apenas o Pulumi; as outras ferramentas são medidas no mesmo ambiente por outra frente, e é por isso que as condições
de execução ficam fixadas e registradas aqui.

O programa e o medidor estão em `experiments/08-kubernetes-timing/`, e as etapas de 1 a 5 já foram validadas até o
`preview`. A série medida depende do namespace e da autorização de quem administra o cluster.

## 1. Ambiente

Levantamento de 2026-09-23, registrado por `scripts/collect-cluster-info.sh`, com a saída em
`~/bench/cluster-info-<data>.txt`.

| Item | Valor medido |
| --- | --- |
| Cluster | Kubernetes v1.32.13, quatro nós: `kub-master` (control-plane, 192.168.20.244) e `kub-worker1` a `kub-worker3` (192.168.20.243, .35, .29) |
| Sistema e runtime | Fedora Linux 43 Server em todos os nós, containerd 2.2.3, CNI flannel |
| Hardware por nó | Intel i5-10400, 12 threads, cerca de 7,7 GB de memória alocável, 110 pods |
| Memória em uso | master 4,8 GiB; workers 2,5, 2,8 e 2,6 GiB. CPU entre 0,07 e 0,24 núcleos |
| Requisições de terceiros | worker1 7%, worker2 17%, worker3 26% da memória; limites chegam a 77% no worker3 |
| Disco | master com 897 GB livres. Nos workers, o sistema de arquivos do kubelet tem 14,9 GiB, com 10,3 a 11,6 GiB usados, ou seja 3,3 a 4,6 GiB livres |
| Agendamento | o master tem taint de control-plane, então a carga do experimento cai nos três workers |
| Storage e entrada | storage class padrão `local-path`, provisionamento local ao nó; controladores de entrada `nginx` e `traefik` |
| Registry | um interno, em ClusterIP na porta 5000, e outro em NodePort 30500 |
| `metrics-server` | não instalado: `kubectl top` não serve como fonte de medida |
| Teto por namespace | nenhum `ResourceQuota` nem `LimitRange` no cluster, então os limites do experimento são declarados por nós |
| Conta usada | administradora do cluster |
| Relógio | seis dias atrás da hora real, com o relógio de hardware em 2021-06-10. A diferença fica registrada e não é corrigida |

O cluster é compartilhado e roda jenkins, jupyterhub, sonarqube, monitoring, ingress e registry de terceiros. A
medição acontece em paralelo com esse uso, o que afeta todas as equipes igualmente e é a razão pela qual o desvio
entre repetições importa mais aqui do que importaria em uma máquina ociosa.

### 1.1 Ambiente do Pulumi na máquina de controle

| Item | Valor |
| --- | --- |
| Onde o CLI roda | `kub-master`, na conta `larces` |
| CLI | Pulumi 3.263.0 em `~/.pulumi/bin`, 113 MB |
| Plugins | `~/.pulumi/plugins`, com o provedor `kubernetes` 4.34.2, cerca de 100 MB |
| Estado | backend de arquivo em `~/.pulumi/state`, com passphrase em `~/.pulumi/passphrase` |
| Python | 3.14.4 do sistema, com venv em `~/workspace/pulumi/.venv` contendo `pulumi` 3.263.0, `pulumi-kubernetes` 4.34.2 e `pytest` 9.1.1 |
| Variáveis | `~/.pulumi/bench-env.sh`, carregado com `source` em cada shell novo |

## 2. Medições

### 2.1 Essenciais

Em Kubernetes, "criar a infraestrutura" são dois tempos diferentes: o da ferramenta, que calcula e envia os objetos
para a API, e o do cluster, que agenda, baixa imagem e deixa tudo pronto. O primeiro é o que a ferramenta controla; o
segundo quase não depende dela. Medir só um dos dois produz número enganoso, então os dois entram.

| Medição | Comando | Equivalente no lado HCL |
| --- | --- | --- |
| Plano inicial, sem estado | `pulumi preview` | `terraform plan` |
| Aplicação sem plano | `pulumi up --skip-preview --yes` | `terraform apply tfplan` |
| Convergência | consulta ao cluster a cada segundo, até todos os deployments ficarem disponíveis, inclusive depois de o `up` retornar | igual |
| Ciclo completo, o que o usuário espera | `pulumi up --yes` | `terraform apply -auto-approve` |
| Plano sem mudanças | `pulumi preview` depois da aplicação | `terraform plan` idempotente |
| Remoção | `pulumi destroy --skip-preview --yes` | `terraform destroy -auto-approve` |

Duas armadilhas de contagem, ambas observadas na execução: o plano do Pulumi conta a própria stack como recurso, e o
provedor Kubernetes não aparece como recurso porque usa o provedor padrão. Por isso a contagem de objetos do
relatório sai do cluster, com `kubectl`, e não do plano.

A linha do **ciclo completo**, o `pulumi up --yes` que é o que o usuário roda no dia a dia, não foi medida: o medidor
executa a aplicação sem plano, para separar plano de aplicação, e o que existe é a soma das duas partes. Fica como
medição pendente.

### 2.2 Recomendadas

| Medição | Como | O que responde |
| --- | --- | --- |
| Curva de escala | 10, 50 e 100 módulos, os mesmos três pontos nas demais ferramentas | Separa o custo fixo do motor (intercepto) do custo por recurso (inclinação) |
| Variância | cinco repetições por ponto, com mediana, mínimo e máximo | O quanto o cluster compartilhado introduz de ruído |
| Fase e por recurso | `--otel-traces file://traces.json` no `up` | Tempo até o primeiro recurso e taxa de criação |
| Update incremental | Aplicar 50 módulos e passar para 51, pela Etapa 6 | O caso do dia a dia, que não é criar do zero |
| Custo do próprio CLI | `/usr/bin/time -v` e `--profiling <arquivo>` | Separa lentidão de rede de consumo de CPU e memória |

### 2.3 Extras, se sobrar janela

- nó indisponível ou `kubectl` interrompido no meio da aplicação, com o tempo e o estado resultante;
- dois stacks diferentes aplicando ao mesmo tempo no mesmo namespace;
- primeira execução sem o plugin instalado, medida à parte;
- `preview` com `--refresh` depois de apagar um pod por fora, para medir detecção de divergência.

### 2.4 O que fica fora

- execução com a imagem ainda não presente nos nós, que mede download e não orquestração;
- troca de backend de estado no meio da série;
- execução concorrente com outra carga na máquina de controle, porque o tempo de plano depende de quem executa o CLI;
- volume persistente, pelo motivo da seção 3.

## 3. Condições fixas

| Item | Valor | Motivo |
| --- | --- | --- |
| Namespace | um só, começando com `bench-` | O `destroy` remove tudo que o stack conhece, então um namespace de terceiros na configuração apagaria recursos que não são nossos |
| Paralelismo | `--parallel 10` explícito nas fases medidas de plano, aplicação e remoção | O padrão da versão 3.263.0 é 96 no `up` e 16 no `preview`. Nesta série o plano rodou com o padrão do CLI, e o medidor passou a fixar 10 também nele, então uma medição nova de plano pode diferir um pouco desta |
| Espera do provedor | desligada nos dois recursos, pela anotação `pulumi.com/skipAwait` | A espera do Pulumi não retornava quando a credencial não podia ler os Endpoints (seção 6), e o desligamento precisa ficar declarado porque do lado HCL o `apply` espera o rollout por padrão |
| Backend de estado | arquivo local, sem serviço da Pulumi | O backend do serviço acrescenta ida e volta de rede ao número |
| Unidade | um `Deployment` de uma réplica com um `Service`, dentro de um `ComponentResource` | Objeto com ciclo de vida real, e um objeto por unidade faz o tempo escalar com o trabalho da ferramenta |
| Imagem | `nginx:1.27-alpine`, cerca de 60 MB descompactada | Compatível com os 3,3 GiB livres no sistema de arquivos do kubelet |
| Pedidos e limites | 50m de CPU e 32Mi de memória de pedido; 100m e 64Mi de limite | Cem módulos somam 3,2 GiB de pedido, distribuídos pelos três workers |
| Período de graça | 5 segundos | Sem isso, cada remoção paga 30 segundos por pod e a medida de `destroy` deixa de ser sobre a ferramenta |
| Sem volume, sem toleration, sem `nodeSelector` | | O taint do master já mantém a carga nos três workers, e volume em `local-path` prenderia o pod a um nó e apagaria dado do nó na remoção |
| Aquecimento | a primeira rodada de cada tamanho é descartada | Aquece o cache de imagem nos nós |
| Máquina de controle | sempre a mesma, com carga registrada | Parte do tempo de plano é CPU local |
| Teto por comando | 600 segundos, com batida de coração a cada 15 na tela | Um travamento já consumiu vinte e três minutos de janela; o teto interrompe o ciclo em vez de esperar |
| Registro | versões do Pulumi, do plugin e do kubectl, hora local, hora externa, contagem de objetos | A hora externa existe porque o relógio do cluster está seis dias atrás. Nas duas execuções de 24/09 a versão do plugin está na seção 1.1 e não no JSON, que passou a registrá-la depois |

## 4. Regras de convivência

O cluster é compartilhado. As regras abaixo são condições do experimento, não recomendações.

| Regra | Como é garantida |
| --- | --- |
| Nenhum recurso fora de um namespace próprio | Namespace exclusivo com prefixo `bench-`. Nunca usar `default`, `teste` ou qualquer namespace existente |
| Nenhum recurso de escopo de cluster | Um teste com mocks falha se alguém acrescentar objeto de escopo de cluster. O namespace é criado fora do programa |
| Nenhum volume persistente | A série não usa `PersistentVolumeClaim`, porque a storage class é `local-path` e a remoção apagaria dado do disco do nó |
| Nenhum comando de nó | `cordon`, `drain`, `taint` e `label` em nó despejam pods de terceiros e ficam fora do experimento |
| Nenhum pod sem limite | Um teste com mocks falha se faltar `requests` ou `limits` de CPU e memória |
| Credencial de medição restrita | A série aceita `KUBECONFIG` de namespace, e o `bench.py` recusa iniciar se a credencial puder criar pods fora do namespace, salvo com `--allow-cluster-admin` explícito |
| Snapshot antes e depois | Antes de cada sessão, o estado do cluster é gravado em arquivo; a comparação tem que dar vazio fora do namespace do experimento |
| `~/.kube/config` intocado | O kubeconfig do experimento é arquivo separado, referenciado por `KUBECONFIG` |

```bash
mkdir -p ~/bench
antes=~/bench/antes-objetos.txt; depois=~/bench/depois-objetos.txt

kubectl get ns -o name | sort > ~/bench/antes-ns.txt
kubectl get pods,svc,deploy,sts,ds,ing,pvc,cm,secret -A --no-headers 2>/dev/null | sort > "$antes"

# depois da sessão, com o mesmo par de comandos em "$depois"
diff ~/bench/antes-ns.txt <(kubectl get ns -o name | sort)
diff <(grep -v bench- "$antes") <(grep -v bench- "$depois")
```

## 5. Procedimento

### Etapa 0, levantamento do ambiente

Feito. O script e a explicação de cada seção estão em `05-levantamento.md`.

### Etapa 1, ambiente do Pulumi

```bash
cd ~/workspace/pulumi/scripts
./setup-pulumi.sh
source ~/.pulumi/bench-env.sh
```

O `source` é obrigatório em cada shell novo: ele aponta o CLI para o estado local e para o Python do venv. Sem ele,
o Pulumi tenta o serviço da Pulumi e usa o Python do sistema, que não tem o SDK instalado.

### Etapa 2, testes sem cluster

```bash
cd ~/workspace/pulumi/experiments/08-kubernetes-timing
~/workspace/pulumi/.venv/bin/python -m pytest tests/ -q
```

Quarenta e seis testes, que não precisam de cluster nem de CLI: dez do programa, com mocks do provedor, e trinta e seis
do medidor, com comandos de verdade no lugar do Pulumi e do kubectl. Verificado nesta montagem.

### Etapa 3, validação contra o cluster, sem criar nada

```bash
cd ~/workspace/pulumi/experiments/08-kubernetes-timing
source ~/.pulumi/bench-env.sh
pulumi stack init dev
pulumi config set namespace bench-larces
pulumi config set unitCount 1
pulumi preview
```

Esperado: quatro recursos no plano, sendo a stack, o componente `WebModule`, um `Deployment` e um `Service`.
Verificado nesta montagem. O `preview` não cria nada e não exige que o namespace exista.

### Etapa 4, namespace e credencial restrita

Feito. O namespace e a credencial restrita na máquina de controle estão registrados na seção 8. O namespace existe
antes da série porque o programa não cria recurso de escopo de cluster, e a credencial restrita reduz o alcance de um
erro a esse namespace.

### Etapa 5, série medida

Antes da série, uma medição de fumaça com dois módulos, para fechar o caminho inteiro (credencial restrita,
convergência, logs e JSON) sem gastar a janela:

```bash
cd ~/workspace/pulumi/experiments/08-kubernetes-timing
source ~/.pulumi/bench-env.sh
export KUBECONFIG=~/bench/kubeconfig-bench-larces.yaml
~/workspace/pulumi/.venv/bin/python bench.py --sizes 2 --repetitions 1 \
  --command-timeout 120 --heartbeat 10 --output resultados-fumaca
```

O `--command-timeout` é o teto de cada comando, em segundos, e o `--heartbeat` é o intervalo da linha "em andamento"
na tela. Os dois existem porque um travamento já consumiu vinte e três minutos de janela. Quando um comando passa do
teto, o medidor mata o grupo de processos, registra a fase que falhou com o tempo já decorrido, libera o lock do stack
e segue para o próximo ciclo. O `Ctrl-C` mata o comando em andamento, que roda em sessão própria e por isso não recebe
o sinal do terminal, libera o lock e imprime como limpar o cluster.

Só depois de a fumaça fechar, a série completa:

```bash
~/workspace/pulumi/.venv/bin/python bench.py --sizes 10,50,100 --repetitions 5
```

Para cada tamanho há uma rodada de aquecimento, descartada do resumo, mais as repetições medidas. Em cada uma:
`destroy` de limpeza, `preview`, `up --skip-preview`, `preview` sem mudanças e `destroy`. Cada comando grava log
próprio, e o conjunto vai para um JSON com a mediana, o mínimo e o máximo por tamanho e por fase.

Antes de começar, o medidor confere se o CLI e o `kubectl` existem, se há stack selecionado, se o namespace existe e
o que a credencial permite fazer. Qualquer uma dessas checagens falhando impede a série.

### Etapa 6, medição incremental

Mede o plano e a aplicação de uma mudança num stack já aplicado, que é o caso do dia a dia, e não o da criação do
zero. Cada valor de `--sizes` é o alvo da mudança, e a base é uma unidade menor:

```bash
~/workspace/pulumi/.venv/bin/python bench.py --incremental --sizes 51,101 \
  --repetitions 3 --output resultados-incremental
```

Em cada ciclo: limpeza, preparo da base sem medida (50 e 100 módulos, com a convergência esperada antes de seguir),
`preview` da mudança, `up` da mudança com a convergência medida por fora, `preview` sem mudanças e `destroy`. A
preparação e a remoção ficam fora da medida, porque o que se quer isolar é o custo da mudança. Cada repetição paga a
preparação inteira, então 51 módulos com três repetições leva cerca de cinco minutos, e 101 módulos, cerca de oito. O
resultado vai para um diretório próprio, e cada registro carrega o campo `base`.

### Etapa 7, coleta e limpeza

O JSON da série é a evidência, e os logs ficam em `resultados/logs/`. A medição de 2026-09-24 está em
`experiments/08-kubernetes-timing/resultados/`, e os números consolidados na seção 7. No fim:

```bash
pulumi destroy --skip-preview --yes
pulumi stack rm dev
```

E a comparação de snapshot da seção 4, que precisa dar vazio fora do namespace do experimento.

## 6. Achados desta montagem

| Achado | Evidência |
| --- | --- |
| Pulumi 3.263.0 com Python 3.14 exige uma linha de ajuste nos testes com mocks | `set_mocks` registra a stack na importação e o `asyncio` do 3.14 não cria mais event loop implicitamente: `RuntimeError: There is no current event loop`. O caminho do CLI não é afetado, e o `preview` rodou no 3.14 sem erro |
| O plano conta a stack como recurso | Um único `ConfigMap` apareceu como `2 to create`, e um módulo com `Deployment` e `Service`, como `4 to create` |
| O `preview` não exige que o namespace exista | O namespace `bench-preview` não existe no cluster e o plano foi calculado normalmente |
| O instalador do CLI grava no `~/.bashrc` | A linha que acrescenta `~/.pulumi/bin` ao `PATH` foi adicionada por ele, e as variáveis do experimento continuam dependendo do `source` |
| O nó de control-plane fica fora do alvo | O taint de control-plane mantém a carga nos três workers, o que também protege o `kube-apiserver` e o `etcd` |
| A credencial restrita não podia ler os Endpoints | O `up` travava sem erro na criação do `Service`, com os objetos prontos no cluster. O waiter de `Service` do provedor assina `services` e `endpoints` (`provider/pkg/await/service.go` da 4.34.2, que não usa EndpointSlices) e exige `endpointsSettled` mais nenhum endereço pendente. Com o `Role` sem `endpoints`, essa assinatura recebia `Forbidden` e o provedor esperava para sempre. Não era intermitente: as execuções que travaram usavam a credencial restrita, a execução com credencial de administrador terminou em erro declarado (`Minimum number of live Pods was not attained`) em vez de espera infinita, e o programa de diagnóstico, com quinze execuções, nunca travou. Corrigido acrescentando `endpoints` ao `Role`: a medição de fumaça de dois módulos fechou os dois ciclos completos |
| A anotação de espera é por recurso | `pulumi.com/skipAwait` no `Deployment` não desliga a espera do `Service`, que tem waiter próprio com dez segundos de acomodação dos Endpoints. O log do provedor mostra `Skipping await logic` por recurso, e a lista de recursos com espera registrada inclui `Pod`, `Service`, `PersistentVolumeClaim`, `ReplicationController`, `Deployment`, `StatefulSet`, `DaemonSet`, `ReplicaSet`, `Job`, `Ingress` e `PodDisruptionBudget` |
| Um ciclo interrompido contaminava os seguintes | O `up` morto no teto deixa o `Service` criado na API e fora do estado, e o `destroy` só remove o que o estado conhece: o ciclo seguinte falhava com `services "bench-web-000" already exists`, e o estado ainda carregava a mensagem `10 pending operations from previous deployment`. Cada ciclo agora limpa o namespace por `kubectl`, restrito ao prefixo dos objetos do experimento, antes de começar |
| A espera de um segundo pelo fim do comando inflava cada fase | A detecção do fim do comando acontecia na batida de um segundo, então cada duração carregava até um segundo de atraso: um comando de 0,3 segundo era medido como 1,3. A espera passou a ser de 0,2 segundo (medição de 0,4 para o mesmo comando) e a convergência continua sendo consultada ao cluster a cada segundo, que é a definição da medida |
| A convergência pode terminar depois do `up` | Com a espera do provedor desligada, o `up` volta assim que entrega os objetos: um módulo em 1,86 segundo, com os pods ainda subindo, e a primeira medição registrou `convergencia sem medida`, porque a consulta ao cluster só rodava dentro do comando. Agora o medidor continua consultando depois do `up`, até os deployments esperados ficarem disponíveis ou até o teto de `--convergence-timeout`, 120 segundos por padrão |
| Números de referência com a espera ligada | Dez módulos, com `--parallel 10`: 31 recursos criados em 22 segundos pelo próprio programa do experimento, e removidos em 7 segundos |
| Um comando pendurado não consome mais a janela | Todo comando tem teto (`--command-timeout`, 600 segundos por padrão), os comandos auxiliares têm limite próprio de 30 segundos e as consultas ao cluster levam `--request-timeout`. Verificado com `pulumi` e `kubectl` falsos: o `preview` pendurado morre no teto, o ciclo entra no JSON com a fase e o tempo decorrido, e a série continua no ciclo seguinte |
| O `Ctrl-C` não deixa o cluster pela metade | O comando roda em sessão própria, então o sinal do terminal não chega nele; o medidor mata o grupo de processos ao receber a interrupção, libera o lock e imprime o comando de limpeza. Verificado com `pulumi` falso e `timeout --signal=INT`: nenhum processo do comando sobreviveu |
| O `kubectl` avisa antes de responder | O `kubectl auth can-i` da 1.32 imprime `Warning: resource 'namespaces' is not namespace scoped` antes do `yes`. Comparar a saída inteira reprovava a credencial de administrador válida no `create-bench-environment.sh` (bloqueou a renovação do token em 24/09) e, no `bench.py`, faria a guarda de credencial ampla passar em silêncio. A resposta útil é a última linha, e o medidor passou a ler `stderr` separado do `stdout`, porque um aviso junto do `-o json` quebraria a leitura do estado dos deployments |

## 7. Números medidos

Série de 2026-09-24 no `kub-master`, com a credencial restrita ao namespace, `--parallel 10` e a espera do provedor
desligada nos dois recursos. Dezoito ciclos, aquecimento mais cinco repetições medidas por tamanho, nenhum ciclo
falhou, e a série inteira levou 1097 segundos: cerca de 134 nos ciclos de 10 módulos, 340 nos de 50 e 622 nos de 100.
Os dados brutos estão em `experiments/08-kubernetes-timing/resultados/serie-20260918-164216.json`, com um log por
comando em `resultados/logs/`. O nome do arquivo carrega o relógio do cluster, seis dias atrás, e o `meta` guarda as
duas horas.

| Módulos | Fase | Mediana | Mínimo | Máximo |
| --- | --- | --- | --- | --- |
| 10 | plano inicial (`preview`) | 1,80 | 1,80 | 1,80 |
| 10 | aplicação (`up --skip-preview`) | 3,94 | 3,76 | 4,11 |
| 10 | convergência | 11,62 | 11,09 | 12,52 |
| 10 | plano sem mudanças | 1,80 | 1,80 | 1,80 |
| 10 | remoção (`destroy`) | 5,60 | 5,20 | 5,80 |
| 50 | plano inicial | 2,20 | 2,20 | 2,40 |
| 50 | aplicação | 15,44 | 14,45 | 15,46 |
| 50 | convergência | 21,12 | 20,21 | 22,23 |
| 50 | plano sem mudanças | 2,80 | 2,60 | 2,80 |
| 50 | remoção | 28,82 | 28,22 | 29,62 |
| 100 | plano inicial | 3,80 | 3,80 | 3,80 |
| 100 | aplicação | 34,21 | 29,53 | 35,82 |
| 100 | convergência | 37,97 | 34,72 | 38,94 |
| 100 | plano sem mudanças | 4,00 | 3,80 | 6,00 |
| 100 | remoção | 57,04 | 56,24 | 58,03 |

Leitura dos números, com três pontos por fase:

- a **aplicação** cresce cerca de 0,34 segundo por módulo, sobre um custo fixo de aproximadamente 0,6 segundo;
- a **convergência** cresce cerca de 0,29 segundo por módulo, sobre um custo fixo de aproximadamente 9 segundos, que é
  o tempo do cluster até o primeiro pod ficar disponível;
- a **remoção** é a fase mais sensível ao tamanho, cerca de 0,57 segundo por módulo e custo fixo praticamente nulo:
  custa quase o dobro da aplicação por unidade;
- o **plano** e o **plano sem mudanças** quase não dependem do tamanho, cerca de 0,02 segundo por módulo sobre um
  custo fixo de 1,6 segundo, e o segundo é a demonstração de idempotência: depois do `up`, o `preview` não propõe
  mudança nenhuma;
- a dispersão entre repetições é pequena nas fases medidas: a aplicação de 100 módulos variou de 29,53 a 35,82
  segundos, cerca de 10% em torno da mediana, e a remoção de 100 módulos variou 3%. A exceção é o plano sem mudanças
  de 100 módulos, com um caso de 6,00 segundos contra mediana de 4,00, sem causa identificada;
- a duração que o próprio Pulumi imprime fecha com a medida do medidor: 4,0 contra 4,13 na aplicação de 10 módulos, e
  a medida do medidor fica até cerca de um segundo acima da duração que o próprio Pulumi imprime (4,13 contra 4,0 na
  aplicação de 10 módulos, e 34,21 contra 34 na de 100), e a diferença é a partida do CLI, que fica fora do trabalho
  do motor que o Pulumi cronometra.

Duas observações de método, para quem for repetir:

- o `up` mede a entrega dos objetos e a convergência mede o cluster; as duas se sobrepõem no tempo, porque a
  convergência é contada desde o início do `up`, e é isso que mostra quanto o cluster levou depois de a ferramenta
  terminar;
- o `destroy` mede a entrega das remoções, não o desaparecimento delas: ele sempre contou as remoções esperadas (31,
  151 e 301, ou seja três objetos por módulo mais a stack), e em 17 dos 18 ciclos a limpeza inicial ainda encontrou de
  4 a 10 objetos com o prefixo do experimento na API, terminando. A contagem saiu na tela da execução; o medidor passou
  a gravá-la no registro, no campo `restos_do_ciclo_anterior`. A limpeza por `kubectl` resolve isso antes de cada
  ciclo começar, então nenhuma fase mede em cima de sobra da anterior.

### Update incremental

Executada na mesma sessão, com a base de 50 e de 100 módulos já aplicada: o medidor prepara a base sem medir e mede
o plano e a aplicação da mudança para 51 e para 101, com três repetições por alvo mais o aquecimento. Oito ciclos,
nenhuma falha, 722 segundos no total entre preparação, medida e remoção. Medianas, em segundos:

| Base | Alvo | plano | aplicação | convergência | plano sem mudanças | remoção |
| --- | --- | --- | --- | --- | --- | --- |
| 50 | 51 | 2,80 | 3,04 | 6,31 | 2,80 | 29,22 |
| 100 | 101 | 3,80 | 4,09 | 7,65 | 3,80 | 58,04 |

O log confirma que a mudança é de um módulo: o plano propôs `+ 3 to create` com 151 ou 301 recursos inalterados, e o
plano seguinte não propôs alteração nenhuma. A leitura e a comparação com a criação do zero estão em
`06-relatorio.md` §6.3.

## 8. Estado da execução

Registro de 2026-09-23, para retomar sem repetir o que já foi feito.

**Pronto no cluster, criado por quem administra e pela autora do experimento:** namespace `bench-larces` com quota,`LimitRange`, `ServiceAccount bench-runner`, `Role` e `RoleBinding`; kubeconfig restrito em `~/bench/kubeconfig-bench-larces.yaml`, com token de 24 horas renovável por
`./scripts/create-bench-environment.sh bench-larces --renew-token`.

**Pronto e verificado na máquina de controle:** CLI 3.263.0, plugin `kubernetes` 4.34.2, venv com o SDK e o
pytest, backend de estado em arquivo, 46 testes passando no Python 3.13 local, `preview` do programa com
um módulo, e o medidor validado com stubs de `kubectl` e `pulumi`.

**Registro de 2026-09-24, quando a fumaça fechou:** token restrito renovado (o anterior de 24 horas tinha vencido, e a renovação estava bloqueada por um bug do script com o aviso do `kubectl`, seção 6), `Role` reaplicado com `endpoints`, estado do stack recriado com `pulumi stack rm dev` e `pulumi stack init dev` para descartar as dez operações pendentes das execuções interrompidas, e a medição de fumaça de dois módulos concluída: dois ciclos completos, com `preview` 2,00s, `up` 12,93 e 12,66s, convergência 5,65 e 6,33s, `preview` sem mudanças 2,00s e `destroy` 2,00s. Os números da fumaça não entram no relatório; eles confirmam o caminho inteiro com a credencial restrita. Com a `infrastructure.py` que leva a anotação também para o `Service`, a conferência de um módulo mostrou `Skipping await logic` nos dois recursos e `up` de 1,86 segundo, contra 12,9 segundos da rodada anterior.

**Configuração para a série:** `--parallel 10`, uma rodada de aquecimento por tamanho, cinco repetições medidas, 600 segundos de limite por comando, 120 segundos de teto para a convergência (`--convergence-timeout`) e a espera do provedor desligada nos dois recursos, com a convergência medida por fora. Ciclo que estoura o limite é registrado como erro, o lock do stack é liberado automaticamente com `pulumi cancel` e a série segue.

**Série medida, em 2026-09-24:** dezoito ciclos concluídos sem falha, 1097 segundos no total, com os números na
seção 7. Cada ciclo terminou com `destroy`, e a limpeza inicial removeu por `kubectl` o que ainda estava terminando.

**Mudança de um módulo medida na mesma sessão:** oito ciclos concluídos sem falha, 722 segundos no total, com os
números no fim da seção 7.

**O que falta, na ordem:**

1. conferir que o namespace ficou vazio: `kubectl get deploy,svc,pods -n bench-larces`. O `pulumi destroy` e o
   `pulumi stack rm dev` foram feitos em 24/09;
2. decidir se o ambiente do cluster continua. `./scripts/create-bench-environment.sh bench-larces --remove` desfaz o
   namespace, a quota, os limites, o `Role` e o kubeconfig restrito. Para uma medição nova, o stack precisa ser criado
   de novo (`pulumi stack init dev` e `pulumi config set skipAwait true`, porque o resto o medidor configura) e o
   token, renovado, porque vale 24 horas;
3. rodar o `/usr/bin/time -v` num `up` de 100 módulos para o custo de CPU e de memória na máquina de controle;
4. rodar a comparação de snapshot da seção 4, se o arquivo de antes da sessão tiver sido gravado;
5. levar os números para o relatório e comparar com as outras equipes.

## 9. Pendências

Fechadas nesta medição: a imagem (`nginx:1.27-alpine` do Docker Hub), a janela (a série rodou em paralelo com o uso
normal do cluster, sem exclusividade, e isso está declarado no relatório), a declaração da espera do provedor
desligada nos dois recursos e a causa do travamento observado, que era a credencial sem permissão de ler os
Endpoints.

Abertas:

1. alinhamento com as outras equipes quanto ao objeto unitário, aos limites e ao passo de aquecimento, para os
   números serem comparáveis;
2. `--otel-traces`, para tempo até o primeiro recurso e taxa de criação, se a janela permitir.
