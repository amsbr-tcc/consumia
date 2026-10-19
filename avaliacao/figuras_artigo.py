"""
Figuras e tabelas escolhidas para o artigo do TCC, geradas a partir das
execuções mais recentes em resultados/ e salvas em resultados/artigo/.

    figura_1_fluxo_do_prototipo.png
    tabela_1_extracao_foto_pdf.png
    tabela_2_precisao_revocacao_f1.png
    tabela_3_casos_com_prazo_alterado.png
    figura_2_matriz_tipo_vicio.png

(As Figuras 3 e 4, telas inicial e do formulário do site, são capturas
da interface web e não são geradas aqui; por isso só os arquivos acima
são sobrescritos.)

Uso:

    python3 -m avaliacao.figuras_artigo
"""
from __future__ import annotations

import csv
from pathlib import Path

from avaliacao.figuras import plt, salvar_matriz_confusao, salvar_tabela
from avaliacao.metricas import matriz_confusao

RAIZ = Path(__file__).resolve().parent.parent
RESULTADOS = RAIZ / "resultados"
SAIDA = RESULTADOS / "artigo"
CAMPOS = [("estabelecimento", "Estabelecimento"), ("data_emissao", "Data de emissão"),
          ("produtos", "Produtos"), ("valor_total", "Valor total")]
CLAUDE = "multimodal_claude-sonnet-5-5"


def ultima_execucao(tipo: str) -> Path:
    execucoes = sorted(p for p in (RESULTADOS / tipo).iterdir() if p.is_dir())
    if not execucoes:
        raise SystemExit(f"Nenhuma execução em resultados/{tipo}/.")
    return execucoes[-1]


def _ler(caminho: Path) -> list[dict]:
    return list(csv.DictReader(caminho.open(encoding="utf-8"), delimiter=";"))


def _pct(valor: float) -> str:
    return f"{valor:.0%}"


def _segundos(valor: float) -> str:
    return f"{valor:.1f} s".replace(".", ",")


# ---------------------------------------------------------------------------
# Figura 1 — fluxo do protótipo
# ---------------------------------------------------------------------------

def figura_fluxo(caminho: Path) -> Path:
    fig, ax = plt.subplots(figsize=(7.6, 8.0), dpi=200)
    ax.set_xlim(0.9, 9.9)
    ax.set_ylim(1.65, 11.9)
    ax.axis("off")
    tinta, azul, cinza = "#1f2328", "#1c5cab", "#57606a"

    def caixa(x, y, w, h, titulo, texto, cor=tinta, preenchimento="white"):
        ax.add_patch(plt.Rectangle((x, y), w, h, facecolor=preenchimento, edgecolor=cor, linewidth=1.2))
        ax.text(x + w / 2, y + h - 0.28, titulo, ha="center", va="top", fontsize=10.5, fontweight="bold", color=cor)
        ax.text(x + w / 2, y + h - 0.68, texto, ha="center", va="top", fontsize=9, color=tinta, linespacing=1.3)

    def seta(x1, y1, x2, y2, rotulo=None, lado="right"):
        ax.annotate("", xy=(x2, y2), xytext=(x1, y1),
                    arrowprops=dict(arrowstyle="-|>", color=tinta, linewidth=1.0, shrinkA=0, shrinkB=0))
        if rotulo:
            dx = 0.12 if lado == "right" else -0.12
            ax.text((x1 + x2) / 2 + dx, (y1 + y2) / 2, rotulo, fontsize=8.5, color=cinza,
                    ha="left" if lado == "right" else "right", va="center", style="italic")

    x, w = 1.0, 5.2
    caixa(x, 10.6, w, 1.2, "Entrada do usuário", "foto ou PDF da nota fiscal, relato do problema\ne datas (entrega, defeito, reclamação, garantia)")
    caixa(x, 8.85, w, 1.25, "Etapa 1 — Extração dos dados da nota",
          "checagem da foto (só para foto) e leitura de\nestabelecimento, data, produtos e valor (Claude)", cor=azul)
    caixa(x, 7.05, w, 1.3, "Etapa 2 — Classificação do relato",
          "vício aparente ou oculto, produto durável ou\nnão durável, ou fora do escopo (Claude)", cor=azul)
    caixa(x, 5.25, w, 1.3, "Etapa 3 — Cálculo do prazo",
          "regra do art. 26 do CDC, sem modelo de linguagem,\ncom garantia contratual e reclamação anterior", cor=azul)
    caixa(x, 3.45, w, 1.3, "Etapa 4 — Carta de reclamação",
          "redigida pelo Claude com os dados do caso;\nartigos e pedido definidos pelo sistema", cor=azul)
    caixa(x, 1.75, w, 1.2, "Resultado", "situação do prazo, dias restantes,\norientação, carta e aviso legal")

    meio = x + w / 2
    for topo, base in ((10.6, 10.1), (8.85, 8.35), (7.05, 6.55), (5.25, 4.75), (3.45, 2.95)):
        seta(meio, topo, meio, base)

    lado_x, lado_w = 7.0, 2.8
    laterais = (
        (9.47, 1.0, "Pedido de nova foto", "foto ilegível"),
        (7.70, 1.0, "Orientação, sem carta", "caso fora do escopo"),
        (5.90, 1.3, "Orientação, sem carta", "fora do prazo ou\nindeterminado"),
    )
    for y_seta, h, titulo, texto in laterais:
        caixa(lado_x, y_seta - h / 2, lado_w, h, titulo, texto, cor=cinza, preenchimento="#f6f8fa")
        seta(x + w, y_seta, lado_x, y_seta)

    fig.savefig(caminho, facecolor="white", bbox_inches="tight", pad_inches=0.05)
    plt.close(fig)
    return caminho


# ---------------------------------------------------------------------------
# Tabela 1 — extração: foto e PDF x Tesseract e Claude
# ---------------------------------------------------------------------------

def _resumo_extracao(pasta: Path) -> dict:
    import json

    tes = {l["campo"]: float(l["revocacao"]) for l in _ler(pasta / "tabelas_csv" / "resultados_tesseract.csv")}
    cla = {l["campo"]: float(l["revocacao"]) for l in _ler(pasta / "tabelas_csv" / f"resultados_{CLAUDE}.csv")}
    dados = json.loads((pasta / "dados.json").read_text(encoding="utf-8"))["extratores"]
    claude = dados[CLAUDE.replace("multimodal_", "multimodal:")]
    n_notas = sum(1 for r in claude["resultados_por_caso"] if not r["foto_ilegivel_esperado"])
    return {
        "tes": tes, "cla": cla, "n": n_notas,
        "tempo_tes": dados["tesseract"]["tempo_medio_segundos"],
        "tempo_cla": claude["tempo_medio_segundos"],
        "consistencia_cla": (claude["consistencia_por_campo"] or {}).get("TODOS"),
    }


def tabela_extracao(caminho: Path) -> Path:
    foto = _resumo_extracao(ultima_execucao("extracao_foto"))
    pdf = _resumo_extracao(ultima_execucao("extracao_pdf"))
    linhas = [[rotulo, _pct(foto["tes"][c]), _pct(pdf["tes"][c]), _pct(foto["cla"][c]), _pct(pdf["cla"][c])]
              for c, rotulo in CAMPOS]
    media = lambda d: sum(d[c] for c, _ in CAMPOS) / len(CAMPOS)  # noqa: E731
    linhas.append(["Média", _pct(media(foto["tes"])), _pct(media(pdf["tes"])),
                   _pct(media(foto["cla"])), _pct(media(pdf["cla"]))])
    linhas.append(["Mesma leitura\nnas 3 execuções", "100%*", "100%*",
                   _pct(foto["consistencia_cla"]), _pct(pdf["consistencia_cla"])])
    linhas.append(["Tempo médio\npor arquivo", _segundos(foto["tempo_tes"]), _segundos(pdf["tempo_tes"]),
                   _segundos(foto["tempo_cla"]), _segundos(pdf["tempo_cla"])])
    cabecalho = ["Campo", f"Tesseract,\nfoto (n={foto['n']})", f"Tesseract,\nPDF (n={pdf['n']})",
                 f"Claude,\nfoto (n={foto['n']})", f"Claude,\nPDF (n={pdf['n']})"]
    return salvar_tabela(cabecalho, linhas, caminho, "", altura_linha=0.42, folga=2)


# ---------------------------------------------------------------------------
# Tabela 2 — precisão, revocação e F1 por campo
# ---------------------------------------------------------------------------

def _prf(pasta: Path, extrator: str) -> dict:
    linhas = {l["campo"]: l for l in _ler(pasta / "tabelas_csv" / f"resultados_{extrator}.csv")}
    return linhas


def _celula_prf(linha: dict) -> str:
    preenchidos = int(linha["correto"]) + int(linha["incorreto"])
    precisao = _pct(float(linha["precisao"])) if preenchidos else "–"
    f1 = f"{float(linha['f1']):.2f}".replace(".", ",")
    return f"{precisao} / {_pct(float(linha['revocacao']))} / {f1}"


def tabela_precisao_revocacao(caminho: Path) -> Path:
    foto, pdf = ultima_execucao("extracao_foto"), ultima_execucao("extracao_pdf")
    colunas = [_prf(foto, "tesseract"), _prf(pdf, "tesseract"), _prf(foto, CLAUDE), _prf(pdf, CLAUDE)]
    linhas = [[rotulo, *(_celula_prf(c[campo]) for c in colunas)]
              for campo, rotulo in [*CAMPOS, ("TOTAL", "Todos os campos")]]
    cabecalho = ["Campo", "Tesseract,\nfoto", "Tesseract,\nPDF", "Claude,\nfoto", "Claude,\nPDF"]
    return salvar_tabela(cabecalho, linhas, caminho, "", altura_linha=0.42, folga=2)


# ---------------------------------------------------------------------------
# Matriz de confusão do tipo de vício (opcional)
# ---------------------------------------------------------------------------

def figura_matriz_tipo_vicio(caminho: Path) -> Path:
    linhas = list(csv.reader((ultima_execucao("fluxo_completo") / "tabelas_csv" / "tipo_vicio.csv")
                             .open(encoding="utf-8"), delimiter=";"))
    classes = linhas[0][1:]
    esperados, previstos = [], []
    for linha in linhas[1:]:
        for classe, n in zip(classes, linha[1:]):
            esperados += [linha[0]] * int(n)
            previstos += [classe] * int(n)
    return salvar_matriz_confusao(matriz_confusao(previstos, esperados, classes), caminho, "")


# ---------------------------------------------------------------------------
# Tabela 2 — casos em que o prazo muda
# ---------------------------------------------------------------------------

def tabela_prazo_alterado(caminho: Path) -> Path:
    from app.models import Durabilidade, TipoVicio
    from app.prazo.calculator import calcular_prazo
    from avaliacao.casos import carregar_casos

    casos = {c.id: c for c in carregar_casos(RAIZ / "dados" / "casos_foto.json")}
    situacoes = {"dentro_do_prazo": "Dentro do prazo", "fora_do_prazo": "Fora do prazo",
                 "indeterminado": "Indeterminado"}
    data = lambda d: d.strftime("%d/%m/%Y")  # noqa: E731
    linhas = []
    for caso_id, situacao_caso in (("real_08", "Garantia\ncontratual"), ("real_05", "Reclamação com\nresposta negativa"),
                             ("real_14", "Reclamação com\nresposta negativa")):
        c = casos[caso_id]
        base = dict(tipo_vicio=TipoVicio(c.esperado.tipo_vicio), durabilidade=Durabilidade(c.esperado.durabilidade),
                    data_entrega=c.data_entrega, data_evidencia_defeito=c.data_evidencia_defeito,
                    data_referencia=c.data_referencia)
        so_art26 = calcular_prazo(**base)
        sistema = calcular_prazo(**base, data_reclamacao_fornecedor=c.data_reclamacao_fornecedor,
                                 data_resposta_negativa=c.data_resposta_negativa,
                                 data_fim_garantia_contratual=c.data_fim_garantia_contratual)
        vencimento = data(sistema.data_vencimento)
        if sistema.data_vencimento_se_interrupcao and sistema.situacao.value == "indeterminado":
            vencimento += f" (suspensão)\n{data(sistema.data_vencimento_se_interrupcao)} (interrupção)"
        linhas.append([situacao_caso, data(c.data_referencia),
                       f"{data(so_art26.data_vencimento)}\n{situacoes[so_art26.situacao.value]}",
                       f"{vencimento}\n{situacoes[sistema.situacao.value]}"])
    cabecalho = ["Situação\ndo caso", "Data da\nconsulta", "Vencimento só\npelo art. 26",
                 "Vencimento calculado\npelo sistema"]
    return salvar_tabela(cabecalho, linhas, caminho, "", altura_linha=0.62, folga=2)


def main() -> None:
    SAIDA.mkdir(parents=True, exist_ok=True)
    gerados = [
        figura_fluxo(SAIDA / "figura_1_fluxo_do_prototipo.png"),
        tabela_extracao(SAIDA / "tabela_1_extracao_foto_pdf.png"),
        tabela_precisao_revocacao(SAIDA / "tabela_2_precisao_revocacao_f1.png"),
        tabela_prazo_alterado(SAIDA / "tabela_3_casos_com_prazo_alterado.png"),
        figura_matriz_tipo_vicio(SAIDA / "figura_2_matriz_tipo_vicio.png"),
    ]
    for caminho in gerados:
        print(caminho.relative_to(RAIZ))


if __name__ == "__main__":
    main()
