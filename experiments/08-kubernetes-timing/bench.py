"""Executa a serie de medicao e grava o resultado em JSON.

Uso:
  python bench.py --sizes 10,50,100 --repetitions 5
  python bench.py --sizes 2 --repetitions 1 --command-timeout 120 --heartbeat 10
  python bench.py --dry-run

Cada tamanho tem uma repeticao de aquecimento, que baixa a imagem nos nos e nao
entra no resumo. O tempo vem de relogio monotonic, entao a hora errada do cluster
nao afeta o resultado; ela fica registrada no cabecalho do JSON.

Nenhum comando roda sem limite de tempo: todo comando auxiliar passa por rodar() e
toda fase longa passa por executar() ou executar_up(), que matam o grupo de
processos no limite e publicam uma batida de coracao enquanto o comando vive. Cada
comando tem log proprio em resultados/logs/, com a linha de comando no cabecalho.

O namespace precisa existir antes, porque o programa nao cria recurso de escopo de
cluster. Ver docs/04-tempos.md.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import statistics
import subprocess
import time
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

FASES = ("preview", "up", "convergencia", "preview_sem_mudanca", "destroy")
BASE = Path(__file__).resolve().parent

LIMITE_AUXILIAR = 30
LIMITE_DO_CANCEL = 60
REQUISICAO_KUBECTL = "--request-timeout=10s"
INTERVALO_DA_CONSULTA = 1.0
INTERVALO_DA_ESPERA = 0.2
PROCESSO_ATUAL: subprocess.Popen | None = None


class ComandoTravou(Exception):
    """O comando passou do limite de tempo e foi interrompido."""


class StackTravado(Exception):
    """O stack tem lock de outra execucao, e nenhum comando de update roda nele.

    Nao herda de RuntimeError de proposito: o ciclo engole RuntimeError para nao
    derrubar a serie, e uma serie inteira com o stack travado nao mede nada.
    """


def matar(processo: subprocess.Popen) -> None:
    """Mata o comando e os filhos, que ficam no mesmo grupo de processo."""
    try:
        os.killpg(processo.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    processo.wait()


def _cabecalho(comando: list[str], limite: int) -> str:
    agora = datetime.now().isoformat(timespec="seconds")
    return f"# comando: {' '.join(comando)}\n# inicio: {agora}  limite: {limite}s\n"


def rodar(
    comando: list[str],
    limite: int = LIMITE_AUXILIAR,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    """Roda um comando auxiliar curto com limite de tempo.

    Nao levanta por codigo de saida diferente de zero: quem chama decide se aquilo
    e erro. Levanta ComandoTravou quando o comando passa do limite, porque um
    kubectl pendurado na leitura do cluster congelaria o medidor inteiro.

    As duas saidas ficam separadas: o kubectl escreve aviso no stderr, e um aviso
    junto do JSON quebraria a leitura do estado dos deployments.
    """
    processo = subprocess.Popen(
        comando,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=cwd,
        start_new_session=True,
    )
    try:
        saida, erro = processo.communicate(timeout=limite)
    except subprocess.TimeoutExpired:
        matar(processo)
        raise ComandoTravou(
            f"passou de {limite}s: {' '.join(comando)}"
        ) from None
    return subprocess.CompletedProcess(comando, processo.returncode, saida, erro)


def ultima_linha(texto: str) -> str:
    """Ultima linha com conteudo, porque o kubectl avisa antes de responder."""
    linhas = [linha.strip() for linha in texto.splitlines() if linha.strip()]
    return linhas[-1] if linhas else ""


def saida_completa(processo: subprocess.CompletedProcess) -> str:
    return "\n".join(
        parte.strip() for parte in (processo.stdout, processo.stderr) if parte.strip()
    )


def _acompanhar(
    processo: subprocess.Popen,
    comando: list[str],
    log: Path,
    limite: int,
    intervalo: int,
    durante: Callable[[float], None] | None = None,
    batida: Callable[[float], None] | None = None,
) -> None:
    """Espera o comando, publica batidas de coracao e mata no limite.

    O limite existe porque um travamento ja consumiu vinte e tres minutos de uma
    janela: sem ele, o medidor espera para sempre. A batida existe para o contrario:
    ver que o comando esta vivo sem esperar pelo fim.
    A convergencia e consultada ao cluster a cada segundo, que e a definicao da
    medida, mas a espera pelo fim do comando e de 0,2s: com um segundo, a deteccao do
    fim atrasava a duracao de cada fase em ate um segundo, o que pesa demais num
    preview de dois segundos.
    """
    inicio = time.monotonic()
    ultima_batida = inicio
    ultima_consulta = -INTERVALO_DA_CONSULTA
    while processo.poll() is None:
        decorrido = time.monotonic() - inicio
        if durante is not None and decorrido - ultima_consulta >= INTERVALO_DA_CONSULTA:
            durante(decorrido)
            ultima_consulta = decorrido
        if intervalo and decorrido - (ultima_batida - inicio) >= intervalo:
            if batida is not None:
                batida(decorrido)
            else:
                print(
                    f"      em andamento: {decorrido:.0f}s"
                    f" (limite {limite}s): {' '.join(comando)}",
                    flush=True,
                )
            ultima_batida = time.monotonic()
        if decorrido > limite:
            matar(processo)
            raise ComandoTravou(
                f"passou de {limite}s: {' '.join(comando)} (log em {log})"
            )
        time.sleep(INTERVALO_DA_ESPERA)


def _longo(
    comando: list[str],
    log: Path,
    limite: int,
    intervalo: int,
    durante: Callable[[float], None] | None = None,
    batida: Callable[[float], None] | None = None,
) -> subprocess.Popen:
    """Inicia o comando com log proprio e acompanha ate o fim.

    O processo fica em PROCESSO_ATUAL porque a sessao propria o isola dos sinais do
    terminal: sem essa referencia, um Ctrl-C deixaria o pulumi criando recurso depois
    de o medidor sair.
    """
    global PROCESSO_ATUAL
    with log.open("w") as arquivo:
        arquivo.write(_cabecalho(comando, limite))
        arquivo.flush()
        processo = subprocess.Popen(
            comando,
            stdout=arquivo,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        PROCESSO_ATUAL = processo
        _acompanhar(
            processo, comando, log, limite, intervalo, durante=durante, batida=batida
        )
    return processo


def matar_processo_atual() -> None:
    """Mata o comando em andamento, que nao recebe o Ctrl-C do terminal."""
    if PROCESSO_ATUAL is None or PROCESSO_ATUAL.poll() is not None:
        return
    print(
        f"    matando o comando em andamento: {' '.join(PROCESSO_ATUAL.args)}",
        flush=True,
    )
    matar(PROCESSO_ATUAL)


def _checar_falha(processo: subprocess.Popen, comando: list[str], log: Path) -> None:
    """Traduz a falha do comando: lock preso para a serie, o resto para o ciclo."""
    if processo.returncode == 0:
        return
    if "currently locked" in log.read_text(errors="replace"):
        raise StackTravado(
            f"o stack esta travado por outra execucao, que impede {' '.join(comando)}"
            f" (log em {log}). libere com: pulumi cancel --yes"
        )
    raise RuntimeError(f"falhou ({processo.returncode}): {' '.join(comando)}")


def executar(
    comando: list[str], log: Path, limite: int, intervalo: int = 0
) -> tuple[float, str]:
    """Roda um comando, guarda a saida em arquivo e devolve a duracao e a saida."""
    inicio = time.monotonic()
    processo = _longo(comando, log, limite, intervalo)
    duracao = time.monotonic() - inicio
    _checar_falha(processo, comando, log)
    return duracao, log.read_text(errors="replace")


def duracao_do_motor(saida: str) -> float | None:
    """Le a linha 'Duration:' que o proprio Pulumi imprime, quando existe."""
    for linha in reversed(saida.splitlines()):
        if "Duration:" in linha:
            try:
                return float(linha.split("Duration:")[1].strip().rstrip("s"))
            except ValueError:
                return None
    return None


_ULTIMO_AVISO = ""


def _avisar_uma_vez(motivo: str) -> None:
    """Mostra o mesmo aviso uma vez, para nao repetir a cada segundo de consulta."""
    global _ULTIMO_AVISO
    if motivo != _ULTIMO_AVISO:
        print(f"      aviso: {motivo}", flush=True)
        _ULTIMO_AVISO = motivo


def _itens_do_experimento(namespace: str, tipo: str, prefixo: str) -> list[dict]:
    """Itens do tipo pedido, so os do experimento, ou vazio com o motivo no aviso."""
    global _ULTIMO_AVISO
    try:
        processo = rodar(
            ["kubectl", "get", tipo, "-n", namespace, "-o", "json", REQUISICAO_KUBECTL]
        )
    except ComandoTravou as erro:
        _avisar_uma_vez(str(erro))
        return []
    if processo.returncode != 0:
        _avisar_uma_vez(f"kubectl {tipo} falhou: {saida_completa(processo)}")
        return []
    try:
        todos = json.loads(processo.stdout or "{}").get("items", [])
    except json.JSONDecodeError:
        _avisar_uma_vez(f"a saida do kubectl {tipo} nao era JSON")
        return []
    _ULTIMO_AVISO = ""
    return [
        item
        for item in todos
        if item.get("metadata", {}).get("name", "").startswith(prefixo)
    ]


def estado_dos_deployments(namespace: str, prefixo: str) -> tuple[int, int]:
    """Quantos deployments do experimento estao prontos, e quantos existem.

    O filtro pelo prefixo e obrigatorio: objeto de outra execucao no mesmo namespace
    faria a convergencia ser detectada de imediato.
    """
    itens = _itens_do_experimento(namespace, "deploy", prefixo)
    prontos = 0
    for item in itens:
        desejadas = item.get("spec", {}).get("replicas", 1)
        if item.get("status", {}).get("availableReplicas", 0) == desejadas:
            prontos += 1
    return prontos, len(itens)


def estado_dos_pods(namespace: str, prefixo: str) -> str:
    itens = _itens_do_experimento(namespace, "pods", prefixo)
    if not itens:
        return "nenhum pod"
    contagem: dict[str, int] = {}
    for item in itens:
        fase = item.get("status", {}).get("phase", "desconhecida").lower()
        contagem[fase] = contagem.get(fase, 0) + 1
    return ", ".join(f"{quantidade} {fase}" for fase, quantidade in sorted(contagem.items()))


def _esperar_convergencia(
    namespace: str,
    prefixo: str,
    esperados: int,
    inicio: float,
    limite: int,
    intervalo: int,
) -> float | None:
    """Consulta o cluster ate os deployments esperados ficarem prontos.

    Roda depois do fim do up, porque com a espera do provedor desligada o comando
    retorna assim que entrega os objetos e o cluster continua subindo.
    """
    anterior = (-1, -1)
    ultima_batida = time.monotonic()
    while True:
        atual = estado_dos_deployments(namespace, prefixo)
        if atual != anterior:
            print(f"      {atual[0]} prontos de {atual[1]} criados", flush=True)
            anterior = atual
        if atual == (esperados, esperados):
            return time.monotonic() - inicio
        decorrido = time.monotonic() - inicio
        if intervalo and time.monotonic() - ultima_batida >= intervalo:
            print(
                f"      esperando a convergencia: {atual[0]} prontos de {atual[1]}"
                f" criados, pods: {estado_dos_pods(namespace, prefixo)}, {decorrido:.0f}s",
                flush=True,
            )
            ultima_batida = time.monotonic()
        if decorrido > limite:
            print(
                f"      aviso: a convergencia nao chegou em {limite}s, fica sem medida",
                flush=True,
            )
            return None
        time.sleep(INTERVALO_DA_CONSULTA)


def executar_up(
    comando: list[str],
    log: Path,
    namespace: str,
    esperados: int,
    prefixo: str,
    limite: int,
    intervalo: int,
    limite_da_convergencia: int,
) -> tuple[float, float | None]:
    """Roda o up e mede, em paralelo, quanto tempo o cluster leva para convergir.

    A convergencia exige a contagem esperada de deployments: contar so os que ja
    existem daria convergencia assim que o primeiro pod ficasse pronto.
    """
    inicio = time.monotonic()
    estado = {"ultimo": (-1, -1), "convergencia": None, "falhas": 0}

    def durante(_: float) -> None:
        atual = estado_dos_deployments(namespace, prefixo)
        if atual != estado["ultimo"]:
            prontos, total = atual
            print(f"      {prontos} prontos de {total} criados", flush=True)
            estado["ultimo"] = atual
        if estado["convergencia"] is None and atual == (esperados, esperados):
            estado["convergencia"] = time.monotonic() - inicio
            print(
                f"      convergencia detectada em {estado['convergencia']:.1f}s",
                flush=True,
            )

    def batida(decorrido: float) -> None:
        prontos, total = estado["ultimo"]
        print(
            f"      em andamento: {prontos} prontos de {total} criados,"
            f" pods: {estado_dos_pods(namespace, prefixo)},"
            f" {decorrido:.0f}s de up (limite {limite}s)",
            flush=True,
        )

    processo = _longo(
        comando, log, limite, intervalo, durante=durante, batida=batida
    )
    duracao = time.monotonic() - inicio
    _checar_falha(processo, comando, log)
    convergencia = estado["convergencia"]
    if convergencia is None:
        convergencia = _esperar_convergencia(
            namespace, prefixo, esperados, inicio, limite_da_convergencia, intervalo
        )
    return duracao, convergencia


def contar_objetos(namespace: str) -> dict[str, int]:
    contagem: dict[str, int] = {}
    for tipo in ("deploy", "service", "pod"):
        try:
            processo = rodar(
                ["kubectl", "get", tipo, "-n", namespace, "--no-headers", REQUISICAO_KUBECTL]
            )
        except ComandoTravou as erro:
            print(f"      aviso: {erro}", flush=True)
            contagem[tipo] = 0
            continue
        contagem[tipo] = len(
            [linha for linha in processo.stdout.splitlines() if linha.strip()]
        )
    return contagem


def objetos_do_experimento(namespace: str, prefixo: str) -> list[str]:
    try:
        processo = rodar(
            ["kubectl", "get", "deploy,svc", "-n", namespace, "-o", "name", REQUISICAO_KUBECTL]
        )
    except ComandoTravou as erro:
        print(f"      aviso: {erro}", flush=True)
        return []
    if processo.returncode != 0:
        print(f"      aviso: {saida_completa(processo)}", flush=True)
        return []
    return [
        nome
        for nome in processo.stdout.split()
        if nome.split("/", 1)[-1].startswith(prefixo)
    ]


def limpar_restos(namespace: str, prefixo: str) -> int:
    """Apaga o que sobrou de um ciclo interrompido e devolve quantos objetos apagou.

    Um ciclo morto no limite deixa Service criado na API e fora do estado do Pulumi,
    e o destroy nao alcanca o que o estado nao conhece: sem esta limpeza o ciclo
    seguinte falha com "already exists".
    """
    restos = objetos_do_experimento(namespace, prefixo)
    if not restos:
        return 0
    print(f"      {len(restos)} objeto(s) de outro ciclo, apagando", flush=True)
    try:
        rodar(
            [
                "kubectl",
                "delete",
                "-n",
                namespace,
                *restos,
                "--timeout=60s",
                REQUISICAO_KUBECTL,
            ],
            LIMITE_AUXILIAR + 60,
        )
    except ComandoTravou as erro:
        print(f"      aviso: {erro}", flush=True)
        return 0
    for _ in range(30):
        if not objetos_do_experimento(namespace, prefixo):
            return len(restos)
        time.sleep(2)
    print("      aviso: ainda sobrou objeto no namespace depois da limpeza", flush=True)
    return len(restos)


def verificar_ferramentas() -> None:
    for comando in ("pulumi", "kubectl"):
        if not shutil.which(comando):
            raise SystemExit(f"{comando} nao esta no PATH")


def verificar_stack() -> None:
    try:
        processo = rodar(
            ["pulumi", "stack", "--show-name"], LIMITE_AUXILIAR, cwd=BASE
        )
    except ComandoTravou as erro:
        raise SystemExit(f"o pulumi nao respondeu: {erro}") from None
    if processo.returncode != 0:
        raise SystemExit(
            "nenhum stack selecionado neste projeto.\n"
            "rode uma vez, antes da serie: pulumi stack init dev"
        )


def explicar_falha_de_credencial(processo: subprocess.CompletedProcess, o_que: str) -> None:
    """Traduz Unauthorized e Forbidden em instrucao, porque a causa nao e obvia."""
    texto = saida_completa(processo)
    if "Unauthorized" in texto:
        raise SystemExit(
            f"a credencial ativa nao esta autenticada no cluster, ao {o_que} (Unauthorized).\n"
            "o token do kubeconfig restrito vale 24 horas e este ja venceu. renove:\n"
            "  unset KUBECONFIG\n"
            "  ./scripts/create-bench-environment.sh <namespace> --renew-token\n"
            "  export KUBECONFIG=~/bench/kubeconfig-<namespace>.yaml"
        )
    if "Forbidden" in texto:
        raise SystemExit(
            f"a credencial ativa esta autenticada, mas nao tem permissao ao {o_que}\n"
            f"(Forbidden). resposta do kubectl:\n  {texto.strip()}"
        )


def verificar_namespace(namespace: str) -> None:
    # A existencia e provada listando pods ali, e nao lendo o objeto Namespace: ele
    # e de escopo de cluster, e um Role dentro do namespace nao da acesso a ele.
    try:
        processo = rodar(
            ["kubectl", "get", "pods", "-n", namespace, "--no-headers", REQUISICAO_KUBECTL]
        )
    except ComandoTravou as erro:
        raise SystemExit(f"o cluster nao respondeu: {erro}") from None
    explicar_falha_de_credencial(processo, f"listar pods em {namespace}")
    if processo.returncode != 0:
        raise SystemExit(
            f"nao consegui listar pods em {namespace}.\n"
            "causa provavel: o namespace nao existe. resposta do kubectl:\n"
            f"  {saida_completa(processo)}"
        )


def verificar_namespace_vazio(namespace: str) -> None:
    """Recusa comecar com objeto de outra execucao no namespace.

    Deployment sobrando de outra execucao entra na contagem de convergencia e faz o
    ciclo parecer pronto antes de comecar.
    """
    for tipo in ("deploy", "service"):
        try:
            processo = rodar(
                ["kubectl", "get", tipo, "-n", namespace, "--no-headers", REQUISICAO_KUBECTL]
            )
        except ComandoTravou as erro:
            raise SystemExit(f"o cluster nao respondeu: {erro}") from None
        if processo.returncode != 0:
            raise SystemExit(
                f"nao consegui ler os {tipo}(s) de {namespace}.\n"
                f"resposta do kubectl:\n  {saida_completa(processo)}"
            )
        linhas = [linha for linha in processo.stdout.splitlines() if linha.strip()]
        if linhas:
            raise SystemExit(
                f"o namespace {namespace} ja tem {len(linhas)} {tipo}(s) antes de comecar.\n"
                "a serie comeca de um namespace vazio, para a contagem e a convergencia\n"
                "serem so dos objetos dela. limpe com:\n"
                f"  kubectl delete deploy,svc --all -n {namespace}"
            )


def verificar_credencial(permitir_admin: bool) -> None:
    try:
        processo = rodar(
            ["kubectl", "auth", "can-i", "create", "pods", "--all-namespaces", REQUISICAO_KUBECTL]
        )
    except ComandoTravou as erro:
        raise SystemExit(f"o cluster nao respondeu: {erro}") from None
    explicar_falha_de_credencial(processo, "conferir o alcance da credencial")
    resposta = ultima_linha(processo.stdout)
    # O kubectl responde "no" com codigo de saida 1, entao aqui so a resposta conta:
    # tratar codigo diferente de zero como falha recusaria a credencial restrita.
    if resposta not in ("yes", "no"):
        raise SystemExit(
            f"o kubectl nao respondeu ao auth can-i (codigo {processo.returncode}):\n"
            f"  {saida_completa(processo)}"
        )
    if resposta == "yes" and not permitir_admin:
        raise SystemExit(
            "a credencial ativa pode criar pods fora do namespace do experimento.\n"
            "use um kubeconfig restrito ao namespace, ou passe --allow-cluster-admin\n"
            "assumindo o risco de um destroy alcancar recursos de terceiros."
        )


def metadados() -> dict[str, str]:
    def saida(*comando: str) -> str:
        try:
            processo = rodar(list(comando), LIMITE_AUXILIAR, cwd=BASE)
        except ComandoTravou:
            return "sem resposta"
        if processo.returncode != 0:
            return "sem resposta"
        linhas = processo.stdout.strip().splitlines()
        return linhas[0] if linhas else ""

    def config_do_stack() -> str:
        try:
            processo = rodar(["pulumi", "config"], LIMITE_AUXILIAR, cwd=BASE)
        except ComandoTravou:
            return "sem resposta"
        linhas = [linha.strip() for linha in processo.stdout.splitlines() if linha.strip()]
        return " | ".join(linhas) if linhas else "vazio"

    return {
        "inicio": datetime.now(timezone.utc).isoformat(),
        "hora_local": saida("date", "-Is"),
        # Com --max-time porque este curl roda antes da serie e ficaria pendurado
        # sem limite, fora do alcance do limite por comando.
        "hora_externa": saida(
            "bash",
            "-c",
            "curl -sI --max-time 5 https://get.pulumi.com | grep -i '^date:' | head -1",
        ),
        "host": saida("hostname"),
        "pulumi": saida("pulumi", "version"),
        "kubectl": saida("kubectl", "version", "--client"),
        "plugin_do_kubernetes": plugin_do_kubernetes(),
        "config_do_stack": config_do_stack(),
    }


def plugin_do_kubernetes() -> str:
    """Versao do provedor, que o ciclo usa e que o `pulumi version` nao mostra."""
    try:
        processo = rodar(["pulumi", "plugin", "ls"], LIMITE_AUXILIAR, cwd=BASE)
    except ComandoTravou:
        return "sem resposta"
    for linha in processo.stdout.splitlines():
        campos = linha.split()
        if len(campos) >= 3 and campos[0] == "kubernetes":
            return f"{campos[0]} {campos[2]}"
    return "sem resposta"


def resumir(resultados: list[dict]) -> None:
    medidos = [r for r in resultados if not r["aquecimento"]]
    if not medidos:
        print()
        print("nenhuma repeticao medida terminou; nada para resumir")
        return
    print()
    print(f"{'tamanho':>8} {'fase':<20} {'mediana':>9} {'minimo':>9} {'maximo':>9}")
    for tamanho in sorted({r["tamanho"] for r in medidos}):
        for fase in FASES:
            valores = [
                r[fase]
                for r in medidos
                if r["tamanho"] == tamanho and r.get(fase) is not None
            ]
            if not valores:
                continue
            print(
                f"{tamanho:>8} {fase:<20} {statistics.median(valores):>9.2f}"
                f" {min(valores):>9.2f} {max(valores):>9.2f}"
            )


def configurar(chave: str, valor: str, limite: int, log: Path) -> None:
    """Grava uma configuracao do stack, com limite, registro e erro legivel."""
    try:
        processo = rodar(["pulumi", "config", "set", chave, valor], limite, cwd=BASE)
    except ComandoTravou as erro:
        raise SystemExit(f"nao consegui configurar {chave}={valor}: {erro}") from None
    with log.open("a") as arquivo:
        arquivo.write(_cabecalho(["pulumi", "config", "set", chave, valor], limite))
        arquivo.write(saida_completa(processo))
        arquivo.write("\n")
    if processo.returncode != 0:
        raise SystemExit(
            f"nao consegui configurar {chave}={valor} (codigo {processo.returncode}):\n"
            f"  {saida_completa(processo)}"
        )
    print(f"    config: {chave}={valor}", flush=True)


def _comando_up(args, comuns: list[str]) -> list[str]:
    return [
        "pulumi",
        "up",
        "--skip-preview",
        "--yes",
        "--parallel",
        str(args.parallel),
        *comuns,
    ]


def _comando_preview(comuns: list[str], paralelo: int) -> list[str]:
    # O paralelismo e condicao fixa da medicao, entao vale tambem para o plano, que
    # tem padrao proprio e ficaria fora da condicao declarada.
    return ["pulumi", "preview", "--parallel", str(paralelo), *comuns]


def _comando_destroy(comuns: list[str], paralelo: int | None = None) -> list[str]:
    comando = ["pulumi", "destroy", "--skip-preview", "--yes"]
    if paralelo is not None:
        comando += ["--parallel", str(paralelo)]
    return [*comando, *comuns]


def um_ciclo(
    rotulo: str,
    tamanho: int,
    args: argparse.Namespace,
    logs: Path,
    comuns: list[str],
    fases: Callable[..., None] | None = None,
) -> dict:
    """Executa um ciclo completo e devolve o registro com os tempos.

    Falha de fase nao levanta para fora: devolve o registro parcial, com a fase que
    falhou e o tempo ja decorrido, para uma fase que morreu no limite nao apagar as
    que passaram antes dela.

    As fases vem de fora para o modo incremental reaproveitar este tratamento de
    falha, o tempo do ciclo e o resumo final.
    """
    registro: dict = {}
    limite = args.command_timeout
    intervalo = args.heartbeat
    inicio = time.monotonic()
    try:
        (fases or _fases_do_ciclo)(rotulo, tamanho, args, logs, comuns, registro)
    except (RuntimeError, ComandoTravou) as erro:
        registro["erro"] = str(erro)
        registro["travou"] = isinstance(erro, ComandoTravou)
        print(f"    FALHOU em {registro.get('fase')}: {erro}", flush=True)
    finally:
        registro["ciclo"] = time.monotonic() - inicio
    if "erro" not in registro:
        registro["fase"] = "concluido"
        convergencia = registro["convergencia"]
        medida = "sem medida" if convergencia is None else f"{convergencia:.2f}s"
        print(
            f"    resultado: preview {registro['preview']:.2f}s"
            f" | up {registro['up']:.2f}s"
            f" | convergencia {medida}"
            f" | destroy {registro['destroy']:.2f}s",
            flush=True,
        )
    return registro


def _limpeza_inicial(
    rotulo: str, args: argparse.Namespace, logs: Path, comuns: list[str], registro: dict
) -> None:
    """Apaga o que ficou de um ciclo anterior, pelo destroy e pelo kubectl."""
    limite = args.command_timeout
    registro["fase"] = "limpeza"
    print(f"    limpeza inicial (limite {limite}s)", flush=True)
    try:
        executar(
            _comando_destroy(comuns), logs / f"{rotulo}-limpeza.log", limite, args.heartbeat
        )
    except (RuntimeError, ComandoTravou) as erro:
        print(f"      a limpeza nao terminou limpa: {erro}", flush=True)
    registro["restos_do_ciclo_anterior"] = limpar_restos(args.namespace, args.name_prefix)


def _preparo_da_base(
    rotulo: str,
    base: int,
    args: argparse.Namespace,
    logs: Path,
    comuns: list[str],
    registro: dict,
) -> None:
    """Aplica a base de um ciclo incremental sem medir o que ela custa."""
    limite = args.command_timeout
    registro["fase"] = "preparo"
    print(f"    preparo: {base} modulos, sem medida (limite {limite}s)", flush=True)
    configurar("unitCount", str(base), limite, logs / "configuracoes.log")
    inicio = time.monotonic()
    executar(_comando_up(args, comuns), logs / f"{rotulo}-preparo.log", limite, args.heartbeat)
    pronto = _esperar_convergencia(
        args.namespace,
        args.name_prefix,
        base,
        inicio,
        args.convergence_timeout,
        args.heartbeat,
    )
    if pronto is None:
        print(
            "      aviso: a base nao convergiu, entao a medida da mudanca fica comprometida",
            flush=True,
        )


def _fases_medidas(
    rotulo: str,
    tamanho: int,
    args: argparse.Namespace,
    logs: Path,
    comuns: list[str],
    registro: dict,
    descricao: str = "",
) -> None:
    """Plano, aplicacao com convergencia, plano sem mudanca e remocao, tudo medido."""
    limite = args.command_timeout
    intervalo = args.heartbeat

    registro["fase"] = "preview"
    print(f"    preview{descricao} (limite {limite}s)", flush=True)
    registro["preview"], _ = executar(
        _comando_preview(comuns, args.parallel),
        logs / f"{rotulo}-preview.log",
        limite,
        intervalo,
    )

    registro["fase"] = "up"
    print(f"    up{descricao}, medindo a convergencia (limite {limite}s)", flush=True)
    registro["up"], registro["convergencia"] = executar_up(
        _comando_up(args, comuns),
        logs / f"{rotulo}-up.log",
        args.namespace,
        tamanho,
        args.name_prefix,
        limite,
        intervalo,
        args.convergence_timeout,
    )
    registro["pulumi_duration"] = duracao_do_motor(
        (logs / f"{rotulo}-up.log").read_text(errors="replace")
    )
    registro["objetos"] = contar_objetos(args.namespace)

    registro["fase"] = "preview_sem_mudanca"
    print(f"    preview sem mudancas (limite {limite}s)", flush=True)
    registro["preview_sem_mudanca"], _ = executar(
        _comando_preview(comuns, args.parallel),
        logs / f"{rotulo}-preview-sem-mudanca.log",
        limite,
        intervalo,
    )

    registro["fase"] = "destroy"
    print(f"    destroy (limite {limite}s)", flush=True)
    registro["destroy"], _ = executar(
        _comando_destroy(comuns, args.parallel),
        logs / f"{rotulo}-destroy.log",
        limite,
        intervalo,
    )


def _fases_do_ciclo(
    rotulo: str,
    tamanho: int,
    args: argparse.Namespace,
    logs: Path,
    comuns: list[str],
    registro: dict,
) -> None:
    """Roda o ciclo completo: limpeza, as quatro fases medidas e a contagem."""
    _limpeza_inicial(rotulo, args, logs, comuns, registro)
    _fases_medidas(rotulo, tamanho, args, logs, comuns, registro)


def _fases_do_ciclo_incremental(
    rotulo: str,
    tamanho: int,
    args: argparse.Namespace,
    logs: Path,
    comuns: list[str],
    registro: dict,
) -> None:
    """Prepara a base sem medir, mede a mudanca de tamanho-1 para tamanho, e remove.

    O que interessa aqui e o custo de uma mudanca num stack grande, entao a criacao
    da base e a espera dela nao entram no registro.
    """
    base = tamanho - 1
    registro["base"] = base
    _limpeza_inicial(rotulo, args, logs, comuns, registro)
    _preparo_da_base(rotulo, base, args, logs, comuns, registro)
    configurar("unitCount", str(tamanho), args.command_timeout, logs / "configuracoes.log")
    _fases_medidas(
        rotulo,
        tamanho,
        args,
        logs,
        comuns,
        registro,
        descricao=f" da mudanca de {base} para {tamanho}",
    )


def fases_do_ciclo(args: argparse.Namespace) -> Callable[..., None]:
    """Escolhe o ciclo: a serie completa, ou a medida de uma mudanca."""
    return _fases_do_ciclo_incremental if args.incremental else _fases_do_ciclo


def liberar_lock(comuns: list[str]) -> None:
    """Libera o lock do stack, que fica preso quando um comando morre no limite."""
    print("    liberando o lock do stack", flush=True)
    try:
        processo = rodar(["pulumi", "cancel", "--yes", *comuns], LIMITE_DO_CANCEL, cwd=BASE)
    except ComandoTravou:
        print("    o proprio cancel passou do limite", flush=True)
        return
    if processo.returncode != 0:
        print(f"    o cancel falhou: {saida_completa(processo)}", flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Serie de medicao do Pulumi no cluster")
    parser.add_argument("--namespace", default="bench-larces")
    parser.add_argument("--sizes", default="10,50,100")
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--parallel", type=int, default=10)
    parser.add_argument("--image", default="nginx:1.27-alpine")
    parser.add_argument("--name-prefix", default="bench-web")
    parser.add_argument("--output", default=str(BASE / "resultados"))
    parser.add_argument("--allow-cluster-admin", action="store_true")
    parser.add_argument(
        "--command-timeout",
        type=int,
        default=600,
        help="segundos por comando antes de ser interrompido (padrao 600)",
    )
    parser.add_argument(
        "--heartbeat",
        type=int,
        default=15,
        help="segundos entre as batidas de coracao na tela; 0 desliga (padrao 15)",
    )
    parser.add_argument(
        "--convergence-timeout",
        type=int,
        default=120,
        help="segundos de espera pela convergencia depois do up (padrao 120)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="mede o plano e a aplicacao de uma mudanca: cada tamanho de --sizes e o alvo, e a base e uma unidade menor",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    tamanhos = [int(s) for s in args.sizes.split(",") if s.strip()]
    if args.repetitions < 0:
        parser.error("--repetitions nao pode ser negativo")
    if args.incremental and any(tamanho < 2 for tamanho in tamanhos):
        parser.error("--incremental precisa de alvos de 2 para cima, porque a base e uma unidade menor")
    destino = Path(args.output)
    logs = destino / "logs"
    ciclos = len(tamanhos) * (args.repetitions + 1)
    if args.incremental:
        sequencia = (
            "preparo sem medida, preview da mudanca, up da mudanca, preview sem mudanca, destroy"
        )
    else:
        sequencia = f"preview, up --parallel {args.parallel}, preview, destroy, por tamanho"

    modo = (
        "incremental: cada tamanho de --sizes e o alvo da mudanca, com a base uma unidade menor"
        if args.incremental
        else "serie completa: do zero ate o tamanho, em cada ciclo"
    )
    if args.dry_run:
        print(f"namespace:  {args.namespace}")
        print(f"modo:       {modo}")
        print(f"tamanhos:   {tamanhos}")
        print(f"repeticoes: {args.repetitions} medidas, mais 1 de aquecimento por tamanho")
        print(f"ciclos:     {ciclos}")
        print(f"saida:      {destino}")
        print(f"sequencia:  {sequencia}")
        print(f"limite por comando: {args.command_timeout}s")
        print(f"limite da convergencia: {args.convergence_timeout}s")
        print(f"batida de coracao:  a cada {args.heartbeat}s (0 desliga)")
        print("credencial: seria verificada antes de comecar")
        return 0

    verificar_ferramentas()
    verificar_stack()
    # Antes do namespace: com token vencido, a mensagem de credencial e a que
    # explica a causa, e a de namespace so confundiria.
    verificar_credencial(args.allow_cluster_admin)
    verificar_namespace(args.namespace)
    verificar_namespace_vazio(args.namespace)
    logs.mkdir(parents=True, exist_ok=True)

    comuns = ["--color", "never", "--non-interactive"]
    resultados: list[dict] = []
    inicio_da_serie = time.monotonic()
    meta = metadados()

    destino.mkdir(parents=True, exist_ok=True)
    saida = destino / f"serie-{datetime.now().strftime('%Y%m%d-%H%M%S')}.json"

    def gravar() -> None:
        # Gravacao a cada ciclo: uma falha no meio da serie nao descarta o que ja rodou.
        conteudo = {"meta": meta, "args": vars(args), "resultados": resultados}
        saida.write_text(json.dumps(conteudo, indent=2))

    print(f"namespace: {args.namespace}")
    print(f"modo:      {modo}")
    print(f"tamanhos:  {tamanhos}, {args.repetitions} medidas mais o aquecimento")
    print(f"ciclos:    {ciclos}")
    print(f"limite:    {args.command_timeout}s por comando, batida a cada {args.heartbeat}s")
    print(f"convergencia: ate {args.convergence_timeout}s depois do up")
    print(f"json:      {saida}")
    print(f"logs:      {logs}")
    print(f"config do stack: {meta['config_do_stack']}")
    print("interromper com Ctrl-C libera o lock e mostra como limpar o cluster")

    limite = args.command_timeout
    registro_config = logs / "configuracoes.log"
    fases = fases_do_ciclo(args)
    parar = False
    try:
        for tamanho in tamanhos:
            configurar("unitCount", str(tamanho), limite, registro_config)
            configurar("namespace", args.namespace, limite, registro_config)
            configurar("image", args.image, limite, registro_config)

            for repeticao in range(args.repetitions + 1):
                aquecimento = repeticao == 0
                rotulo = f"{tamanho}-{'aquecimento' if aquecimento else repeticao}"
                registro: dict = {
                    "tamanho": tamanho,
                    "repeticao": repeticao,
                    "aquecimento": aquecimento,
                    "namespace": args.namespace,
                }
                print(f"--- {rotulo}", flush=True)
                try:
                    registro.update(um_ciclo(rotulo, tamanho, args, logs, comuns, fases))
                except StackTravado as erro:
                    registro["erro"] = str(erro)
                    print(f"    {erro}", flush=True)
                    parar = True
                except Exception as erro:
                    # Falha inesperada no cluster compartilhado nao derruba a serie: o
                    # erro fica registrado no JSON e o proximo ciclo continua.
                    registro["erro"] = f"{type(erro).__name__}: {erro}"
                    print(
                        f"    FALHOU inesperado em {registro.get('fase')}: {erro}",
                        flush=True,
                    )
                if registro.get("travou"):
                    liberar_lock(comuns)
                resultados.append(registro)
                gravar()
                print(
                    f"    decorrido: {time.monotonic() - inicio_da_serie:.0f}s", flush=True
                )
                if parar:
                    print()
                    print("a serie para aqui: com o stack travado nenhum ciclo mede nada.")
                    print("libere o lock e comece de novo: pulumi cancel --yes")
                    print(f"o que ja rodou esta em: {saida}")
                    return 1
    except KeyboardInterrupt:
        gravar()
        print()
        print("interrompido por voce.")
        matar_processo_atual()
        liberar_lock(comuns)
        print("o que ja rodou esta no json:")
        print(f"  {saida}")
        print("para limpar o que ficou no cluster:")
        print(f"  kubectl delete deploy,svc --all -n {args.namespace}")
        print(f"tempo total ate a interrupcao: {time.monotonic() - inicio_da_serie:.0f}s")
        return 130

    gravar()
    resumir(resultados)
    print()
    print(f"tempo total da serie: {time.monotonic() - inicio_da_serie:.0f}s")
    print(f"resultado salvo em: {saida}")
    print(f"logs por comando em: {logs}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
