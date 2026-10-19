"""
Testes da entrada em PDF: texto embutido lido sem OCR, PDF escaneado
passando pelo Tesseract, PDF enviado ao modelo como documento e sem a
checagem de qualidade de foto. Os PDFs são gerados na hora, numa pasta
temporária do pytest.
"""
import json
import shutil
from datetime import date

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pytest  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from app.config import DocumentoPDF, ModeloClaude  # noqa: E402
from app.extracao.detector import extrair_dados_nota_fiscal  # noqa: E402
from app.extracao.entrada_pdf import tem_texto_embutido, texto_do_pdf  # noqa: E402
from app.extracao.ocr_multimodal import extrair_via_modelo_multimodal  # noqa: E402
from app.extracao.ocr_tesseract import extrair_via_tesseract  # noqa: E402
from app.models import FonteExtracao  # noqa: E402

LINHAS_DANFE = [
    "FARMACIA BEM ESTAR LTDA",
    "CNPJ: 12.345.678/0001-99",
    "DOCUMENTO AUXILIAR DA NOTA FISCAL DE CONSUMIDOR ELETRONICA",
    "001 DIPIRONA 500MG 1 UN 12,90",
    "002 PROTETOR SOLAR FPS50 1 UN 33,00",
    "VALOR A PAGAR R$ 45,90",
    "EMISSAO: 20/01/2026 14:32:10",
]


@pytest.fixture
def pdf_digital(tmp_path):
    """PDF com texto embutido, como o baixado no portal da Fazenda."""
    caminho = tmp_path / "nota_digital.pdf"
    with matplotlib.rc_context({"pdf.fonttype": 42}):
        fig = plt.figure(figsize=(8.27, 11.69))
        for i, linha in enumerate(LINHAS_DANFE):
            fig.text(0.08, 0.92 - i * 0.04, linha, fontsize=11, family="monospace")
        fig.savefig(caminho)
        plt.close(fig)
    return caminho


@pytest.fixture
def pdf_escaneado(tmp_path):
    """PDF só com a imagem da página (sem texto embutido)."""
    imagem = Image.new("RGB", (1240, 1754), "white")
    desenho = ImageDraw.Draw(imagem)
    try:
        fonte = ImageFont.truetype("DejaVuSansMono.ttf", 34)
    except OSError:
        fonte = ImageFont.load_default(size=34)
    for i, linha in enumerate(LINHAS_DANFE):
        desenho.text((70, 90 + i * 70), linha, fill="black", font=fonte)
    caminho = tmp_path / "nota_escaneada.pdf"
    imagem.save(caminho, "PDF", resolution=150)
    return caminho


class ModeloFalso:
    def __init__(self, resposta):
        self.resposta = resposta
        self.chamadas = []

    def gerar(self, conteudo, esquema=None):
        self.chamadas.append(conteudo)
        return json.dumps(self.resposta)


RESPOSTA_MODELO = {
    "legivel": True, "problema_imagem": None, "estabelecimento": "FARMACIA BEM ESTAR LTDA",
    "data_emissao": "2026-01-20", "produtos": ["DIPIRONA 500MG", "PROTETOR SOLAR FPS50"], "valor_total": 45.9,
}


def test_texto_embutido_e_lido_sem_ocr(pdf_digital):
    texto = texto_do_pdf(pdf_digital)
    assert tem_texto_embutido(texto)
    assert "FARMACIA BEM ESTAR LTDA" in texto


def test_tradicional_usa_texto_do_pdf_e_as_mesmas_regex(pdf_digital):
    nota = extrair_via_tesseract(pdf_digital)
    assert nota.fonte == FonteExtracao.TEXTO_PDF
    assert nota.estabelecimento == "FARMACIA BEM ESTAR LTDA"
    assert nota.data_emissao == date(2026, 1, 20)
    assert nota.valor_total == 45.90
    assert nota.produtos == ["DIPIRONA 500MG", "PROTETOR SOLAR FPS50"]


@pytest.mark.skipif(shutil.which("tesseract") is None, reason="Tesseract não instalado")
def test_pdf_escaneado_passa_pelo_tesseract(pdf_escaneado):
    assert not tem_texto_embutido(texto_do_pdf(pdf_escaneado))
    nota = extrair_via_tesseract(pdf_escaneado)
    assert nota.fonte == FonteExtracao.OCR_TESSERACT
    assert nota.valor_total == 45.90


def test_multimodal_envia_o_pdf_como_documento(pdf_digital):
    modelo = ModeloFalso(RESPOSTA_MODELO)
    nota = extrair_via_modelo_multimodal(pdf_digital, modelo=modelo)

    instrucao, entrada = modelo.chamadas[0]
    assert isinstance(entrada, DocumentoPDF)
    assert bytes(entrada) == pdf_digital.read_bytes()
    assert "documento PDF" in instrucao
    # "imagem" só aparece no nome do campo JSON, que é o mesmo para foto e PDF.
    assert "imagem" not in instrucao.replace("problema_imagem", "")
    assert nota.valor_total == 45.9


def test_adaptador_monta_bloco_de_documento(pdf_digital):
    from types import SimpleNamespace

    chamadas = []
    resposta = SimpleNamespace(stop_reason="end_turn", stop_details=None,
                               content=[SimpleNamespace(type="text", text="{}")])
    cliente = SimpleNamespace(messages=SimpleNamespace(create=lambda **p: chamadas.append(p) or resposta))
    ModeloClaude(cliente, "claude-sonnet-5-5").gerar(["instrução", DocumentoPDF(pdf_digital.read_bytes())])

    blocos = chamadas[0]["messages"][0]["content"]
    assert [b["type"] for b in blocos] == ["document", "text"]
    assert blocos[0]["source"]["media_type"] == "application/pdf"


def test_pdf_nao_passa_pela_checagem_de_qualidade_de_foto(pdf_digital, monkeypatch):
    import app.extracao.detector as detector

    def falhar(*_):
        raise AssertionError("a checagem de foto não deve rodar para PDF")

    monkeypatch.setattr(detector, "verificar_qualidade", falhar)
    nota = extrair_dados_nota_fiscal(pdf_digital, extrator="tesseract")
    assert nota.fonte == FonteExtracao.TEXTO_PDF


def test_caso_em_pdf_reaproveita_o_gabarito_da_foto(tmp_path):
    from avaliacao.casos import carregar_casos

    (tmp_path / "casos_foto.json").write_text(json.dumps([{
        "id": "real_01", "imagem": "f.jpg",
        "nota": {"estabelecimento": "LOJA X", "data_emissao": "2026-01-20", "produtos": ["A"], "valor_total": 10.0},
    }]), encoding="utf-8")
    (tmp_path / "casos_pdf.json").write_text(json.dumps([
        {"id": "pdf_01", "arquivo": "n.pdf", "mesma_nota_que": "real_01"},
    ]), encoding="utf-8")
    (tmp_path / "f.jpg").write_bytes(b"")
    (tmp_path / "n.pdf").write_bytes(b"")

    caso = carregar_casos(tmp_path / "casos_pdf.json")[0]
    assert caso.tipo_entrada == "pdf"
    assert caso.mesma_nota_que == "real_01"
    assert caso.gabarito["valor_total"] == 10.0
    assert caso.gabarito["data_emissao"] == date(2026, 1, 20)
