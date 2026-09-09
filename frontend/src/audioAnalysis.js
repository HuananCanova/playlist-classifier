/**
 * Análise do áudio da prévia, feita uma vez sobre o buffer decodificado.
 *
 * Tudo aqui sai das amostras reais — nada é estimado a partir de metadados. É o
 * que justifica mostrar estes números: eles medem o arquivo que está tocando.
 *
 * Houve aqui um detector de BPM por autocorrelação, removido depois de medido:
 * validado contra os valores do Deezer em 8 faixas, acertava 3, errava 2 (as duas
 * por confusão métrica de 2/3 e 4/3, com erro de 33%) e se abstinha em 3 — 60% de
 * precisão quando respondia. Tentativas de filtrar os erros por concordância entre
 * metades da prévia rejeitaram acertos sem barrar um único erro, porque as faixas
 * problemáticas têm pulso estável no nível métrico errado. As métricas abaixo são
 * medições diretas do sinal e não têm esse problema.
 */

/** FFT iterativa radix-2, in-place. `re`/`im` têm comprimento potência de 2. */
function fft(re, im) {
  const n = re.length;
  for (let i = 1, j = 0; i < n; i++) {
    let bit = n >> 1;
    for (; j & bit; bit >>= 1) j ^= bit;
    j ^= bit;
    if (i < j) {
      [re[i], re[j]] = [re[j], re[i]];
      [im[i], im[j]] = [im[j], im[i]];
    }
  }
  for (let len = 2; len <= n; len <<= 1) {
    const ang = (-2 * Math.PI) / len;
    const wRe = Math.cos(ang);
    const wIm = Math.sin(ang);
    for (let i = 0; i < n; i += len) {
      let curRe = 1;
      let curIm = 0;
      for (let k = 0; k < len / 2; k++) {
        const uRe = re[i + k];
        const uIm = im[i + k];
        const vRe = re[i + k + len / 2] * curRe - im[i + k + len / 2] * curIm;
        const vIm = re[i + k + len / 2] * curIm + im[i + k + len / 2] * curRe;
        re[i + k] = uRe + vRe;
        im[i + k] = uIm + vIm;
        re[i + k + len / 2] = uRe - vRe;
        im[i + k + len / 2] = uIm - vIm;
        const nextRe = curRe * wRe - curIm * wIm;
        curIm = curRe * wIm + curIm * wRe;
        curRe = nextRe;
      }
    }
  }
}

/** Mistura os canais em mono — as métricas descrevem a faixa, não a estereofonia. */
function paraMono(buffer) {
  const n = buffer.length;
  const saida = new Float32Array(n);
  for (let c = 0; c < buffer.numberOfChannels; c++) {
    const ch = buffer.getChannelData(c);
    for (let i = 0; i < n; i++) saida[i] += ch[i];
  }
  const div = buffer.numberOfChannels || 1;
  for (let i = 0; i < n; i++) saida[i] /= div;
  return saida;
}

const paraDb = (v) => (v > 0 ? 20 * Math.log10(v) : -Infinity);

/**
 * Picos por faixa horizontal, para desenhar a onda completa da prévia.
 * Guarda mínimo e máximo de cada balde: usar só o máximo achataria a forma.
 */
export function calcularPicos(buffer, baldes = 900) {
  const dados = paraMono(buffer);
  const porBalde = Math.floor(dados.length / baldes);
  const picos = new Float32Array(baldes * 2);
  for (let b = 0; b < baldes; b++) {
    let min = 1;
    let max = -1;
    const inicio = b * porBalde;
    for (let i = 0; i < porBalde; i++) {
      const v = dados[inicio + i];
      if (v < min) min = v;
      if (v > max) max = v;
    }
    picos[b * 2] = min;
    picos[b * 2 + 1] = max;
  }
  return picos;
}

/**
 * Métricas espectrais e de dinâmica.
 *
 * - `rmsDb` / `peakDb`: volume médio e pico, em dBFS (0 é o máximo digital).
 * - `crest`: pico menos RMS. Valores altos indicam dinâmica preservada; baixos,
 *   compressão pesada (a "loudness war").
 * - `bandas`: energia relativa em graves, médios e agudos.
 * - `centroideHz`: centro de massa do espectro — correlaciona com "brilho".
 */
export function calcularMetricas(buffer) {
  const dados = paraMono(buffer);
  const taxa = buffer.sampleRate;

  let pico = 0;
  let somaQuadrados = 0;
  for (let i = 0; i < dados.length; i++) {
    const v = Math.abs(dados[i]);
    if (v > pico) pico = v;
    somaQuadrados += dados[i] * dados[i];
  }
  const rms = Math.sqrt(somaQuadrados / dados.length);

  // Espectro médio: janelas de 2048 com Hann, saltando de 4 em 4 para ser rápido.
  const N = 2048;
  const espectro = new Float64Array(N / 2);
  const janela = new Float64Array(N);
  for (let i = 0; i < N; i++) janela[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / (N - 1));

  let quadros = 0;
  for (let inicio = 0; inicio + N < dados.length; inicio += N * 4) {
    const re = new Float64Array(N);
    const im = new Float64Array(N);
    for (let i = 0; i < N; i++) re[i] = dados[inicio + i] * janela[i];
    fft(re, im);
    for (let k = 0; k < N / 2; k++) {
      espectro[k] += Math.hypot(re[k], im[k]);
    }
    quadros++;
  }
  if (quadros) for (let k = 0; k < espectro.length; k++) espectro[k] /= quadros;

  const hzPorBin = taxa / N;
  let energiaTotal = 0;
  let somaPonderada = 0;
  let graves = 0;
  let medios = 0;
  let agudos = 0;
  for (let k = 1; k < espectro.length; k++) {
    const hz = k * hzPorBin;
    const e = espectro[k];
    energiaTotal += e;
    somaPonderada += hz * e;
    if (hz < 250) graves += e;
    else if (hz < 4000) medios += e;
    else agudos += e;
  }

  const pct = (v) => (energiaTotal ? Math.round((v / energiaTotal) * 100) : 0);

  return {
    peakDb: paraDb(pico),
    rmsDb: paraDb(rms),
    crest: paraDb(pico) - paraDb(rms),
    centroideHz: energiaTotal ? Math.round(somaPonderada / energiaTotal) : 0,
    bandas: { graves: pct(graves), medios: pct(medios), agudos: pct(agudos) },
  };
}

/** Baixa e decodifica a prévia, devolvendo tudo o que as telas precisam. */
export async function analisarPrevia(url) {
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`Falha ao baixar a prévia: ${resp.status}`);
  const bytes = await resp.arrayBuffer();

  const Ctx = window.AudioContext || window.webkitAudioContext;
  const ctx = new Ctx();
  try {
    const buffer = await ctx.decodeAudioData(bytes);
    return {
      picos: calcularPicos(buffer),
      metricas: calcularMetricas(buffer),
      duracao: buffer.duration,
      taxaAmostragem: buffer.sampleRate,
      canais: buffer.numberOfChannels,
    };
  } finally {
    await ctx.close();
  }
}
