"""
Checagem da qualidade da foto da nota fiscal ANTES de tentar extrair
os dados dela, para avisar o usuário que a foto precisa ser tirada de
novo em vez de devolver um diagnóstico baseado em dados errados.

Por que isso importa: se a foto está borrada, o OCR (e até o modelo
multimodal) pode "ler" um CNPJ, uma data ou um valor errado, e a data
da compra alimenta diretamente o cálculo do prazo. É mais seguro pedir
uma nova foto do que seguir com um dado duvidoso.

Os critérios são simples e explicáveis (sem modelo de aprendizado):

1. Resolução: uma foto muito pequena não tem pixels suficientes para
   os caracteres de um cupom fiscal.
2. Iluminação: foto escura demais, ou "lavada" (sem contraste entre a
   tinta e o papel).
3. Nitidez: variância do Laplaciano (Pech-Pacheco et al., 2000), uma
   medida clássica de foco — bordas nítidas (como as letras impressas)
   geram valores altos; uma foto tremida ou fora de foco, valores
   baixos. Antes do Laplaciano a imagem passa por um filtro gaussiano
   leve (o "Laplaciano do Gaussiano"), para que o ruído granulado de
   foto de celular em pouca luz não seja confundido com nitidez. Como a maior parte de um cupom é papel em branco (que
   também tem variância baixa, mesmo numa foto nítida), a nitidez é
   medida só nas regiões da imagem que têm conteúdo (os "blocos" com
   mais bordas), e não na média da imagem inteira.

Os limites (LIMIAR_*) foram calibrados com as imagens de
tests/casos/imagens e podem ser ajustados por variável de ambiente
depois de testar com fotos reais tiradas por celular.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

# Lado maior para o qual toda imagem é redimensionada antes de medir a
# nitidez, para que fotos de resoluções diferentes sejam comparáveis.
_LADO_PADRAO = 1200
_TAMANHO_BLOCO = 48
# Fração dos blocos com mais bordas usada na medida de nitidez.
_FRACAO_BLOCOS_CONTEUDO = 0.10

LIMIAR_LADO_MINIMO_PX = int(os.getenv("QUALIDADE_LADO_MINIMO_PX", "300"))
# Referência (imagens sintéticas de tests/casos/imagens): fotos boas
# ~190-240; desfoque gaussiano de raio 1 ~45, raio 1,5 ~16; borrada ~1.
LIMIAR_NITIDEZ = float(os.getenv("QUALIDADE_LIMIAR_NITIDEZ", "25"))
LIMIAR_BRILHO_MINIMO = float(os.getenv("QUALIDADE_BRILHO_MINIMO", "50"))
# Diferença entre os tons mais escuros (tinta) e mais claros (papel).
LIMIAR_CONTRASTE_MINIMO = float(os.getenv("QUALIDADE_CONTRASTE_MINIMO", "60"))


class MotivoImagemRuim(str, Enum):
    RESOLUCAO_BAIXA = "resolucao_baixa"
    ESCURA = "escura"
    SEM_CONTRASTE = "sem_contraste"
    BORRADA = "borrada"
    ILEGIVEL = "ilegivel"  # passou nas checagens, mas a extração não leu nada


# Mensagens mostradas ao usuário final (o front-end pode exibir direto).
MENSAGENS_USUARIO = {
    MotivoImagemRuim.RESOLUCAO_BAIXA: (
        "A foto da nota fiscal está muito pequena para ser lida. "
        "Tire outra foto mais de perto, enquadrando só a nota."
    ),
    MotivoImagemRuim.ESCURA: (
        "A foto da nota fiscal ficou escura demais. Tire outra foto "
        "em um lugar mais iluminado."
    ),
    MotivoImagemRuim.SEM_CONTRASTE: (
        "Não dá para distinguir o texto da nota fiscal nessa foto "
        "(pode ser reflexo ou luz forte demais). Tire outra foto, "
        "evitando reflexos sobre o papel."
    ),
    MotivoImagemRuim.BORRADA: (
        "A foto da nota fiscal está borrada. Tire outra foto com o "
        "celular parado e a nota em foco."
    ),
    MotivoImagemRuim.ILEGIVEL: (
        "Não conseguimos ler os dados da nota fiscal nessa foto. Tire "
        "outra foto da nota inteira, bem iluminada, nítida e sem dobras."
    ),
}


class ImagemIlegivelError(Exception):
    """
    Levantado quando a foto da nota não tem qualidade suficiente para
    a extração. Carrega a mensagem já pronta para o usuário, pedindo
    que ele tire outra foto.
    """

    def __init__(self, motivo: MotivoImagemRuim, detalhe: str | None = None):
        self.motivo = motivo
        self.mensagem_usuario = MENSAGENS_USUARIO[motivo]
        self.detalhe = detalhe
        texto = self.mensagem_usuario + (f" ({detalhe})" if detalhe else "")
        super().__init__(texto)


@dataclass
class AvaliacaoQualidade:
    largura: int
    altura: int
    brilho_medio: float
    contraste: float
    nitidez: float
    problemas: list[MotivoImagemRuim] = field(default_factory=list)

    @property
    def aprovada(self) -> bool:
        return not self.problemas


def _medir_nitidez(cinza: Image.Image) -> float:
    """
    Variância do Laplaciano, medida bloco a bloco, considerando só a
    fração de blocos com mais bordas (as regiões com texto).
    """
    escala = _LADO_PADRAO / max(cinza.size)
    novo_tamanho = (max(1, round(cinza.width * escala)), max(1, round(cinza.height * escala)))
    cinza = cinza.resize(novo_tamanho, Image.Resampling.LANCZOS)
    cinza = cinza.filter(ImageFilter.GaussianBlur(1.5))

    g = np.asarray(cinza, dtype=np.float64)
    if g.shape[0] < 3 or g.shape[1] < 3:
        return 0.0
    laplaciano = (
        g[1:-1, :-2] + g[1:-1, 2:] + g[:-2, 1:-1] + g[2:, 1:-1] - 4 * g[1:-1, 1:-1]
    )

    variancias = []
    altura, largura = laplaciano.shape
    for y in range(0, altura - _TAMANHO_BLOCO + 1, _TAMANHO_BLOCO):
        for x in range(0, largura - _TAMANHO_BLOCO + 1, _TAMANHO_BLOCO):
            bloco = laplaciano[y : y + _TAMANHO_BLOCO, x : x + _TAMANHO_BLOCO]
            variancias.append(bloco.var())

    if not variancias:
        return float(laplaciano.var())

    variancias.sort(reverse=True)
    n = max(1, int(len(variancias) * _FRACAO_BLOCOS_CONTEUDO))
    return float(np.mean(variancias[:n]))


def avaliar_qualidade(imagem: Image.Image) -> AvaliacaoQualidade:
    """Mede resolução, iluminação e nitidez e lista os problemas encontrados."""
    imagem = ImageOps.exif_transpose(imagem)  # respeita a rotação da foto do celular
    cinza = ImageOps.grayscale(imagem)
    pixels = np.asarray(cinza, dtype=np.float64)

    avaliacao = AvaliacaoQualidade(
        largura=cinza.width,
        altura=cinza.height,
        brilho_medio=float(pixels.mean()),
        # percentis (e não mínimo/máximo) para ignorar pixels isolados
        contraste=float(np.percentile(pixels, 99.5) - np.percentile(pixels, 0.5)),
        nitidez=_medir_nitidez(cinza),
    )

    if min(cinza.size) < LIMIAR_LADO_MINIMO_PX:
        avaliacao.problemas.append(MotivoImagemRuim.RESOLUCAO_BAIXA)
    if avaliacao.brilho_medio < LIMIAR_BRILHO_MINIMO:
        avaliacao.problemas.append(MotivoImagemRuim.ESCURA)
    elif avaliacao.contraste < LIMIAR_CONTRASTE_MINIMO:
        avaliacao.problemas.append(MotivoImagemRuim.SEM_CONTRASTE)
    if avaliacao.nitidez < LIMIAR_NITIDEZ:
        avaliacao.problemas.append(MotivoImagemRuim.BORRADA)

    return avaliacao


def verificar_qualidade(caminho_imagem: str | Path) -> AvaliacaoQualidade:
    """
    Avalia a foto e levanta ImagemIlegivelError (com a mensagem pedindo
    uma nova foto) se ela não tiver qualidade para a extração.
    """
    with Image.open(caminho_imagem) as imagem:
        avaliacao = avaliar_qualidade(imagem)

    if not avaliacao.aprovada:
        raise ImagemIlegivelError(
            avaliacao.problemas[0],
            detalhe=(
                f"nitidez={avaliacao.nitidez:.0f}, brilho={avaliacao.brilho_medio:.0f}, "
                f"contraste={avaliacao.contraste:.0f}, "
                f"tamanho={avaliacao.largura}x{avaliacao.altura}"
            ),
        )
    return avaliacao
