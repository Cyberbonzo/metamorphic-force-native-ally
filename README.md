# Metamorphic Force no ROG Ally

Port Linux x86-64 do arcade **Metamorphic Force** (Konami, 1993), versão **AAA (Ásia, em inglês)**. O programa Motorola 68000 da placa é traduzido para código x86-64 durante a compilação. O executável SDL2 e a biblioteca da placa são específicos deste jogo. A compilação usa as ROMs do próprio jogador.

## Imagem

- **16:9 sem esticar.** O raster da placa foi ampliado de 288×224 para 384×224. São 48 colunas reais de cenário, sprites e HUD de cada lado, com a mesma proporção de pixel do monitor 4:3 do arcade. Os jogadores e os inimigos usam a largura toda: os limites horizontais que o programa aplica aos personagens foram ampliados com a tela. No início de uma fase, à esquerda do cenário não há mapa; ali o jogador para no mesmo ponto do arcade e a faixa fora do cenário fica preta.
- **Telas fixas em 4:3.** Testes de inicialização, história, título, seleção de personagem, Hall of Fame e logotipo só desenham as 288 colunas originais. Nessas telas as laterais ficam pretas; durante as fases (inclusive demonstrações, continue e mapas) a imagem volta a ocupar 16:9.
- **1080p.** A apresentação ocupa os 1920×1080 do Ally. A imagem é ampliada em escala inteira (5×) com vizinho mais próximo e reduzida em uma única passada linear até 1080 linhas (“sharp bilinear”): pixels nítidos e colunas de largura uniforme.
- **60 fps.** A placa original roda a 59,1856 Hz. Este port executa a lógica a 60,00 Hz, um quadro por atualização da tela do Ally, sem quadros repetidos. Por isso o jogo e o som ficam 1,38% mais rápidos que no arcade.

| Ação | ROG Ally | Teclado |
|---|---|---|
| Inserir crédito | View | 5 |
| Iniciar | Menu / Start | 1 ou Enter |
| Andar | Direcional ou analógico esquerdo | Setas |
| Ataque | A | Z |
| Pulo | B | X |
| Especial | X | C |
| Pausar ou continuar | Y | Esc |

O port guarda o estado da partida em `saves/progress.mfs`. Ele salva a cada 30 segundos de jogo, ao pausar e no encerramento normal; a gravação em disco roda fora do laço de vídeo, e carrega esse estado automaticamente na próxima abertura. A EEPROM do gabinete (configurações e recordes) fica em `saves/metamrpha.nv`.

## Compilar com suas ROMs

Em Linux x86-64, a compilação usa Git, Python 3, GCC/G++, Make, pkg-config e os arquivos de desenvolvimento do SDL2 e do zlib. Execute na pasta deste projeto:

```sh
bash build.sh "/caminho/para/metamrph.zip"
```

O script aceita o set *merged* `metamrph.zip`, ou o set pai junto com `metamrpha.zip` (*split*), e também ZIPs externos que contenham esses arquivos. Ele confere os 15 arquivos da versão AAA pelo tamanho e CRC, obtém a revisão fixada do FBNeo e gera o código nativo localmente. A saída pronta fica em `.work/dist/`: execute `jogar.sh` ou adicione esse arquivo à Steam. Use `MFORCE_WORK` para escolher outra pasta de compilação e `MFORCE_MARGIN=0` para gerar a versão 4:3 original.

## Limites horizontais em 16:9

O programa principal mantém o X de tela dos personagens (palavra em `(8,A0)`) dentro da tela original. As adaptações, aplicadas somente ao código traduzido e conferidas byte a byte antes da troca, ficam em `aot/generate.py`:

- **Jogadores (`0x058b80`).** O intervalo era [32, 244]. A nova rotina, colocada em `0x0F0000` (janela de ROM sem uso), aceita [32 − m, 244 + 48], com m = min(48, câmera) e a câmera lida em `0x202824`. Assim o jogador alcança as duas bordas sem entrar na área sem mapa do começo da fase.
- **Estados que dependem da borda.** Dois estados do jogador (atingido ou arremessado, em `0x05d818` e `0x05d992`) só avançam quando o X de tela está entre 0 e 276. Com os limites antigos isso sempre acontecia; com os novos, o jogador podia ficar imóvel encostado na borda direita. A faixa passou a ser [−48, 324]. O estado que termina ao tocar a borda (`0x05d8d6`) usa os mesmos limites dinâmicos da trava, por meio de uma segunda rotina em `0x0F0100`. As marcas de "jogador na borda" (`0x058c28`) foram ampliadas com a tela.
- **Outros personagens (`0x070ae0` e `0x070b52`).** Os intervalos [16, 272] e [32, 256] ganham 48 pixels de cada lado. As comparações passam a ter sinal, porque o limite esquerdo fica negativo.

## Laterais sem cenário

Algumas telas só desenham as 288 colunas originais, e as laterais extras ficariam com restos de outras cenas. O adaptador da placa (`board/mforce_board.cpp`) pinta de preto:

- as duas laterais fora das fases, quando o byte `0x2027c1` da RAM não vale 32 (testes, história, título, seleção, Hall of Fame, logotipo);
- as duas laterais na tela do emblema entre fases, quando o byte `0x202a16` vale 3;
- as colunas à esquerda do início do mapa, quando a câmera (`0x202824`) está a menos de 48 pixels da origem;
- a cor de fundo de uma lateral que tem praticamente uma só cor (97% dos pixels), como na escalada do penhasco, mantendo visíveis os personagens que entram nela.

## Como funciona

O gerador monta a ROM de programa de 2 MB (chips 01/02 em `0x000000`, 03/04 em `0x100000`). Para cada palavra par emite uma entrada x86-64 que carrega as palavras de extensão como imediato e salta para a semântica pré-compilada da instrução. Toda a decodificação acontece na compilação, e saltos calculados usam aritmética PC→código. O FBNeo guarda a memória do 68000 com os bytes trocados no host, então os chips 02 e 04 fornecem o byte alto de cada palavra.

O **Z80 de som não é traduzido**: ele roda no núcleo Z80 do FBNeo, assim como os dispositivos de vídeo e áudio da placa GX224 (K055555, K054338, K056832, K053246/K053247, K053250 PSAC e dois K054539). A interface SDL2 apresenta a imagem e lê os controles.

As ferramentas e adaptações estão neste repositório. As imagens dos chips e a biblioteca gerada a partir delas ficam na cópia privada do jogador. As condições de uso do código do FBNeo estão em [licenses/FBNeo.txt](licenses/FBNeo.txt). [Fontes dos dispositivos na revisão usada](https://github.com/finalburnneo/FBNeo/tree/61cd3ede225ec44b84011f7679db68123d72725d).

## Verificação

- **Tradução do 68000.** Uma compilação de referência com o interpretador Musashi e a versão traduzida foram executadas lado a lado. Os PCs, o SR e os 16 registradores coincidiram em todas as 16.519.004 instruções dos primeiros 600 quadros. Em 5.400 quadros com crédito, start, ataques, pulo, especial e avanço pela primeira fase, os hashes de vídeo e de áudio das duas compilações foram idênticos.
- **16:9.** No mesmo quadro, as 288 colunas centrais da versão 16:9 coincidem pixel a pixel com a imagem 4:3 em todas as faixas da tela: HUD, céu, cenário, chão e personagens. O tilemap K056832 limita sua origem global em zero; os 24 pixels restantes da margem são aplicados no deslocamento de cada camada.
- **Reprodutibilidade.** Uma compilação limpa pelo `build.sh` reproduziu os mesmos hashes de vídeo e de áudio.
- **Save.** Pelo atalho da Steam, o jogo foi encerrado no meio de uma luta e reaberto; a cena, o placar e o cronômetro voltaram iguais.
- **No ROG Ally.** O atalho abriu o executável em 1920×1080, o controle Elite 2 foi reconhecido e o áudio saiu pelo PipeWire. Em 80 segundos de partida a apresentação ficou em 60,00 fps, com intervalo máximo de 16,85 ms entre quadros e nenhum quadro atrasado, inclusive durante dois saves automáticos.
- **Limites.** Com as mesmas entradas, o X de tela do jogador alcançou −16 (esquerda, câmera avançada) e 292 (direita); no início da fase parou em 32, como no arcade. Uma partida automática de 40.000 quadros passou pelas fases 1 a 3 sem erro. A partir do save em que o jogador ficou imóvel na borda direita, a versão corrigida retomou o controle em 30 quadros; em três sequências aleatórias de entradas, o maior tempo no mesmo estado e posição foi de 129 quadros (animação de queda).

Ainda não verificado: as fases 4 em diante jogadas manualmente, o fim de cada fase (a área à direita do último trecho do mapa) e o modo para dois jogadores. A verificação de 16.519.004 instruções idênticas vale para a compilação 4:3 (`MFORCE_MARGIN=0`), que não altera o programa; a compilação 16:9 difere dela apenas nas rotinas de limite acima.
