---
trigger: always_on
description: Topologia oficial de diretorios e artefatos do repositorio. Estendido pela skill harness-setup.
---

# Estrutura do Repositório

| Artefato | Localização | Regra |
| :--- | :--- | :--- |
| Código da aplicação | A definir (`harness-setup`) | Alinhar antes de criar novas pastas na raiz |
| Suíte de testes | A definir (`harness-setup`) | Espelhar a estrutura do código fonte |
| Regras locais e skills | `.agents/rules/`, `.agents/skills/<skill>/SKILL.md` | Manter `.agents/rules/*.md` abaixo de `24000` bytes |
| Gate de CI OpenBot | `.github/workflows/harness-verify.yml` | Gerado pelo `cli.py init`; sem secrets, Actions fixadas por SHA |
| Contexto topológico (Perfil 3) | `docs/context/<arquivo>.md` | Leitura sob demanda indexada no `AGENTS.md`; nunca `always_on` |
| Contratos e schemas de produção | `contracts/<dominio>.*` ou `schemas/<dominio>.*` | Isolados na raiz; proibido acoplar runtime dentro de `.agents/` |
| Especificações de feature | `specs/<feature>/` | Seguir fases `Specify -> Design -> Tasks -> Implement` |
| Gates e runtime local | `scripts/harness/` | Exclusivo stdlib Python `>= 3.11`, saída `0`/`1` |
| Decisões arquiteturais | `docs/adr/` | Um arquivo por ADR aceito; não reescrever histórico |
