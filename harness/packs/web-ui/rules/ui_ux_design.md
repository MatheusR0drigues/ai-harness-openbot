---
trigger: glob
globs: "**/*.html, **/*.css, **/*.tsx, **/*.jsx, **/*.vue"
description: "Regras de UI/UX, acessibilidade WCAG 2.2 AA e performance para HTML, CSS e componentes."
---

# Regras de Design de UI/UX e Performance

Vale para qualquer mudança visual ou estrutural de HTML, CSS ou componentes de interface.

## Clareza e conversão

- A proposta de valor de cada tela precisa ficar clara em poucos segundos. Remova opções sem
  relação com o objetivo e distrações (aplique a **Lei de Hick**: menos escolhas, uma ação
  central por tela).
- A chamada para ação (CTA) principal tem destaque visual inequívoco; ações secundárias ficam
  visualmente subordinadas.
- Agrupe o conteúdo em blocos visuais de 3 a 5 itens (chunking), no máximo.

## Interação e acessibilidade (WCAG 2.2 AA)

- **Lei de Fitts:** todo alvo clicável ou tocável tem no mínimo **24x24 pixels CSS** (critério
  2.5.8 da WCAG 2.2), com espaçamento suficiente entre alvos vizinhos.
- **Contraste de texto:** razão mínima de **4.5:1** para texto normal e de **3:1** para texto
  grande (a partir de 24 px, ou 18,66 px em negrito) contra o fundo.
- **Contraste de componentes:** razão mínima de **3:1** para bordas de campos, ícones, estados
  de foco e demais componentes de interface e objetos gráficos necessários para entender a tela.
- Cor nunca é o único meio de transmitir informação (erro, status, seleção): acompanhe com
  texto, ícone ou padrão.
- Todo elemento interativo funciona pelo teclado, em ordem lógica, com foco sempre visível
  (`:focus-visible`) e sem ficar escondido atrás de cabeçalhos fixos.
- Use HTML semântico (`button`, `a`, `nav`, `main`, `label`) antes de ARIA; ARIA só complementa.
- Imagens informativas têm `alt` descritivo; imagens decorativas usam `alt=""`.
- Campos de formulário têm `label` associado e mensagens de erro ligadas ao campo
  (`aria-describedby`).
- Respeite `prefers-reduced-motion`: animações não essenciais são desligadas ou reduzidas.

## Tipografia fluida (CSS)

- Não use media queries rígidas para trocar tamanhos de fonte de forma abrupta entre
  breakpoints.
- Use `clamp(min, preferido, max)` para tamanhos e espaçamentos (`font-size`, `padding`,
  `margin`, `gap`).
- Para respeitar o zoom do sistema operacional e do navegador, combine `vw` com `rem` dentro de
  `calc()` em vez de usar `px` absolutos nos limites.
  - Exemplo: `font-size: clamp(1.5rem, calc(1.5rem + 2vw), 3rem);`

## Performance (Core Web Vitals)

- Toda imagem abaixo da dobra recebe `loading="lazy"`.
- A imagem principal acima da dobra (hero) não usa lazy loading; aplique `fetchpriority="high"`.
- Prefira formatos leves (WebP ou AVIF).
- Use `<picture>` com `srcset` e `sizes` para servir imagens adequadas à densidade e ao tamanho
  da tela do usuário.
- Toda imagem ou vídeo no HTML declara `width` e `height` (ou `aspect-ratio`) para evitar
  deslocamento de layout (CLS).
- Fontes web usam `font-display: swap` e carregam apenas os pesos usados.

## Design Tokens W3C DTCG e Acessibilidade Visual Avançada

- Estruture tokens visuais no padrão **W3C DTCG** (`$value`, `$type`, `$description`) em 3 camadas:
  **Primitivo** (escala bruta), **Semântico** (papel visual e tema via alias com chaves simples) e
  **Componente**, usando espaço perceptual `oklch(...)` sempre que possível.
- Em gráficos e visualizações categóricas, prefira paletas distinguíveis para daltonismo
  (**Okabe-Ito**) e gradientes uniformes (**Viridis** / **Cividis**), nunca dependendo apenas da cor.
- Além dos pisos WCAG 2.2 AA (`4.5:1` e `3:1`), avalie legibilidade em modo escuro com contraste
  perceptual **APCA ($L_c$)**.
- **Dark Mode por elevação tonal:** evite preto puro (`#000000`) e branco puro (`#FFFFFF`) em grandes
  superfícies; parta de base escura controlada (ex.: `#121212`) e eleve gradualmente a luminância de
  cartões e modais.
