# Verificações

Registro do que foi executado e observado ao usar o Pulumi, em setembro de 2026, com o Docker como alvo. Cada
item traz a evidência, e as comparações com OpenTofu e Terraform foram feitas com a mesma topologia escrita em
HCL, no experimento `07-docker-hcl`.

As afirmações verificadas aparecem como fato. As que dependem apenas da documentação oficial estão
identificadas.

## 1. O programa é executado, e o grafo decorre dos dados

O experimento 02 constrói uma frota com um laço `for` sobre `serviceCount`, injeta um valor secreto e calcula
uma lista de endpoints com `Output.all(...).apply(...)`. Não há construção de laço, sintaxe de variável nem
ligação explícita: `docker:index:Container::nginx` depende de
`docker:index:remoteImage:RemoteImage::nginx-image` porque o input `image` do container recebeu o output do
recurso de imagem.

Duas consequências para quem for revisar código escrito assim: infraestrutura pode ser gerada por código comum,
o que permite geradores e matrizes de ambientes, e um programa pode ser código arbitrário, o que torna a
revisão diferente da revisão de um arquivo declarativo.

## 2. Interface para máquina: JSON e códigos de saída

`pulumi up --json` produz um documento de sumário seguido de 368 documentos de evento em uma atualização de
três recursos:

```
doc 0: {config, steps, duration, changeSummary}
doc N: {sequence, timestamp, preludeEvent | diagnosticEvent | resourcePreEvent |
        resOutputsEvent | summaryEvent | cancelEvent}
```

O campo `steps[]` inclui `op`, `urn`, `inputs`, `dependencies` e os `__defaults` aplicados pelo provedor. As
dependências saem como lista de URNs por recurso, o que permite reconstruir o grafo.

No lado HCL, o plano em JSON (`tofu show -json tfplan`) tem as chaves `format_version`, `terraform_version`,
`variables`, `planned_values`, `resource_changes`, `output_changes`, `prior_state` e `configuration`, sem
arestas entre recursos. As referências cruzadas aparecem em `relevant_attributes`:

```json
[{"resource": "docker_container.client", "attribute": ["name"]},
 {"resource": "docker_image.client", "attribute": ["image_id"]},
 {"resource": "docker_network.metrics_net", "attribute": ["name"]}]
```

Para automação, os códigos de saída também diferem:

| Situação | Pulumi | OpenTofu |
| --- | --- | --- |
| Sem mudanças | 0, com `changeSummary: {'same': 6}` | 0, com `No changes` |
| Com mudança detectada | 7, com `--refresh`, e `changeSummary: {'create': 1, 'same': 5}` | 2, com `-detailed-exitcode` |
| Com mudança não vista | 0 sem `--refresh`, porque o preview não lê o ambiente | não se aplica |

## 3. O plano é verificável e recusa adulteração

`pulumi preview --save-plan plan.json` grava `{manifest: {time, magic, version}, config, resourcePlans}`, e
cada entrada contém o estado `goal`, com as `dependencies`. Aplicar com `pulumi up --plan plan.json` funciona.
Editar o plano, alterando a porta de 8086 para 8085, produz recusa por recurso:

```
error: resource urn:...:Container::nginx violates plan: properties changed:
~~ports[{... external:{8085} ...}!={... external:{8086} ...}]
```

O motor reexecuta o programa durante a aplicação e compara o estado desejado com o plano; o campo `magic` é um
valor de integridade. Ressalva: o `--plan` é aceito pelo `up`, mas não consta do `pulumi up --help` da versão
3.263.0.

No lado HCL, `plan -out` seguido de `apply tfplan` funciona, e um plano adulterado também foi recusado, com
`Provider produced inconsistent final plan`, além de `Saved plan is stale` quando o estado mudou depois do
plano. A recusa vem de verificações de consistência, e não de um campo de integridade próprio.

Consequência para auditoria: nos dois casos o plano editado não é aplicado, mas apenas o Pulumi tem um
mecanismo cujo propósito declarado é esse.

## 4. O preview não consulta o ambiente real

Um container removido com `docker rm -f` não alterou o resultado: o `preview` continuou informando
`5 unchanged`, e o `--expect-no-changes` confirmou. Após `pulumi refresh`, que reportou
`- docker:index:Container pulumi-study-web-1 delete`, a verificação passou a falhar com
`error: no changes were expected for preview but changes were proposed`, e o `pulumi up` seguinte recriou o
recurso.

No lado HCL o mesmo cenário resultou em `1 to add`, sem nenhuma flag: o plano consulta o ambiente por padrão. A
capacidade existe nas duas ferramentas, já que `pulumi preview --refresh` existe; a diferença está no padrão.

## 5. A infraestrutura é testável sem provedor

`pulumi.runtime.set_mocks` e `pulumi.runtime.test` executam o programa em processo, contra mocks: sete testes em
0,14s, sem daemon Docker e sem CLI. Dois comportamentos foram identificados:

- **o registro de recursos é assíncrono.** Asserções que leem o registrador a partir de um método de teste
  comum passam sem verificar nada, porque o laço itera uma lista vazia. A asserção precisa estar dentro de
  `@pulumi.runtime.test`, retornando um future;
- **o mock devolve apenas o que lhe é informado.** Retornar somente `id` deixa `image.image_id` desconhecido, e
  inputs desconhecidos são removidos dos inputs registrados, o que permite que um teste de ligação passe vazio.

Os valores atravessam uma fronteira JSON e protobuf: portas registradas como `9500` retornam como `9500.0`, e a
ordem do registrador segue a conclusão, não o programa.

No lado HCL o mesmo tipo de verificação existe: três asserções com `mock_provider` rodaram em 0,14s no OpenTofu
e 0,10s no Terraform. A diferença está em escrever as asserções em Python ou Jest, com o grafo de recursos como
objetos, em vez de expressões em HCL.

## 6. A Automation API é uma camada sobre o CLI

`automation_demo.py` executa preview, up e destroy a partir do Python e recebe resultados tipados:
`preview.change_summary` é `{OpType.CREATE: 1, ...}`, `up.outputs` mapeia nomes para
`OutputValue(value, secret)`, `update.summary.resource_changes` é um `OpMap`, e os eventos chegam como objetos
com `resource_pre_event`, `diagnostic_event` e equivalentes. Programas inline dispensam `Pulumi.yaml`, porque o
workspace gera um arquivo em diretório temporário.

O traceback evidencia `self.workspace.pulumi_command.run(...)`: a API executa o binário `pulumi` como
subprocesso. Não há SDK oficial em processo equivalente no lado HCL.

## 7. Qualquer provedor se torna uma interface de linha de comando

```bash
pulumi do docker:index:getNetwork --name pulumi-study-net --output json
pulumi do docker:index:Container read <full-id> --stateless --output json
```

O primeiro devolveu a rede com os containers vinculados; o segundo, as propriedades do container. O `--help` em
cada nível descreve inputs e outputs a partir do schema. O modo stateless não registra nada; o stateful, que é o
padrão, registra o que cria no estado, mantendo aplicação de políticas e detecção de divergência.

Duas particularidades: em modo stateless, o provedor do Docker não lê a variável `DOCKER_HOST` e falha com
`unable to parse docker host 'null'` até que o `--provider-file` informe o `host:`; e o `read` exige o
identificador completo do provedor, e não o identificador curto do `docker ps`.

A documentação do Pulumi lista "agent-driven ad-hoc operations" como caso de uso desse comando.

## 8. Segredos ficam cifrados, com a chave em outro local

Com o backend Cloud, o `Pulumi.dev.yaml` contém `secure: AAABAHO9YVst...`, e a chave pertence ao serviço. Com o
backend de arquivo, o mesmo arquivo contém `encryptionsalt: v1:...` e o texto cifrado, com a chave derivada de
`PULUMI_CONFIG_PASSPHRASE`. A busca pelo valor de um segredo de teste no arquivo de estado, no checkpoint e no
backup não encontrou ocorrências.

No lado HCL, o valor marcado como `sensitive` é omitido na saída do plano (`(sensitive value)`) e gravado em
texto claro no estado:

```
$ grep -c "hello from a sensitive variable" terraform.tfstate
1
```

O OpenTofu tem cifra de estado desde a versão 1.7, não habilitada por padrão; o Terraform não tem equivalente.

## 9. A propriedade termina na fronteira do stack

`docker.RemoteImage` remove a imagem local durante o destroy, por padrão. Como o container do experimento 01
pertence a outro stack, a remoção falhou com `conflict: unable to delete nginx:1.27-alpine (must be forced) -
container c980b1521138 is using its referenced image`. O motor não tinha informação para prever o conflito: o
estado é por stack, e os stacks não se enxergam.

O cenário foi reproduzido com OpenTofu e dois estados independentes, com o mesmo resultado:

```
Error: Unable to remove Docker image: ... conflict: unable to delete alpine:3.20 (must be forced)
- container 02c04ba489ac is using its referenced image d9e853e87e55
```

A imagem permaneceu e o serviço do outro estado continuou no ar. O limite de posse decorre da separação do
estado em unidades, e não do Pulumi.

## 10. A ferramenta tem recursos voltados a agentes

O CLI provisionou uma conta efêmera no Pulumi Cloud durante o estudo, sem solicitação, imprimiu um link de
reivindicação em cada comando e indicou que o link deveria ser repassado ao usuário. É recurso documentado:
contas de agente concedem conta gratuita com acesso de escrita por 72 horas e janela de reivindicação de 30
dias, com o estado em modo somente leitura após o período
([documentação](https://www.pulumi.com/docs/administration/concepts/agent-accounts/)).

Além disso: `pulumi neo`, com execução local de ferramentas, modos de aprovação e de permissão, e modo
`--print` descrito como "intended for use with other AI agents and scripts"; servidor MCP com ferramentas de
consulta, schema do provedor e delegação ao Neo; catálogo de Agent Skills; e o `pulumi do`. O servidor MCP e o
agente hospedado não foram exercitados, porque exigem conta reivindicada.

## 11. Uma substituição que falha não é atômica

Com a porta 8080 ocupada, os dois lados falharam do mesmo modo:

```
Error: Unable to start container: ... driver failed programming external connectivity on endpoint
pulumi-guide-nginx: Bind for 0.0.0.0:8080 failed: port is already allocated
```

A sequência já havia removido o container em funcionamento e criado o substituto. A atualização terminou com a
aplicação indisponível, sem rollback, e com um container remanescente no daemon em estado `Created`. A
recuperação exigiu corrigir a configuração e executar `pulumi up`, o que criou um terceiro container e deixou o
remanescente no daemon.

| Ferramenta | Indicação no plano | Ordem executada | Resultado |
| --- | --- | --- | --- |
| Pulumi | `+- docker:index:Container nginx replace [diff: ~ports]` | remove o antigo, cria o novo | container em `Created`, serviço fora do ar |
| OpenTofu | `# docker_container.web must be replaced` e `~ external = 8081 -> 8080 # forces replacement` | `Destroying...` e depois `Creating...` | container em `Created`, serviço fora do ar |

O HCL permite pedir a ordem inversa com `lifecycle { create_before_destroy = true }`, e o Pulumi tem a opção
`delete_before_replace`, com a ressalva de que o provedor pode exigir a remoção prévia. O preview não prevê
falhas de inicialização, porque a porta só é vinculada quando o container inicia.

## 12. Comportamentos ausentes da documentação oficial

| Comportamento | Onde está registrado |
| --- | --- |
| `--plan` funciona, mas está oculto no `pulumi up --help` da versão 3.263.0 | Item 3 |
| Asserções de teste passam sem verificar nada, porque o registro é assíncrono | Item 5 |
| Substituição malsucedida deixa remanescente no daemon, sem rollback | Item 11 |
| O modo stateless do `pulumi do` não lê a variável de ambiente do provedor | Item 7 |
| A seleção de stack quebra quando o proprietário do estado muda | Item 17 |

## 13. Concorrência

Duas operações simultâneas sobre o mesmo estado não se atropelam: o segundo processo falha antes de alterar
qualquer coisa.

| Ferramenta e backend | Mensagem |
| --- | --- |
| Pulumi com backend Cloud | `error: [409] Conflict: Another update is currently in progress.` |
| Pulumi com backend de arquivo | `error: the stack is currently locked by 1 lock(s). Either wait for the other process(es) to end or delete the lock file with pulumi cancel.` |
| OpenTofu com backend local | `Error: Error acquiring the state lock`, com `resource temporarily unavailable` e a indicação de `-lock=false` |

## 14. Superfícies fora do fluxo revisável

- `pulumi do --stateless` não registra estado, e portanto não passa por política nem por detecção de
  divergência;
- o arquivo de plano pode conter segredos em texto claro quando `--show-secrets` é usado com `--save-plan`,
  conforme a ajuda do CLI;
- a conta de agente é provisionada automaticamente na ausência de credencial (item 10).

## 15. Limites de escopo

- **não é ferramenta de gestão de configuração.** Cria a máquina e pode entregar um `cloud-init` ou executar um
  comando remoto; instalar e manter software dentro do servidor é tarefa de outra categoria;
- **não é plataforma de operação contínua.** Executa quando chamado, sem laço de reconciliação;
- **não tem cobertura universal de alvos.** Cada alvo depende de um provedor existente.

## 16. Comparação de tempos

Topologia idêntica nas duas famílias: uma rede, duas imagens e dois containers.

| Medição | Pulumi 3.263.0 | OpenTofu 1.11.5 | Terraform 1.16.3 |
| --- | --- | --- | --- |
| Plano inicial, sem estado | 3,2s | 0,15s | 0,14s |
| Aplicação | 6s (6 recursos) | 2,6s (5 recursos) | não executada |
| Remoção | 10,1s | 4,5s | não executada |
| Plano sem mudanças | 3,2s | 2,2s | 0,14s |

Duas ressalvas: o Pulumi gravou o estado no Pulumi Cloud, com ida e volta de rede, e o HCL em arquivo local; e a
contagem de recursos difere, porque o Pulumi registra o provedor como recurso. Os números servem como ordem de
grandeza, não como comparação controlada.

Outro confundimento a considerar: o lado HCL depende do provedor `kreuzwerker/docker`, mantido pela comunidade,
enquanto o provedor Docker do Pulumi é nativo. Diferenças de comportamento entre as famílias podem vir do
provedor, e não da ferramenta.

## 17. Obstáculos encontrados na execução

Falhas ocorridas ao montar o estudo, com causa e correção. São os problemas que a equipe provavelmente
enfrentará na primeira execução.

| Falha | Causa | Correção |
| --- | --- | --- |
| `template 'docker-python' not found` | o template não existe no repositório oficial | escrever o projeto manualmente, com `Pulumi.yaml` e `__main__.py` |
| `TypeError: sequence item 1: expected str instance, int found` | `Output.concat` aceita apenas strings | `str(host_port)` |
| `failed to connect to any docker daemon` | Docker em modo rootless; o provedor não consulta o `docker context` | `export DOCKER_HOST=unix:///run/user/1000/docker.sock` |
| `AttributeError: module 'pulumi' has no attribute 'is_secret'` | o método pertence ao valor, e não ao módulo | `valor.is_secret()` |
| Testes passando sem verificar nada | registro assíncrono de recursos | envolver em `@pulumi.runtime.test`, retornando um future |
| `conflict: unable to delete nginx:1.27-alpine` | outro stack usa a mesma imagem | `keep_locally=True` ou ordem de remoção acordada (item 9) |
| `must be passed in to proceed when running in non-interactive mode` | `up --plan` pede confirmação | acrescentar `--yes` |
| `unable to open state directory "file://..."` | o diretório do backend de arquivo não existe | criar antes com `mkdir -p` |
| `unable to parse docker host 'null'` em `pulumi do` | o modo stateless não lê a variável de ambiente | `--provider-file` com `host:` (item 7) |
| `no stack selected`, com o stack aparecendo no `pulumi stack ls` | o proprietário do estado mudou | `pulumi stack select <org>/dev` em cada projeto |

Os comandos e a ordem de execução estão em `03-reproducao.md`.
