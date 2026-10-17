"""
Ponto de entrada da primeira etapa do pipeline: extração dos dados da
nota fiscal a partir da IMAGEM enviada pelo usuário (Metodologia).

Antes de extrair, a foto passa por uma checagem de qualidade (nitidez,
iluminação e resolução, ver qualidade_imagem.py). Se estiver borrada,
escura ou pequena demais, o usuário é avisado para tirar outra foto
(ImagemIlegivelError), em vez de o sistema seguir com dados errados.

Depois, os dados são extraídos por uma das duas abordagens comparadas
na Metodologia: OCR com Tesseract ("tesseract") ou modelo de linguagem
multimodal ("multimodal"). A abordagem com melhor desempenho na
comparação (app/evaluation/comparar_extracao.py) deve ser configurada
em EXTRATOR_DE_IMAGEM_PADRAO, ou pela variável de ambiente
EXTRATOR_IMAGEM, como a usada no fluxo final.
"""
from __future__ import annotations

import os
from pathlib import Path

from app.extraction.qualidade_imagem import ImagemIlegivelError, verificar_qualidade
from app.models import NotaFiscalExtraida

__all__ = [
    "EXTRATOR_DE_IMAGEM_PADRAO",
    "EXTRATORES",
    "FormatoNaoSuportadoError",
    "ImagemIlegivelError",
    "extrair_dados_nota_fiscal",
]

EXTENSOES_IMAGEM = {".jpg", ".jpeg", ".png", ".webp"}
EXTRATORES = ("tesseract", "multimodal")

EXTRATOR_DE_IMAGEM_PADRAO = os.getenv("EXTRATOR_IMAGEM", "multimodal")  # vencedor da comparação


class FormatoNaoSuportadoError(ValueError):
    """Levantado quando o arquivo enviado não é uma imagem suportada."""


def extrair_dados_nota_fiscal(
    caminho_imagem: str | Path,
    extrator: str = EXTRATOR_DE_IMAGEM_PADRAO,
    checar_qualidade: bool = True,
    nome_modelo: str | None = None,
) -> NotaFiscalExtraida:
    """
    Extrai estabelecimento, data de emissão, produtos e valor total da
    foto da nota fiscal, com a abordagem indicada em `extrator`.

    Com `checar_qualidade=True` (o padrão), a foto é avaliada antes, e
    ImagemIlegivelError é levantado se ela não tiver qualidade, com a
    mensagem pedindo que o usuário tire outra foto. Os próprios
    extratores também levantam ImagemIlegivelError se não conseguirem
    ler os campos.

    `nome_modelo` só vale para o extrator multimodal (ver
    ocr_multimodal.py).

    Usada tanto pelo fluxo normal quanto pela comparação de extratores,
    para que a comparação meça exatamente o que o usuário experimentaria.
    """
    caminho_imagem = Path(caminho_imagem)
    if caminho_imagem.suffix.lower() not in EXTENSOES_IMAGEM:
        raise FormatoNaoSuportadoError(
            f"Formato {caminho_imagem.suffix!r} não suportado. Envie uma foto "
            "da nota fiscal (.jpg, .jpeg, .png ou .webp)."
        )
    if extrator not in EXTRATORES:
        raise ValueError(f"Extrator desconhecido: {extrator!r} (use {' ou '.join(EXTRATORES)}).")

    if checar_qualidade:
        verificar_qualidade(caminho_imagem)

    if extrator == "multimodal":
        from app.extraction.ocr_multimodal import extrair_via_modelo_multimodal

        return extrair_via_modelo_multimodal(caminho_imagem, nome_modelo=nome_modelo)

    from app.extraction.ocr_tesseract import extrair_via_tesseract

    return extrair_via_tesseract(caminho_imagem)
