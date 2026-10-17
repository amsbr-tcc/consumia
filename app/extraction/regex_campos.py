"""
Expressões regulares que localizam, no texto reconhecido pelo Tesseract,
os quatro campos da nota fiscal previstos na Metodologia:
estabelecimento, data de emissão, descrição dos produtos e valor total.

As regras são pensadas para o leiaute do DANFE NFC-e (o cupom fiscal
de venda presencial), que é padronizado nacionalmente:

    NOME DO ESTABELECIMENTO LTDA        <- estabelecimento
    CNPJ: 12.345.678/0001-99            <- âncora (não é extraído)
    ...
    COD DESCRICAO  QTD UN  VL TOTAL
    001 DIPIRONA 500MG  1 UN  12,90     <- produtos
    ...
    VALOR A PAGAR R$  45,90             <- valor total (pago, após descontos)
    ...
    EMISSAO: 20/01/2026 14:32:10        <- data de emissão

Todas as funções aqui são puras (recebem texto, devolvem o campo), para
poderem ser testadas sem o Tesseract instalado (tests/test_regex_campos.py).
"""
from __future__ import annotations

import re
from datetime import date

# O CNPJ não é um campo avaliado, mas serve de âncora para achar o nome
# do estabelecimento (que vem logo acima dele no DANFE). É buscado sem
# exigir a pontuação exata, porque o OCR frequentemente lê mal esses
# símbolos em papel térmico (ex.: "12345678/0001:99").
PADRAO_CNPJ = re.compile(r"\d{2}[.\s]?\d{3}[.\s]?\d{3}[/\s]?\d{4}[-:\s]?\d{2}")

PADRAO_DATA = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
# Data precedida de "EMISSÃO" (com ou sem acento, como o OCR costuma ler).
PADRAO_DATA_EMISSAO = re.compile(
    r"EMISS[AÃ]O\D{0,20}?(\d{2})/(\d{2})/(\d{4})", re.IGNORECASE
)

# Valor em reais: "1.234,56" (padrão) ou "18.29" (algumas notas usam ponto).
_VALOR = r"(\d{1,3}(?:\.\d{3})*,\d{2}|\d+\.\d{2})(?![\d,])"

# O valor da nota é o que o consumidor pagou, depois de descontos: em
# muitos cupons "VALOR TOTAL" vem antes do desconto e "VALOR A PAGAR"
# depois. Por isso os rótulos são tentados nesta ordem de preferência.
PADROES_VALOR_TOTAL = [
    re.compile(rf"(?:VALOR\s+(?:TOTAL\s+)?A?\s*PAGAR|TOTAL\s+A\s+PAGAR)\D{{0,40}}?{_VALOR}", re.IGNORECASE),
    re.compile(rf"(?:VALOR\s+TOTAL|TOTAL\s+DA\s+NOTA)\D{{0,40}}?{_VALOR}", re.IGNORECASE),
    re.compile(rf"(?<![A-Z])TOTAL\s+R\$\D{{0,40}}?{_VALOR}", re.IGNORECASE),
]

# Linha de item do DANFE NFC-e: código, descrição, quantidade, unidade
# e valores. A descrição é tudo entre o código e a quantidade.
_UNIDADES = r"(?:UN|UND|UNID|KG|G|L|LT|ML|M|CX|PC|PCT|FD|DZ)"
PADRAO_ITEM = re.compile(
    rf"^\s*\d{{1,4}}\s+(?P<descricao>.+?)\s+\d+(?:[.,]\d+)?\s*{_UNIDADES}\b.*\d,\d{{2}}\s*$",
    re.IGNORECASE,
)

# Linhas do cabeçalho que nunca são o nome do estabelecimento.
_NAO_E_ESTABELECIMENTO = re.compile(
    r"CNPJ|CPF|DOCUMENTO\s+AUXILIAR|DANFE|NFC-?E|NOTA\s+FISCAL|CONSUMIDOR|"
    r"\bIE\b|INSCRI|FONE|TEL\b|TELEFONE|\bCEP\b",
    re.IGNORECASE,
)

# Linhas de endereço: logradouro, bairro, ou "cidade - UF" no fim da linha.
# Em muitos cupons o endereço fica entre o nome e o CNPJ, então "a linha
# logo acima do CNPJ" costuma ser o endereço (ex.: "CENTRO - SAO PAULO -").
_ENDERECO = re.compile(
    r"^\s*(?:RUA|R\.?|AV\.?|AVENIDA|ESTRADA|ROD\.?|RODOVIA|ALAMEDA|TRAVESSA|PRA[CÇ]A|"
    r"ENDERE[CÇ]O)\b|\b(?:CENTRO|JD\.?|JARDIM|VILA|PISO|LOJA\s+\w*\d)\b|"
    r"[-/,]\s*(?:SP|RJ|MG|PR|SC|RS|BA|GO|DF|ES|PE|CE)\s*-?\s*$|\d{5}-?\d{3}",
    re.IGNORECASE,
)

# Termos típicos de razão social, usados para preferir a linha certa
# quando o cabeçalho tem nome fantasia, razão social e endereço.
_RAZAO_SOCIAL = re.compile(
    r"\b(?:LTDA|S\.?\s?A\.?|EIRELI|ME|EPP|COM[EÉ]RCIO|COMERCIAL|LOJAS?|SUPERMERCADO|DROGARIA)\b\.?",
    re.IGNORECASE,
)

# Sufixo jurídico no fim da linha: indica que a razão social termina ali.
_SUFIXO_JURIDICO = re.compile(r"\b(?:LTDA|S\.?\s?A|EIRELI|ME|EPP)\.?\s*$", re.IGNORECASE)

_PREFIXO_RAZAO = re.compile(r"^\s*RAZ[AÃ]O\s+SOCIAL\s*:\s*", re.IGNORECASE)
# Rótulo do CNPJ como o OCR costuma ler ("CNPJ:", "CNPJ-", "CHRJ:").
_ROTULO_CNPJ = re.compile(r"\bC\w{2}J\b\s*[:\-]?\s*|\bIE\s*:?\s*\d+", re.IGNORECASE)


def _linhas(texto: str) -> list[str]:
    return [linha.strip() for linha in texto.splitlines() if linha.strip()]


def _tem_letras_suficientes(linha: str) -> bool:
    return sum(c.isalpha() for c in linha) >= 3


def _candidata_a_nome(linha: str) -> bool:
    return (
        _tem_letras_suficientes(linha)
        and not _NAO_E_ESTABELECIMENTO.search(linha)
        and not _ENDERECO.search(linha)
    )


def extrair_estabelecimento(texto: str) -> str | None:
    """
    O nome do estabelecimento fica no cabeçalho, antes do CNPJ do
    emitente (ou na mesma linha dele). Entre as linhas do cabeçalho que
    não são endereço nem título do documento, prefere a primeira que tem
    cara de razão social (LTDA, S.A., ME, COMERCIO...); senão, a primeira
    de cima para baixo. Sem CNPJ reconhecido, usa as primeiras linhas.
    """
    linhas = [_PREFIXO_RAZAO.sub("", linha) for linha in _linhas(texto)]

    indice_cnpj = next((i for i, linha in enumerate(linhas) if PADRAO_CNPJ.search(linha)), None)
    if indice_cnpj is None:
        cabecalho = linhas[:5]
    else:
        cabecalho = linhas[:indice_cnpj]
        # Nome na mesma linha do CNPJ ("CNPJ: 05.406.034/0025-71 PUMA SPORTS LTDA"),
        # às vezes continuando na linha de baixo.
        resto = _ROTULO_CNPJ.sub(" ", PADRAO_CNPJ.sub(" ", linhas[indice_cnpj]))
        resto = re.sub(r"\s+", " ", resto).strip(" -:")
        if _candidata_a_nome(resto):
            seguinte = linhas[indice_cnpj + 1] if indice_cnpj + 1 < len(linhas) else ""
            if not _SUFIXO_JURIDICO.search(resto) and _candidata_a_nome(seguinte) \
                    and _SUFIXO_JURIDICO.search(seguinte):
                resto = f"{resto} {seguinte}"
            cabecalho.append(resto)

    candidatas = [linha for linha in cabecalho if _candidata_a_nome(linha)]
    for linha in candidatas:
        if _RAZAO_SOCIAL.search(linha):
            return linha
    return candidatas[0] if candidatas else None


def extrair_produtos(texto: str) -> list[str]:
    """Descrição de cada item, a partir das linhas no formato de item do DANFE."""
    produtos = []
    for linha in _linhas(texto):
        achado = PADRAO_ITEM.match(linha)
        if achado:
            produtos.append(re.sub(r"\s+", " ", achado.group("descricao")).strip())
    return produtos


def extrair_data_emissao(texto: str) -> date | None:
    """Prefere a data marcada como "EMISSÃO"; senão, a primeira data do texto."""
    return parse_data(PADRAO_DATA_EMISSAO.search(texto) or PADRAO_DATA.search(texto))


def extrair_valor_total(texto: str) -> float | None:
    """Valor pago (depois de descontos), pelo primeiro rótulo encontrado em PADROES_VALOR_TOTAL."""
    for padrao in PADROES_VALOR_TOTAL:
        achado = padrao.search(texto)
        if achado:
            return parse_valor(achado.group(1))
    return None


def parse_valor(valor_texto: str | None) -> float | None:
    """Converte '1.234,56' (formato brasileiro) ou '18.29' para float."""
    if not valor_texto:
        return None
    if "," not in valor_texto and re.fullmatch(r"\d+\.\d{2}", valor_texto):
        normalizado = valor_texto  # ponto como separador decimal
    else:
        normalizado = valor_texto.replace(".", "").replace(",", ".")
    try:
        return float(normalizado)
    except ValueError:
        return None


def parse_data(match: re.Match | None) -> date | None:
    """Converte um match com grupos (DD, MM, AAAA) para date."""
    if not match:
        return None
    dia, mes, ano = match.groups()[-3:]
    try:
        return date(int(ano), int(mes), int(dia))
    except ValueError:
        return None
