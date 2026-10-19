"""
Avaliação da primeira etapa (Metodologia): compara as duas abordagens
de extração — OCR com Tesseract e modelo de linguagem multimodal
(Claude, um ou mais modelos) — sobre AS MESMAS imagens, para decidir
qual delas será adotada no fluxo final (ver app/extracao/detector.py).

Métricas, conforme a Metodologia:
- acurácia por campo (estabelecimento, data de emissão, produtos e
  valor total), para cada abordagem;
- matriz de resultados de cada abordagem: para cada campo, quantas
  notas tiveram o valor extraído correto, incorreto (devolveu um valor
  errado), não extraído (devolveu vazio) ou tiveram a foto recusada;
  daí saem precisão, revocação e F1 por campo;
- matriz de concordância Tesseract x multimodal: em quantas notas as
  duas acertam, só uma acerta, ou as duas erram o mesmo campo — mostra
  se uma abordagem acerta as notas que a outra erra, ou as mesmas;
e, como informação complementar:
- tempo médio por imagem;
- matriz de confusão da checagem da foto (gabarito: legível/ilegível
  x sistema: aceitou/recusou), que mostra tanto as fotos ruins que
  passaram (e geraram dados errados) quanto as fotos boas que o
  usuário teria de refazer sem necessidade.

Uso pelo terminal (a partir da raiz do projeto):

    python3 -m avaliacao.comparar_extracao dados/casos_foto.json
    python3 -m avaliacao.comparar_extracao dados/casos_foto.json \\
        --modelos claude-sonnet-5-5,claude-opus-5-5
    python3 -m avaliacao.comparar_extracao dados/casos_foto.json --sem-multimodal
    python3 -m avaliacao.comparar_extracao dados/casos_pdf.json

O relatório é impresso e salvo em resultados/extracao_<foto|pdf>/<data>/ (texto,
JSON, tabelas em CSV e figuras em PNG).

A lógica de comparação (`executar_extrator_sobre_casos`,
`comparar_extratores`, `montar_relatorio_texto`) recebe os extratores
como funções, o que permite testá-la com extratores falsos, sem
Tesseract nem chave de API (tests/test_comparar_extracao.py).
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from functools import partial
from pathlib import Path
from typing import Any, Callable

from avaliacao.casos import CasoDeTeste, carregar_casos
from avaliacao.metricas import (
    CORRETO,
    FOTO_RECUSADA,
    NAO_EXTRAIDO,
    RESULTADOS_CAMPO,
    MatrizConfusao,
    MetricasExtracaoCampo,
    acuracia_por_campo,
    campo_correto,
    matriz_confusao,
    resultado_do_campo,
)
from app.extracao.qualidade_imagem import ImagemIlegivelError
from app.models import CAMPOS_NOTA, NotaFiscalExtraida

ExtratorFn = Callable[[Path], NotaFiscalExtraida]

PASTA_RESULTADOS_PADRAO = Path("resultados")  # resultados/extracao_<foto|pdf>/<data>/


@dataclass
class ResultadoCaso:
    caso_id: str
    duracao_segundos: float
    foto_ilegivel_esperado: bool
    recusada: bool                  # o extrator pediu nova foto (ImagemIlegivelError)
    motivo_recusa: str | None
    erro: str | None                # qualquer outra exceção
    campos: dict[str, tuple] = field(default_factory=dict)  # campo -> (extraído, esperado)
    # Leituras repetidas da mesma foto (2ª execução em diante), para medir
    # a consistência: (recusada, {campo: valor extraído}).
    leituras_repetidas: list[tuple[bool, dict[str, Any]]] = field(default_factory=list)

    def resultados_campos(self) -> dict[str, str]:
        """campo -> correto / incorreto / nao_extraido / foto_recusada."""
        if self.recusada:
            return {campo: FOTO_RECUSADA for campo in self.campos}
        return {campo: resultado_do_campo(ext, esp) for campo, (ext, esp) in self.campos.items()}


@dataclass
class RelatorioExtrator:
    nome: str
    resultados_por_caso: list[ResultadoCaso]
    acuracia_por_campo: dict[str, float]
    acuracia_media: float | None
    tempo_medio_segundos: float
    fotos_ruins_recusadas: int
    fotos_ruins_total: int
    recusas_indevidas: list[str]
    casos_com_erro: list[str]
    matriz_qualidade_foto: MatrizConfusao | None = None
    # campo (e "TOTAL") -> contagem de correto/incorreto/não extraído/foto recusada
    matriz_resultados: dict[str, MetricasExtracaoCampo] = field(default_factory=dict)
    execucoes: int = 1
    # campo (e "TODOS") -> proporção das fotos legíveis com a mesma leitura
    # em todas as execuções; None quando houve só uma execução.
    consistencia_por_campo: dict[str, float] | None = None
    # proporção de fotos (todas) com a mesma decisão aceitar/recusar.
    consistencia_recusa: float | None = None


def _rodar_extrator(extrator: ExtratorFn, imagem: Path):
    """Uma leitura: (nota, recusada, motivo da recusa, erro, duração)."""
    inicio = time.perf_counter()
    nota, recusada, motivo_recusa, erro = None, False, None, None
    try:
        nota = extrator(imagem)
    except ImagemIlegivelError as exc:
        recusada, motivo_recusa = True, f"{exc.motivo.value}: {exc.detalhe or ''}".strip(": ")
    except Exception as exc:  # noqa: BLE001 — queremos registrar qualquer falha do extrator
        erro = f"{type(exc).__name__}: {exc}"
    return nota, recusada, motivo_recusa, erro, time.perf_counter() - inicio


def _consistencia(resultados: list[ResultadoCaso]) -> tuple[dict[str, float] | None, float | None]:
    """
    Consistência entre as execuções repetidas da mesma foto:
    - por campo, nas fotos legíveis: a leitura é consistente se todas as
      execuções aceitaram a foto e devolveram o mesmo valor (pelo mesmo
      critério de igualdade da acurácia), ou se todas recusaram a foto;
      "TODOS" exige que os quatro campos sejam consistentes;
    - recusa, em todas as fotos: mesma decisão de aceitar ou recusar.
    """
    com_repeticao = [r for r in resultados if r.leituras_repetidas and r.erro is None]
    if not com_repeticao:
        return None, None

    def mesma_leitura(r: ResultadoCaso, campo: str) -> bool:
        primeira = r.campos[campo][0]
        for recusada, valores in r.leituras_repetidas:
            if recusada != r.recusada:
                return False
            if not recusada and not campo_correto(valores.get(campo), primeira):
                return False
        return True

    legiveis = [r for r in com_repeticao if not r.foto_ilegivel_esperado and r.campos]
    por_campo: dict[str, float] = {}
    for campo in CAMPOS_NOTA:
        casos_campo = [r for r in legiveis if campo in r.campos]
        if casos_campo:
            por_campo[campo] = sum(mesma_leitura(r, campo) for r in casos_campo) / len(casos_campo)
    if legiveis:
        por_campo["TODOS"] = sum(all(mesma_leitura(r, c) for c in r.campos) for r in legiveis) / len(legiveis)

    recusa = sum(all(rec == r.recusada for rec, _ in r.leituras_repetidas) for r in com_repeticao) / len(com_repeticao)
    return por_campo or None, recusa


def executar_extrator_sobre_casos(
    nome: str, extrator: ExtratorFn, casos: list[CasoDeTeste], progresso: bool = False,
    execucoes: int = 1,
) -> RelatorioExtrator:
    """
    Executa um extrator sobre todos os casos e monta o relatório dele.

    - Casos com foto boa entram na acurácia por campo. Se o extrator
      recusar a foto ou levantar exceção, todos os campos do caso contam
      como erro (e o caso é listado em `recusas_indevidas` ou
      `casos_com_erro`, para a falha não passar despercebida).
    - Casos marcados como `foto_ilegivel` não entram na acurácia: o
      acerto, ali, é o extrator recusar a foto.
    - Com `execucoes` > 1, cada arquivo (foto ou PDF) é lido várias vezes. A acurácia usa
      a 1ª leitura (a que o usuário receberia); as demais servem para
      medir a consistência (ver _consistencia).
    """
    resultados: list[ResultadoCaso] = []

    for caso in casos:
        nota, recusada, motivo_recusa, erro, duracao = _rodar_extrator(extrator, caso.imagem)
        leituras_repetidas = []
        for _ in range(execucoes - 1):
            nota_extra, recusada_extra, _, erro_extra, _ = _rodar_extrator(extrator, caso.imagem)
            if erro_extra is None:
                leituras_repetidas.append((
                    recusada_extra,
                    {c: getattr(nota_extra, c, None) for c in CAMPOS_NOTA} if nota_extra is not None else {},
                ))
        if progresso:
            situacao = (f"recusada ({motivo_recusa})" if recusada else f"ERRO {erro}" if erro else
                        f"ok: {getattr(nota, 'estabelecimento', None)!r}, {getattr(nota, 'valor_total', None)}")
            if leituras_repetidas:
                iguais = sum(
                    rec == recusada and (rec or all(
                        campo_correto(v.get(c), getattr(nota, c, None)) for c in CAMPOS_NOTA))
                    for rec, v in leituras_repetidas
                )
                situacao += f"; leituras repetidas iguais à 1ª: {iguais}/{len(leituras_repetidas)}"
            print(f"  [{nome}] {caso.id}: {situacao} ({duracao:.1f}s)", flush=True)

        campos = {}
        if not caso.foto_ilegivel:
            for campo, valor_esperado in caso.gabarito.items():
                valor_extraido = getattr(nota, campo, None) if nota is not None else None
                campos[campo] = (valor_extraido, valor_esperado)


        resultados.append(
            ResultadoCaso(
                caso_id=caso.id,
                duracao_segundos=duracao,
                foto_ilegivel_esperado=caso.foto_ilegivel,
                recusada=recusada,
                motivo_recusa=motivo_recusa,
                erro=erro,
                campos=campos,
                leituras_repetidas=leituras_repetidas,
            )
        )

    def resultado_foto(r: ResultadoCaso) -> str:
        if r.erro is not None:
            return "erro"
        return "recusou" if r.recusada else "aceitou"

    # A checagem da foto só se aplica a fotos (o PDF não passa por ela).
    so_pdf = bool(casos) and all(c.tipo_entrada == "pdf" for c in casos)
    matriz_foto = None if so_pdf else matriz_confusao(
        [resultado_foto(r) for r in resultados],
        ["ilegivel" if r.foto_ilegivel_esperado else "legivel" for r in resultados],
        ["legivel", "ilegivel"],
    )

    legiveis = [r for r in resultados if not r.foto_ilegivel_esperado]
    ruins = [r for r in resultados if r.foto_ilegivel_esperado]
    acuracia = acuracia_por_campo([r.campos for r in legiveis if r.campos])
    consistencia_campos, consistencia_recusa = _consistencia(resultados)

    return RelatorioExtrator(
        nome=nome,
        resultados_por_caso=resultados,
        acuracia_por_campo=acuracia,
        acuracia_media=sum(acuracia.values()) / len(acuracia) if acuracia else None,
        tempo_medio_segundos=(
            sum(r.duracao_segundos for r in resultados) / len(resultados) if resultados else 0.0
        ),
        fotos_ruins_recusadas=sum(1 for r in ruins if r.recusada),
        fotos_ruins_total=len(ruins),
        recusas_indevidas=[r.caso_id for r in legiveis if r.recusada],
        casos_com_erro=[r.caso_id for r in resultados if r.erro is not None],
        matriz_qualidade_foto=matriz_foto,
        matriz_resultados=_matriz_resultados(legiveis),
        execucoes=execucoes,
        consistencia_por_campo=consistencia_campos,
        consistencia_recusa=consistencia_recusa,
    )


def _matriz_resultados(resultados: list[ResultadoCaso]) -> dict[str, MetricasExtracaoCampo]:
    contagens = {campo: {r: 0 for r in RESULTADOS_CAMPO} for campo in CAMPOS_NOTA}
    for resultado in resultados:
        for campo, situacao in resultado.resultados_campos().items():
            contagens[campo][situacao] += 1
    contagens = {campo: c for campo, c in contagens.items() if sum(c.values())}
    if contagens:
        contagens["TOTAL"] = {
            r: sum(c[r] for c in contagens.values()) for r in RESULTADOS_CAMPO
        }
    return {campo: MetricasExtracaoCampo(c) for campo, c in contagens.items()}


def matriz_concordancia(
    relatorio_a: RelatorioExtrator, relatorio_b: RelatorioExtrator, campo: str | None = None
) -> MatrizConfusao:
    """
    Cruza, nota a nota, se cada uma das duas abordagens acertou o campo
    (ou todos os campos, se `campo` for None). Linhas = abordagem A,
    colunas = abordagem B. As células "acertou x errou" e "errou x
    acertou" são as notas em que só uma das duas acerta — a base do
    teste de McNemar para comparar duas abordagens nos mesmos casos.
    """
    def situacoes(relatorio: RelatorioExtrator) -> dict[tuple[str, str], str]:
        return {
            (r.caso_id, c): ("acertou" if s == CORRETO else "errou")
            for r in relatorio.resultados_por_caso
            if not r.foto_ilegivel_esperado
            for c, s in r.resultados_campos().items()
            if campo is None or c == campo
        }

    a, b = situacoes(relatorio_a), situacoes(relatorio_b)
    chaves = sorted(set(a) & set(b))
    return matriz_confusao([b[k] for k in chaves], [a[k] for k in chaves], ["acertou", "errou"])


def comparar_extratores(
    casos: list[CasoDeTeste], extratores: dict[str, ExtratorFn], progresso: bool = False,
    execucoes: int = 1,
) -> dict[str, RelatorioExtrator]:
    """Executa cada extrator (nome -> função) sobre os mesmos casos."""
    return {
        nome: executar_extrator_sobre_casos(nome, extrator, casos, progresso=progresso, execucoes=execucoes)
        for nome, extrator in extratores.items()
    }


def melhor_extrator(relatorios: dict[str, RelatorioExtrator]) -> str | None:
    """Nome do extrator com maior acurácia média por campo (empate: o mais rápido)."""
    candidatos = [r for r in relatorios.values() if r.acuracia_media is not None]
    if not candidatos:
        return None
    return max(candidatos, key=lambda r: (r.acuracia_media, -r.tempo_medio_segundos)).nome


def _pct(valor: float | None) -> str:
    return f"{valor:.0%}" if valor is not None else "—"


def _formatar_valor(valor: Any) -> str:
    if isinstance(valor, date):
        return valor.isoformat()
    if isinstance(valor, list):
        return "[" + "; ".join(map(str, valor)) + "]"
    return "—" if valor is None else str(valor)


def _formatar_matriz_foto(matriz: MatrizConfusao) -> str:
    """
    A matriz é montada com as mesmas classes nas linhas e colunas
    (legivel, ilegivel, aceitou, recusou, ...); aqui mostramos só o
    recorte que importa: gabarito (legível/ilegível) x sistema
    (aceitou/recusou/erro).
    """
    colunas = [c for c in ("aceitou", "recusou", "erro") if c in matriz.classes]
    linhas = [f"{'gabarito \\ sistema':<22}" + "".join(f"{c:>10}" for c in colunas)]
    for esperado in ("legivel", "ilegivel"):
        linhas.append(f"{esperado:<22}" + "".join(f"{matriz.valor(esperado, c):>10}" for c in colunas))
    return "\n".join(linhas)


_ROTULOS_RESULTADO = {
    "correto": "correto",
    "incorreto": "incorreto",
    "nao_extraido": "não extraído",
    "foto_recusada": "foto recusada",
}


def _formatar_matriz_resultados(matriz: dict[str, MetricasExtracaoCampo]) -> list[str]:
    colunas = list(_ROTULOS_RESULTADO.values())
    linhas = [f"{'campo':<18}" + "".join(f"{c:>15}" for c in colunas)
              + f"{'precisão':>10}{'revocação':>11}{'F1':>7}"]
    for campo, m in matriz.items():
        linhas.append(
            f"{campo:<18}"
            + "".join(f"{m.contagens.get(r, 0):>15}" for r in _ROTULOS_RESULTADO)
            + f"{m.precisao:>10.0%}{m.revocacao:>11.0%}{m.f1:>7.2f}"
        )
    return linhas


def _formatar_concordancia(matriz: MatrizConfusao, nome_a: str, nome_b: str) -> list[str]:
    largura = max(len(nome_a), 12) + 12
    linhas = [f"{'':<{largura}}{nome_b + ' acertou':>32}{nome_b + ' errou':>30}"]
    for situacao in ("acertou", "errou"):
        linhas.append(
            f"{nome_a + ' ' + situacao:<{largura}}"
            f"{matriz.valor(situacao, 'acertou'):>32}{matriz.valor(situacao, 'errou'):>30}"
        )
    return linhas


def montar_relatorio_texto(relatorios: dict[str, RelatorioExtrator]) -> str:
    """Formata os relatórios como texto, para imprimir ou salvar em arquivo."""
    linhas = []
    campos = [c for c in CAMPOS_NOTA if any(c in r.acuracia_por_campo for r in relatorios.values())]
    largura = max([15] + [len(n) + 2 for n in relatorios])

    for nome, relatorio in relatorios.items():
        linhas.append(f"\n=== {nome} ===")
        linhas.append(f"Tempo médio por arquivo: {relatorio.tempo_medio_segundos:.2f}s")
        if relatorio.consistencia_por_campo:
            linhas.append(f"Consistência entre as {relatorio.execucoes} leituras de cada arquivo:")
            for campo, valor in relatorio.consistencia_por_campo.items():
                rotulo = "todos os campos" if campo == "TODOS" else campo
                linhas.append(f"  {rotulo:<20} {_pct(valor)}")
            linhas.append(f"  {'aceitar/recusar':<20} {_pct(relatorio.consistencia_recusa)}")
        if relatorio.fotos_ruins_total:
            linhas.append(
                f"Fotos ruins recusadas (pedindo nova foto): "
                f"{relatorio.fotos_ruins_recusadas}/{relatorio.fotos_ruins_total}"
            )
        if relatorio.matriz_qualidade_foto is not None:
            linhas.append("Checagem da foto (linhas = gabarito, colunas = sistema):")
            linhas += ["  " + l for l in _formatar_matriz_foto(relatorio.matriz_qualidade_foto).splitlines()]
        if relatorio.recusas_indevidas:
            linhas.append(
                f"Fotos boas recusadas indevidamente ({len(relatorio.recusas_indevidas)}): "
                + ", ".join(relatorio.recusas_indevidas)
            )
        if relatorio.casos_com_erro:
            linhas.append(
                f"Casos com erro ({len(relatorio.casos_com_erro)}): "
                + ", ".join(relatorio.casos_com_erro)
            )
            for r in relatorio.resultados_por_caso:
                if r.erro:
                    linhas.append(f"  {r.caso_id}: {r.erro}")
        linhas.append("Acurácia por campo:")
        for campo in campos:
            linhas.append(f"  {campo:<20} {_pct(relatorio.acuracia_por_campo.get(campo))}")

        if relatorio.matriz_resultados:
            linhas.append("Matriz de resultados (notas com foto boa; linhas = campo):")
            linhas += ["  " + l for l in _formatar_matriz_resultados(relatorio.matriz_resultados)]

        linhas.append("Erros por caso (extraído ≠ esperado):")
        algum_erro = False
        for r in relatorio.resultados_por_caso:
            for campo, (extraido, esperado) in r.campos.items():
                if not campo_correto(extraido, esperado):
                    algum_erro = True
                    linhas.append(
                        f"  {r.caso_id} {campo}: {_formatar_valor(extraido)} "
                        f"≠ {_formatar_valor(esperado)}"
                    )
        if not algum_erro:
            linhas.append("  nenhum")

    linhas.append("\n=== Comparação lado a lado ===")
    linhas.append(f"{'campo':<20}" + "".join(f"{nome:>{largura}}" for nome in relatorios))
    for campo in campos:
        linhas.append(
            f"{campo:<20}"
            + "".join(f"{_pct(r.acuracia_por_campo.get(campo)):>{largura}}" for r in relatorios.values())
        )
    linhas.append(
        f"{'MÉDIA':<20}" + "".join(f"{_pct(r.acuracia_media):>{largura}}" for r in relatorios.values())
    )
    linhas.append(
        f"{'tempo médio':<20}"
        + "".join(f"{f'{r.tempo_medio_segundos:.2f}s':>{largura}}" for r in relatorios.values())
    )

    if "tesseract" in relatorios:
        for nome, relatorio in relatorios.items():
            if nome == "tesseract":
                continue
            linhas.append(f"\n=== Concordância: tesseract x {nome} (notas legíveis) ===")
            for campo in campos + [None]:
                matriz = matriz_concordancia(relatorios["tesseract"], relatorio, campo)
                if not matriz.total:
                    continue
                linhas.append(f"{campo or 'TODOS OS CAMPOS'}:")
                linhas += ["  " + l for l in _formatar_concordancia(matriz, "tesseract", "multimodal")]

    vencedor = melhor_extrator(relatorios)
    if vencedor:
        linhas.append(f"\nMaior acurácia média: {vencedor}")
    return "\n".join(linhas)


def _para_json(valor: Any) -> Any:
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, tuple):
        return [_para_json(v) for v in valor]
    if isinstance(valor, list):
        return [_para_json(v) for v in valor]
    if isinstance(valor, dict):
        return {k: _para_json(v) for k, v in valor.items()}
    return valor


def salvar_relatorio(
    relatorios: dict[str, RelatorioExtrator], pasta: Path, metadados: dict[str, Any],
    tipo_entrada: str | None = None,
) -> tuple[Path, Path]:
    """
    Salva tudo de uma execução numa pasta própria,
    <pasta>/extracao_<foto|pdf>/<AAAA-MM-DD_HHMMSS>/:

        relatorio.txt   relatório completo em texto
        dados.json      todos os números, caso a caso
        tabelas_csv/    matrizes e tabelas em CSV (para planilha)
        figuras/        matrizes e tabelas em PNG (para o TCC)
    """
    pasta_tipo = f"extracao_{tipo_entrada}" if tipo_entrada else "extracao"
    pasta_execucao = pasta / pasta_tipo / f"{datetime.now():%Y-%m-%d_%H%M%S}"
    pasta_execucao.mkdir(parents=True, exist_ok=True)
    caminho_txt = pasta_execucao / "relatorio.txt"
    caminho_json = pasta_execucao / "dados.json"

    salvar_matrizes_csv(relatorios, pasta_execucao / "tabelas_csv")
    salvar_figuras(relatorios, pasta_execucao / "figuras")

    cabecalho = "\n".join(f"{k}: {v}" for k, v in metadados.items())
    caminho_txt.write_text(cabecalho + "\n" + montar_relatorio_texto(relatorios) + "\n", encoding="utf-8")
    caminho_json.write_text(
        json.dumps(
            {"metadados": metadados, "extratores": {n: _para_json(asdict(r)) for n, r in relatorios.items()}},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return caminho_txt, caminho_json


def _nome_arquivo(nome: str) -> str:
    return nome.replace(":", "_").replace("/", "_").replace(".", "-")


def _nome_exibicao(nome: str) -> str:
    return "Tesseract" if nome == "tesseract" else nome.replace("multimodal:", "Multimodal (") + ")"


_ROTULOS_CAMPO = {
    "estabelecimento": "Estabelecimento",
    "data_emissao": "Data de emissão",
    "produtos": "Produtos",
    "valor_total": "Valor total",
    "TOTAL": "Total",
}


def salvar_figuras(relatorios: dict[str, RelatorioExtrator], pasta: Path) -> list[Path]:
    """
    Matrizes e tabelas da etapa 1 em PNG:
    - 01_comparacao_acuracia.png: acurácia por campo, lado a lado;
    - 02_resultados_<extrator>.png: correto/incorreto/não extraído/foto
      recusada, com precisão, revocação e F1 por campo;
    - 03_checagem_foto_<extrator>.png: matriz legível/ilegível x aceitou/recusou;
    - 04_concordancia_tesseract_x_<extrator>.png: matriz acertou/errou.
    """
    from avaliacao.figuras import pct, salvar_matriz_confusao, salvar_tabela

    gerados = []
    nomes = list(relatorios)
    campos = [c for c in CAMPOS_NOTA if any(c in r.acuracia_por_campo for r in relatorios.values())]
    linhas = [[_ROTULOS_CAMPO[c], *(pct(relatorios[n].acuracia_por_campo.get(c)) for n in nomes)] for c in campos]
    linhas.append(["Média", *(pct(relatorios[n].acuracia_media) for n in nomes)])
    linhas.append(["Tempo médio por arquivo", *(f"{relatorios[n].tempo_medio_segundos:.1f} s" for n in nomes)])
    gerados.append(salvar_tabela(
        ["Campo", *(_nome_exibicao(n) for n in nomes)], linhas,
        pasta / "01_comparacao_acuracia.png", "Acurácia por campo na extração da nota fiscal",
    ))

    for nome, relatorio in relatorios.items():
        exibicao = _nome_exibicao(nome)
        if relatorio.matriz_resultados:
            linhas = [
                [_ROTULOS_CAMPO.get(campo, campo), *(str(m.contagens.get(r, 0)) for r in RESULTADOS_CAMPO),
                 pct(m.precisao), pct(m.revocacao), f"{m.f1:.2f}"]
                for campo, m in relatorio.matriz_resultados.items()
            ]
            gerados.append(salvar_tabela(
                ["Campo", "Correto", "Incorreto", "Não extraído", "Foto recusada", "Precisão", "Revocação", "F1"],
                linhas, pasta / f"02_resultados_{_nome_arquivo(nome)}.png",
                f"Resultados da extração por campo — {exibicao}", destacar_ultima_linha=True,
            ))
        if relatorio.matriz_qualidade_foto is not None:
            matriz = relatorio.matriz_qualidade_foto
            colunas = [c for c in ("aceitou", "recusou", "erro") if c != "erro" or matriz.valor("legivel", "erro")
                       or matriz.valor("ilegivel", "erro")]
            gerados.append(salvar_matriz_confusao(
                matriz, pasta / f"03_checagem_foto_{_nome_arquivo(nome)}.png",
                f"Checagem da foto — {exibicao}", linhas=["legivel", "ilegivel"], colunas=colunas,
            ))
        if nome != "tesseract" and "tesseract" in relatorios:
            gerados.append(salvar_matriz_confusao(
                matriz_concordancia(relatorios["tesseract"], relatorio),
                pasta / f"04_concordancia_tesseract_x_{_nome_arquivo(nome)}.png",
                f"Concordância por campo: Tesseract x {exibicao}",
                rotulo_linhas="Tesseract", rotulo_colunas=exibicao,
                rotulo_diagonal="Mesmo resultado nas duas abordagens (diagonal)",
            ))
    if any(r.consistencia_por_campo for r in relatorios.values()):
        execucoes = max(r.execucoes for r in relatorios.values())
        chaves = [*campos, "TODOS"]
        linhas = [
            [_ROTULOS_CAMPO.get(c, "Todos os campos" if c == "TODOS" else c),
             *(pct((relatorios[n].consistencia_por_campo or {}).get(c)) for n in nomes)]
            for c in chaves
        ]
        linhas.append(["Decisão aceitar/recusar a foto", *(pct(relatorios[n].consistencia_recusa) for n in nomes)])
        gerados.append(salvar_tabela(
            ["Campo", *(_nome_exibicao(n) for n in nomes)], linhas, pasta / "05_consistencia.png",
            f"Consistência: mesma leitura nas {execucoes} execuções de cada arquivo",
        ))
    return gerados


def salvar_matrizes_csv(relatorios: dict[str, RelatorioExtrator], pasta: Path) -> None:
    """
    Salva em CSV (separador ';'), para montar as tabelas do TCC:
    - resultados_<extrator>.csv: matriz de resultados por campo;
    - concordancia_tesseract_x_<extrator>.csv: concordância por campo;
    - foto_<extrator>.csv: checagem da foto.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    nome_arquivo = _nome_arquivo

    for nome, relatorio in relatorios.items():
        linhas = ["campo;" + ";".join(RESULTADOS_CAMPO) + ";precisao;revocacao;f1"]
        for campo, m in relatorio.matriz_resultados.items():
            linhas.append(
                f"{campo};" + ";".join(str(m.contagens.get(r, 0)) for r in RESULTADOS_CAMPO)
                + f";{m.precisao:.4f};{m.revocacao:.4f};{m.f1:.4f}"
            )
        (pasta / f"resultados_{nome_arquivo(nome)}.csv").write_text("\n".join(linhas) + "\n", encoding="utf-8")

        if relatorio.matriz_qualidade_foto is not None:
            matriz = relatorio.matriz_qualidade_foto
            foto = ["gabarito \\ sistema;aceitou;recusou;erro"] + [
                f"{e};{matriz.valor(e, 'aceitou')};{matriz.valor(e, 'recusou')};{matriz.valor(e, 'erro')}"
                for e in ("legivel", "ilegivel")
            ]
            (pasta / f"foto_{nome_arquivo(nome)}.csv").write_text("\n".join(foto) + "\n", encoding="utf-8")

        if nome != "tesseract" and "tesseract" in relatorios:
            linhas = ["campo;ambos_acertaram;so_tesseract_acertou;so_multimodal_acertou;ambos_erraram"]
            for campo in [*CAMPOS_NOTA, None]:
                m = matriz_concordancia(relatorios["tesseract"], relatorio, campo)
                if m.total:
                    linhas.append(
                        f"{campo or 'TOTAL'};{m.valor('acertou', 'acertou')};{m.valor('acertou', 'errou')};"
                        f"{m.valor('errou', 'acertou')};{m.valor('errou', 'errou')}"
                    )
            (pasta / f"concordancia_tesseract_x_{nome_arquivo(nome)}.csv").write_text(
                "\n".join(linhas) + "\n", encoding="utf-8"
            )


def montar_extratores(
    modelos_multimodais: list[str], checar_qualidade: bool = True
) -> dict[str, ExtratorFn]:
    """
    Tesseract sempre; um extrator multimodal para cada modelo em
    `modelos_multimodais` (lista vazia = só Tesseract). Todos passam
    pelo mesmo fluxo do sistema (app.extracao.detector), inclusive a
    checagem de qualidade da foto, para medir o que o usuário veria.
    """
    from app.extracao.detector import extrair_dados_nota_fiscal

    extratores: dict[str, ExtratorFn] = {
        "tesseract": partial(
            extrair_dados_nota_fiscal, extrator="tesseract", checar_qualidade=checar_qualidade
        )
    }
    for modelo in modelos_multimodais:
        extratores[f"multimodal:{modelo}"] = partial(
            extrair_dados_nota_fiscal,
            extrator="multimodal",
            nome_modelo=modelo,
            checar_qualidade=checar_qualidade,
        )
    return extratores


def main(argv: list[str] | None = None) -> None:
    from app.config import MODELO_LLM, modelo_configurado

    parser = argparse.ArgumentParser(
        description="Compara Tesseract e modelo(s) multimodal(is) na extração da nota fiscal."
    )
    parser.add_argument("casos", type=Path, help="arquivo JSON de casos (ex.: dados/casos_foto.json)")
    parser.add_argument(
        "--modelos",
        default=MODELO_LLM,
        help=f"modelos multimodais (Claude), separados por vírgula (padrão: {MODELO_LLM})",
    )
    parser.add_argument("--sem-multimodal", action="store_true", help="roda só o Tesseract")
    parser.add_argument(
        "--sem-checagem-qualidade",
        action="store_true",
        help="não recusa fotos ruins antes da extração (mede os extratores 'puros')",
    )
    parser.add_argument("--saida", type=Path, default=PASTA_RESULTADOS_PADRAO, help="pasta dos relatórios")
    parser.add_argument("--execucoes", type=int, default=3,
                        help="leituras de cada arquivo, para medir a consistência (padrão: 3)")
    args = parser.parse_args(argv)

    casos = carregar_casos(args.casos)
    tipos = {c.tipo_entrada for c in casos}
    tipo_entrada = tipos.pop() if len(tipos) == 1 else "misto"
    print(f"{len(casos)} caso(s) carregados de {args.casos} (entrada: {tipo_entrada})")

    modelos = [] if args.sem_multimodal else [m.strip() for m in args.modelos.split(",") if m.strip()]
    if modelos and not modelo_configurado():
        print("Aviso: chave de API do modelo não configurada; rodando só o Tesseract (ver README.md).")
        modelos = []
    if modelos:
        print(
            "Lembrete (LGPD/Metodologia): só envie ao modelo de linguagem imagens com CPF e "
            "dados pessoais já ocultados ao modelo de linguagem."
        )

    extratores = montar_extratores(modelos, checar_qualidade=not args.sem_checagem_qualidade)
    relatorios = comparar_extratores(casos, extratores, progresso=True, execucoes=args.execucoes)

    print(montar_relatorio_texto(relatorios))
    caminho_txt, caminho_json = salvar_relatorio(
        relatorios,
        args.saida,
        metadados={
            "arquivo_de_casos": str(args.casos),
            "data_execucao": datetime.now().isoformat(timespec="seconds"),
            "extratores": list(extratores),
            "checagem_de_qualidade": not args.sem_checagem_qualidade,
            "tipo_entrada": tipo_entrada,
            "execucoes_por_arquivo": args.execucoes,
        },
        tipo_entrada=tipo_entrada,
    )
    print(f"\nResultados salvos em {caminho_txt.parent}/ (relatorio.txt, dados.json, tabelas_csv/, figuras/)")


if __name__ == "__main__":
    main()
