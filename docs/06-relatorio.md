# Relatório: quanto tempo o Pulumi leva no cluster

O Pulumi é uma ferramenta de infraestrutura como código: em vez de criar serviços à mão, você descreve em código
Python o que quer que exista, e ele mostra o que vai fazer, faz, guarda o registro do que criou e sabe remover tudo
depois. Este relatório mede quanto tempo isso leva no cluster do laboratório, em duas situações: criar do zero e
mudar um detalhe num ambiente que já está no ar.

São duas execuções de 24 de setembro de 2026, com 26 ciclos no total, nenhuma falha e cerca de trinta minutos de
janela. Tudo o que aparece aqui saiu do JSON e dos logs dessas execuções.

## Resumo

- criar 10 módulos do zero leva cerca de 12 segundos até os serviços estarem funcionando, e 100 módulos, cerca de
  38 segundos;
- o tempo cresce quase linearmente com o tamanho, cerca de 0,3 segundo por módulo, mais um custo fixo de alguns
  segundos;
- remover é a operação mais cara por módulo, quase o dobro da criação;
- mudar um módulo num ambiente grande é barato: 3 a 4 segundos de aplicação e cerca de 7 até o serviço novo estar
  funcionando, mas o plano e a remoção continuam custando o mesmo que num ciclo completo.

## 1. O que foi medido

Cada ciclo mede cinco tempos:

| Tempo | O que é, em palavras simples |
| --- | --- |
| Plano | Quanto o Pulumi leva para calcular o que precisa criar, sem criar nada |
| Aplicação | Quanto ele leva para entregar a criação ao cluster |
| Convergência | Quanto o cluster leva até os serviços estarem funcionando de verdade |
| Plano de novo | Depois de aplicar, ele não deve propor mudança nenhuma |
| Remoção | Quanto ele leva para apagar tudo o que criou |

A distinção importante: plano e aplicação medem a ferramenta, e convergência mede o cluster. Se os serviços já
existem e só falta o cluster terminar de subir, o tempo é do cluster, não do Pulumi.

Foram medidos três tamanhos, 10, 50 e 100 módulos, com cinco repetições cada, mais uma rodada de aquecimento
descartada. Um módulo é um serviço web pequeno: um container com nginx e o endereço interno para chegar nele, o que
dá três objetos no cluster por módulo. Depois, com 50 e com 100 módulos já no ar, foi medida a mudança de um módulo,
que é o caso do dia a dia.

## 2. Onde rodou

| Item | Valor |
| --- | --- |
| Cluster | Kubernetes 1.32.13, um nó de controle e três de trabalho, Fedora 43, rede flannel |
| Máquinas | Intel i5-10400, 12 threads, cerca de 7,7 GB de memória alocável por nó |
| Uso | cluster compartilhado, com jenkins, jupyterhub, sonarqube e o registry de terceiros rodando em paralelo |
| Onde o Pulumi roda | no nó de controle, Pulumi 3.263.0, provedor do Kubernetes 4.34.2, estado em arquivo local |
| Isolamento | uma pasta própria no cluster, com acesso restrito a ela, que não alcança o resto |
| Limites | cada container tem pedido e teto de CPU e de memória declarados, para não atrapalhar quem usa o cluster |
| Recorte | sem nuvem, sem volume de disco e sem comando nos nós; nada de escopo do cluster é criado |
| Relógio | o cluster está seis dias atrás da hora real, e o JSON guarda as duas horas lado a lado |

## 3. Como foi medido, e por quê

O medidor é um programa em Python, `bench.py`, que roda os comandos do Pulumi e cronometra cada um por fora, com
relógio monotônico, guardando um log por comando e um JSON com os tempos. Ele foi escrito para este estudo porque
medir à mão não dá o que precisávamos:

- **a convergência precisa ser medida por fora**, perguntando ao cluster a cada segundo quantos serviços já estão
  disponíveis, porque o Pulumi pode terminar antes de o cluster terminar;
- **cada comando tem teto de tempo**, porque um travamento do motor já consumiu vinte e três minutos de uma janela;
- **a tela mostra que está vivo** a cada 15 segundos, e o `Ctrl-C` mata o comando, libera o registro do Pulumi e diz
  como limpar o cluster;
- **cada ciclo começa de um cluster limpo**, com uma limpeza própria antes de medir, e o medidor se recusa a começar
  se a pasta tiver sobra de uma execução anterior;
- **o aquecimento** garante que a imagem do container já esteja baixada nos nós antes de a medida valer.

Três escolhas que mudam a leitura dos números e precisam ser declaradas: a espera do Pulumi pelo serviço ficou
desligada nos dois objetos, então a aplicação mede a entrega ao cluster e não a prontidão; a remoção também mede a
entrega do comando, não o desaparecimento dos objetos, que termina alguns segundos depois; e o plano desta série rodou
com o paralelismo padrão do CLI, enquanto a aplicação e a remoção usaram 10, porque o medidor só passou a fixar 10 no
plano depois desta execução.

## 4. Resultados

### Criar do zero

Medianas em segundos, com cinco repetições por tamanho:

| Módulos | Plano | Aplicação | Convergência | Plano de novo | Remoção |
| --- | --- | --- | --- | --- | --- |
| 10 | 1,80 | 3,94 | 11,62 | 1,80 | 5,60 |
| 50 | 2,20 | 15,44 | 21,12 | 2,80 | 28,82 |
| 100 | 3,80 | 34,21 | 37,97 | 4,00 | 57,04 |

- **o plano quase não depende do tamanho**: 1,8 a 3,8 segundos de 10 a 100 módulos;
- **a aplicação cresce cerca de 0,34 segundo por módulo** e a **convergência, 0,29**, mas a convergência começa com
  um custo fixo de cerca de 9 segundos, que é o cluster deixando o primeiro serviço pronto;
- **a remoção é a fase mais sensível ao tamanho**, cerca de 0,57 segundo por módulo, quase o dobro da aplicação;
- **as repetições variaram pouco**: a aplicação de 100 módulos variou cerca de 10% em torno da mediana, e a remoção
  de 100, cerca de 3%. A exceção é o plano de novo de 100 módulos, com um caso de 6 segundos contra mediana de 4;
- **o plano de novo não propôs mudança nenhuma** nas três escalas, o que mostra que ele não refaz o que já está
  certo.

### Mudar um módulo num ambiente que já existe

| Ambiente | Plano | Aplicação | Convergência | Plano de novo | Remoção |
| --- | --- | --- | --- | --- | --- |
| 50 módulos no ar, mudando para 51 | 2,80 | 3,04 | 6,31 | 2,80 | 29,22 |
| 100 módulos no ar, mudando para 101 | 3,80 | 4,09 | 7,65 | 3,80 | 58,04 |

O log confirma que a mudança foi mesmo de um módulo: o plano propôs criar 3 objetos e manter os outros 151 ou 301
intactos, e a aplicação criou só esses 3.

- **o plano de uma mudança custa o mesmo que o plano completo**, porque ele lê o ambiente inteiro para decidir;
- **aplicar um módulo é barato**: 3 a 4 segundos, contra 15 e 34 segundos para criar 50 ou 100 do zero;
- **a remoção não fica mais barata** por a mudança ser pequena: ela apaga tudo, e ficou igual à da criação do zero;
- em resumo, num ambiente grande quem pesa é o plano e a remoção, não a mudança.

## 5. O que os números não dizem

- medem só o Pulumi, num cluster Kubernetes, com estado em arquivo local e sem nuvem;
- a aplicação mede a entrega dos objetos ao cluster, e não a espera até eles ficarem prontos: essa espera estava
  desligada de propósito, então o número é menor do que seria com ela ligada;
- a janela não foi exclusiva: o cluster estava sendo usado por outros serviços ao mesmo tempo;
- a remoção também mede a entrega do comando, e não o desaparecimento dos objetos: em 17 dos 18 ciclos da criação do
  zero ainda havia de 4 a 10 objetos terminando quando o ciclo seguinte começou;
- a precisão é de 0,2 segundo por fase, e a convergência é consultada a cada segundo, que é a definição da medida;
- o ciclo completo num comando só (`pulumi up --yes`), que é o que o usuário roda no dia a dia, não foi medido: o que
  existe é a soma de plano e aplicação;
- não foi medido o consumo de CPU e memória do Pulumi na máquina que o executa.

## 6. Onde está a evidência

| Item | O que contém |
| --- | --- |
| `experiments/08-kubernetes-timing/resultados/serie-20260918-164216.json` | A execução de criação do zero: ambiente e os cinco tempos de cada um dos 18 ciclos |
| `experiments/08-kubernetes-timing/resultados-incremental/serie-20260918-171627.json` | A execução da mudança de um módulo: os 8 ciclos, com a base de cada um |
| `experiments/08-kubernetes-timing/resultados/logs/` e `resultados-incremental/logs/` | Um log por comando das duas execuções, com a linha de comando, o horário e a saída completa |
| `experiments/08-kubernetes-timing/bench.py` | O medidor, com os testes em `tests/` |
| `04-tempos.md` | Desenho, condições, procedimento e achados da medição |
| `05-levantamento.md` | Levantamento do cluster, com o script de coleta |
