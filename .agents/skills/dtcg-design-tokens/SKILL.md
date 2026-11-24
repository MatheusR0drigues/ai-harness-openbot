---
name: dtcg-design-tokens
description: "Padronização de Design Tokens segundo W3C DTCG ($value, $type, $description), arquitetura em 3 camadas (Primitivo, Semântico, Componente) com espaço OKLCH, aliases com chaves simples e versionamento SemVer."
---

# Design Tokens Padrão W3C DTCG

Estrutura agnóstica de plataforma para definir, versionar e distribuir decisões visuais (cores, tipografia, espaçamento, elevação e temas Claro/Escuro) entre CSS, temas BI/PBIP, Figma e frameworks web.

## Formato Canônico W3C DTCG

- Utilize estritamente as chaves reservadas com prefixo `$`:
  - `$value`: valor concreto ou referência de alias em **chaves simples**, por exemplo `"{color.neutral.900}"` (nunca use chaves duplas).
  - `$type`: tipo explícito (`color`, `dimension`, `fontFamily`, `fontWeight`, `duration`, `number`), herdável pelo grupo pai quando uniforme.
  - `$description`: intenção de uso ou regra de acessibilidade associada ao token.
- Prefira o espaço de cores **`oklch(...)`** para interpolação perceptual uniforme e controle previsível de luminância entre temas claro e escuro, fornecendo fallback `sRGB`/hex apenas na compilação de saída quando a plataforma destino exigir.

## Arquitetura em 3 Camadas

1. **Camada 1 — Tokens Primitivos (Escala Bruta):**
   - Valores brutos sem significado de interface (ex.: `color.slate.950`, `space.4`). Nunca são referenciados diretamente por telas ou componentes de negócio.

2. **Camada 2 — Tokens Semânticos (Intenção e Tema):**
   - Mapeiam papel visual e acessibilidade usando aliases `{...}` para a camada primitiva (ex.: `surface.canvas`, `surface.elevated`, `text.primary`, `status.danger.fg`).
   - É nesta camada que ocorrem as trocas entre **Light Mode**, **Dark Mode** e alto contraste mantendo os contratos de contraste WCAG/APCA.

3. **Camada 3 — Tokens de Componente (Opcional e Restrita):**
   - Sobrescritas locais quando um componente específico precisa de isolamento sem poluir os semânticos globais (ex.: `button.primary.bg` apontando para `{accent.solid}`).

## Governança e Versionamento SemVer

- Trate o pacote de tokens como contrato versionado (**SemVer**):
  - `MAJOR`: remoção ou renomeação de token semântico público ou mudança drástica de papel.
  - `MINOR`: novos tokens semânticos ou novos temas compatíveis.
  - `PATCH`: ajuste fino de calibração de valor preservando nome, tipo e contraste mínimo.
- Valide em build que todos os aliases `{caminho.do.token}` resolvem sem ciclos antes de gerar CSS variables (`--token`) ou JSON de tema Power BI.
