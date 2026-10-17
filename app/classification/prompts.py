"""
Instrução e exemplos usados na classificação do relato do usuário.

Seguem a técnica de aprendizado em contexto (in-context learning), na
qual um modelo de linguagem de grande escala já pré-treinado realiza a
tarefa a partir de instruções e de alguns exemplos incluídos no próprio
texto de entrada, sem que seja necessário treinar ou ajustar o modelo
(Brown et al., 2020). Isso dispensa um conjunto de dados rotulado e
etapas de treinamento e validação, ao custo de menos controle sobre o
comportamento do modelo, o que é compensado aqui por (a) forçar a
saída num formato estruturado (ver classifier.py) e (b) reservar o
cálculo do prazo, a parte mais sensível a erro, para uma regra
determinística separada (ver app/prazo/calculator.py).
"""
import json

INSTRUCAO_SISTEMA = """\
Você ajuda a classificar relatos de consumidores sobre problemas com
produtos, segundo as categorias usadas pelo art. 26 do Código de Defesa
do Consumidor brasileiro (Lei nº 8.078/1990).

Classifique o relato em duas dimensões:

1. tipo_vicio:
   - "aparente": o defeito é perceptível de imediato ou logo no início
     do uso (ex.: o produto já chega quebrado, não liga, tem uma peça
     faltando).
   - "oculto": o defeito só se manifesta depois de um tempo de uso
     normal, sem que houvesse como percebê-lo antes (ex.: um
     eletrodoméstico que funciona bem por meses e então para de
     funcionar).

2. durabilidade:
   - "duravel": bens que não se consomem com o primeiro uso e duram por
     um período extenso (ex.: eletrodomésticos, eletrônicos, móveis,
     roupas, calçados).
   - "nao_duravel": bens consumidos rapidamente, geralmente com o
     próprio uso (ex.: alimentos, produtos de higiene e limpeza,
     cosméticos consumíveis).

Se o relato descrever uma situação que foge do escopo deste sistema —
por exemplo, um serviço (não um produto), ou um caso em que o defeito
tenha causado dano à saúde ou à segurança do consumidor (que é regido
pelos arts. 12 a 17 do CDC, não pelo art. 26) — marque fora_de_escopo
como true, preencha tipo_vicio e durabilidade com "nenhum" e explique o
motivo em vez de forçar uma classificação. Quando fora_de_escopo for
false, tipo_vicio e durabilidade NUNCA podem ser "nenhum".

Responda SEMPRE em formato JSON, com uma justificativa breve (1-2
frases) baseada apenas no que o relato efetivamente diz.
"""

# Poucos exemplos (few-shot) que fixam o padrão esperado de resposta.
# Mantidos curtos deliberadamente: o objetivo é ancorar o formato e os
# casos de fronteira mais comuns, não cobrir exaustivamente o domínio.
# Aqui, diferente de uma API baseada em "tool use" (como a da
# Anthropic), os exemplos são simplesmente escritos como texto dentro
# do próprio prompt — mais simples de montar e igualmente eficaz para
# aprendizado em contexto.
EXEMPLOS = [
    {
        "relato": "Comprei uma televisão e, na hora de tirar da caixa, "
        "a tela já estava trincada.",
        "resposta": {
            "tipo_vicio": "aparente",
            "durabilidade": "duravel",
            "fora_de_escopo": False,
            "justificativa": "O defeito (tela trincada) é perceptível de "
            "imediato, ao abrir a caixa, e televisão é um bem durável.",
        },
    },
    {
        "relato": "Meu liquidificador funcionou bem por uns 4 meses e "
        "de repente parou de ligar, sem eu ter feito nada de errado.",
        "resposta": {
            "tipo_vicio": "oculto",
            "durabilidade": "duravel",
            "fora_de_escopo": False,
            "justificativa": "O defeito só apareceu depois de meses de "
            "uso normal, o que caracteriza vício oculto num bem durável.",
        },
    },
    {
        "relato": "O técnico que contratei para consertar minha geladeira "
        "não apareceu no dia combinado.",
        "resposta": {
            "tipo_vicio": "nenhum",
            "durabilidade": "nenhum",
            "fora_de_escopo": True,
            "justificativa": "O relato trata de um serviço (conserto), "
            "não de vício em um produto, o que foge do escopo deste "
            "sistema.",
        },
    },
    {
        "relato": "O carregador do celular que comprei esquentou demais, "
        "pegou fogo e queimou minha mão.",
        "resposta": {
            "tipo_vicio": "nenhum",
            "durabilidade": "nenhum",
            "fora_de_escopo": True,
            "justificativa": "O defeito causou dano à segurança do "
            "consumidor (queimadura), o que é fato do produto (arts. 12 "
            "a 17 do CDC), e não vício regido pelo art. 26.",
        },
    },
    {
        "relato": "Abri o pacote de biscoito que comprei ontem e ele "
        "estava todo mofado.",
        "resposta": {
            "tipo_vicio": "aparente",
            "durabilidade": "nao_duravel",
            "fora_de_escopo": False,
            "justificativa": "O mofo é perceptível assim que se abre a "
            "embalagem, e alimento é um bem não durável.",
        },
    },
]


def montar_prompt_com_exemplos(relato: str) -> str:
    """
    Monta um único prompt de texto com os exemplos (few-shot) seguidos
    do relato real a classificar, no formato que o modelo recebe como
    entrada de texto simples.
    """
    partes = ["Aqui estão alguns exemplos de como classificar:\n"]

    for exemplo in EXEMPLOS:
        partes.append(f'Relato: "{exemplo["relato"]}"')
        # json.dumps (e não o dict do Python) para o exemplo mostrar
        # exatamente o formato JSON exigido na resposta.
        resposta_json = json.dumps(exemplo["resposta"], ensure_ascii=False)
        partes.append(f"Resposta: {resposta_json}\n")

    partes.append("Agora classifique este relato:\n")
    partes.append(f'Relato: "{relato}"')
    partes.append("Resposta:")

    return "\n".join(partes)
