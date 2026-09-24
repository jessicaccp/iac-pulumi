# Levantamento

Levantamento do cluster compartilhado onde a medição de tempo vai rodar. Todos os comandos são de leitura: nada
cria, altera ou remove recurso. A saída é o insumo para dimensionar a topologia e para preencher a seção Estado do
ambiente de `04-tempos.md`.

## Comando

```bash
./scripts/collect-cluster-info.sh
```

A saída aparece na tela e fica gravada em `~/bench/cluster-info-<data>.txt`, que é o arquivo a repassar para quem
for consolidar o desenho. O script leva menos de um minuto e pode ser rodado quantas vezes for preciso.

## O que ele responde

| Seção da saída | Pergunta que ela fecha |
| --- | --- |
| ferramentas desta máquina | O que já existe instalado, incluindo se o Pulumi está presente, e quanto espaço há na home |
| acesso | Qual contexto do kubeconfig está ativo, qual namespace ele adota por padrão e o que a credencial atual pode fazer |
| nós | Quantos nós, quais papéis, quanto cada um oferece de CPU, memória e pods, e quais taints impedem agendamento |
| o que terceiros já reservaram | Quanto de cada nó já está comprometido por requisição de outros serviços |
| uso real por nó | Quanto está em uso agora, lido do kubelet, sem depender de `metrics-server` |
| namespaces e quem ocupa | Quantos pods cada namespace tem, o que mostra o que já roda e quem mais usa o cluster |
| teto por namespace | Se algum namespace já impõe `ResourceQuota` ou `LimitRange` |
| storage e entrada | A storage class padrão e como o laboratório publica serviço para fora |
| registry interno | Endereço e porta do registry do laboratório, para não depender de pull externo |
| metrics-server | Se `kubectl top` serve como fonte de medida neste cluster |
| saída de rede | Se a máquina alcança `get.pulumi.com` e o PyPI, o que decide entre instalação direta e cópia de arquivos |

## Segurança

- nenhum comando cria, altera, reinicia ou remove qualquer objeto;
- `kubectl describe`, `kubectl get` e `kubectl get --raw .../proxy/stats/summary` são leitura pura;
- o kubeconfig pessoal em `~/.kube/config` não é editado em nenhum momento;
- a saída não contém credencial, porque o kubeconfig não é impresso.

## Outros scripts

- `scripts/setup-pulumi.sh` instala o CLI e o ambiente Python, sem `sudo`. O CLI e os plugins ficam em
  `~/.pulumi`, o venv fica em `~/workspace/pulumi/.venv`, e o arquivo de variáveis, em
  `~/.pulumi/bench-env.sh`, para ser carregado em cada shell novo;
- `scripts/pulumi-preview-check.sh` confirma que o provedor Kubernetes alcança o cluster, usando somente `preview`,
  com estado em diretório temporário, sem criar nada no cluster.
