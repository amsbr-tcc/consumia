"""
Métricas de avaliação usadas sobre os casos de teste, conforme descrito
na Metodologia:

- acurácia por campo, na extração da nota fiscal, e a matriz de
  resultados por campo (correto / incorreto / não extraído / foto
  recusada), com precisão, revocação e F1 de cada abordagem;
- acurácia, precisão, revocação e F1 por categoria, na classificação
  do vício (Manning; Raghavan; Schütze, 2008), e a matriz de confusão
  da qual essas medidas derivam;
- proporção de casos com diagnóstico completo correto (classificação e
  prazo iguais ao gabarito).

Implementadas como funções puras, sem qualquer dependência de API ou de
E/S, para que possam ser testadas isoladamente e para que o cálculo das
métricas em si (diferente da extração e da classificação) não dependa
de nenhum modelo de linguagem.
"""
from __future__ import annotations

import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Extração: acurácia por campo
# ---------------------------------------------------------------------------

def normalizar_texto(texto: str) -> str:
    """
    Remove diferenças só de formatação, que não deveriam contar como
    erro de extração: maiúsculas/minúsculas, acentos (papel térmico e
    OCR costumam perdê-los), pontuação e espaços repetidos.
    """
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    so_letras_e_numeros = re.sub(r"[^A-Za-z0-9]+", " ", sem_acento)
    return so_letras_e_numeros.strip().upper()


class AlternativasAceitas(tuple):
    """
    Gabarito com mais de um valor aceito para o mesmo campo (ex.: o
    estabelecimento pode ser a razão social ou o nome que aparece no
    topo da nota). Basta o valor extraído coincidir com um deles.
    """


def campo_correto(valor_extraido, valor_esperado) -> bool:
    """
    Compara um campo extraído com o valor do gabarito:

    - texto (estabelecimento): igual após normalizar_texto;
    - lista (produtos): mesmos itens, na mesma quantidade, após
      normalizar cada descrição (a ordem não importa). Basta um item
      errado ou faltando para o campo contar como erro;
    - número (valor total): igual até o centavo;
    - data: igual;
    - AlternativasAceitas: igual a qualquer uma das alternativas.
    """
    if isinstance(valor_esperado, AlternativasAceitas):
        return any(campo_correto(valor_extraido, alternativa) for alternativa in valor_esperado)
    if valor_extraido is None or valor_esperado is None:
        return valor_extraido is None and valor_esperado is None
    if isinstance(valor_esperado, str) and isinstance(valor_extraido, str):
        return normalizar_texto(valor_extraido) == normalizar_texto(valor_esperado)
    if isinstance(valor_esperado, list) and isinstance(valor_extraido, list):
        if any(isinstance(v, AlternativasAceitas) for v in valor_esperado):
            return _mesmos_itens_com_alternativas(valor_extraido, valor_esperado)
        return Counter(normalizar_texto(str(v)) for v in valor_extraido) == Counter(
            normalizar_texto(str(v)) for v in valor_esperado
        )
    if isinstance(valor_esperado, (int, float)) and isinstance(valor_extraido, (int, float)):
        return abs(float(valor_extraido) - float(valor_esperado)) < 0.005
    return valor_extraido == valor_esperado


def _mesmos_itens_com_alternativas(extraidos: list, esperados: list) -> bool:
    """
    Mesmos itens, em qualquer ordem, quando um item do gabarito aceita
    mais de uma forma (AlternativasAceitas). Cada item extraído precisa
    corresponder a exatamente um item do gabarito.
    """
    if len(extraidos) != len(esperados):
        return False
    normalizados = [normalizar_texto(str(v)) for v in extraidos]

    def aceitos(item) -> set[str]:
        opcoes = item if isinstance(item, AlternativasAceitas) else [item]
        return {normalizar_texto(str(o)) for o in opcoes}

    restantes = list(range(len(normalizados)))

    def casar(i: int) -> bool:
        if i == len(esperados):
            return True
        opcoes = aceitos(esperados[i])
        for j in list(restantes):
            if normalizados[j] in opcoes:
                restantes.remove(j)
                if casar(i + 1):
                    return True
                restantes.append(j)
        return False

    return casar(0)


def acuracia_por_campo(resultados: list[dict]) -> dict[str, float]:
    """
    Recebe uma lista de dicionários, um por caso, cada um com pares
    {nome_do_campo: (valor_extraido, valor_esperado)}, e devolve a
    proporção de acertos por campo.

    Exemplo de entrada, para dois casos avaliando dois campos:
        [
            {"cnpj": ("12.345.678/0001-99", "12.345.678/0001-99"),
             "valor_total": (249.80, 249.80)},
            {"cnpj": ("00.000.000/0000-00", "11.111.111/0001-11"),
             "valor_total": (None, 59.90)},
        ]
    """
    acertos: dict[str, int] = defaultdict(int)
    totais: dict[str, int] = defaultdict(int)

    for caso in resultados:
        for campo, (extraido, esperado) in caso.items():
            totais[campo] += 1
            if campo_correto(extraido, esperado):
                acertos[campo] += 1

    return {campo: acertos[campo] / totais[campo] for campo in totais}


# Resultado de cada campo de cada nota, para a matriz de resultados da
# extração (ver resultado_do_campo).
CORRETO = "correto"
INCORRETO = "incorreto"
NAO_EXTRAIDO = "nao_extraido"
FOTO_RECUSADA = "foto_recusada"
RESULTADOS_CAMPO = [CORRETO, INCORRETO, NAO_EXTRAIDO, FOTO_RECUSADA]


def _vazio(valor) -> bool:
    return valor is None or valor == [] or (isinstance(valor, str) and not valor.strip())


def resultado_do_campo(valor_extraido, valor_esperado) -> str:
    """
    Classifica a extração de um campo em uma de três situações:

    - "correto": igual ao gabarito (ver campo_correto);
    - "incorreto": a abordagem devolveu um valor, mas errado. É o erro
      mais grave, porque o valor errado segue para o diagnóstico e a
      carta como se fosse verdadeiro;
    - "nao_extraido": a abordagem não devolveu valor (ele vira um
      marcador [ ] na carta, para o usuário preencher).

    ("foto_recusada" é atribuído por quem chama, quando a abordagem
    pediu nova foto e, por isso, nenhum campo foi extraído.)
    """
    if campo_correto(valor_extraido, valor_esperado):
        return CORRETO
    if _vazio(valor_extraido):
        return NAO_EXTRAIDO
    return INCORRETO


@dataclass
class MetricasExtracaoCampo:
    contagens: dict[str, int]   # resultado -> quantidade

    @property
    def total(self) -> int:
        return sum(self.contagens.values())

    @property
    def precisao(self) -> float:
        """Dos valores que a abordagem devolveu, quantos estavam certos."""
        devolvidos = self.contagens.get(CORRETO, 0) + self.contagens.get(INCORRETO, 0)
        return self.contagens.get(CORRETO, 0) / devolvidos if devolvidos else 0.0

    @property
    def revocacao(self) -> float:
        """Dos valores que existiam na nota, quantos foram extraídos corretamente (= acurácia)."""
        return self.contagens.get(CORRETO, 0) / self.total if self.total else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precisao, self.revocacao
        return 2 * p * r / (p + r) if (p + r) else 0.0


# ---------------------------------------------------------------------------
# Classificação: acurácia, precisão, revocação e F1 por categoria
# ---------------------------------------------------------------------------

@dataclass
class MetricasClasse:
    precisao: float
    revocacao: float
    f1: float
    suporte: int  # número de casos verdadeiros dessa classe no gabarito


def precisao_revocacao_f1(
    previstos: list[str], esperados: list[str]
) -> dict[str, MetricasClasse]:
    """
    Calcula precisão, revocação e F1 para cada classe presente nos
    dados, no estilo "um contra todos" (Manning; Raghavan; Schütze,
    2008): para a classe X, um verdadeiro positivo é um caso em que
    tanto o valor previsto quanto o esperado são X.

    `previstos` e `esperados` devem ter o mesmo tamanho, com os rótulos
    de cada caso na mesma ordem.
    """
    if len(previstos) != len(esperados):
        raise ValueError("previstos e esperados devem ter o mesmo tamanho.")

    classes = sorted(set(esperados) | set(previstos))
    resultado = {}

    for classe in classes:
        verdadeiros_positivos = sum(
            1 for p, e in zip(previstos, esperados) if p == classe and e == classe
        )
        falsos_positivos = sum(
            1 for p, e in zip(previstos, esperados) if p == classe and e != classe
        )
        falsos_negativos = sum(
            1 for p, e in zip(previstos, esperados) if p != classe and e == classe
        )
        suporte = sum(1 for e in esperados if e == classe)

        precisao = (
            verdadeiros_positivos / (verdadeiros_positivos + falsos_positivos)
            if (verdadeiros_positivos + falsos_positivos) > 0
            else 0.0
        )
        revocacao = (
            verdadeiros_positivos / (verdadeiros_positivos + falsos_negativos)
            if (verdadeiros_positivos + falsos_negativos) > 0
            else 0.0
        )
        f1 = (
            2 * precisao * revocacao / (precisao + revocacao)
            if (precisao + revocacao) > 0
            else 0.0
        )

        resultado[classe] = MetricasClasse(
            precisao=precisao, revocacao=revocacao, f1=f1, suporte=suporte
        )

    return resultado


@dataclass
class MatrizConfusao:
    """
    Matriz de confusão: linhas = classe esperada (gabarito), colunas =
    classe prevista pelo sistema. A diagonal são os acertos; cada célula
    fora dela mostra QUAL confusão aconteceu (ex.: vício oculto
    classificado como aparente), o que a acurácia sozinha esconde.
    """
    classes: list[str]
    contagens: dict[str, dict[str, int]]  # esperado -> previsto -> quantidade

    def valor(self, esperado: str, previsto: str) -> int:
        return self.contagens.get(esperado, {}).get(previsto, 0)

    @property
    def total(self) -> int:
        return sum(sum(linha.values()) for linha in self.contagens.values())

    @property
    def acertos(self) -> int:
        return sum(self.valor(c, c) for c in self.classes)

    def confusoes(self) -> list[tuple[str, str, int]]:
        """Células fora da diagonal com pelo menos um caso, da mais frequente à menos."""
        fora_da_diagonal = [
            (esperado, previsto, self.valor(esperado, previsto))
            for esperado in self.classes
            for previsto in self.classes
            if esperado != previsto and self.valor(esperado, previsto)
        ]
        return sorted(fora_da_diagonal, key=lambda item: -item[2])

    def formatar_texto(self, rotulo_linhas: str = "esperado", rotulo_colunas: str = "previsto") -> str:
        largura_linha = max(len(rotulo_linhas) + len(rotulo_colunas) + 4, *(len(c) + 2 for c in self.classes))
        largura_coluna = max(8, *(len(c) + 2 for c in self.classes))
        linhas = [
            f"{rotulo_linhas + ' \\ ' + rotulo_colunas:<{largura_linha}}"
            + "".join(f"{c:>{largura_coluna}}" for c in self.classes)
            + f"{'total':>{largura_coluna}}"
        ]
        for esperado in self.classes:
            celulas = [self.valor(esperado, previsto) for previsto in self.classes]
            linhas.append(
                f"{esperado:<{largura_linha}}"
                + "".join(f"{v:>{largura_coluna}}" for v in celulas)
                + f"{sum(celulas):>{largura_coluna}}"
            )
        return "\n".join(linhas)

    def para_csv(self) -> str:
        """Mesma tabela em CSV (separador ';'), para abrir em planilha e montar a tabela do TCC."""
        linhas = ["esperado \\ previsto;" + ";".join(self.classes)]
        for esperado in self.classes:
            linhas.append(esperado + ";" + ";".join(str(self.valor(esperado, p)) for p in self.classes))
        return "\n".join(linhas) + "\n"


def matriz_confusao(
    previstos: list[str], esperados: list[str], classes: list[str] | None = None
) -> MatrizConfusao:
    """
    Monta a matriz de confusão. `classes` fixa a ordem das linhas e
    colunas (e garante que uma classe sem nenhum caso apareça zerada);
    classes que surgirem nos dados e não estiverem na lista (ex.:
    "resposta_invalida") são acrescentadas ao final.
    """
    if len(previstos) != len(esperados):
        raise ValueError("previstos e esperados devem ter o mesmo tamanho.")

    ordem = list(classes or [])
    for rotulo in sorted(set(esperados) | set(previstos)):
        if rotulo not in ordem:
            ordem.append(rotulo)

    contagens: dict[str, dict[str, int]] = {c: {p: 0 for p in ordem} for c in ordem}
    for previsto, esperado in zip(previstos, esperados):
        contagens[esperado][previsto] += 1

    return MatrizConfusao(classes=ordem, contagens=contagens)


def acuracia(previstos: list[str], esperados: list[str]) -> float:
    if len(previstos) != len(esperados):
        raise ValueError("previstos e esperados devem ter o mesmo tamanho.")
    if not previstos:
        return 0.0
    acertos = sum(1 for p, e in zip(previstos, esperados) if p == e)
    return acertos / len(previstos)


def consistencia(rotulos_por_caso: list[list[str]]) -> float:
    """
    Proporção de casos em que todas as execuções repetidas do mesmo
    relato (três, na Metodologia) devolveram o mesmo rótulo. 1.0 quer
    dizer que o modelo respondeu sempre igual em todos os casos.
    """
    if not rotulos_por_caso:
        return 0.0
    consistentes = sum(1 for rotulos in rotulos_por_caso if len(set(rotulos)) == 1)
    return consistentes / len(rotulos_por_caso)


# ---------------------------------------------------------------------------
# Diagnóstico completo
# ---------------------------------------------------------------------------

def proporcao_diagnostico_correto(resultados: list[bool]) -> float:
    """
    Proporção de casos em que o fluxo completo chegou ao diagnóstico
    correto (classificação e prazo iguais aos do gabarito). `resultados`
    é uma lista de booleanos, um por caso, já calculada pelo chamador.
    """
    if not resultados:
        return 0.0
    return sum(resultados) / len(resultados)
