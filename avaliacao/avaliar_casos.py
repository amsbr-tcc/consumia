"""
Avaliação das etapas 2, 3 e 4 e do fluxo completo sobre os casos de
teste, conforme a Metodologia (a etapa 1, extração, é avaliada em
comparar_extracao.py):

- Classificação: cada relato é classificado TRÊS vezes. Para a
  primeira execução (a resposta que o usuário receberia) são montadas
  as matrizes de confusão (tipo de vício, durabilidade e classificação
  completa) e, a partir delas, acurácia e, por categoria, precisão,
  revocação e F1 (Manning; Raghavan; Schütze, 2008). A consistência é a
  proporção de casos em que as três execuções deram a mesma resposta,
  e uma matriz com as 3×N execuções mostra se as variações caem sempre
  na mesma confusão.
- Prazo: a função do art. 26 é executada com a classificação e as
  datas do GABARITO e comparada aos dias restantes esperados (isola a
  etapa 3 dos erros da etapa 2). Os limites exatos do prazo são
  testados em tests/test_prazo.py.
- Diagnóstico completo: proporção de casos em que o fluxo chegou à
  classificação E ao prazo iguais aos do gabarito, mais a matriz de
  confusão da situação final (dentro do prazo / fora do prazo / fora
  do escopo), que mostra o impacto prático dos erros de classificação
  (ex.: um caso dentro do prazo apontado como vencido).

Cada execução fica em resultados/fluxo_completo/<AAAA-MM-DD_HHMMSS>/, com
relatorio.txt, dados.json, tabelas_csv/ e figuras/ (matrizes de confusão
e tabelas em PNG, prontas para o TCC) e cartas/.
- Cartas: geradas para os casos dentro do escopo e do prazo e salvas,
  cada uma com a lista de verificação da análise qualitativa, para as
  autoras preencherem.

Uso (a partir da raiz do projeto; requer a chave de API do modelo, ver README):

    python3 -m avaliacao.avaliar_casos dados/casos_foto.json
    python3 -m avaliacao.avaliar_casos dados/casos_foto.json --extrator multimodal
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.classificacao.classifier import RespostaInvalidaError, classificar_relato
from avaliacao.casos import CasoDeTeste, carregar_casos
from avaliacao.metricas import (
    MatrizConfusao,
    consistencia,
    matriz_confusao,
    precisao_revocacao_f1,
    proporcao_diagnostico_correto,
)
from app.extracao.qualidade_imagem import ImagemIlegivelError
from app.models import CasoConsumidor, ClassificacaoVicio, Durabilidade, RelatoUsuario, TipoVicio
from app.prazo.calculator import DadosInsuficientesError, calcular_prazo

EXECUCOES_POR_CASO = 3

# Ordem fixa das classes nas matrizes de confusão (classes sem casos
# aparecem zeradas, para as tabelas terem sempre o mesmo formato).
CLASSES_TIPO = ["aparente", "oculto", "fora_de_escopo"]
CLASSES_DURABILIDADE = ["duravel", "nao_duravel", "fora_de_escopo"]
CLASSES_COMPLETA = [
    "aparente/duravel",
    "aparente/nao_duravel",
    "oculto/duravel",
    "oculto/nao_duravel",
    "fora_de_escopo",
]
CLASSES_SITUACAO = ["dentro_do_prazo", "fora_do_prazo", "indeterminado", "fora_de_escopo"]
PASTA_RESULTADOS_PADRAO = Path("resultados")

# Artigos que o sistema manda citar (ver app/carta/prompts.py). Usado
# só como ajuda automática à lista de verificação, que é feita à mão.
_ARTIGOS_PERMITIDOS = {"18", "26", "50"}
_PADRAO_ARTIGO = re.compile(r"\bart(?:igo)?s?\.?\s*(\d+)", re.IGNORECASE)

LISTA_DE_VERIFICACAO = [
    "Traz a identificação das partes (consumidor e fornecedor)",
    "Traz o relato dos fatos",
    "Traz o fundamento legal",
    "Traz o pedido (art. 18, §1º: sanar em 30 dias; depois substituição, restituição ou abatimento)",
    "Traz o prazo para resposta",
    "Usa apenas os dados informados, sem inventar informações (dados ausentes marcados com [ ])",
    "Os artigos citados estão corretos",
]


@dataclass
class ResultadoAvaliacaoCaso:
    caso_id: str
    rotulo_esperado: str
    rotulos_obtidos: list[str] = field(default_factory=list)
    justificativas: list[str] = field(default_factory=list)
    dias_restantes_esperado: int | None = None
    dias_restantes_calculado_gabarito: int | None = None   # etapa 3 isolada
    dias_restantes_fluxo: int | None = None                # com a classificação do modelo
    situacao_esperada: str | None = None                   # dentro/fora do prazo ou fora de escopo
    situacao_fluxo: str | None = None
    situacao_calculada_gabarito: str | None = None         # etapa 3 isolada
    diagnostico_correto: bool = False
    carta: str | None = None
    artigos_citados: list[str] = field(default_factory=list)
    observacao: str | None = None

    @property
    def classificacao_correta(self) -> bool:
        return bool(self.rotulos_obtidos) and self.rotulos_obtidos[0] == self.rotulo_esperado

    @property
    def prazo_correto(self) -> bool | None:
        if self.dias_restantes_esperado is None:
            return None
        return (
            self.dias_restantes_calculado_gabarito == self.dias_restantes_esperado
            and self.situacao_calculada_gabarito == self.situacao_esperada
        )


def _prazo(caso: CasoDeTeste, tipo_vicio: str, durabilidade: str):
    try:
        return calcular_prazo(
            tipo_vicio=TipoVicio(tipo_vicio),
            durabilidade=Durabilidade(durabilidade),
            data_entrega=caso.data_entrega,
            data_evidencia_defeito=caso.data_evidencia_defeito,
            data_referencia=caso.data_referencia,
            **_datas_que_alteram_prazo(caso),
        )
    except (DadosInsuficientesError, ValueError):
        return None


def _datas_que_alteram_prazo(caso: CasoDeTeste) -> dict:
    return {
        "data_reclamacao_fornecedor": caso.data_reclamacao_fornecedor,
        "data_resposta_negativa": caso.data_resposta_negativa,
        "data_fim_garantia_contratual": caso.data_fim_garantia_contratual,
    }


def _dias_restantes(caso: CasoDeTeste, tipo_vicio: str, durabilidade: str) -> int | None:
    prazo = _prazo(caso, tipo_vicio, durabilidade)
    return prazo.dias_restantes if prazo else None


def _situacao(caso: CasoDeTeste, fora_de_escopo: bool, tipo_vicio: str | None, durabilidade: str | None) -> str:
    if fora_de_escopo:
        return "fora_de_escopo"
    prazo = _prazo(caso, tipo_vicio, durabilidade)
    if prazo is None:
        return "sem_dados"
    return prazo.situacao.value


def _gerar_carta(caso: CasoDeTeste, classificacao: ClassificacaoVicio, extrator: str) -> tuple[str | None, str | None]:
    """Roda extração + prazo + carta (etapas 1, 3 e 4) para o caso."""
    from app.extracao.detector import extrair_dados_nota_fiscal
    from app.carta.generator import gerar_carta

    try:
        nota = extrair_dados_nota_fiscal(caso.imagem, extrator=extrator)
    except ImagemIlegivelError as exc:
        return None, f"foto recusada na extração ({exc.motivo.value})"

    prazo = calcular_prazo(
        tipo_vicio=classificacao.tipo_vicio,
        durabilidade=classificacao.durabilidade,
        data_entrega=caso.data_entrega,
        data_evidencia_defeito=caso.data_evidencia_defeito,
        data_referencia=caso.data_referencia,
        **_datas_que_alteram_prazo(caso),
    )
    if not prazo.dentro_do_prazo:
        return None, f"{prazo.situacao.value}: o sistema não gera carta"

    caso_consumidor = CasoConsumidor(
        nota=nota,
        relato=RelatoUsuario(caso.relato, caso.data_entrega, caso.data_evidencia_defeito,
                             **_datas_que_alteram_prazo(caso)),
        classificacao=classificacao,
        prazo=prazo,
    )
    return gerar_carta(caso_consumidor), None


def avaliar_caso(caso: CasoDeTeste, extrator: str, gerar_cartas: bool = True) -> ResultadoAvaliacaoCaso:
    esperado = caso.esperado
    resultado = ResultadoAvaliacaoCaso(
        caso_id=caso.id,
        rotulo_esperado=esperado.rotulo,
        dias_restantes_esperado=esperado.dias_restantes,
    )

    classificacoes: list[ClassificacaoVicio] = []
    for _ in range(EXECUCOES_POR_CASO):
        try:
            classificacao = classificar_relato(caso.relato)
            classificacoes.append(classificacao)
            resultado.rotulos_obtidos.append(classificacao.rotulo)
            resultado.justificativas.append(classificacao.justificativa)
        except RespostaInvalidaError as exc:
            resultado.rotulos_obtidos.append("resposta_invalida")
            resultado.justificativas.append(str(exc))

    if not esperado.fora_de_escopo:
        resultado.dias_restantes_calculado_gabarito = _dias_restantes(
            caso, esperado.tipo_vicio, esperado.durabilidade
        )
    resultado.situacao_esperada = esperado.situacao or _situacao(
        caso, esperado.fora_de_escopo, esperado.tipo_vicio, esperado.durabilidade
    )
    resultado.situacao_calculada_gabarito = _situacao(
        caso, esperado.fora_de_escopo, esperado.tipo_vicio, esperado.durabilidade
    )

    primeira = classificacoes[0] if classificacoes and resultado.rotulos_obtidos[0] != "resposta_invalida" else None
    if primeira is not None and not primeira.fora_de_escopo:
        resultado.dias_restantes_fluxo = _dias_restantes(
            caso, primeira.tipo_vicio.value, primeira.durabilidade.value
        )
    if primeira is None:
        resultado.situacao_fluxo = "resposta_invalida"
    else:
        resultado.situacao_fluxo = _situacao(
            caso,
            primeira.fora_de_escopo,
            primeira.tipo_vicio.value if primeira.tipo_vicio else None,
            primeira.durabilidade.value if primeira.durabilidade else None,
        )

    if esperado.fora_de_escopo:
        resultado.diagnostico_correto = resultado.classificacao_correta
    else:
        resultado.diagnostico_correto = (
            resultado.classificacao_correta
            and resultado.dias_restantes_fluxo == esperado.dias_restantes
            and resultado.situacao_fluxo == resultado.situacao_esperada
        )

    if gerar_cartas and primeira is not None and not primeira.fora_de_escopo:
        resultado.carta, resultado.observacao = _gerar_carta(caso, primeira, extrator)
        if resultado.carta:
            resultado.artigos_citados = sorted(set(_PADRAO_ARTIGO.findall(resultado.carta)), key=int)

    return resultado


def _tipo(rotulo: str) -> str:
    return rotulo.split("/")[0]


def _durabilidade(rotulo: str) -> str:
    return rotulo.split("/")[-1]


def montar_matrizes(resultados: list[ResultadoAvaliacaoCaso]) -> dict[str, MatrizConfusao]:
    """
    Matrizes de confusão da avaliação (linhas = gabarito, colunas =
    sistema). As três primeiras usam a 1ª execução de cada caso; a
    "todas_execucoes" usa as 3 execuções de todos os casos.
    """
    esperados = [r.rotulo_esperado for r in resultados]
    previstos = [r.rotulos_obtidos[0] if r.rotulos_obtidos else "sem_resposta" for r in resultados]
    todas_esperadas = [r.rotulo_esperado for r in resultados for _ in r.rotulos_obtidos]
    todas_obtidas = [rotulo for r in resultados for rotulo in r.rotulos_obtidos]

    return {
        "tipo_vicio": matriz_confusao(
            [_tipo(p) for p in previstos], [_tipo(e) for e in esperados], CLASSES_TIPO
        ),
        "durabilidade": matriz_confusao(
            [_durabilidade(p) for p in previstos], [_durabilidade(e) for e in esperados], CLASSES_DURABILIDADE
        ),
        "classificacao_completa": matriz_confusao(previstos, esperados, CLASSES_COMPLETA),
        "classificacao_completa_todas_execucoes": matriz_confusao(todas_obtidas, todas_esperadas, CLASSES_COMPLETA),
        "situacao_final": matriz_confusao(
            [r.situacao_fluxo or "sem_resposta" for r in resultados],
            [r.situacao_esperada for r in resultados],
            CLASSES_SITUACAO,
        ),
    }


_TITULOS_MATRIZES = {
    "tipo_vicio": "Tipo de vício (1ª execução)",
    "durabilidade": "Durabilidade (1ª execução)",
    "classificacao_completa": "Classificação completa — tipo/durabilidade (1ª execução)",
    "classificacao_completa_todas_execucoes": f"Classificação completa — todas as {EXECUCOES_POR_CASO} execuções",
    "situacao_final": "Situação final do caso (gabarito x fluxo completo)",
}


def _bloco_matriz(titulo: str, matriz: MatrizConfusao, com_metricas: bool = True) -> list[str]:
    linhas = [f"\n--- {titulo} ---", "Matriz de confusão (linhas = gabarito, colunas = sistema):"]
    linhas += ["  " + linha for linha in matriz.formatar_texto("gabarito", "sistema").splitlines()]
    if matriz.total:
        linhas.append(f"  acertos (diagonal): {matriz.acertos}/{matriz.total} = {matriz.acertos / matriz.total:.0%}")
    if matriz.confusoes():
        linhas.append("  confusões: " + "; ".join(
            f"{esperado} → {previsto} ({n})" for esperado, previsto, n in matriz.confusoes()
        ))
    if com_metricas:
        previstos = [p for e in matriz.classes for p in matriz.classes for _ in range(matriz.valor(e, p))]
        esperados = [e for e in matriz.classes for p in matriz.classes for _ in range(matriz.valor(e, p))]
        if previstos:
            linhas.append(f"  {'categoria':<26}{'precisão':>10}{'revocação':>11}{'F1':>7}{'suporte':>9}")
            for classe, m in precisao_revocacao_f1(previstos, esperados).items():
                linhas.append(f"  {classe:<26}{m.precisao:>10.0%}{m.revocacao:>11.0%}{m.f1:>7.2f}{m.suporte:>9}")
    return linhas


def montar_relatorio_texto(resultados: list[ResultadoAvaliacaoCaso]) -> str:
    matrizes = montar_matrizes(resultados)

    linhas = [f"=== Classificação ({len(resultados)} casos, {EXECUCOES_POR_CASO} execuções cada) ==="]
    for chave in ("tipo_vicio", "durabilidade", "classificacao_completa", "classificacao_completa_todas_execucoes"):
        linhas += _bloco_matriz(_TITULOS_MATRIZES[chave], matrizes[chave])

    linhas.append(
        f"\nConsistência (mesma resposta nas {EXECUCOES_POR_CASO} execuções): "
        f"{consistencia([r.rotulos_obtidos for r in resultados]):.0%}"
    )
    for r in resultados:
        if len(set(r.rotulos_obtidos)) > 1:
            linhas.append(f"  {r.caso_id} variou: {', '.join(r.rotulos_obtidos)}")

    com_prazo = [r for r in resultados if r.prazo_correto is not None]
    linhas.append("\n=== Prazo (classificação e datas do gabarito) ===")
    if com_prazo:
        acertos = sum(1 for r in com_prazo if r.prazo_correto)
        linhas.append(f"  dias restantes e situação iguais ao gabarito: {acertos}/{len(com_prazo)}")
        for r in com_prazo:
            if not r.prazo_correto:
                linhas.append(
                    f"  {r.caso_id}: calculado {r.dias_restantes_calculado_gabarito} "
                    f"({r.situacao_calculada_gabarito}), esperado {r.dias_restantes_esperado} "
                    f"({r.situacao_esperada})"
                )

    linhas.append("\n=== Diagnóstico completo (classificação e prazo corretos) ===")
    linhas.append(
        f"  {proporcao_diagnostico_correto([r.diagnostico_correto for r in resultados]):.0%} "
        f"({sum(r.diagnostico_correto for r in resultados)}/{len(resultados)})"
    )
    linhas += _bloco_matriz(_TITULOS_MATRIZES["situacao_final"], matrizes["situacao_final"], com_metricas=False)

    linhas.append("\n=== Por caso ===")
    for r in resultados:
        linhas.append(
            f"  {r.caso_id}: esperado {r.rotulo_esperado}, obtido {', '.join(r.rotulos_obtidos)}; "
            f"dias restantes esperado {r.dias_restantes_esperado}, fluxo {r.dias_restantes_fluxo}; "
            f"diagnóstico {'OK' if r.diagnostico_correto else 'ERRADO'}"
            + (f"; {r.observacao}" if r.observacao else "")
        )
    return "\n".join(linhas)


def salvar_matrizes(matrizes: dict[str, MatrizConfusao], pasta: Path) -> None:
    """Salva cada matriz em CSV (separador ';'), para abrir em planilha."""
    pasta.mkdir(parents=True, exist_ok=True)
    for nome, matriz in matrizes.items():
        (pasta / f"{nome}.csv").write_text(matriz.para_csv(), encoding="utf-8")


def salvar_carta(resultado: ResultadoAvaliacaoCaso, pasta: Path) -> Path:
    """Salva a carta com a lista de verificação da análise qualitativa."""
    pasta.mkdir(parents=True, exist_ok=True)
    artigos_fora = [a for a in resultado.artigos_citados if a not in _ARTIGOS_PERMITIDOS]
    conteudo = [
        f"# Carta — {resultado.caso_id}",
        "",
        "## Lista de verificação (preencher manualmente)",
        "",
        *[f"- [ ] {item}" for item in LISTA_DE_VERIFICACAO],
        "",
        f"Ajuda automática: artigos citados na carta: {', '.join(resultado.artigos_citados) or 'nenhum'}"
        + (f" — ATENÇÃO, fora dos indicados pelo sistema: {', '.join(artigos_fora)}" if artigos_fora else ""),
        "",
        "Observações:",
        "",
        "## Texto gerado",
        "",
        resultado.carta or "",
        "",
    ]
    caminho = pasta / f"{resultado.caso_id}.md"
    caminho.write_text("\n".join(conteudo), encoding="utf-8")
    return caminho


_TITULOS_FIGURAS = {
    "tipo_vicio": "Matriz de confusão — tipo de vício",
    "durabilidade": "Matriz de confusão — durabilidade do produto",
    "classificacao_completa": "Matriz de confusão — classificação completa",
    "classificacao_completa_todas_execucoes": f"Matriz de confusão — todas as {EXECUCOES_POR_CASO} execuções",
    "situacao_final": "Matriz de confusão — situação final do caso",
}


def _tabela_metricas(matriz: MatrizConfusao) -> list[list[str]]:
    from avaliacao.figuras import pct, rotulo

    previstos = [p for e in matriz.classes for p in matriz.classes for _ in range(matriz.valor(e, p))]
    esperados = [e for e in matriz.classes for p in matriz.classes for _ in range(matriz.valor(e, p))]
    metricas = precisao_revocacao_f1(previstos, esperados)
    # Mesma ordem das linhas da matriz; classes sem nenhum caso no gabarito ficam de fora.
    linhas = [
        [rotulo(classe).replace("\n", " "), pct(m.precisao), pct(m.revocacao), f"{m.f1:.2f}", str(m.suporte)]
        for classe in matriz.classes
        if (m := metricas.get(classe)) and m.suporte
    ]
    if matriz.total:
        linhas.append(["Acurácia", pct(matriz.acertos / matriz.total), "", "", str(matriz.total)])
    return linhas


def salvar_figuras(resultados: list[ResultadoAvaliacaoCaso], pasta: Path) -> list[Path]:
    """
    Matrizes de confusão e tabelas das etapas 2 a 4 em PNG:
    01 tipo de vício (matriz + métricas), 02 durabilidade, 03 classificação
    completa, 04 todas as execuções, 05 situação final, 06 resumo e
    07 resultado por caso.
    """
    from avaliacao.figuras import pct, rotulo, salvar_matriz_confusao, salvar_tabela

    matrizes = montar_matrizes(resultados)
    gerados = []
    cabecalho_metricas = ["Categoria", "Precisão", "Revocação", "F1", "Suporte"]
    for numero, chave in enumerate(
        ["tipo_vicio", "durabilidade", "classificacao_completa", "classificacao_completa_todas_execucoes"], 1
    ):
        gerados.append(salvar_matriz_confusao(matrizes[chave], pasta / f"{numero:02d}_matriz_{chave}.png",
                                              _TITULOS_FIGURAS[chave]))
        if chave != "classificacao_completa_todas_execucoes":
            gerados.append(salvar_tabela(
                cabecalho_metricas, _tabela_metricas(matrizes[chave]), pasta / f"{numero:02d}_metricas_{chave}.png",
                "Métricas — " + _TITULOS_FIGURAS[chave].split("— ")[1], destacar_ultima_linha=True,
            ))

    gerados.append(salvar_matriz_confusao(matrizes["situacao_final"], pasta / "05_matriz_situacao_final.png",
                                          _TITULOS_FIGURAS["situacao_final"]))

    com_prazo = [r for r in resultados if r.prazo_correto is not None]
    resumo = [
        ["Acurácia da classificação (1ª execução)",
         pct(sum(r.classificacao_correta for r in resultados) / len(resultados)) if resultados else "—"],
        [f"Consistência entre as {EXECUCOES_POR_CASO} execuções",
         pct(consistencia([r.rotulos_obtidos for r in resultados]))],
        ["Prazo igual ao gabarito (etapa 3 isolada)",
         f"{sum(r.prazo_correto for r in com_prazo)} de {len(com_prazo)}"],
        ["Diagnóstico completo correto",
         f"{sum(r.diagnostico_correto for r in resultados)} de {len(resultados)} "
         f"({proporcao_diagnostico_correto([r.diagnostico_correto for r in resultados]):.0%})"],
        ["Cartas geradas", str(sum(1 for r in resultados if r.carta))],
    ]
    gerados.append(salvar_tabela(["Indicador", "Resultado"], resumo, pasta / "06_resumo.png",
                                 "Resumo da avaliação"))

    def _r(r: str) -> str:
        return rotulo(r).replace("\n", " ")

    por_caso = [
        [r.caso_id, _r(r.rotulo_esperado), ", ".join(_r(x) for x in r.rotulos_obtidos[:1]) or "—",
         "Sim" if len(set(r.rotulos_obtidos)) == 1 else "Não",
         "—" if r.dias_restantes_esperado is None else str(r.dias_restantes_esperado),
         "—" if r.dias_restantes_fluxo is None else str(r.dias_restantes_fluxo),
         _r(r.situacao_fluxo or "sem_resposta"), "Correto" if r.diagnostico_correto else "Errado"]
        for r in resultados
    ]
    gerados.append(salvar_tabela(
        ["Caso", "Gabarito", "Sistema (1ª exec.)", "Consistente", "Dias (gabarito)", "Dias (sistema)",
         "Situação (sistema)", "Diagnóstico"],
        por_caso, pasta / "07_resultado_por_caso.png", "Resultado por caso",
    ))
    return gerados


def main(argv: list[str] | None = None) -> None:
    from app.config import MODELO_LLM, modelo_configurado
    from app.extracao.detector import EXTRATOR_DE_IMAGEM_PADRAO, EXTRATORES

    parser = argparse.ArgumentParser(description="Avalia classificação, prazo, diagnóstico e cartas.")
    parser.add_argument("casos", type=Path, help="arquivo JSON de casos (ex.: dados/casos_foto.json)")
    parser.add_argument("--extrator", choices=EXTRATORES, default=EXTRATOR_DE_IMAGEM_PADRAO,
                        help="extrator usado para os dados da nota nas cartas")
    parser.add_argument("--sem-cartas", action="store_true", help="não gera as cartas")
    parser.add_argument("--saida", type=Path, default=PASTA_RESULTADOS_PADRAO, help="pasta dos relatórios")
    args = parser.parse_args(argv)

    if not modelo_configurado():
        raise SystemExit("Chave de API do modelo não configurada (ver README.md).")

    casos = [c for c in carregar_casos(args.casos) if c.esperado is not None and c.relato]
    print(f"{len(casos)} caso(s) com relato e gabarito em {args.casos} — modelo {MODELO_LLM}")

    resultados = []
    for caso in casos:
        print(f"  avaliando {caso.id}...")
        resultados.append(avaliar_caso(caso, extrator=args.extrator, gerar_cartas=not args.sem_cartas))

    relatorio = montar_relatorio_texto(resultados)
    print("\n" + relatorio)

    pasta_execucao = args.saida / "fluxo_completo" / f"{datetime.now():%Y-%m-%d_%H%M%S}"
    pasta_execucao.mkdir(parents=True, exist_ok=True)
    (pasta_execucao / "relatorio.txt").write_text(
        f"modelo: {MODELO_LLM}\nextrator: {args.extrator}\n\n{relatorio}\n", encoding="utf-8"
    )
    (pasta_execucao / "dados.json").write_text(
        json.dumps([{**r.__dict__} for r in resultados], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    salvar_matrizes(montar_matrizes(resultados), pasta_execucao / "tabelas_csv")
    salvar_figuras(resultados, pasta_execucao / "figuras")
    for r in resultados:
        if r.carta:
            salvar_carta(r, pasta_execucao / "cartas")
    print(f"\nResultados salvos em {pasta_execucao}/ (relatorio.txt, dados.json, tabelas_csv/, figuras/, cartas/)")


if __name__ == "__main__":
    main()
