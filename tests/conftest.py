"""
Fotos usadas pelos testes: só as fotos REAIS de tests/casos/reais/.

As versões ruins (borrada, escura) usadas para testar a checagem de
qualidade são geradas a partir de uma foto real, na hora, numa pasta
temporária do pytest, sem criar arquivo novo no projeto.
"""
import json
from pathlib import Path

import pytest
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

PASTA_CASOS = Path(__file__).parent / "casos"
ARQUIVO_CASOS = PASTA_CASOS / "casos.json"
FOTO_REAL = PASTA_CASOS / "reais" / "real_10.jpg"  # foto nítida, de frente


def ids_fotos_legiveis() -> list[str]:
    casos = json.loads(ARQUIVO_CASOS.read_text(encoding="utf-8"))
    return [c["id"] for c in casos if not c.get("foto_ilegivel")]


def foto_real(caso_id: str) -> Path:
    return PASTA_CASOS / "reais" / f"{caso_id}.jpg"


def _reduzida() -> Image.Image:
    # Reduz para agilizar os filtros (continua acima da resolução mínima).
    imagem = ImageOps.exif_transpose(Image.open(FOTO_REAL)).convert("RGB")
    imagem.thumbnail((1500, 1500))
    return imagem


@pytest.fixture
def foto_boa() -> Image.Image:
    return _reduzida()


@pytest.fixture
def foto_borrada(tmp_path) -> Path:
    caminho = tmp_path / "borrada.jpg"
    _reduzida().filter(ImageFilter.GaussianBlur(8)).save(caminho)
    return caminho


@pytest.fixture
def foto_escura(tmp_path) -> Path:
    caminho = tmp_path / "escura.jpg"
    ImageEnhance.Brightness(_reduzida()).enhance(0.2).save(caminho)
    return caminho
