# AGENTS.md

Contrato operacional para agentes de engenharia no **OpenBot** neste repositório (modo **hookless / CI-first**, `1 Gerente por repositório`, kit compartilhado em `/data/OpenBot/Shared/ai-harness-openbot`).
Este arquivo é um mapa enxuto (mantenha em até 150 linhas; limite rígido de 200). Detalhes vivem nas regras do plugin global, `.agents/rules/` e skills.

## Projeto

Ainda não preenchido. Antes de iniciar trabalho de feature, acione a skill `harness-setup` para registrar propósito, usuários e escopo em `.agents/rules/product.md`.

## Stack

Ainda não definida. Execute `harness-setup` para configurar `harness.toml` e ativar os packs aplicáveis (`python`, `node`, `web-ui`, `research-guard`, `data-engineering`, `bi-pbip`). O runtime de hooks e gates usa apenas biblioteca padrão Python (`>= 3.11`).

## Comandos

Em sistemas Unix onde `python` apontar para Python 2 ou não existir, utilize `python3` nos comandos abaixo. A trava de CI roda em `.github/workflows/harness-verify.yml`.

| Objetivo | Comando |
| :--- | :--- |
| Gate completo (antes de concluir entrega) | `python scripts/harness/verify.py` |
| Gate parcial entre tarefas (`--fast`) | `python scripts/harness/verify.py --fast` |
| Diagnóstico do ambiente | `python scripts/harness/doctor.py` |
| Varredura de segredos | `python scripts/harness/check_secrets.py` |
| Varredura de conteúdo não confiável | `python scripts/harness/check_untrusted.py` |
| Auditoria de baseline de controles | `python scripts/harness/check_controls.py` |
| Varredura estática de riscos de código | `python scripts/harness/check_code_risks.py` |
| Validação de especificações | `python scripts/harness/validate_spec.py --all` |
| Verificação estrutural do harness | `python scripts/harness/check_structure.py` |

## Topologia do Repositório

- `.agents/rules/`: regras locais específicas do projeto (máximo de `24000` bytes por arquivo).
- `.agents/skills/<skill>/SKILL.md`: skills específicas do repositório, quando houver.
- `.github/workflows/harness-verify.yml`: gate obrigatório de CI OpenBot projetado pelo `init`.
- `specs/<feature>/`: especificações `spec-driven` (`requirements.md`, `design.md`, `tasks.md`, `progress.md`).
- `scripts/harness/`: runtime `stdlib-only` de hooks, guardas e sensores determinísticos.
- `harness/core.toml` e `harness.toml`: baseline de controles e configuração local do projeto.
- `docs/context/<arquivo>.md`: contexto topológico sob demanda em repositórios de domínio rico (Perfil 3: catálogos, pipelines, integrações).
- `contracts/<dominio>.*` ou `schemas/<dominio>.*`: contratos consumidos em produção (nunca dentro de `.agents/`).
- `docs/adr/`: registros de decisões arquiteturais.

## Convenções Críticas

- **Zero credenciais hardcoded:** use variáveis de ambiente, vaults ou ADC/OIDC; nunca imprima segredos nem dados pessoais (PII) em logs ou prompts.
- **Evidência ou zero:** nunca declare conclusão, correção ou aprovação sem saída real de comando executado após a última edição ou referência exata `arquivo:linha`.
- **Integridade de sensores:** nunca afrouxe asserções, marque `skip` ou edite guardas/testes apenas para forçar passagem verde.
- **Segurança de código:** proibido `eval`/`exec`, desserialização com `pickle`, `shell=True` e TLS com `verify=False`.
- **Git e PR:** trabalhe sempre em worktree dedicada (`../wt-<repo>-<slug>`), nunca no checkout principal nem em `main`/`master`; commit após tarefa com `verify --fast` verde e push em branch de feature são livres; abrir PR exige permissão explícita no fim da demanda.

## Comportamento do Agente

- Leia os arquivos relevantes antes de editar; declare premissas e pergunte objetivamente se houver ambiguidade de contrato.
- Faça mudanças cirúrgicas no escopo exato pedido; preserve comentários e docstrings alheios à mudança.
- **Ciclo anti-loop:** após 2 falhas consecutivas na mesma abordagem, pare imediatamente, analise a causa raiz e mude a estratégia ou consulte o usuário.
- Em tarefas não triviais ou de contexto longo, releia explicitamente o diff antes de finalizar (`git diff --stat` e inspeção das alterações).

## Fluxo de Trabalho

1. **Tier 0 (Micro — 1–2 arquivos triviais):** edição direta + `python scripts/harness/verify.py --fast` + inspeção do diff.
2. **Tier 1 (Fast-Track — até 3–5 arquivos sem contrato/segurança):** plano curto inline (`spec-fast-track`, sem criar pasta de spec), delegação em `flash` (escala para `inherit` após 1 falha de gate), `python scripts/harness/verify.py --fast` e `git diff --stat`.
3. **Tier 2 (`spec-driven` completo):** feature, contrato, segurança ou `>5` arquivos seguem `specs/<feature>/`, orquestração em ondas via `run_workflow` (`/data/OpenBot/Shared/ai-harness-openbot/workflows/spec_dag_runner.py`), `python scripts/harness/verify.py`, `git diff --stat` e revisão independente (`code-reviewer` + `security-auditor`).
4. **Bug:** skill `fix-bug`; o teste de regressão automatizado é escrito antes da correção e precisa reproduzir a falha; o bug não trivial vira entrada no Registro de erros.

## Critério de Pronto

- Requisitos e critérios de aceite aplicáveis cobertos por testes determinísticos (sem rede real, relógio real ou `sleep` longo).
- `python scripts/harness/verify.py` retornando código `0` após a edição final.
- `git diff --stat` auditado sem arquivos fora do escopo ou segredos residuais.

## Mapa de Conhecimento

- **Camada Quente (`always_on`):** `.agents/rules/product.md`, `.agents/rules/tech.md`, `.agents/rules/structure.md`.
- **Camada Morna (`model_decision` / `glob`):** regras por escopo em `.agents/rules/<escopo>.md`.
- **Camada Fria (sob demanda):** `docs/context/<arquivo>.md` (quando Perfil 3) e decisões arquiteturais em `docs/adr/`.
- **Registro de erros (sob demanda):** `.agents/rules/anti-patterns.md`; projeto com registro próprio troca este caminho.
- **Baseline de controles:** `harness/core.toml` e `harness.toml`.
- **Kit compartilhado OpenBot:** `/data/OpenBot/Shared/ai-harness-openbot`.
