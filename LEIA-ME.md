# Bolsa Simplificada: site com atualização automática

O site (pasta `docs/`) lê o arquivo `docs/data.json`. Um robô do GitHub (`.github/workflows/atualizar.yml`) roda a cada 30 minutos nos dias úteis, atualiza as cotações e, depois do fechamento, gera as justificativas com IA. Tudo grátis no GitHub, exceto o uso da API da Anthropic.

## Passo a passo
1. Crie uma conta em github.com e um repositório **público** novo (ex.: `bolsa-simples`). O GitHub Pages gratuito exige repositório público, então o site ficará visível a qualquer pessoa com o link.
2. Descompacte o zip e envie todo o conteúdo para o repositório (Add file → Upload files). Se a pasta oculta `.github` não subir, use Add file → Create new file, digite `.github/workflows/atualizar.yml` como nome e cole o conteúdo do arquivo.
3. Em console.anthropic.com crie uma chave de API. No repositório: Settings → Secrets and variables → Actions → New repository secret. Nome: `ANTHROPIC_API_KEY`. Valor: a chave. Nunca coloque a chave dentro de arquivos do repositório.
4. Settings → Pages → Source: "Deploy from a branch" → branch `main`, pasta `/docs` → Save.
5. Aba Actions → "Atualizar dados da bolsa" → Run workflow, num dia de pregão. Em 1 ou 2 minutos o site abre em `https://SEU-USUARIO.github.io/bolsa-simples/`.

## Ajustes
- Lista de ações, horário de fechamento (`FECHAMENTO`, confirme no site da B3), quantidade de altas e quedas e modelo de IA: topo de `bolsa_simples.py`.
- O cron do workflow está em UTC (Brasília = UTC−3).
- O GitHub pode atrasar execuções agendadas e pausar agendamentos de repositórios sem atividade. Se parar de atualizar, reative em Actions.
- Teste local com dados fictícios: `python bolsa_simples.py --demo`.
