"""
Primeira das duas abordagens de extração comparadas na Metodologia:
OCR tradicional com o motor Tesseract (Smith, 2007), via a biblioteca
pytesseract, com pré-processamento básico da imagem (conversão para
tons de cinza e binarização) e expressões regulares para localizar os
campos no texto reconhecido (ver regex_campos.py).

A outra abordagem é o modelo de linguagem multimodal (ocr_multimodal.py);
as duas são comparadas sobre as mesmas imagens em
avaliacao/comparar_extracao.py.

Requer o binário `tesseract` instalado no sistema operacional, com o
pacote de idioma português (no macOS: `brew install tesseract
tesseract-lang`; no Ubuntu/Debian: `apt-get install tesseract-ocr
tesseract-ocr-por`).
"""
from __future__ import annotations

from pathlib import Path

import pytesseract
from PIL import Image, ImageOps

from app.extracao.entrada_pdf import eh_pdf, paginas_como_imagem, tem_texto_embutido, texto_do_pdf
from app.extracao.qualidade_imagem import ImagemIlegivelError, MotivoImagemRuim
from app.extracao.regex_campos import (
    extrair_data_emissao,
    extrair_estabelecimento,
    extrair_produtos,
    extrair_valor_total,
)
from app.models import FonteExtracao, NotaFiscalExtraida


def _pre_processar(imagem: Image.Image) -> Image.Image:
    """
    Pré-processamento básico para melhorar a taxa de acerto do OCR em
    fotos tiradas por celular: converte para tons de cinza e aumenta o
    contraste antes de binarizar.

    Um limiar de binarização FIXO (ex.: "tudo acima de 150 vira
    branco") funciona mal em papel térmico com sombra ou iluminação
    irregular, porque o mesmo valor de cinza pode ser "papel" numa
    região da foto e "tinta" em outra. Por isso o limiar aqui é
    calculado a partir do histograma da própria imagem (o ponto médio
    entre os tons mais escuros e mais claros), o que se ajusta melhor a
    cada foto do que um número fixo escolhido a priori.
    """
    cinza = ImageOps.grayscale(imagem)
    cinza = ImageOps.autocontrast(cinza, cutoff=1)

    histograma = cinza.histogram()
    tons_presentes = [i for i, contagem in enumerate(histograma) if contagem > 0]
    limiar = (min(tons_presentes) + max(tons_presentes)) // 2 if tons_presentes else 128

    return cinza.point(lambda pixel: 255 if pixel > limiar else 0)


def _ocr(imagem: Image.Image) -> str:
    return pytesseract.image_to_string(_pre_processar(imagem), lang="por")


def extrair_via_tesseract(caminho_imagem: str | Path) -> NotaFiscalExtraida:
    """
    Obtém o texto da nota fiscal e localiza os quatro campos
    (estabelecimento, data de emissão, produtos e valor total) por
    expressões regulares.

    - Foto: o texto vem do OCR com Tesseract.
    - PDF: usa o texto embutido no arquivo, sem OCR; se o PDF for
      escaneado (sem texto embutido), as páginas passam pelo Tesseract.

    Levanta ImagemIlegivelError quando não consegue achar nenhum dos
    campos: nesse caso, os dados não servem para o diagnóstico e o
    usuário deve enviar outro arquivo.
    """
    fonte = FonteExtracao.OCR_TESSERACT
    if eh_pdf(caminho_imagem):
        texto = texto_do_pdf(caminho_imagem)
        if tem_texto_embutido(texto):
            fonte = FonteExtracao.TEXTO_PDF
        else:
            texto = "\n".join(_ocr(pagina) for pagina in paginas_como_imagem(caminho_imagem))
    else:
        with Image.open(caminho_imagem) as original:
            # respeita a rotação da foto do celular
            texto = _ocr(ImageOps.exif_transpose(original))

    nota = NotaFiscalExtraida(
        estabelecimento=extrair_estabelecimento(texto),
        data_emissao=extrair_data_emissao(texto),
        produtos=extrair_produtos(texto),
        valor_total=extrair_valor_total(texto),
        fonte=fonte,
        texto_reconhecido=texto,
    )

    # Estabelecimento sozinho não conta: qualquer ruído com letras pode
    # ser tomado como "nome". Data, valor ou produtos indicam que o OCR
    # de fato leu a nota.
    campos_confiaveis = [nota.data_emissao, nota.valor_total, nota.produtos or None]
    if all(campo is None for campo in campos_confiaveis):
        raise ImagemIlegivelError(
            MotivoImagemRuim.ILEGIVEL,
            detalhe=(
                "o OCR não reconheceu nenhum texto"
                if not texto.strip()
                else "o OCR não encontrou data, valor total nem produtos no texto"
            ),
        )

    campos_encontrados = sum(
        campo not in (None, []) for campo in
        (nota.estabelecimento, nota.data_emissao, nota.produtos, nota.valor_total)
    )
    nota.confianca = campos_encontrados / 4
    if campos_encontrados < 4:
        nota.observacoes.append(f"O OCR encontrou só {campos_encontrados} de 4 campos.")

    return nota
