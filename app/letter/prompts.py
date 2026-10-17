"""
Instrução usada na geração da carta de reclamação (quarta etapa).

Segue a divisão de Reiter e Dale (2000) em planejamento do conteúdo
(o que a carta deve conter), estruturação do documento e realização
linguística das sentenças finais — aqui, a divisão do conteúdo é
imposta pela própria instrução (identificação das partes, relato dos
fatos, fundamento legal, pedido e prazo de resposta), e a redação em si
é deixada para o modelo.

Importante (Metodologia): os artigos de lei citados na carta são
decididos pelo SISTEMA (`artigos_aplicaveis`), com base na classificação
já feita, e informados na instrução — o modelo NÃO escolhe quais artigos
citar, para não expor a carta ao risco de alucinação jurídica (Dahl et
al., 2024) numa peça que o consumidor pode efetivamente enviar a um
fornecedor. O pedido segue o art. 18, §1º, do CDC.
"""
from __future__ import annotations

from app.models import Durabilidade, TipoVicio

INSTRUCAO_SISTEMA = """\
Você redige cartas formais de reclamação de consumidor, em português do
Brasil, para serem enviadas por um consumidor a um fornecedor.

Regras que você deve seguir estritamente:

1. Use SOMENTE as informações fornecidas nos dados abaixo. Nunca invente
   nomes, datas, valores, endereços ou qualquer outro dado que não
   tenha sido fornecido.
2. Quando um dado necessário não estiver disponível, escreva um
   marcador entre colchetes no lugar dele (ex.: "[nome do consumidor]",
   "[nome do fornecedor]"), para que o consumidor preencha manualmente
   antes de enviar.
3. Cite APENAS os artigos de lei indicados nos dados fornecidos, com a
   mesma numeração. Não cite nenhum outro artigo, lei ou jurisprudência.
4. A carta deve conter, nesta ordem: identificação das partes
   (consumidor e fornecedor), relato objetivo dos fatos, fundamento
   legal (os artigos fornecidos), o pedido (exatamente como fornecido)
   e o prazo dado ao fornecedor para responder.
5. Tom formal, mas direto e claro; evite jargão jurídico desnecessário,
   já que o texto final é lido tanto pelo consumidor quanto pelo
   fornecedor.
6. Responda apenas com o texto da carta, sem comentários antes ou depois.
"""

PEDIDO_ART_18 = (
    "Que o fornecedor sane o vício do produto no prazo máximo de 30 "
    "(trinta) dias, conforme o art. 18, §1º, do CDC. Não sendo o vício "
    "sanado nesse prazo, o consumidor poderá exigir, à sua escolha: "
    "(I) a substituição do produto por outro da mesma espécie, em "
    "perfeitas condições de uso; (II) a restituição imediata da quantia "
    "paga, monetariamente atualizada, sem prejuízo de eventuais perdas e "
    "danos; ou (III) o abatimento proporcional do preço."
)

PRAZO_RESPOSTA = "30 (trinta) dias, contados do recebimento desta carta (art. 18, §1º, do CDC)"


def artigos_aplicaveis(
    tipo_vicio: TipoVicio,
    durabilidade: Durabilidade,
    garantia_contratual: bool = False,
    reclamacao_anterior: bool = False,
) -> list[str]:
    """
    Artigos do CDC (Lei nº 8.078/1990) que a carta deve citar, decididos
    em código a partir da classificação e do cálculo do prazo — e não
    pelo modelo. `garantia_contratual` e `reclamacao_anterior` indicam
    se essas situações alteraram a contagem (ver app/prazo/calculator.py).
    """
    inciso = (
        "art. 26, inciso I (prazo de 30 dias para produtos não duráveis)"
        if durabilidade == Durabilidade.NAO_DURAVEL
        else "art. 26, inciso II (prazo de 90 dias para produtos duráveis)"
    )
    inicio_contagem = (
        "art. 26, §1º (no vício aparente, o prazo conta da entrega efetiva do produto)"
        if tipo_vicio == TipoVicio.APARENTE
        else "art. 26, §3º (no vício oculto, o prazo conta do momento em que o defeito ficou evidenciado)"
    )
    artigos = [
        "art. 18, caput e §1º (responsabilidade do fornecedor pelos vícios de qualidade do produto)",
        inciso,
        inicio_contagem,
    ]
    if reclamacao_anterior:
        artigos.append(
            "art. 26, §2º, inciso I (a reclamação comprovadamente formulada ao fornecedor "
            "obsta a decadência até a resposta negativa inequívoca)"
        )
    if garantia_contratual:
        artigos.append("art. 50 (a garantia contratual é complementar à legal)")
    return artigos


def montar_prompt_usuario(dados_carta: dict) -> str:
    """
    Serializa os dados já calculados nas etapas anteriores (extração,
    classificação e prazo) num prompt textual para o modelo redigir a
    carta. Mantido como função separada da instrução de sistema para
    deixar claro que aqui entram apenas DADOS, e a regra de negócio
    (quais artigos citar, o pedido) já foi decidida em código antes de
    chegar ao modelo.
    """
    def ou_marcador(valor, marcador: str) -> str:
        return str(valor) if valor not in (None, "", []) else marcador

    linhas = ["Redija a carta de reclamação com base nestes dados:\n"]

    linhas.append("Consumidor: [nome do consumidor] (dados pessoais não são coletados pelo sistema)")
    linhas.append(f"Estabelecimento/fornecedor: {ou_marcador(dados_carta.get('estabelecimento'), '[nome do fornecedor]')}")
    linhas.append(f"Produto(s): {ou_marcador(', '.join(dados_carta.get('produtos') or []), '[produto]')}")
    linhas.append(f"Valor total da nota fiscal: {ou_marcador(dados_carta.get('valor_total'), '[valor]')}")
    linhas.append(f"Data de emissão da nota fiscal: {ou_marcador(dados_carta.get('data_emissao'), '[data da compra]')}")
    linhas.append(f"Data de entrega do produto: {ou_marcador(dados_carta.get('data_entrega'), '[data de entrega]')}")
    if dados_carta.get("data_evidencia_defeito"):
        linhas.append(f"Data em que o defeito se evidenciou: {dados_carta['data_evidencia_defeito']}")
    if dados_carta.get("data_fim_garantia_contratual"):
        linhas.append(f"Fim da garantia contratual: {dados_carta['data_fim_garantia_contratual']}")
    if dados_carta.get("data_reclamacao_fornecedor"):
        resposta = dados_carta.get("data_resposta_negativa")
        linhas.append(
            f"Reclamação anterior feita pelo consumidor ao fornecedor: {dados_carta['data_reclamacao_fornecedor']}"
            + (f", com resposta negativa em {resposta}" if resposta else ", ainda sem resposta")
        )
    linhas.append(f"Relato do problema (escrito pelo consumidor): {dados_carta.get('descricao_problema')}")
    linhas.append(
        f"Classificação: vício {dados_carta.get('tipo_vicio')}, "
        f"produto {dados_carta.get('durabilidade')}"
    )
    linhas.append(
        f"Prazo legal para reclamar: {dados_carta.get('prazo_total_dias')} dias, "
        f"contados a partir de {dados_carta.get('data_inicio_contagem')}, "
        f"com vencimento em {dados_carta.get('data_vencimento')} "
        f"({dados_carta.get('dias_restantes')} dias restantes na data desta carta)"
    )
    linhas.append(f"Data desta carta: {dados_carta.get('data_carta')}")
    linhas.append(
        "Artigos de lei a citar, todos da Lei nº 8.078/1990 (CDC) "
        "(não cite nenhum outro): " + "; ".join(dados_carta["artigos"])
    )
    linhas.append(f"Pedido: {PEDIDO_ART_18}")
    linhas.append(f"Prazo para resposta do fornecedor: {PRAZO_RESPOSTA}")

    return "\n".join(linhas)
