# Estudo de Pulumi

Registro das verificações feitas ao executar o [Pulumi](https://www.pulumi.com), ferramenta de infraestrutura
como código, em setembro de 2026, para apoiar a escolha de ferramenta pela equipe. O alvo das execuções é o
Docker da máquina local, porque não havia credencial de nuvem disponível. As afirmações verificadas aparecem
acompanhadas das saídas de terminal; o que depende apenas da documentação oficial está identificado.

O conteúdo está em `docs/`, com quatro documentos, e em `experiments/`, com seis programas Pulumi em Python e um
programa em HCL para a comparação com OpenTofu e Terraform.

## Documentos

| Documento | Assunto |
| --- | --- |
| `docs/00-duvidas.md` | As perguntas que a escolha costuma levantar, com a resposta verificada |
| `docs/01-verificacoes.md` | O que foi executado e observado, com a evidência de cada item |
| `docs/02-comparacao.md` | Comparação entre as três ferramentas, licenças e adequação por cenário |
| `docs/03-reproducao.md` | Configuração de referência, comandos dos sete experimentos e lista de verificação |

Percursos de leitura:

- **decidir:** `00-duvidas.md` e `02-comparacao.md`;
- **avaliar a evidência:** `01-verificacoes.md`;
- **repetir as execuções:** `03-reproducao.md`.

## Experimentos

| Experimento | O que demonstra |
| --- | --- |
| `01-docker-python` | Imagem e container, com configuração e outputs |
| `02-language-and-graph` | Laços, valor secreto na configuração, `Output.apply` e grafo de dependências |
| `03-unit-tests-with-mocks` | Programa testado em processo, sem daemon e sem CLI |
| `04-automation-api` | `preview`, `up` e `destroy` chamados de dentro do Python |
| `05-local-backend-and-state` | Backend de arquivo, segredo por passphrase e formato do estado |
| `06-network-and-metrics` | Rede com servidor e gerador de tráfego, e o coletor de métricas |
| `07-docker-hcl` | A mesma topologia escrita em HCL, para OpenTofu e Terraform |
