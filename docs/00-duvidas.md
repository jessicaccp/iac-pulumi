# Dúvidas

Respostas para as perguntas que costumam aparecer na escolha de uma ferramenta de infraestrutura como código,
com o resultado das verificações feitas ao executar o Pulumi em setembro de 2026, usando o Docker como alvo.
Cada resposta indica onde está a evidência e, quando for o caso, o que não foi verificado.

## 1. Conta, estado e segredos

### 1.1 Precisa de conta na Pulumi?

Não, para o ciclo completo. Com `PULUMI_BACKEND_URL=file:///caminho` e `PULUMI_CONFIG_PASSPHRASE`, os comandos
`preview`, `up`, `destroy`, `refresh`, o uso de planos, o `pulumi do` e o histórico funcionam sem login, e o
`pulumi whoami` devolve o usuário do sistema operacional.

A conta passa a ser necessária para o console web, o Insights, o ESC, a política em nível de organização e as
superfícies de agente (Neo e servidor MCP). Sem credencial e em execução sob um agente, o CLI provisiona uma
conta efêmera sozinho, como aconteceu nas execuções deste estudo.

Evidência: `03-reproducao.md`, seção do backend de arquivo.

### 1.2 Onde fica o estado, e quem tem a chave dos segredos?

| Backend | Estado | Chave dos segredos |
| --- | --- | --- |
| Nuvem da Pulumi | no serviço | o serviço |
| Arquivo local | JSON no disco | derivada da passphrase |
| Bucket de objeto | no bucket | passphrase ou cofre externo (não exercitado) |

No backend de arquivo, o estado fica em `.pulumi/stacks/<projeto>/<stack>.json`, com histórico e backups ao
lado. O arquivo versionável, `Pulumi.dev.yaml`, guarda apenas `secure:` cifrado.

### 1.3 O segredo fica protegido no estado?

No Pulumi, sim. A busca pelo valor de um segredo de teste no arquivo de estado, no checkpoint e no backup não
encontrou ocorrências. Com backend de arquivo, quem tiver o arquivo **e** a passphrase lê o segredo.

No lado HCL, não: o estado guarda o valor em texto claro mesmo com `sensitive = true`, e o `sensitive` protege
apenas a saída do plano. O OpenTofu tem cifra de estado desde a versão 1.7, desligada por padrão.

### 1.4 O segredo aparece no arquivo de plano?

Só se `--show-secrets` for usado junto de `--save-plan`, conforme a própria ajuda do CLI. Arquivar planos sem
essa flag não expõe segredo.

## 2. Plano, preview e concorrência

### 2.1 O plano serve como contrato do que foi aprovado?

Em parte. `pulumi preview --save-plan` seguido de `pulumi up --plan` aplica exatamente aquele plano, e o campo
`magic` faz a aplicação recusar arquivo editado, com a mensagem `violates plan: properties changed`.

Duas ressalvas: o `--plan` funciona mas não aparece no `pulumi up --help` da versão 3.263.0, e o plano é
gerado a partir do programa, de modo que um programa diferente produz um plano diferente.

No lado HCL, `plan -out` seguido de `apply tfplan` é o fluxo documentado. Plano adulterado também foi
recusado, mas por verificação de consistência interna, e não por um campo de integridade próprio.

### 2.2 O preview mostra o que existe de verdade?

Não por padrão. Com um container removido por `docker rm -f`, o `preview` informou `5 unchanged` e o
`--expect-no-changes` concordou. Somente `pulumi preview --refresh` detectou a diferença, e com ele o código de
saída passou de 0 para 7.

No lado HCL o plano consulta o ambiente por padrão: o mesmo cenário resultou em `1 to add`, sem nenhuma flag.
A capacidade existe nos dois; o padrão é que difere.

### 2.3 Duas execuções simultâneas no mesmo estado se atropelam?

Não. Nos três casos o segundo processo falha antes de alterar qualquer coisa:

| Ferramenta e backend | Mensagem |
| --- | --- |
| Pulumi com backend Cloud | `[409] Conflict: Another update is currently in progress.` |
| Pulumi com backend de arquivo | `the stack is currently locked by 1 lock(s). Either wait for the other process(es) to end or delete the lock file with pulumi cancel.` |
| OpenTofu com backend local | `Error: Error acquiring the state lock`, com `resource temporarily unavailable` e a indicação de `-lock=false` |

## 3. Verificação antes de aplicar

### 3.1 Dá para verificar uma mudança sem criar nada, e quanto custa?

Dá, nos dois lados, com custo equivalente.

| Ferramenta | Verificação sem alvo | Tempo |
| --- | --- | --- |
| Pulumi | 7 testes com `set_mocks`, sem daemon, CLI ou credencial | 0,14s |
| OpenTofu | 3 asserções com `mock_provider` | 0,14s |
| Terraform | 3 asserções com `mock_provider` | 0,10s |

A diferença está na linguagem das asserções, escritas em Python ou Jest no Pulumi, e em expressões HCL nos
outros dois. Duas armadilhas foram encontradas do lado do Pulumi: asserção síncrona passa sem verificar nada
porque o registro é assíncrono, e mock que não devolve a propriedade lida pelo programa faz um teste de
ligação passar vazio.

## 4. Falhas e recuperação

### 4.1 O que acontece quando a execução falha no meio?

A substituição não é atômica e não há rollback. Com a porta 8080 ocupada, o container em funcionamento foi
removido, a criação do substituto falhou com `Bind for 0.0.0.0:8080 failed: port is already allocated`, um
container remanescente ficou no daemon em estado `Created` e o serviço permaneceu fora do ar. O estado registra
o recurso.

O comportamento foi idêntico no OpenTofu com o mesmo provedor de destino, o que indica origem na combinação
entre ferramenta e provedor, e não em uma delas. A recuperação exige inspeção do daemon, correção da causa e
nova aplicação.

### 4.2 Um recurso pode ser usado por dois estados ao mesmo tempo?

Pode, e a remoção de um deles falha. Com dois estados declarando a mesma imagem, o destroy de um terminou em
`Error: Unable to remove Docker image: ... conflict: unable to delete alpine:3.20 (must be forced) - container
... is using its referenced image`. A imagem permaneceu e o serviço do outro estado continuou no ar.

A propriedade termina na fronteira do estado, o que vale também para o lado HCL. Como mitigação: `keep_locally`
e uma ordem de remoção acordada entre os estados.

## 5. Custo do ciclo

| Medição, topologia de uma rede, duas imagens e dois containers | Pulumi 3.263.0 | OpenTofu 1.11.5 | Terraform 1.16.3 |
| --- | --- | --- | --- |
| Plano inicial, sem estado | 3,2s | 0,15s | 0,14s |
| Aplicação | 6s | 2,6s | não executada |
| Remoção | 10,1s | 4,5s | não executada |
| Plano sem mudanças | 3,2s | 2,2s | 0,14s |

Os números são ordem de grandeza, com duas ressalvas: o Pulumi gravou o estado no Cloud, com ida e volta de
rede, e o HCL em arquivo local; e a contagem de recursos difere, porque o Pulumi registra o provedor como
recurso, o que faz a topologia aparecer como 6 recursos em vez de 5.

## 6. Cobertura

### 6.1 Funciona com equipamento de rede?

Sim. O provedor Cisco Catalyst SD-WAN tem 262 recursos, conferidos no schema, e o catálogo inclui Meraki, ISE,
IOS XE, NX-OS, f5 BIG-IP, Fortinet, Check Point, Cloudflare, Akamai, Fastly, Cilium e Consul.

Não existe provedor universal: cada alvo depende de alguém ter escrito o provedor. Sem provedor, as
alternativas são escrever um ou usar um provedor genérico de comandos. Existem também os pacotes *Any
Terraform Provider* e *Any HCL Module*, que aproveitam o ecossistema do outro lado.

### 6.2 O que a ferramenta não faz?

- **não é ferramenta de gestão de configuração:** cria a máquina e pode entregar um `cloud-init` ou executar um
  comando remoto, mas instalar e manter software dentro do servidor é outra categoria de ferramenta;
- **não é plataforma de operação contínua:** executa quando chamada, sem laço de reconciliação;
- **não cobre todo alvo existente:** depende de provedor escrito por terceiros.

## 7. Agentes de IA

### 7.1 A ferramenta serve para um agente operar infraestrutura?

É onde o Pulumi tem superfície própria, sem equivalente no lado HCL:

| Recurso | O que oferece |
| --- | --- |
| `pulumi neo` | Agente com execução local de ferramentas, modos de aprovação e de permissão, e modo `--print` para uso por outros agentes |
| Servidor MCP | Consulta de stacks e recursos, schema do provedor e delegação ao Neo, por chamadas de ferramenta |
| Agent Skills | Catálogo de conhecimento publicado pela Pulumi, integrado ao Neo |
| Conta efêmera de agente | Conta gratuita provisionada automaticamente quando não existe credencial |
| `pulumi do` | Qualquer provedor como interface de linha de comando, com `--output json` |
| `--json` em preview, up e destroy | Resultado e fluxo de eventos em formato de dados, com as dependências por recurso |

O servidor MCP e o agente hospedado não foram exercitados, porque exigem conta reivindicada.

### 7.2 Existe controle do que o agente pode fazer?

No motor, não. Três superfícies ficam fora do fluxo revisável:

- `pulumi do --stateless` não registra estado, então não passa por política nem por detecção de divergência;
- o arquivo de plano pode conter segredos em texto claro quando `--show-secrets` é usado com `--save-plan`;
- a conta de agente é provisionada automaticamente, sem revisão humana.

O que existe é política do agente do fornecedor, com os modos de aprovação e de permissão do Neo, e não uma
propriedade do motor que outros agentes herdem.

## 8. Licença e governança

| Artefato | Licença | Uso e distribuição |
| --- | --- | --- |
| Núcleo do Pulumi, SDKs e plugin do provedor Docker | Apache 2.0 | Uso, modificação e redistribuição, inclusive comercial, mantendo os avisos |
| Provedores por ponte (AWS, GCP, Azure) | O repositório é Apache 2.0 | Contêm código do provedor equivalente do Terraform, cuja licença se aplica a esses arquivos, em geral MPL 2.0. Verificar caso a caso |
| Pulumi Cloud, Neo, Insights | Comercial | Termos de uso do serviço |
| Terraform | BUSL 1.1 | Uso em produção concorrente com a HashiCorp é restrito; cada arquivo converte para MPL 2.0 quatro anos após a publicação |
| OpenTofu | MPL 2.0, sob a Linux Foundation | Uso livre, inclusive comercial, com obrigação de compartilhar modificações nos arquivos MPL |

Para estudo e para construir ferramentas que chamam as ferramentas, nenhuma das licenças impõe restrição. Para
publicar um artefato que terceiros executarão em produção, o OpenTofu é o caminho que dispensa análise
jurídica.

## 9. Documentação oficial

Cinco comportamentos observados na execução não constam da documentação consultada:

| Comportamento | Onde está registrado |
| --- | --- |
| `--plan` funciona, mas está oculto no `pulumi up --help` da versão 3.263.0 | Achado 3 |
| A seleção de stack quebra quando o proprietário do estado muda | Achado 12 |
| Asserções de teste passam sem verificar nada, porque o registro é assíncrono | Achado 5 |
| Substituição malsucedida deixa remanescente no daemon, sem rollback | Achado 11 |
| O modo stateless do `pulumi do` não lê a variável de ambiente do provedor | Achado 7 |

## 10. O que não foi verificado

- **Nuvem:** nenhuma credencial de AWS, GCP ou Azure estava disponível, então todo o estudo usou o Docker local.
- **Backends de objeto:** S3, GCS e Azure Blob não foram exercitados.
- **Política como código e importação de recurso:** não testadas nos dois lados.
- **Superfícies do serviço da Pulumi:** Neo, servidor MCP e Insights foram lidos na documentação, não
  executados.
- **Terraform e OpenTofu:** executados apenas na parte compartilhada com o Pulumi, que é a topologia em Docker
  escrita em HCL.
- **Tempo controlado:** a comparação de tempos tem backend e contagem de recursos diferentes entre os lados.
