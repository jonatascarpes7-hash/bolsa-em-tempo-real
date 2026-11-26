#!/usr/bin/env python3
"""Bolsa Simplificada: coleta cotações e notícias ao longo do dia e, no fechamento,
gera uma planilha com a movimentação e uma justificativa (feita por IA) para cada
grande alta ou queda.

Instalar:  pip install yfinance feedparser anthropic openpyxl
Chave:     defina a variável de ambiente ANTHROPIC_API_KEY
Rodar:     python bolsa_simples.py            (coleta o dia todo e analisa no fechamento)
           python bolsa_simples.py --agora    (analisa já, com os dados atuais)
           python bolsa_simples.py --demo     (teste com dados FICTÍCIOS, sem internet)

Aviso: a justificativa é uma hipótese baseada nas manchetes coletadas, não uma prova
de causa. Nada aqui é recomendação de investimento.
"""
import argparse, json, math, os, sys, time, urllib.parse
from datetime import datetime
from zoneinfo import ZoneInfo

# ===== CONFIGURAÇÃO (edite aqui) =====
LISTA = ["PETR4", "VALE3", "ITUB4", "BBDC4", "BBAS3", "ABEV3", "WEGE3", "MGLU3", "B3SA3", "SUZB3",
         "JBSS3", "RENT3", "GGBR4", "CSNA3", "PRIO3", "RADL3", "LREN3", "HAPV3", "CSAN3", "EMBR3"]
FECHAMENTO = (18, 0)      # hora e minuto (Brasília) em que a análise roda. Confirme o horário no site da B3.
INTERVALO_MIN = 10        # de quantos em quantos minutos coletar
QTD_ALTAS, QTD_QUEDAS = 5, 5
MODELO = "claude-sonnet-5-5"
PRAZOS = {"1 dia": 1, "1 semana": 5, "1 mês": 21, "3 meses": 63, "6 meses": 126, "12 meses": 252}
ARQ_ESTADO = "dados_do_dia.json"
FUSO = ZoneInfo("America/Sao_Paulo")

PROMPT = """Você é um analista de mercado explicando para um investidor iniciante, em português simples.
Ação: {t}. Abriu a R$ {ab:.2f} e está/fechou a R$ {pr:.2f} ({va:+.2f}% no pregão; {vd:+.2f}% sobre o fechamento anterior).
Máxima R$ {mx:.2f}, mínima R$ {mn:.2f}.
Contexto do dia: {ctx}
Evolução durante o dia (hora→preço): {curva}
Manchetes coletadas hoje (fonte, hora):
{notas}

Explique em até 120 palavras por que a ação se moveu assim.
Regras: 1) use SOMENTE fatos presentes nos dados acima; 2) separe "O que as notícias dizem" de
"Hipóteses (não confirmadas)"; 3) se os dados não mostram uma causa clara, diga isso com todas as letras;
4) não recomende comprar nem vender; 5) cite a fonte das manchetes que usar."""


def agora():
    return datetime.now(FUSO)


# ---------- 1. Bot de cotações ----------
def cotacoes(tickers):
    """Cotação do dia de cada ação (via yfinance). Para usar outra fonte, troque só esta função."""
    import yfinance as yf
    out = {}
    for t in tickers:
        try:
            d = yf.Ticker(t + ".SA").history(period="5d", interval="1d")
            if len(d) < 2 or d.index[-1].date() != agora().date():
                continue  # sem pregão hoje (feriado, fim de semana) ou sem dados
            h, o = d.iloc[-1], d.iloc[-2]
            out[t] = dict(abertura=float(h["Open"]), maxima=float(h["High"]), minima=float(h["Low"]),
                          preco=float(h["Close"]), anterior=float(o["Close"]), volume=float(h["Volume"]),
                          var_pregao=(h["Close"] / h["Open"] - 1) * 100,
                          var_dia=(h["Close"] / o["Close"] - 1) * 100)
        except Exception as e:
            print(f"  aviso: {t} falhou ({e})")
    return out


def contexto():
    import yfinance as yf
    partes = []
    for nome, s in (("Ibovespa", "^BVSP"), ("Dólar", "BRL=X")):
        try:
            d = yf.Ticker(s).history(period="5d", interval="1d")
            partes.append(f"{nome}: {(d['Close'].iloc[-1] / d['Close'].iloc[-2] - 1) * 100:+.2f}% no dia")
        except Exception:
            pass
    return "; ".join(partes) or "indisponível"


def volatilidade(t):
    import yfinance as yf
    try:
        r = yf.Ticker(t + ".SA").history(period="1y")["Close"].pct_change().dropna()
        return float(r.std() * math.sqrt(252) * 100) if len(r) > 30 else None
    except Exception:
        return None


# ---------- 2. Bot de notícias ----------
def coletar_noticias(t, est):
    import feedparser
    q = urllib.parse.quote(f"{t} ações when:1d")
    url = f"https://news.google.com/rss/search?q={q}&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    guardadas = est["noticias"].setdefault(t, {})
    for e in feedparser.parse(url).entries[:15]:
        guardadas.setdefault(e.get("title", ""), {"fonte": e.get("source", {}).get("title", "?"),
                                                  "hora": e.get("published", "")})


# ---------- 3. Bot analista (IA) ----------
def justificar(t, c, ctx, est):
    import anthropic
    notas = "\n".join(f"- {n} ({d['fonte']}, {d['hora']})"
                      for n, d in list(est["noticias"].get(t, {}).items())[:12]) or "(nenhuma manchete encontrada)"
    pts = est["curva"].get(t, [])
    curva = ", ".join(f"{h}→{p}" for h, p in pts[::max(1, len(pts) // 12)])
    prompt = PROMPT.format(t=t, ab=c["abertura"], pr=c["preco"], va=c["var_pregao"], vd=c["var_dia"],
                           mx=c["maxima"], mn=c["minima"], ctx=ctx, curva=curva, notas=notas)
    r = anthropic.Anthropic().messages.create(model=MODELO, max_tokens=500,
                                              messages=[{"role": "user", "content": prompt}])
    return r.content[0].text


# ---------- 4. Planilha ----------
def faixa(preco, vol, dias):
    m = vol / 100 * math.sqrt(dias / 252)
    return preco * math.exp(-m), preco * math.exp(m)


def planilha(data, cot, dest, just, vols, est):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font
    wb = Workbook()
    ws = wb.active
    ws.title = "Movimentação"
    ws.append(["Ação", "Abertura", "Atual/Fechamento", "Var. no pregão %", "Var. vs anterior %",
               "Máxima", "Mínima", "Volume"])
    for t in sorted(cot, key=lambda x: cot[x]["var_dia"], reverse=True):
        c = cot[t]
        ws.append([t, round(c["abertura"], 2), round(c["preco"], 2), round(c["var_pregao"], 2),
                   round(c["var_dia"], 2), round(c["maxima"], 2), round(c["minima"], 2), c["volume"]])
    w2 = wb.create_sheet("Por que se moveu")
    w2.append(["Ação", "Var. vs anterior %", "Justificativa (IA, hipótese)", "Manchetes usadas"])
    for t in dest:
        fontes = "\n".join(f"{n} ({d['fonte']})" for n, d in list(est["noticias"].get(t, {}).items())[:8])
        w2.append([t, round(cot[t]["var_dia"], 2), just.get(t, ""), fontes])
        for cel in w2[w2.max_row]:
            cel.alignment = Alignment(wrap_text=True, vertical="top")
    w2.column_dimensions["C"].width = 80
    w2.column_dimensions["D"].width = 60
    w3 = wb.create_sheet("Faixas de cenário")
    w3.append(["Ação", "Preço", "Oscilação anual %"] + [f"Faixa em {p}" for p in PRAZOS])
    for t in dest:
        v = vols.get(t)
        if v:
            fx = [f"R$ {a:.2f} a {b:.2f}" for a, b in (faixa(cot[t]["preco"], v, d) for d in PRAZOS.values())]
            w3.append([t, round(cot[t]["preco"], 2), round(v, 1)] + fx)
    w3.append([])
    w3.append(["Faixa = intervalo em que o preço ficaria ~2 de cada 3 vezes se a oscilação passada se repetir. "
               "Não é previsão."])
    for s in wb.worksheets:
        for cel in s[1]:
            cel.font = Font(bold=True)
    arq = f"relatorio_{data}.xlsx"
    wb.save(arq)
    return arq


# ---------- Estado do dia ----------
def carregar():
    hoje = str(agora().date())
    try:
        e = json.load(open(ARQ_ESTADO, encoding="utf-8"))
        if e.get("data") == hoje:
            return e
    except Exception:
        pass
    return {"data": hoje, "curva": {}, "noticias": {}}


def salvar(est):
    json.dump(est, open(ARQ_ESTADO, "w", encoding="utf-8"), ensure_ascii=False)


def destaques(cot):
    o = sorted(cot, key=lambda t: cot[t]["var_dia"], reverse=True)
    return o[:QTD_ALTAS], o[-QTD_QUEDAS:][::-1]


def demo():
    """Dados FICTÍCIOS só para testar a geração da planilha."""
    cot, est = {}, {"data": "DEMO", "curva": {}, "noticias": {}}
    for i, v in enumerate([5.1, 3.2, 1.0, -0.5, -3.8, -6.2], 1):
        t = f"FICT{i}"
        cot[t] = dict(abertura=10.0, maxima=11.0, minima=9.0, preco=10.0 * (1 + v / 100), anterior=10.0,
                      volume=1e6 * i, var_pregao=v, var_dia=v)
    altas, quedas = destaques(cot)
    just = {t: "[DEMO] Texto fictício. Aqui vai a justificativa escrita pela IA." for t in altas + quedas}
    vols = {t: 30.0 + i * 5 for i, t in enumerate(altas + quedas)}
    print("Pronto:", planilha("DEMO", cot, altas + quedas, just, vols, est))


def main():
    ap = argparse.ArgumentParser(description="Bolsa Simplificada")
    ap.add_argument("--agora", action="store_true", help="analisa já, sem esperar o fechamento")
    ap.add_argument("--demo", action="store_true", help="teste com dados FICTÍCIOS (sem internet)")
    a = ap.parse_args()
    if a.demo:
        return demo()
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Defina a variável de ambiente ANTHROPIC_API_KEY antes de rodar.")
    est = carregar()
    while True:
        cot = cotacoes(LISTA)
        if not cot:
            sys.exit("Sem cotações (sem pregão hoje ou fonte indisponível).")
        hh = agora().strftime("%H:%M")
        for t, c in cot.items():
            est["curva"].setdefault(t, []).append([hh, round(c["preco"], 2)])
        altas, quedas = destaques(cot)
        for t in altas + quedas:
            coletar_noticias(t, est)
        salvar(est)
        print(f"[{hh}] coletado. Altas: {altas} | Quedas: {quedas}")
        if a.agora or (agora().hour, agora().minute) >= FECHAMENTO:
            break
        time.sleep(INTERVALO_MIN * 60)
    ctx = contexto()
    dest = altas + quedas
    just = {t: justificar(t, cot[t], ctx, est) for t in dest}
    vols = {t: volatilidade(t) for t in dest}
    print("Pronto:", planilha(est["data"], cot, dest, just, vols, est))


if __name__ == "__main__":
    main()
