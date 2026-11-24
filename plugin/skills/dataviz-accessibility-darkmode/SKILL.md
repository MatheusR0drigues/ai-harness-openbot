---
name: dataviz-accessibility-darkmode
description: "Visualização de dados acessível e Dark Mode: paleta Okabe-Ito, sequenciais Viridis/Cividis, contraste WCAG 2.2 AA (4.5:1 e 3:1) com APCA Lc, elevação tonal sem preto puro e hierarquia Gestalt."
---

# Dataviz Acessível, Contraste APCA e Dark Mode

Regras de engenharia visual para dashboards, relatórios BI, gráficos web e artefatos analíticos legíveis para todos os públicos, incluindo usuários com discromatopsia e baixa visão.

## Paletas Seguras e Redundância Visual

- **Paleta Categórica Okabe-Ito (até 8 séries):** utilize combinações distinguíveis para deuteranopia, protanopia e tritanopia; evite pares problemáticos isolados como vermelho-verde ou azul-roxo próximos.
- **Escalas Contínuas e Divergentes:** prefira gradientes perceptualmente uniformes (**Viridis**, **Cividis**) no lugar de escalas arco-íris (*jet/rainbow*), que criam falsos degraus visuais.
- **Redundância Não-Cromática:** cor nunca é o único canal de significado. Combine séries ou estados com rótulos diretos (*direct labeling*), marcadores distintos (círculo, triângulo, quadrado), tracejados ou padrões.

## Contraste (WCAG 2.2 AA + APCA) e Dark Mode

- **Pisos de Contraste:**
  - Texto normal: mínimo **4.5:1** contra o fundo (e texto grande `>= 3:1`).
  - Componentes gráficos, bordas de barras, linhas de série e eixos significativos: mínimo **3:1** contra a superfície.
  - Complemente com contraste perceptual **APCA ($L_c$)** especialmente para texto fino ou modo escuro, evitando falsos positivos com cores saturadas sobre fundo escuro.
- **Dark Mode por Elevação Tonal:**
  - **Evite preto puro (`#000000`) e branco puro (`#FFFFFF`)** em grandes áreas para prevenir *halation* (ofuscamento em OLED/alta luminância).
  - Use base escura neutra ou fria controlada (ex.: `#121212` / `#161B22`) e crie hierarquia elevando a luminosidade das superfícies de cartões, cabeçalhos e modais progressivamente.
  - Reduza saturação de cores vibrantes no Dark Mode para manter conforto visual sem violar o contraste de `3:1`/`4.5:1`.

## Hierarquia Cognitiva e Eficiência Visual

- Aplique **princípios Gestalt** (proximidade para métricas relacionadas, alinhamento em grade, encerramento sutil por superfície em vez de bordas grossas).
- Maximize o *data-ink ratio*: elimine bordas 3D, fundos de grade pesados, linhas de eixo redundantes quando já houver rótulo direto nos valores e legendas separadas quando for possível rotular diretamente na série.
- Alinhe comparações quantitativas ao longo de eixo comum e inicie gráficos de barras sempre no zero.
