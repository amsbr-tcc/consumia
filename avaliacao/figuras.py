"""
Geração das matrizes de confusão e tabelas da avaliação como IMAGENS
(PNG), prontas para inserir no texto do TCC.

- Matrizes de confusão: mapa de calor de um tom só (azul claro -> azul
  escuro conforme o número de casos), com o número escrito em cada
  célula, gabarito nas linhas e sistema nas colunas, e a diagonal (os
  acertos) contornada.
- Tabelas: padrão ABNT do modelo do TCC, só com linhas horizontais
  (acima e abaixo do cabeçalho e no fim da tabela).

Por padrão, as imagens não trazem título: no TCC, o título vai no
texto, acima da figura ou tabela, e a fonte abaixo. Use
`mostrar_titulo=True` para gerar a imagem com o título embutido.

Os nomes internos das classes (ex.: "nao_duravel") são trocados por
rótulos legíveis em português (ex.: "Não durável").
"""
from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # gera arquivos, sem abrir janela

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402

from avaliacao.metricas import MatrizConfusao  # noqa: E402

ROTULOS = {
    "aparente": "Vício aparente",
    "oculto": "Vício oculto",
    "fora_de_escopo": "Fora do escopo",
    "duravel": "Durável",
    "nao_duravel": "Não durável",
    "aparente/duravel": "Aparente /\ndurável",
    "aparente/nao_duravel": "Aparente /\nnão durável",
    "oculto/duravel": "Oculto /\ndurável",
    "oculto/nao_duravel": "Oculto /\nnão durável",
    "dentro_do_prazo": "Dentro do prazo",
    "fora_do_prazo": "Fora do prazo",
    "indeterminado": "Indeterminado",
    "resposta_invalida": "Resposta inválida",
    "sem_resposta": "Sem resposta",
    "sem_dados": "Sem dados",
    "legivel": "Legível",
    "ilegivel": "Ilegível",
    "aceitou": "Aceitou",
    "recusou": "Recusou (pediu nova foto)",
    "erro": "Erro",
    "acertou": "Acertou",
    "errou": "Errou",
}

# Escala sequencial de um tom (azul), do quase branco ao azul escuro.
_AZUL = LinearSegmentedColormap.from_list(
    "azul", ["#f4f8fd", "#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#104281"]
)
_TINTA = "#1f2328"
_TINTA_SECUNDARIA = "#57606a"
_LINHA = "#c6cbd1"

plt.rcParams.update({
    # Mesma fonte do texto do TCC (Times New Roman), quando disponível.
    "font.family": "serif",
    "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
    "font.size": 10,
    "axes.edgecolor": _LINHA,
    "text.color": _TINTA,
    "axes.labelcolor": _TINTA,
    "xtick.color": _TINTA,
    "ytick.color": _TINTA,
})


def rotulo(classe: str) -> str:
    return ROTULOS.get(classe, classe.replace("_", " ").capitalize())


def salvar_matriz_confusao(
    matriz: MatrizConfusao,
    caminho: Path,
    titulo: str,
    rotulo_linhas: str = "Gabarito",
    rotulo_colunas: str = "Sistema",
    linhas: list[str] | None = None,
    colunas: list[str] | None = None,
    rotulo_diagonal: str = "Acertos (diagonal)",
    mostrar_titulo: bool = False,
) -> Path:
    """
    Salva a matriz como PNG. `linhas` e `colunas` permitem mostrar só um
    recorte (ex.: gabarito legível/ilegível x sistema aceitou/recusou).
    """
    linhas = linhas or matriz.classes
    colunas = colunas or matriz.classes
    valores = [[matriz.valor(e, p) for p in colunas] for e in linhas]
    maximo = max((v for linha in valores for v in linha), default=0) or 1

    largura = 1.6 + 1.35 * len(colunas)
    altura = 1.5 + 0.75 * len(linhas)
    fig, ax = plt.subplots(figsize=(largura, altura), dpi=200)
    ax.imshow(valores, cmap=_AZUL, vmin=0, vmax=maximo, aspect="auto")

    for i, linha in enumerate(valores):
        for j, valor in enumerate(linha):
            escuro = valor / maximo > 0.55
            ax.text(j, i, str(valor), ha="center", va="center", fontsize=13,
                    fontweight="bold" if valor else "normal",
                    color="white" if escuro else (_TINTA if valor else _TINTA_SECUNDARIA))
            if linhas[i] == colunas[j]:
                ax.add_patch(Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, edgecolor=_TINTA, linewidth=1.6))

    ax.set_xticks(range(len(colunas)), [rotulo(c) for c in colunas])
    ax.set_yticks(range(len(linhas)), [rotulo(c) for c in linhas])
    ax.xaxis.tick_top()
    ax.xaxis.set_label_position("top")
    ax.set_xlabel(rotulo_colunas, fontweight="bold", labelpad=8)
    ax.set_ylabel(rotulo_linhas, fontweight="bold")
    ax.tick_params(length=0)
    ax.set_xticks([x - 0.5 for x in range(1, len(colunas))], minor=True)
    ax.set_yticks([y - 0.5 for y in range(1, len(linhas))], minor=True)
    ax.grid(which="minor", color="white", linewidth=2)
    ax.tick_params(which="minor", length=0)
    for lado in ax.spines.values():
        lado.set_visible(False)

    total = sum(sum(linha) for linha in valores)
    acertos = sum(valores[i][j] for i, e in enumerate(linhas) for j, p in enumerate(colunas) if e == p)
    rodape = f"{rotulo_diagonal}: {acertos} de {total}" + (f" ({acertos / total:.0%})" if total else "")
    if set(linhas) & set(colunas):
        fig.text(0.5, 0.01, rodape, ha="center", fontsize=9, color=_TINTA_SECUNDARIA)
    if mostrar_titulo:
        fig.suptitle(titulo, fontsize=11, fontweight="bold", y=0.995)
    fig.tight_layout(rect=(0, 0.04, 1, 0.97 if mostrar_titulo else 1))
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return caminho


def salvar_tabela(
    cabecalho: list[str],
    linhas: list[list[str]],
    caminho: Path,
    titulo: str,
    destacar_ultima_linha: bool = False,
    mostrar_titulo: bool = False,
    altura_linha: float = 0.36,
    folga: int = 3,
) -> Path:
    """
    Salva uma tabela como PNG, só com linhas horizontais (ABNT). A
    largura de cada coluna segue o texto mais longo (quebras de linha com
    "\n" estreitam a coluna) mais `folga` caracteres.
    """
    n_col = len(cabecalho)
    def comprimento(texto) -> int:
        return max(len(parte) for parte in str(texto).split("\n"))

    larguras = [max(comprimento(c) for c in [cabecalho[j], *[l[j] for l in linhas]]) + folga for j in range(n_col)]
    largura_fig = max(4.0, 0.105 * sum(larguras))
    altura_tabela = altura_linha * (len(linhas) + 1)
    margem_titulo = 0.55 if mostrar_titulo else 0.05
    fig = plt.figure(figsize=(largura_fig, altura_tabela + margem_titulo), dpi=200)
    ax = fig.add_axes((0.01, 0.01, 0.98, altura_tabela / (altura_tabela + margem_titulo)))
    ax.axis("off")

    tabela = ax.table(
        cellText=linhas, colLabels=cabecalho, cellLoc="center", bbox=(0, 0, 1, 1),
        colWidths=[w / sum(larguras) for w in larguras],
    )
    tabela.auto_set_font_size(False)
    tabela.set_fontsize(10)
    for (i, j), celula in tabela.get_celld().items():
        celula.set_edgecolor(_TINTA)
        celula.set_linewidth(0.8)
        # Só linhas horizontais: acima e abaixo do cabeçalho e no fim.
        if i == 0:
            celula.visible_edges = "TB"
            celula.set_text_props(fontweight="bold")
        elif i == len(linhas):
            celula.visible_edges = "B"
        else:
            celula.visible_edges = ""
        if destacar_ultima_linha and i == len(linhas):
            celula.set_text_props(fontweight="bold")

    if mostrar_titulo:
        fig.suptitle(titulo, fontsize=11, fontweight="bold", y=0.985)
    caminho.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(caminho, facecolor="white", bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)
    return caminho


def pct(valor: float | None) -> str:
    return "—" if valor is None else f"{valor:.0%}"
