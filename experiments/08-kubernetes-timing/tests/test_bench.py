"""Testes do medidor, com comandos de verdade no lugar do Pulumi e do kubectl.

Nenhum teste aqui toca o cluster: o que se verifica e o comportamento do medidor
diante de um comando que demora, que falha ou que deixa filho vivo. Rodar a partir
deste diretorio:

  ~/workspace/pulumi/.venv/bin/python -m pytest tests/ -q
"""

import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import bench


def argumentos() -> SimpleNamespace:
    """Opcoes minimas que um ciclo usa, sem passar pelo argparse."""
    return SimpleNamespace(
        command_timeout=1,
        convergence_timeout=10,
        heartbeat=0,
        parallel=10,
        namespace="bench-teste",
        name_prefix="bench-web",
    )


def test_rodar_devolve_a_saida() -> None:
    processo = bench.rodar(["bash", "-c", "echo pronto"])

    assert processo.returncode == 0
    assert processo.stdout.strip() == "pronto"


def test_rodar_nao_levanta_por_codigo_de_saida() -> None:
    processo = bench.rodar(["bash", "-c", "exit 3"])

    assert processo.returncode == 3


def test_rodar_mata_o_comando_no_limite() -> None:
    inicio = time.monotonic()
    with pytest.raises(bench.ComandoTravou):
        bench.rodar(["sleep", "30"], limite=1)

    assert time.monotonic() - inicio < 15


def test_rodar_mata_tambem_os_filhos() -> None:
    with pytest.raises(bench.ComandoTravou):
        bench.rodar(["bash", "-c", "sleep 987654 & wait"], limite=1)

    sobraram = subprocess.run(["pgrep", "-f", "987654"], capture_output=True)
    assert sobraram.returncode != 0, "o processo filho sobreviveu ao limite"


def test_executar_grava_o_cabecalho_e_a_saida(tmp_path: Path) -> None:
    log = tmp_path / "comando.log"

    duracao, saida = bench.executar(["bash", "-c", "echo pronto"], log, limite=10)

    assert duracao >= 0
    assert "pronto" in saida
    conteudo = log.read_text()
    assert "# comando: bash -c echo pronto" in conteudo
    assert "limite: 10s" in conteudo


def test_executar_detecta_o_stack_travado(tmp_path: Path) -> None:
    comando = [
        "bash",
        "-c",
        "echo 'error: the stack is currently locked by 1 lock(s).'; exit 1",
    ]

    with pytest.raises(bench.StackTravado) as capturado:
        bench.executar(comando, tmp_path / "travado.log", limite=10)

    assert "pulumi cancel --yes" in str(capturado.value)


def test_stack_travado_nao_e_runtime_error() -> None:
    """Se virar RuntimeError, o ciclo engole e a serie inteira queima sem medir."""
    assert not issubclass(bench.StackTravado, RuntimeError)


def test_um_ciclo_nao_engole_o_stack_travado(monkeypatch, tmp_path: Path) -> None:
    def trava(*_args, **_kwargs):
        raise bench.StackTravado("o stack esta travado por outra execucao")

    monkeypatch.setattr(bench, "executar", trava)
    monkeypatch.setattr(bench, "limpar_restos", lambda *args, **kwargs: 0)

    with pytest.raises(bench.StackTravado):
        bench.um_ciclo("2-1", 2, argumentos(), tmp_path, ["--color", "never"])


def test_a_duracao_nao_carrega_um_segundo_de_atraso(tmp_path: Path) -> None:
    duracao, _ = bench.executar(["sleep", "0.3"], tmp_path / "curto.log", limite=10)

    assert duracao < 1.0, f"medida inflada para {duracao:.2f}s na deteccao do fim"


def test_executar_mata_no_limite(tmp_path: Path) -> None:
    with pytest.raises(bench.ComandoTravou) as capturado:
        bench.executar(["sleep", "30"], tmp_path / "longo.log", limite=1)

    assert "passou de 1s" in str(capturado.value)
    assert "longo.log" in str(capturado.value)


def test_executar_levanta_quando_o_comando_falha(tmp_path: Path) -> None:
    with pytest.raises(RuntimeError):
        bench.executar(["bash", "-c", "exit 2"], tmp_path / "falha.log", limite=10)


def test_executar_publica_batida_de_coracao(tmp_path: Path, capsys) -> None:
    bench.executar(["sleep", "2.5"], tmp_path / "batida.log", limite=20, intervalo=1)

    assert "em andamento" in capsys.readouterr().out


def test_resumir_avisa_quando_nada_terminou(capsys) -> None:
    bench.resumir([])

    assert "nada para resumir" in capsys.readouterr().out


def test_resumir_ignora_o_aquecimento(capsys) -> None:
    bench.resumir(
        [
            {"tamanho": 2, "aquecimento": True, "preview": 9.0, "up": 9.0,
             "convergencia": 9.0, "preview_sem_mudanca": 9.0, "destroy": 9.0},
            {"tamanho": 2, "aquecimento": False, "preview": 1.0, "up": 2.0,
             "convergencia": 3.0, "preview_sem_mudanca": 4.0, "destroy": 5.0},
        ]
    )

    saida = capsys.readouterr().out
    assert "1.00" in saida
    assert "9.00" not in saida


def test_o_processo_atual_fica_guardado_para_o_ctrl_c(tmp_path: Path) -> None:
    bench.executar(["bash", "-c", "true"], tmp_path / "curto.log", limite=10)

    assert bench.PROCESSO_ATUAL is not None
    assert bench.PROCESSO_ATUAL.args[0] == "bash"


def test_matar_processo_atual_mata_o_comando_vivo(monkeypatch) -> None:
    processo = subprocess.Popen(["bash", "-c", "sleep 987655"], start_new_session=True)
    monkeypatch.setattr(bench, "PROCESSO_ATUAL", processo)

    bench.matar_processo_atual()

    assert processo.poll() is not None
    assert subprocess.run(["pgrep", "-f", "987655"], capture_output=True).returncode != 0


def test_matar_processo_atual_nao_quebra_sem_comando_vivo(monkeypatch) -> None:
    monkeypatch.setattr(bench, "PROCESSO_ATUAL", None)
    bench.matar_processo_atual()

    terminado = subprocess.Popen(["bash", "-c", "true"])
    terminado.wait()
    monkeypatch.setattr(bench, "PROCESSO_ATUAL", terminado)
    bench.matar_processo_atual()


def test_um_ciclo_registra_a_fase_que_falhou(monkeypatch, tmp_path: Path) -> None:
    def estoura(*_args, **_kwargs):
        raise bench.ComandoTravou("passou de 1s: pulumi preview")

    monkeypatch.setattr(bench, "executar", estoura)
    monkeypatch.setattr(bench, "limpar_restos", lambda *args, **kwargs: 0)

    registro = bench.um_ciclo("2-1", 2, argumentos(), tmp_path, ["--color", "never"])

    assert registro["fase"] == "preview"
    assert registro["travou"] is True
    assert "passou de 1s" in registro["erro"]
    assert registro["ciclo"] >= 0
    assert "preview" not in registro


def test_um_ciclo_guarda_o_tempo_das_fases_que_passaram(monkeypatch, tmp_path: Path) -> None:
    def trava_no_up(*_args, **_kwargs):
        raise bench.ComandoTravou("passou de 1s: pulumi up")

    monkeypatch.setattr(bench, "executar", lambda *_a, **_k: (4.2, ""))
    monkeypatch.setattr(bench, "executar_up", trava_no_up)
    monkeypatch.setattr(bench, "limpar_restos", lambda *args, **kwargs: 0)

    registro = bench.um_ciclo("2-1", 2, argumentos(), tmp_path, ["--color", "never"])

    assert registro["preview"] == 4.2
    assert registro["fase"] == "up"
    assert registro["travou"] is True


def test_erro_de_credencial_explica_a_renovacao_do_token() -> None:
    processo = subprocess.CompletedProcess(
        [], 1, "error: You must be logged in to the server (Unauthorized)\n", ""
    )

    with pytest.raises(SystemExit) as capturado:
        bench.explicar_falha_de_credencial(processo, "listar pods em bench-larces")

    mensagem = str(capturado.value)
    assert "renew-token" in mensagem
    assert "bench-larces" in mensagem


def test_forbidden_explica_a_falta_de_permissao() -> None:
    processo = subprocess.CompletedProcess(
        [], 1, "Error from server (Forbidden): pods is forbidden\n", ""
    )

    with pytest.raises(SystemExit) as capturado:
        bench.explicar_falha_de_credencial(processo, "listar pods em bench-larces")

    assert "permissao" in str(capturado.value)


def test_resposta_normal_nao_levanta() -> None:
    processo = subprocess.CompletedProcess([], 0, "no\n", "")

    bench.explicar_falha_de_credencial(processo, "conferir o alcance da credencial")


def test_ultima_linha_ignora_o_aviso_do_kubectl() -> None:
    aviso = "Warning: resource 'namespaces' is not namespace scoped\n\nyes\n"

    assert bench.ultima_linha(aviso) == "yes"
    assert bench.ultima_linha("") == ""


def test_credencial_restrita_responde_no_com_codigo_de_saida_um(monkeypatch) -> None:
    """O `kubectl auth can-i` responde `no` com codigo 1, e isso nao e falha do comando."""
    monkeypatch.setattr(
        bench,
        "rodar",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 1, "no\n", ""),
    )

    bench.verificar_credencial(False)


def test_verificar_credencial_recusa_admin_mesmo_com_aviso(monkeypatch) -> None:
    aviso = "Warning: resource 'pods' is not namespace scoped\n"
    monkeypatch.setattr(
        bench,
        "rodar",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "yes\n", aviso),
    )

    with pytest.raises(SystemExit):
        bench.verificar_credencial(False)


def test_verificar_credencial_aceita_a_credencial_restrita(monkeypatch) -> None:
    monkeypatch.setattr(
        bench,
        "rodar",
        lambda *args, **kwargs: subprocess.CompletedProcess([], 0, "no\n", ""),
    )

    bench.verificar_credencial(False)


def test_estado_dos_deployments_ignora_aviso_no_stderr(monkeypatch) -> None:
    itens = (
        '{"items": [{"metadata": {"name": "bench-web-000"},'
        ' "spec": {"replicas": 1}, "status": {"availableReplicas": 1}}]}'
    )
    monkeypatch.setattr(
        bench,
        "rodar",
        lambda *args, **kwargs: subprocess.CompletedProcess(
            [], 0, itens, "Warning: algo mudou\n"
        ),
    )

    assert bench.estado_dos_deployments("bench-larces", "bench-web") == (1, 1)


def test_erro_de_credencial_no_stderr_tambem_e_traduzido() -> None:
    processo = subprocess.CompletedProcess(
        [], 1, "", "error: You must be logged in to the server (Unauthorized)\n"
    )

    with pytest.raises(SystemExit):
        bench.explicar_falha_de_credencial(processo, "conferir o alcance da credencial")


def test_limpar_restos_apaga_so_o_que_tem_o_prefixo(monkeypatch) -> None:
    listagens = [
        "deployment.apps/bench-web-000\nservice/bench-web-000\nservice/outro-namespace\n",
        "",
    ]
    comandos = []

    def falso(comando, *args, **kwargs):
        comandos.append(comando)
        if comando[1] == "get":
            return subprocess.CompletedProcess(comando, 0, listagens.pop(0), "")
        return subprocess.CompletedProcess(comando, 0, "", "")

    monkeypatch.setattr(bench, "rodar", falso)

    assert bench.limpar_restos("bench-larces", "bench-web") == 2
    apagados = comandos[1]
    assert apagados[1] == "delete"
    assert "deployment.apps/bench-web-000" in apagados
    assert "service/bench-web-000" in apagados
    assert "service/outro-namespace" not in apagados


def test_limpar_restos_nao_apaga_nada_com_o_namespace_limpo(monkeypatch) -> None:
    comandos = []

    def falso(comando, *args, **kwargs):
        comandos.append(comando)
        return subprocess.CompletedProcess(comando, 0, "", "")

    monkeypatch.setattr(bench, "rodar", falso)

    assert bench.limpar_restos("bench-larces", "bench-web") == 0
    assert all(comando[1] == "get" for comando in comandos)


def test_convergencia_e_medida_depois_do_fim_do_comando(monkeypatch, tmp_path: Path) -> None:
    """Com a espera do provedor desligada, o up volta antes do cluster convergir."""
    respostas = [(0, 1), (1, 1)]
    monkeypatch.setattr(
        bench,
        "estado_dos_deployments",
        lambda *args: respostas.pop(0) if respostas else (1, 1),
    )
    monkeypatch.setattr(bench, "estado_dos_pods", lambda *args: "1 running")

    duracao, convergencia = bench.executar_up(
        ["bash", "-c", "true"],
        tmp_path / "up.log",
        "bench-teste",
        1,
        "bench-web",
        10,
        0,
        10,
    )

    assert duracao < 1.0
    assert convergencia is not None and convergencia >= 0


def test_convergencia_sem_medida_depois_do_limite(monkeypatch) -> None:
    monkeypatch.setattr(bench, "estado_dos_deployments", lambda *args: (0, 1))

    assert bench._esperar_convergencia("bench-teste", "bench-web", 1, 0.0, 0, 0) is None


def test_fases_do_ciclo_escolhe_o_incremental() -> None:
    assert bench.fases_do_ciclo(SimpleNamespace(incremental=True)) is (
        bench._fases_do_ciclo_incremental
    )
    assert bench.fases_do_ciclo(SimpleNamespace(incremental=False)) is bench._fases_do_ciclo


def test_o_ciclo_incremental_prepara_a_base_sem_medir(monkeypatch, tmp_path: Path) -> None:
    eventos: list[tuple] = []

    def falso_configurar(chave, valor, limite, log):
        eventos.append(("configurar", chave, valor))

    def falso_executar(comando, log, limite, intervalo=0):
        eventos.append(("executar", log.name))
        return 1.0, ""

    def falso_up(comando, log, namespace, esperados, prefixo, limite, intervalo, conv):
        eventos.append(("up", esperados, log.name))
        log.write_text("Duration: 2.0s\n")
        return 2.0, 3.0

    monkeypatch.setattr(bench, "configurar", falso_configurar)
    monkeypatch.setattr(bench, "executar", falso_executar)
    monkeypatch.setattr(bench, "executar_up", falso_up)
    monkeypatch.setattr(bench, "limpar_restos", lambda *args, **kwargs: 0)
    monkeypatch.setattr(
        bench, "contar_objetos", lambda *args: {"deploy": 51, "service": 51, "pod": 51}
    )
    monkeypatch.setattr(bench, "_esperar_convergencia", lambda *args, **kwargs: 1.0)

    registro = bench.um_ciclo(
        "51-1",
        51,
        argumentos(),
        tmp_path,
        ["--color", "never"],
        bench._fases_do_ciclo_incremental,
    )

    assert registro["base"] == 50
    assert [e for e in eventos if e[0] == "configurar"] == [
        ("configurar", "unitCount", "50"),
        ("configurar", "unitCount", "51"),
    ]
    assert ("executar", "51-1-preparo.log") in eventos
    assert [e for e in eventos if e[0] == "up"] == [("up", 51, "51-1-up.log")]
    assert registro["up"] == 2.0
    assert registro["convergencia"] == 3.0
    assert registro["pulumi_duration"] == 2.0
    assert registro["fase"] == "concluido"


def test_o_plano_leva_o_paralelismo_fixo() -> None:
    assert bench._comando_preview(["--color", "never"], 10) == [
        "pulumi",
        "preview",
        "--parallel",
        "10",
        "--color",
        "never",
    ]


def test_o_incremental_recusa_alvo_menor_que_dois(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "sys.argv", ["bench.py", "--dry-run", "--incremental", "--sizes", "1"]
    )

    with pytest.raises(SystemExit):
        bench.main()

    assert "base e uma unidade menor" in capsys.readouterr().err


def test_dry_run_do_incremental_mostra_o_modo(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["bench.py", "--dry-run", "--incremental", "--sizes", "51"])
    monkeypatch.setattr(bench, "verificar_credencial", lambda *_: pytest.fail("tocou o cluster"))

    assert bench.main() == 0
    saida = capsys.readouterr().out
    assert "incremental" in saida
    assert "preparo sem medida" in saida


def test_dry_run_nao_toca_o_cluster(monkeypatch, capsys) -> None:
    monkeypatch.setattr("sys.argv", ["bench.py", "--dry-run", "--sizes", "2,4"])
    monkeypatch.setattr(
        bench, "verificar_credencial", lambda *_: pytest.fail("tocou o cluster")
    )

    assert bench.main() == 0
    saida = capsys.readouterr().out
    assert "[2, 4]" in saida
    assert "limite por comando" in saida
