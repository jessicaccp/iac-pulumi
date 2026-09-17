# Comparação

Comparação entre Pulumi, Terraform e OpenTofu, orientada à decisão. O que se refere ao Pulumi foi verificado na
execução, com o registro em `01-verificacoes.md`. Do lado HCL, o mesmo programa em Docker foi executado com
OpenTofu 1.11.5 e Terraform 1.16.3. O que depende do serviço da Pulumi e as licenças vêm da documentação, com
a fonte indicada.

## 1. Em comum

| Elemento | Presente nos três |
| --- | --- |
| Ciclo | escrever, planejar, aplicar, registrar estado, detectar divergência |
| Provedores | plugins que se comunicam com APIs, baixados sob demanda |
| Plano | mudanças apresentadas antes da aplicação |
| Estado | registro do que foi criado, com valores devolvidos pelas APIs |
| Backends | estado local, em armazenamento de objetos ou no serviço do fornecedor |
| Segredos | tratamento específico para valores sensíveis |
| Módulos | recursos agrupados em unidades reaproveitáveis |
| Política | regras avaliadas antes da aplicação |
| Multiprovedor | AWS, Cloudflare, Kubernetes e outros no mesmo programa |

A diferença de fundo é única: **a linguagem em que o estado desejado é calculado**.

## 2. HCL e linguagem de programação

**Terraform e OpenTofu usam HCL**, linguagem declarativa própria, com primitivas como `count`, `for_each`,
blocos `dynamic`, expressões `for`, condicional e funções. Os limites são os da linguagem.

**O Pulumi usa Python, TypeScript, Go, C#, Java ou YAML.** Neste estudo, Python.

O efeito prático aparece na modelagem: laços, condições, funções, classes e bibliotecas ficam disponíveis, e uma
frota de serviços com regras por ambiente resulta de um laço em vez de blocos repetidos. Em HCL isso é feito com
`for_each` e módulos, e o limite aparece mais cedo.

O custo é que o programa passa a ser código arbitrário. Revisar um arquivo HCL consiste em revisar uma lista de
recursos, verificável linha a linha; revisar um programa consiste em revisar software, e um laço mal escrito pode
gerar centenas de recursos onde se esperava três.

A alternativa de usar linguagem de programação sobre o Terraform era o CDKTF, descontinuado com repositório
arquivado em 10 de dezembro de 2025. A HashiCorp declarou que "o CDKTF não encontrou product-market fit em
escala" e recomendou migração para HCL ou AWS CDK
([README do repositório](https://github.com/hashicorp/terraform-cdk)). Existe um fork comunitário; com suporte
de fornecedor, a alternativa é o Pulumi.

## 3. Onde o Pulumi é melhor

- **Modelagem de infraestrutura complexa ou gerada**, por usar linguagem de programação.
- **Automação programática com resultado tipado**, pela Automation API: `preview`, `up` e `destroy` como
  chamadas de função no mesmo processo, com `change_summary` e `outputs` como objetos. Não há SDK oficial em
  processo no lado HCL.
- **Segredos cifrados no estado por padrão.** No HCL, `sensitive` protege a saída do plano e o estado guarda o
  valor em texto claro, salvo se a cifra de estado do OpenTofu for habilitada.
- **Recursos voltados a agentes:** `pulumi neo`, servidor MCP, Agent Skills e conta efêmera de agente.
- **Aproveitamento do ecossistema do outro lado**, pelos pacotes *Any Terraform Provider* e *Any HCL Module* e
  pelo comando `pulumi package add`, que gera SDK a partir do schema de qualquer plugin.
- **Dependências explícitas na saída para máquina.** O `steps[].dependencies` lista as URNs por recurso; o plano
  em JSON do HCL não apresenta arestas entre recursos.

## 4. Onde o Pulumi é pior

- **Ecossistema menor.** Em setembro de 2026: o Registry do Pulumi tem **312 pacotes**; o OpenTofu anuncia
  **3.900+ provedores e 23.600+ módulos**; o Registry do Terraform passa de 1.500 provedores. A ponte reduz a
  diferença, mas provedor gerado por ponte carrega texto e semântica do original, e a ajuda do provedor Docker
  do Pulumi menciona "Terraform" em vários campos.
- **Menos referências e mão de obra.** A quantidade de exemplos, respostas e profissionais em HCL é maior, o que
  influi na resolução de problemas e no número de pessoas aptas a revisar.
- **O plano consulta o ambiente apenas com `--refresh`.** No lado HCL o plano lê o ambiente por padrão.
- **Plano como contrato em recurso não documentado.** O `--plan` funciona e recusa adulteração, mas não aparece
  no `pulumi up --help` da versão 3.263.0. No HCL, `plan -out` e `apply tfplan` é o fluxo documentado.
- **Maturidade nas bordas.** `pulumi do` e `pulumi insights` estão marcados como experimentais, e o `neo` é
  recente.
- **Governança e licença mais simples no OpenTofu.** O núcleo do Pulumi é Apache 2.0, mas o produto é de uma
  empresa e a parte completa está no serviço dela. O Terraform passou de MPL 2.0 para BUSL 1.1 na versão 1.6 e
  hoje é "source-available", sem aprovação da OSI; o OpenTofu é o fork sob a Linux Foundation, em MPL 2.0
  permanente.

## 5. Confundimento a considerar

O lado HCL depende do provedor `kreuzwerker/docker`, mantido pela comunidade, com 56 milhões de downloads,
enquanto o provedor Docker do Pulumi é nativo. Campos disponíveis, tratamento de imagens, política de recriação
de containers e mensagens de erro são definidos por quem implementa o provedor. As medições comparam as
ferramentas com esses provedores, e não os provedores entre si.

## 6. Semelhanças mal interpretadas

- **"Terraform é declarativo e Pulumi é imperativo."** Ambos descrevem o estado desejado, e a ferramenta decide
  as operações. A diferença está na linguagem em que esse estado é calculado.
- **"Pulumi é mais moderno."** O modelo é o mesmo, com as mesmas vantagens e problemas. O que difere é
  linguagem, automação, ecossistema e recursos para agentes.
- **"Um é mais seguro que o outro."** A falha na substituição e o conflito de posse entre estados deram
  resultado idêntico nas duas famílias, com o mesmo provedor de destino. São propriedades da combinação entre
  ferramenta e provedor.

## 7. Adequação por cenário

| Cenário | Mais adequado | Motivo |
| --- | --- | --- |
| Referência ou baseline em publicação | Terraform ou OpenTofu | Vocabulário conhecido pela comunidade revisora |
| Alvo com provedor maduro apenas no lado HCL | Terraform ou OpenTofu | Cobertura do provedor |
| Infraestrutura gerada, com repetição e variação | Pulumi | Linguagem de programação, componentes e testes |
| Automação dentro de um serviço próprio | Pulumi | Automation API com resultado tipado |
| Operação por agentes de IA | Pulumi | JSON de plano e eventos, `pulumi do`, MCP, Neo e mocks |
| Segredos que não podem aparecer em disco | Pulumi, ou OpenTofu com cifra de estado | O padrão do HCL grava o valor em texto claro |
| Licença e governança como requisito formal | OpenTofu | MPL 2.0 permanente, sob a Linux Foundation |
| Equipe grande, revisão por leitura | Terraform ou OpenTofu | HCL é mais simples de revisar e tem mais praticantes |
| Muitos provedores heterogêneos em produção | Terraform ou OpenTofu | Catálogo maior, menos dependência de ponte |
| Ensino de IaC para quem já programa | Pulumi, seguido de HCL | A sintaxe não é obstáculo, e o HCL consolida o modelo |

## 8. Síntese

**Melhor:** modelagem com linguagem de programação, automação programática com resultado tipado, segredos
cifrados no estado por padrão, recursos para agentes.

**Pior:** tamanho do ecossistema, volume de referências e profissionais, plano que só lê o ambiente com
`--refresh`, maturidade do plano como contrato e governança de fundação.

**Adequado para:** infraestrutura complexa ou gerada por código, automação dentro de software, cenários com
segredos sensíveis e operação por agentes. **Menos adequado para:** equipes que priorizam volume de exemplos e
vocabulário comum, produção com provedores pouco cobertos, e cenários em que licença e governança de fundação
são requisitos.

## 9. Licenças

| Artefato | Licença | Implicação |
| --- | --- | --- |
| Núcleo do Pulumi (CLI) | Apache 2.0 ([LICENSE](https://github.com/pulumi/pulumi/blob/master/LICENSE)) | Uso, modificação e redistribuição, inclusive comercial, com manutenção dos avisos |
| SDKs Python (`pulumi`, `pulumi-docker`) | Apache 2.0 | Idem |
| Plugin do provedor Docker | Apache 2.0 | Idem; este provedor é nativo, e não uma ponte |
| Provedores por ponte (AWS, GCP, Azure) | O `LICENSE` do repositório é Apache 2.0 | Contêm código do provedor equivalente do Terraform, cuja licença se aplica a esses arquivos (em geral MPL 2.0). Verificar caso a caso antes de redistribuir |
| Pulumi Cloud, Neo, Insights | Comercial | Termos de uso do serviço |
| Terraform | BUSL 1.1 ([LICENSE](https://github.com/hashicorp/terraform/blob/main/LICENSE)) | "Source-available", sem aprovação da OSI. Uso em produção concorrente com a HashiCorp é restrito, e cada arquivo converte para MPL 2.0 quatro anos após a publicação |
| OpenTofu | MPL 2.0 ([LICENSE](https://github.com/opentofu/opentofu/blob/main/LICENSE)), sob a Linux Foundation | Uso livre, inclusive comercial, com obrigação de compartilhar modificações nos arquivos MPL |

Quatro cenários:

- **estudo e pesquisa:** livre nos dois lados. O Terraform sob BUSL permite uso não comercial, mas os termos
  "não produção" e "não concorrente" admitem interpretação;
- **ferramentas que chamam as ferramentas:** livre. Executar um CLI como processo ou importar um SDK Apache 2.0
  não cria obrigações sobre o código novo;
- **escrita ou modificação de provedor:** a licença importa. Provedor nativo é código do autor; provedor por
  ponte carrega código de origem, com as obrigações correspondentes;
- **distribuição de produto concorrente:** com o núcleo do Pulumi em Apache 2.0, a restrição é de marca e de
  serviço; com o Terraform sob BUSL, a restrição é jurídica.

## 10. Fontes

| Afirmação | Fonte | Tipo |
| --- | --- | --- |
| Pulumi tem 312 pacotes no Registry | [pulumi.com/registry](https://www.pulumi.com/registry/) | Medido |
| Pulumi é Apache 2.0 no núcleo | [LICENSE do pulumi/pulumi](https://github.com/pulumi/pulumi/blob/master/LICENSE) | Fonte primária |
| Ecossistema HCL com 3.900+ provedores e 23.600+ módulos | [opentofu.org](https://opentofu.org/) | Declaração do projeto |
| Registry do Terraform com mais de 1.500 provedores | API `registry.terraform.io/v1/providers` | Medido |
| CDKTF descontinuado e arquivado em 10/12/2025 | [README de hashicorp/terraform-cdk](https://github.com/hashicorp/terraform-cdk) | Fonte primária |
| Provedor Docker do lado HCL | `kreuzwerker/docker` 4.6.0, API do Registry do Terraform | Medido |
| Cifra de estado no OpenTofu desde a 1.7 | [opentofu.org](https://opentofu.org/) | Declaração do projeto |
| Terraform em BUSL 1.1 desde a 1.6; OpenTofu em MPL 2.0 sob a Linux Foundation | [opentofu.org](https://opentofu.org/) e [HashiCorp](https://www.hashicorp.com/en/license-faq) | Fonte do projeto e do fornecedor |
| Contas de agente, Neo e servidor MCP | Documentação do Pulumi | Não exercitado |
