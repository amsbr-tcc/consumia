"""
Testes da checagem de qualidade da foto (app.extraction.qualidade_imagem):
fotos borradas, escuras ou pequenas demais devem ser recusadas com uma
mensagem pedindo ao usuário que tire outra foto; as fotos reais
legíveis dos casos de teste, mesmo com ruído de câmera, sombra ou
inclinação, devem passar. As versões ruins são geradas a partir de uma
foto real (ver conftest.py).

Não exigem Tesseract nem chave de API.
"""
import numpy as np
import pytest
from PIL import Image, ImageFilter

from app.extraction.detector import FormatoNaoSuportadoError, extrair_dados_nota_fiscal
from app.extraction.qualidade_imagem import (
    ImagemIlegivelError,
    MotivoImagemRuim,
    avaliar_qualidade,
    verificar_qualidade,
)

from tests.conftest import foto_real, ids_fotos_legiveis


def _ruido(imagem: Image.Image, desvio: float) -> Image.Image:
    pixels = np.asarray(imagem.convert("L"), dtype=np.float64)
    pixels = pixels + np.random.default_rng(0).normal(0, desvio, pixels.shape)
    return Image.fromarray(np.clip(pixels, 0, 255).astype("uint8"))


@pytest.mark.parametrize("caso", ids_fotos_legiveis())
def test_fotos_reais_legiveis_passam(caso):
    avaliacao = verificar_qualidade(foto_real(caso))
    assert avaliacao.aprovada


def test_foto_borrada_e_recusada_pedindo_nova_foto(foto_borrada):
    with pytest.raises(ImagemIlegivelError) as erro:
        verificar_qualidade(foto_borrada)

    assert erro.value.motivo == MotivoImagemRuim.BORRADA
    assert "borrada" in erro.value.mensagem_usuario
    assert "Tire outra foto" in erro.value.mensagem_usuario


def test_foto_escura_e_recusada(foto_escura):
    with pytest.raises(ImagemIlegivelError) as erro:
        verificar_qualidade(foto_escura)

    assert erro.value.motivo == MotivoImagemRuim.ESCURA
    assert "Tire outra foto" in erro.value.mensagem_usuario


def test_foto_pequena_demais_e_recusada(foto_boa):
    pequena = foto_boa.resize((200, 120))
    assert MotivoImagemRuim.RESOLUCAO_BAIXA in avaliar_qualidade(pequena).problemas


@pytest.mark.parametrize("raio", [2, 3, 5])
def test_quanto_mais_borrada_menor_a_nitidez(foto_boa, raio):
    nitida = avaliar_qualidade(foto_boa).nitidez
    borrada = avaliar_qualidade(foto_boa.filter(ImageFilter.GaussianBlur(raio)))

    assert borrada.nitidez < nitida
    assert MotivoImagemRuim.BORRADA in borrada.problemas


def test_ruido_de_camera_nao_engana_a_medida_de_nitidez(foto_boa):
    # Foto borrada com muito ruído granulado (comum em pouca luz) não
    # pode ser tomada por nítida só porque o ruído cria "bordas".
    borrada_com_ruido = _ruido(foto_boa.filter(ImageFilter.GaussianBlur(3)), desvio=15)
    assert MotivoImagemRuim.BORRADA in avaliar_qualidade(borrada_com_ruido).problemas

    nitida_com_ruido = _ruido(foto_boa, desvio=15)
    assert avaliar_qualidade(nitida_com_ruido).aprovada


def test_foto_lavada_sem_contraste_e_recusada(foto_boa):
    lavada = foto_boa.convert("L").point(lambda p: 210 + p * 40 // 255)
    assert MotivoImagemRuim.SEM_CONTRASTE in avaliar_qualidade(lavada).problemas


def test_detector_recusa_foto_ruim_antes_de_chamar_qualquer_extrator(foto_borrada, monkeypatch):
    # Se a checagem não barrasse antes, o extrator multimodal tentaria
    # chamar a API (e falharia por falta de chave); o erro esperado é o
    # de foto ilegível.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ImagemIlegivelError):
        extrair_dados_nota_fiscal(foto_borrada, extrator="multimodal")


def test_detector_aceita_so_imagem(tmp_path):
    xml = tmp_path / "nota.xml"
    xml.write_text("<nfe/>")
    with pytest.raises(FormatoNaoSuportadoError):
        extrair_dados_nota_fiscal(xml)
