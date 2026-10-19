"""
Extração de dados da nota fiscal usando um modelo de linguagem
multimodal, que recebe a imagem e uma instrução em texto e devolve
diretamente os campos estruturados, sem que seja necessário programar
onde cada campo costuma aparecer no layout do documento.

Este é o segundo dos dois caminhos usados quando a nota chega apenas
como imagem (o outro é ocr_tesseract.py). A Metodologia prevê comparar
o desempenho dos dois sobre o mesmo conjunto de imagens de teste (ver
avaliacao/comparar_extracao.py).

Usa o modelo de linguagem configurado em app/config.py (Claude Sonnet
5.5, pela API da Anthropic). Requer a chave de API no .env (ver
.env.example).

Como qualquer modelo de linguagem, esta etapa está sujeita a alucinação
(Ji et al., 2023), isto é, pode devolver um valor que não está de fato
na imagem. Por isso a instrução abaixo (a) pede explicitamente que
campos não identificados venham como null, em vez de inventados, e
(b) pede ao modelo que diga se a foto está legível: quando não está,
o usuário é avisado para tirar outra foto (ImagemIlegivelError), em vez
de o sistema seguir com dados possivelmente inventados.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageOps

from app.config import DocumentoPDF, obter_modelo
from app.extracao.entrada_pdf import eh_pdf
from app.extracao.qualidade_imagem import ImagemIlegivelError, MotivoImagemRuim
from app.models import FonteExtracao, NotaFiscalExtraida

_INSTRUCAO = """\
Você vai analisar a imagem de uma nota fiscal ou cupom fiscal brasileiro.

Primeiro, avalie se a imagem tem qualidade para ser lida: se estiver
borrada, tremida, escura, cortada a ponto de esconder os dados, ou se
não for uma nota/cupom fiscal, marque "legivel" como false e explique
o problema em "problema_imagem", em uma frase curta.

Depois, extraia os seguintes campos, preenchendo cada um apenas com o
que está de fato escrito e legível na imagem:

- estabelecimento: nome da loja/empresa emissora, como aparece no topo da nota (string ou null)
- data_emissao: data da compra, no formato AAAA-MM-DD (string ou null)
- produtos: lista com a descrição de cada produto/item comprado, exatamente como
  impressa, sem código, quantidade nem valor (lista de strings, pode ser vazia)
- valor_total: valor efetivamente pago pela compra (o "valor a pagar", já com
  descontos), como número, com ponto decimal (número ou null)

Se um campo não estiver legível ou não existir na imagem, retorne null
para ele. NUNCA invente, adivinhe ou complete um valor que não esteja
claramente visível na imagem — isso é mais importante do que preencher
todos os campos.
"""

_TEXTO_OU_NULO = {"anyOf": [{"type": "string"}, {"type": "null"}]}

# Mesma instrução para o PDF, trocando só a referência ao meio (imagem ->
# documento PDF), para a comparação foto x PDF medir o efeito da entrada.
_INSTRUCAO_PDF = (
    _INSTRUCAO
    .replace("a imagem de uma nota fiscal", "o documento PDF de uma nota fiscal")
    .replace("se a imagem tem qualidade para ser lida", "se o documento pode ser lido")
    .replace("legível na imagem", "legível no documento")
    .replace("não existir na imagem", "não existir no documento")
    .replace("claramente visível na imagem", "claramente visível no documento")
)

# JSON Schema da resposta (saída estruturada): força a resposta a vir
# sempre nesse formato, em vez de depender de o modelo "lembrar" de
# responder só em JSON. Campos que podem faltar na foto aceitam null.
_ESQUEMA_RESPOSTA = {
    "type": "object",
    "properties": {
        "legivel": {"type": "boolean"},
        "problema_imagem": _TEXTO_OU_NULO,
        "estabelecimento": _TEXTO_OU_NULO,
        "data_emissao": _TEXTO_OU_NULO,
        "produtos": {"type": "array", "items": {"type": "string"}},
        "valor_total": {"anyOf": [{"type": "number"}, {"type": "null"}]},
    },
    "required": ["legivel", "problema_imagem", "estabelecimento", "data_emissao", "produtos", "valor_total"],
    "additionalProperties": False,
}


def _parse_data_iso(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return datetime.strptime(valor, "%Y-%m-%d").date()
    except ValueError:
        return None


def extrair_via_modelo_multimodal(
    caminho_imagem: str | Path,
    modelo=None,
    nome_modelo: str | None = None,
) -> NotaFiscalExtraida:
    """
    Envia a imagem da nota fiscal a um modelo de linguagem multimodal e
    devolve os campos extraídos já estruturados.

    Levanta ImagemIlegivelError quando o próprio modelo julga a foto
    ilegível, ou quando não consegue ler data, valor total nem produtos.

    `nome_modelo` permite comparar mais de um modelo multimodal (ex.:
    dois modelos do mesmo provedor); sem ele, usa o modelo configurado
    (MODELO_LLM, ver app/config.py).
    O parâmetro `modelo` existe para permitir injetar um modelo mockado
    nos testes, sem precisar de uma chamada de API real.
    """
    modelo = modelo or obter_modelo(nome_modelo=nome_modelo)
    if eh_pdf(caminho_imagem):
        # O PDF vai inteiro ao modelo, que lê o texto e o leiaute da página.
        entrada = DocumentoPDF(Path(caminho_imagem).read_bytes())
    else:
        with Image.open(caminho_imagem) as original:
            entrada = ImageOps.exif_transpose(original).convert("RGB")

    instrucao = _INSTRUCAO_PDF if isinstance(entrada, DocumentoPDF) else _INSTRUCAO
    campos = json.loads(modelo.gerar([instrucao, entrada], esquema=_ESQUEMA_RESPOSTA))

    if campos.get("legivel") is False:
        raise ImagemIlegivelError(
            MotivoImagemRuim.ILEGIVEL,
            detalhe=campos.get("problema_imagem") or "o modelo julgou a imagem ilegível",
        )

    nota = NotaFiscalExtraida(
        estabelecimento=campos.get("estabelecimento"),
        data_emissao=_parse_data_iso(campos.get("data_emissao")),
        produtos=campos.get("produtos") or [],
        valor_total=campos.get("valor_total"),
        fonte=FonteExtracao.OCR_MULTIMODAL,
        confianca=None,  # o modelo não fornece uma estimativa de confiança
        observacoes=[],
    )

    # Mesmo critério do Tesseract (ver ocr_tesseract.py), para a
    # comparação entre as duas abordagens ser justa.
    if nota.data_emissao is None and nota.valor_total is None and not nota.produtos:
        raise ImagemIlegivelError(
            MotivoImagemRuim.ILEGIVEL,
            detalhe="o modelo não leu data, valor total nem produtos",
        )

    return nota
