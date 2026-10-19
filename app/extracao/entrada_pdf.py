"""
Leitura da nota fiscal enviada em PDF (DANFE NFC-e ou NF-e).

Um PDF gerado digitalmente (ex.: baixado no portal da Secretaria da
Fazenda, ou recebido por e-mail) já traz o texto embutido, que é lido
diretamente, sem OCR. Um PDF escaneado só tem a imagem da página: nesse
caso, a página é convertida em imagem para passar pelo Tesseract.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

# Abaixo disto, considera-se que o PDF não tem texto embutido (escaneado).
_MINIMO_CARACTERES_TEXTO = 40
# Resolução usada para converter a página em imagem (OCR do PDF escaneado).
_DPI_RENDERIZACAO = 300


def eh_pdf(caminho: str | Path) -> bool:
    return Path(caminho).suffix.lower() == ".pdf"


def texto_do_pdf(caminho: str | Path) -> str:
    """Texto embutido em todas as páginas do PDF ("" se não houver)."""
    import pdfplumber

    with pdfplumber.open(caminho) as pdf:
        return "\n".join(pagina.extract_text() or "" for pagina in pdf.pages)


def tem_texto_embutido(texto: str) -> bool:
    return len(texto.strip()) >= _MINIMO_CARACTERES_TEXTO


def paginas_como_imagem(caminho: str | Path, dpi: int = _DPI_RENDERIZACAO) -> list[Image.Image]:
    """Converte cada página do PDF em imagem (para o OCR do PDF escaneado)."""
    import pypdfium2

    documento = pypdfium2.PdfDocument(str(caminho))
    try:
        return [pagina.render(scale=dpi / 72).to_pil().convert("RGB") for pagina in documento]
    finally:
        documento.close()
