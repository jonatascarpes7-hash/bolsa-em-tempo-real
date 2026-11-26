"""Roda no GitHub Actions a cada 30 min durante o pregão e atualiza docs/data.json.
Durante o pregão: só cotações e notícias. Após o fechamento: gera as justificativas com IA
(uma vez por dia) e as mantém nas execuções seguintes. Reaproveita as funções de bolsa_simples.py."""
import json, os
import bolsa_simples as b

SAIDA = "docs/data.json"


def curva_do_dia(t):
    import yfinance as yf
    try:
        d = yf.Ticker(t + ".SA").history(period="1d", interval="15m")
        return [[i.astimezone(b.FUSO).strftime("%H:%M"), round(float(p), 2)] for i, p in d["Close"].items()]
    except Exception:
        return []


def main():
    hoje = str(b.agora().date())
    try:
        ant = json.load(open(SAIDA, encoding="utf-8"))
    except Exception:
        ant = {}
    if ant.get("data") != hoje:
        ant = {}
    cot = b.cotacoes(b.LISTA)
    if not cot:
        print("Sem pregão hoje ou fonte indisponível. Nada a atualizar.")
        return
    just = ant.get("justificativas") or {}
    altas, quedas = (ant["altas"], ant["quedas"]) if just else b.destaques(cot)
    dest = [t for t in altas + quedas if t in cot]
    est = {"curva": {t: curva_do_dia(t) for t in dest}, "noticias": {}}
    for t in dest:
        b.coletar_noticias(t, est)
    ctx = ant.get("contexto") or ""
    agora = b.agora()
    if not just and (agora.hour, agora.minute) >= b.FECHAMENTO and os.environ.get("ANTHROPIC_API_KEY"):
        ctx = b.contexto()
        for t in dest:
            try:
                just[t] = b.justificar(t, cot[t], ctx, est)
            except Exception as e:
                print(f"  aviso: justificativa de {t} falhou ({e})")
    vols = {t: (ant.get("volatilidade") or {}).get(t) or b.volatilidade(t) for t in dest}
    saida = dict(
        data=hoje, atualizado=agora.strftime("%H:%M"), fechado=bool(just), contexto=ctx,
        acoes=[dict(t=t, **cot[t]) for t in cot], altas=altas, quedas=quedas,
        justificativas=just, volatilidade=vols,
        noticias={t: [dict(titulo=n, **d) for n, d in list(est["noticias"].get(t, {}).items())[:8]]
                  for t in dest})
    os.makedirs("docs", exist_ok=True)
    json.dump(saida, open(SAIDA, "w", encoding="utf-8"), ensure_ascii=False)
    print("Atualizado:", saida["atualizado"], "| justificativas prontas:", saida["fechado"])


if __name__ == "__main__":
    main()
