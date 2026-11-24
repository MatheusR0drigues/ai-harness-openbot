---
trigger: always_on
description: Decisoes de stack tecnologica, versoes fixadas e gerenciadores de pacote do projeto. Preenchido pela skill harness-setup.
---

# Stack Tecnológica

A definir. Carregue a skill `harness-setup` para registrar linguagens, frameworks, versões pinadas e os packs selecionados em `harness.toml` (`python`, `node`, `web-ui`, `research-guard`, `data-engineering`, `bi-pbip`).

Ferramental fixo do harness: runtime 100% biblioteca padrão Python `>= 3.11` em `scripts/harness/`, com `harness/core.toml` provendo os gates centrais e `harness.toml` gerenciando extensões do projeto.
