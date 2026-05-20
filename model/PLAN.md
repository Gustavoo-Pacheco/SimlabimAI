# model/PLAN.md — Parte 1: representação e augmentation

## Escopo deste documento

Este plano cobre **apenas as duas primeiras etapas** do pipeline de treino:

1. Pré-processamento determinístico do waveform
2. Extração das representações (mel-spectrograma + f0)
3. Data augmentation (waveform e mel)

A definição da CNN, da loss (sub-center ArcFace), do loop de treino, do enrollment e da inferência ficam para um documento subsequente. O objetivo aqui é congelar a **interface de entrada** que a CNN vai consumir, para que o desenho dela seja feito sobre premissas estáveis.

## Premissas do dataset

Tudo o que entra no pipeline vem do `collection/` via `dataset/`, com as invariantes garantidas no `CLAUDE.md` raiz:

- WAV 16 kHz mono PCM-16, header 44 bytes (`shared/wav.json`).
- Duração entre 8 KB e 40 MB, até 1200 s (`shared/limits.json`).
- Style ∈ `{cantar, cantarolar, assobiar}` (`shared/styles.json`).
- Storage key `raw_audio/{songSlug}/{takeUuid}.wav` (`shared/storage.json`).
- Takes são imutáveis após o upload (CLAUDE.md, invariante 5).

Assume-se que `dataset/` produz um manifest JSON com `{path_local, song_slug, style, duration_s, status}` por take aprovada. Esse manifest é a fonte única consumida por `model/`.

## Premissas do projeto

- Tudo **do zero** — sem MERT, CLAP, wav2vec2, HuBERT, BEATs, AST ou qualquer backbone pré-treinado. As únicas redes "prontas" autorizadas são extratores de f0 (PESTO) usados como feature engineering, não como backbone.
- Stack PyTorch (`model/.venv/`).
- Framework de identificação no estilo *face recognition*: encoder produz embedding 256-d L2-normalizado; loss de margin softmax no treino; inferência por busca em galeria (FAISS).
- Split por **música** (não por take) — músicas de val/test são disjuntas das de train.

## Pipeline desta parte

```
WAV 16kHz mono PCM-16
        │
        ▼
[1] Pré-processamento determinístico
        │ VAD / trim silêncio
        │ Loudness normalize (LUFS -23)
        │ Crop/pad para janela fixa de 10 s
        ▼
[2a] Augmentation no waveform              (apenas treino)
        │ pitch shift, time stretch, ruído, IR,
        │ EQ, codec, formant shift
        ▼
[3a] Mel-spectrograma                      (determinístico)
        │ n_mels=128, win=25ms, hop=10ms, log
        ▼
[2b] Augmentation no mel                   (apenas treino)
        │ SpecAugment, mixup
        ▼
[3b] f0 stream                             (extraído em paralelo, sobre o waveform pós-aug)
        │ PESTO, ~30ms hop, output em semitons + confiança
        ▼
mel: [1, 80, 1000] + f0: [2, ~334]
        │
        ▼
ENTRADA DA CNN (próxima parte do plano)
```

Observação: o f0 é extraído **depois** das augmentations de waveform, para que pitch shift e time stretch afetem o f0 consistentemente com o mel. Isso preserva o alinhamento físico entre os dois streams.

---

# [1] Pré-processamento determinístico

Aplicado **identicamente em treino, validação, teste e inferência**. Sem aleatoriedade. Roda no `Dataset.__getitem__` antes de qualquer aug.

## 1.1 Trim de silêncio inicial/final

**Objetivo**: remover regiões sem voz no começo/fim da take.

**Opção escolhida**: usar a confiança do PESTO. Durante o pré-processamento, roda uma passada rápida do PESTO em janela coarse (hop 30 ms), identifica o primeiro e último frame com confidence ≥ 0.5, e corta o waveform entre eles com margem de 100 ms em cada ponta.

**Por quê não webrtcvad ou energia simples**:
- webrtcvad é treinado em fala, não em canto/assobio — falha em assobio agudo sustentado.
- Energy gate falha em takes gravadas com ruído de fundo persistente (a energia nunca cai).
- PESTO já vai ser rodado mesmo, então o custo é amortizado.

**Fallback**: se nenhum frame ultrapassa confidence ≥ 0.5, usa a take inteira sem trim (caso degenerado de qualidade ruim — será filtrado pelo treino via loss alta, ou exclusão por estatística posterior em `dataset/`).

## 1.2 Loudness normalization

**Objetivo**: eliminar variação de volume entre takes (mic ruim, contribuinte gravando longe, etc.) sem distorcer o sinal.

**Opção escolhida**: LUFS integrated a **-23 LUFS** (padrão EBU R128), com limiter para evitar clipping. Biblioteca: `pyloudnorm`.

**Por quê não peak normalize ou RMS**:
- Peak normalize é sensível a 1 sample de transiente.
- RMS não pondera percepção auditiva.
- LUFS é o que streaming services usam — proxy decente do que o ouvido percebe como "mesmo volume".

## 1.3 Cropping / padding para janela fixa

**Objetivo**: alimentar a CNN com tensores de tamanho fixo. Necessário para batching.

**Decisão**: janela de **10 s = 160 000 samples**.

**Por quê 10 s**:
- Cobertura: 10 s pega uma frase melódica completa (refrão inteiro ou estrofe), com contexto suficiente pra diferenciar músicas com motivos curtos parecidos.
- Custo: mel resulta em [128, 1000], ainda confortável pra ResNet-18 (input ~1 MB por amostra em fp32).
- Inferência: na inferência o Simsalabim usará janela deslizante 10 s, hop 5 s — consistente com o treino.
- Verificado contra a distribuição real da manifest (50 takes, min 8 s, mediana 77 s): só 1 take fica abaixo de 10 s e cai no caminho de padding.

**Estratégia**:

- **Treino**: take mais longa que 10 s → crop aleatório uniforme de 10 s (vira aug implícita de localização temporal). Take mais curta que 10 s → padding com zeros à direita.
- **Validação/teste**: crop **central** de 10 s (determinístico, reprodutível).
- **Inferência**: janela deslizante (fora do escopo deste doc).

---

# [2] Representação

Duas representações em paralelo, alimentadas no mesmo waveform já augmentado.

## 2.1 Mel-spectrograma

Stream principal, captura timbre + harmônicos + ritmo.

| Parâmetro | Valor | Justificativa |
|---|---|---|
| `sample_rate` | 16 000 | invariante do `collection/` |
| `n_fft` | 400 | 25 ms em 16 kHz — janela curta o bastante pra capturar transientes |
| `win_length` | 400 | igual a `n_fft` |
| `hop_length` | 160 | 10 ms — overlap 60%, padrão de tarefas de áudio |
| `n_mels` | 80 | padrão de áudio 16 kHz (Whisper, AudioMAE). Acima disso, com `n_fft=400` (`n_freqs=201`), bins superiores ficam vazios — desperdício de capacidade. |
| `f_min` | 50 Hz | corta rumble de DC e ruído de mic |
| `f_max` | 8 000 Hz | Nyquist em 16 kHz |
| `mel_scale` | "htk" | mais simétrico para canto |
| `power` | 2.0 | magnitude squared antes do log |
| escala final | `log(1 + S)` | log-mel; evita log(0) sem precisar de epsilon |

**Shape de saída**: `[80, 1000]` para janela de 10 s. Tratado como imagem de 1 canal pela CNN downstream.

**Implementação**: `torchaudio.transforms.MelSpectrogram` + `torch.log1p`. Determinístico, sem learnable params (fora do escopo do gradient flow).

**Normalização**: log-mel já comprime a faixa dinâmica. Aplicar `(x - mean) / std` por feature (mean/std calculados sobre todo o train set, salvos em `model/data/stats.json`). Aplica também em val/test/inferência com as mesmas estatísticas.

## 2.2 f0 contour (PESTO)

Stream auxiliar, captura melodia destilada — invariante a timbre, complementar ao mel.

| Parâmetro | Valor | Justificativa |
|---|---|---|
| Modelo | PESTO oficial (pip `pesto-pitch`) | self-supervised, SOTA leve, PyTorch nativo |
| `step_size_ms` | 30 | resolução típica do paper; ~334 frames em 10 s |
| Output | `(pitch_semitones, confidence)` por frame | duas linhas |
| Pós-processamento | subtrair mediana de pitch da janela (só frames com confidence ≥ 0.5) | normaliza tonalidade — duas takes da mesma melodia em chaves diferentes ficam iguais |
| Frames com confidence < 0.5 | substitui pitch por 0 (sentinela) | evita f0 lixo de regiões sem voz |

**Shape de saída**: `[2, ~334]` — duas linhas (pitch normalizado, confidence), ~334 frames para 10 s.

**Por quê PESTO e não SPICE/CREPE**:
- **PESTO** > SPICE em benchmark e em tamanho; PyTorch nativo (SPICE é TF Hub).
- **PESTO** ≈ CREPE em acurácia mas 10× mais leve.
- Detalhe pragmático: SPICE traz TensorFlow inteiro como dependência num projeto PyTorch.

**Por quê subtrair a mediana**: o que define "mesma música" é o **contorno relativo** das notas, não a chave absoluta. Subtraindo a mediana, o sinal f0 vira invariante a transposição — duas pessoas cantando "Parabéns" em chaves diferentes produzem o mesmo f0 normalizado. Reduz drasticamente o trabalho que a CNN tem que fazer pra aprender essa invariância.

**Alinhamento entre streams**: o mel tem 1000 frames; o f0 tem ~334. Não é problema — cada stream é processado por sua própria rede e os vetores resultantes são concatenados depois do GAP. Não exige alinhamento temporal.

---

# [3] Data augmentation

**Princípio**: cada aug simula uma transformação real (acústica ou de canal) que vai aparecer na inferência. Augmentations físicas rodam **no waveform, antes do mel**; augmentations de regularização rodam **no mel, depois**.

**Onde roda**: só no `Dataset` em modo `train=True`. Val/test/inferência passam pelo pipeline determinístico puro.

**Quando roda**: online, no `__getitem__`, com sorteio aleatório por sample por epoch. Cada take é vista com aug diferente em cada epoch — equivalente a dataset infinito.

## 3.1 Augmentations no waveform

Aplicadas em ordem fixa, cada uma com probabilidade de ativação `p`. Biblioteca: `audiomentations` (cobre tudo) + `torchaudio` para pitch shift e time stretch de alta qualidade (phase vocoder).

| Aug | Range | `p` | Comentário |
|---|---|---|---|
| `PitchShift` | ±6 semitons (uniforme) | 0.8 | **crítica** — usuários cantam em chaves diferentes. ±6 cobre a maior parte da variação humana sem extrapolar pra absurdo (>1 oitava). |
| `TimeStretch` | 0.8–1.25× (uniforme em log) | 0.8 | **crítica** — variação de andamento. Range em log porque 1.25 e 0.8 são simétricos perceptualmente. |
| `AddGaussianSNR` | SNR 5–30 dB | 0.5 | ruído branco como aproximação rude. |
| `AddBackgroundNoise` | DEMAND ou ESC-50 subset, SNR 5–30 dB | 0.4 | ruído real (cafeteria, rua, sala) — mais fiel à inferência mobile. Requer baixar dataset auxiliar uma vez. |
| `ApplyImpulseResponse` | MIT IR Survey ou subset OpenAIR | 0.3 | simula reverb de sala. Carrega ~50 IRs e sorteia uniforme. |
| `SevenBandParametricEQ` | ±6 dB por banda | 0.3 | simula response curve de mic. |
| `Mp3Compression` ou `OpusEncoder` | 32–96 kbps | 0.2 | simula upload mobile (raro nessa pipeline porque o `collection/` já envia WAV, mas vale pra robustez geral). |
| `FormantShifting` | ±200 cents | 0.2 | simula variação de cantor (não muda pitch). Implementação manual via pyworld se não houver no audiomentations. |
| `Gain` | -10 a +3 dB | 0.5 | mesmo com LUFS normalize, varia perceptual loudness. Pequena. |

**Ordem total**:

```
waveform
  → Gain
  → PitchShift
  → TimeStretch
  → FormantShifting
  → SevenBandParametricEQ
  → AddBackgroundNoise  (ou AddGaussianSNR se não houver background dataset)
  → ApplyImpulseResponse
  → Mp3Compression
  → waveform augmentado
```

A ordem importa: `Gain` antes de `PitchShift` (gain não afeta pitch); IR depois de noise (a sala "ouve" o ruído também); codec por último (efeito de canal final).

## 3.2 Augmentations no mel

Aplicadas depois do `MelSpectrogram + log1p`, antes da normalização por estatísticas.

| Aug | Parâmetros | `p` | Comentário |
|---|---|---|---|
| `SpecAugment time mask` | 2 masks, largura ≤ 30 frames (~300 ms) | 0.7 | regularização tipo dropout temporal |
| `SpecAugment freq mask` | 2 masks, altura ≤ 20 bins | 0.7 | regularização tipo dropout em frequência |
| `Mixup` (intra-batch) | α=0.2, restrito a pares da **mesma música** | 0.2 | suaviza o embedding sem confundir classes |

**Mixup intra-classe**: ao contrário do mixup tradicional (mistura entre classes), aqui só misturamos takes da mesma música. Mantém a label clara e ainda interpola entre duas execuções diferentes da mesma melodia. Implementação: dentro do `collate_fn`, sortear pares com o mesmo `song_id`.

**Não aplicar mixup entre classes**: misturar takes de músicas diferentes destruiria a tarefa de identificação.

## 3.3 Resumo de quando cada aug roda

```
                   train      val       test      inferência
waveform-augs      ✓          ✗         ✗         ✗
mel-augs           ✓          ✗         ✗         ✗
preproc determ.    ✓          ✓         ✓         ✓
mel + f0 extr.     ✓          ✓         ✓         ✓
```

Val/test/inferência veem **exatamente** o pipeline determinístico — qualquer divergência aqui é bug.

---

# Implementação concreta

## Estrutura de arquivos (dentro de `model/`)

```
model/
├── PLAN.md                  # este arquivo (vai crescer com a parte 2)
├── README.md
├── requirements.txt
├── .venv/                   # gitignored
├── configs/
│   └── preproc.yaml         # todos os hiperparâmetros desta parte
├── data/
│   ├── manifests/           # JSON consumido daqui (produzido por dataset/)
│   └── stats.json           # mean/std do mel sobre train set
└── src/
    ├── __init__.py
    ├── io.py                # carrega WAV, valida sample rate / bit depth
    ├── preproc.py           # trim + LUFS + crop  (determinístico)
    ├── representation.py    # MelSpectrogram + PESTO wrappers
    ├── augment_waveform.py  # audiomentations Compose
    ├── augment_mel.py       # SpecAugment + mixup
    └── dataset.py           # torch.utils.data.Dataset que costura tudo
```

## requirements.txt (escopo desta parte)

```
torch>=2.2
torchaudio>=2.2
audiomentations>=0.34
pesto-pitch>=0.1
pyloudnorm>=0.1.1
numpy
soundfile
pyyaml
```

Sem `librosa` no path de treino (lento). `librosa` só pra notebooks de debug.

## configs/preproc.yaml (alvo)

Todos os números acima centralizados aqui — nada hardcoded em `.py`. Permite varredura de hiperparâmetros depois sem editar código.

```yaml
sample_rate: 16000
crop:
  duration_s: 10.0
  train_mode: random
  eval_mode: center
loudness:
  target_lufs: -23.0
mel:
  n_fft: 400
  hop_length: 160
  win_length: 400
  n_mels: 80
  f_min: 50
  f_max: 8000
  log: log1p
pesto:
  step_size_ms: 30
  conf_threshold: 0.5
  normalize: median_subtract
augment:
  waveform:
    pitch_shift:  {p: 0.8, range_semitones: [-6, 6]}
    time_stretch: {p: 0.8, range_log: [0.8, 1.25]}
    gaussian_snr: {p: 0.5, range_db: [5, 30]}
    background_noise: {p: 0.4, range_db: [5, 30], dataset: demand}
    ir_reverb: {p: 0.3, dataset: mit_ir_survey}
    eq: {p: 0.3, range_db: [-6, 6]}
    mp3: {p: 0.2, bitrate_kbps: [32, 96]}
    formant_shift: {p: 0.2, range_cents: [-200, 200]}
    gain: {p: 0.5, range_db: [-10, 3]}
  mel:
    spec_augment:
      time_mask:  {p: 0.7, count: 2, max_width: 30}
      freq_mask:  {p: 0.7, count: 2, max_width: 20}
    mixup_intra_class: {p: 0.2, alpha: 0.2}
```

---

# Parte 2: encoder, loss, treino, enrollment, inferência

## Escopo

Parte 2 cobre tudo da CNN até a inferência. Premissa: a interface de entrada da Parte 1 está congelada (`mel: [1, 80, 1000]` + `f0: [2, ~334]`).

Fica de fora:
- Quantização e otimização para mobile.
- Empacotamento do modelo no app `Simsalabim/`.
- Active learning / loop de coleta orientada por incerteza.
- Cross-modal: matching contra MIDI ou gravação de estúdio (continua opção pra Parte 3).

## Premissa de dataset

Tudo aqui assume um dataset com **N_train ≫ N_catalogue** (idealmente 5×). Sub-center ArcFace só ensina embedding bom se houver muitas classes (músicas) e múltiplos exemplos por classe no treino. Com a manifest atual (≈30 músicas, 50 takes, todas `pending`), **não dá pra treinar um modelo que generaliza**. Os números abaixo são pra quando o dataset crescer para algo como **200+ músicas em treino, 5+ takes/música**, com val/test em músicas disjuntas.

Enquanto não chegar lá, o caminho prático é: implementar tudo, rodar com dataset pequeno como sanity-check de wiring (loss desce, gradiente flui, FAISS retorna algo), e usar o resultado **só** pra verificar que o pipeline está correto — não pra concluir sobre qualidade do modelo.

---

# [4] Encoder

Two-stream: mel passa por CNN 2D estilo ResNet; f0 passa por CNN 1D leve; vetores são concatenados antes do projection head.

## 4.1 Mel stream — ResNet-18 adaptada

Input: `[B, 1, 80, 1000]` (B = batch, 1 canal, 80 mel bins, 1000 frames).

ResNet-18 padrão do `torchvision`, com duas mudanças mínimas:

1. **Stem aceita 1 canal** em vez de 3 — `conv1 = Conv2d(1, 64, kernel_size=7, stride=2, padding=3)`.
2. **Sem FC final** — a saída do `layer4` vai pro GAP, depois pra fusão. Descarta o `model.fc`.

Trace de shapes:

```
input               [B,   1,  80, 1000]
conv7×7 s=2, 64ch   [B,  64,  40,  500]
maxpool 3×3 s=2     [B,  64,  20,  250]
layer1 (2 blocks)   [B,  64,  20,  250]
layer2 (2 blocks)   [B, 128,  10,  125]
layer3 (2 blocks)   [B, 256,   5,   63]
layer4 (2 blocks)   [B, 512,   3,   32]
GAP                 [B, 512]
```

~11.2 M parâmetros (sem o FC original).

**Por quê ResNet-18 e não 34/50:**
- Capacidade adequada pro tamanho do dataset esperado (centenas a alguns milhares de takes).
- Treino rápido em GPU única.
- Skip connections facilitam treino do zero — sem isso, com BatchNorm, dá pra ficar travado em early epochs.

**Mudar pra ResNet-34 ou EfficientNet-B0** é viável quando dataset crescer.

## 4.2 F0 stream — 1D-CNN leve

Input: `[B, 2, ~334]` (pitch normalizado + confidence).

Não vale uma rede grande aqui: o sinal já é uma feature destilada. CNN 1D com kernels médios e algum dilated conv pra cobrir frase melódica.

Arquitetura proposta:

```
input                [B,   2, 334]
conv1d k=7 s=2 ch=32 [B,  32, 167]   + BN + GELU
conv1d k=5 s=1 ch=64 [B,  64, 167]   + BN + GELU
conv1d k=5 s=2 ch=96 [B,  96,  84]   + BN + GELU
conv1d k=3 d=2 ch=128[B, 128,  84]   + BN + GELU   (dilated)
conv1d k=3 s=2 ch=128[B, 128,  42]   + BN + GELU
GAP                  [B, 128]
```

~250 K parâmetros. Recebe o stream complementar e devolve um vetor curto.

## 4.3 Fusão + projection head

```
mel_vec  [B, 512]
f0_vec   [B, 128]
       ↓ concat
       [B, 640]
       ↓ Linear(640, 512) + GELU + Dropout(0.1)
       ↓ Linear(512, 256)
       ↓ L2-normalize
embedding [B, 256]
```

256-d é o "rosto" da música. **L2-norm é essencial** — torna distância cosseno = inner product, casa com FAISS `IndexFlatIP` e com ArcFace (que opera em hiperesfera).

Dimensão 256 escolhida por:
- Suficiente capacidade pra centenas/milhares de músicas (ArcFace original usa 512 pra MS1M com 85k identidades — aqui dá pra encolher).
- Memória do índice FAISS: 256 floats × 4 bytes × N_takes_galeria. 10k takes × 1KB = 10 MB. Trivial.

---

# [5] Loss: Sub-center ArcFace

A escolha foi argumentada no design da abordagem. Recap dos parâmetros e justificativa:

| Parâmetro | Valor | Por quê |
|---|---|---|
| `num_classes` | N_train (músicas no train set) | uma classe = uma música |
| `embedding_size` | 256 | dimensão do embedding |
| `margin (m)` | 0.5 | padrão ArcFace; aumenta separação angular |
| `scale (s)` | 30 | padrão ArcFace; tempera o softmax após normalização |
| `sub_centers (K)` | 3 | cada música tem 3 protótipos — encaixa naturalmente nos 3 estilos (cantar/cantarolar/assobiar) |

**Implementação**: `pytorch-metric-learning` tem `losses.SubCenterArcFaceLoss` pronto. Adiciona ao `requirements.txt` quando chegar nesse ponto.

```python
from pytorch_metric_learning.losses import SubCenterArcFaceLoss

loss_fn = SubCenterArcFaceLoss(
    num_classes=N_train,
    embedding_size=256,
    margin=0.5,
    scale=30,
    sub_centers=3,
)
# forward:
embeddings = model(mel, f0)   # já L2-normalizado
loss = loss_fn(embeddings, song_ids)
```

A loss **tem parâmetros próprios** (os protótipos das classes). Ela vai pro optimizer junto com o modelo: `optim = AdamW(list(model.parameters()) + list(loss_fn.parameters()), ...)`.

**Por quê não AdaFace, CosFace, ArcFace puro**:
- AdaFace: pondera margem por qualidade da amostra — ganho marginal sem instrumentação de "qualidade".
- CosFace: margem aditiva no cosseno; ArcFace (margem angular) tende a generalizar um pouco melhor.
- ArcFace puro (sem sub-centros): single prototype por música; perde representação de "modo de execução" (canto vs assobio).

---

# [6] Splits

## 6.1 Unidade de split = música, não take

Crítico pra evitar leak: takes da mesma música no train e no val "vazariam" identidade. O encoder pode decorar a take, não aprender o conceito de melodia.

## 6.2 Proporções

```
train         70% das músicas        + todas as takes delas
val           15% das músicas        + 50% das takes na galeria, 50% na query
test          15% das músicas        + 50% das takes na galeria, 50% na query
```

Random stratificado por estilo dentro do split (cada split deve ter razão ~igual de cantar/cantarolar/assobiar).

**Caveat com dataset atual**: 30 músicas viram 21/4/5. Val/test são tão pequenos que mAP fica ruidoso. Tolerável só pra sanity check; relatórios reais precisam de mais.

## 6.3 Reprodutibilidade

Splits são gerados uma vez e salvos em `data/splits.json`:

```json
{
  "seed": 0,
  "train": ["hotel-california", "garota-de-ipanema", ...],
  "val":   ["balada", ...],
  "test":  ["disritmia", ...]
}
```

Re-rodar o split com `--seed` diferente é OK pra experimentos, mas o arquivo commitado é o oficial.

---

# [7] Stats do mel (one-shot)

A normalização `(x - mean) / std` por bin precisa de stats computadas **apenas sobre o train set**, sem augmentation. Script dedicado: `scripts/compute_mel_stats.py`.

Loop:

```
for take em train_manifest:
    waveform = load_wav(take.path)
    waveform = trim + LUFS + center_crop_10s
    mel = MelExtractor()(waveform)
    acumula sum, sum_sq, count por bin

mean = sum / count       # [80]
std  = sqrt(sum_sq / count - mean^2)
salva em data/stats.json
```

Roda **uma vez** por configuração de splits/preproc. Quando o split muda ou o preproc muda, re-roda.

Val/test/inferência usam exatamente os mesmos mean/std.

---

# [8] Loop de treino

## 8.1 Hyperparams iniciais

| Item | Valor |
|---|---|
| Otimizador | AdamW (lr=3e-4, weight_decay=1e-4) |
| Schedule | cosine annealing, warmup 5% das steps |
| Batch size | 64 (ou maior se a GPU couber — ArcFace tolera batch pequeno) |
| Epochs | 200 (early stop por val mAP@10 sem melhora por 20 epochs) |
| Mixed precision | sim (`torch.cuda.amp`) |
| Gradient clipping | norm 5.0 |
| Loss params no optim | sim (`loss_fn.parameters()`) |
| Workers DataLoader | 4–8 (limitado por CPU; PESTO é caro) |

## 8.2 Loop por epoch

```
para cada epoch:
    modelo.train()
    para cada batch (mel, f0, song_id):
        mel, f0, song_id = intra_class_mixup_se_train()    # opcional
        embeds = model(mel, f0)
        loss = sub_center_arcface(embeds, song_id)
        backward + step + zero_grad
    log: loss média, lr atual
    
    se epoch % 5 == 0:
        modelo.eval()
        mAP = evaluate_retrieval(model, val_galeria, val_query)
        log: mAP, top-1, top-5
        save_checkpoint_se_melhor()
```

## 8.3 Checkpointing

Salva:
- `model/checkpoints/best_map.pt` — melhor mAP em val.
- `model/checkpoints/last.pt` — última epoch (pra resume).
- Estado do optim, scheduler, e da loss (os protótipos contam!).

---

# [9] Validação durante treino

**Não usar accuracy do classificador como métrica de qualidade.** O sub-center ArcFace classifica entre músicas do *train set*; isso não diz nada sobre generalização pra músicas novas (val/test).

A métrica certa é **mAP@10 de retrieval** no val set:

```
embeds_galeria = []  # de val_galeria
song_ids_galeria = []
para cada take em val_galeria:
    e = encoder(take.mel, take.f0)
    embeds_galeria.append(e), song_ids_galeria.append(take.song_id)

mAP_total = 0
para cada take em val_query:
    e_q = encoder(take.mel, take.f0)
    sims = cosine(e_q, embeds_galeria)
    top10 = sorted indices by sims desc, take 10
    precision = positions where song_ids_galeria[i] == take.song_id
    mAP_total += average_precision(precision)
mAP = mAP_total / len(val_query)
```

mAP@10 é o número que decide checkpoint. Loss do treino só serve pra log diagnóstico.

---

# [10] Enrollment (montagem da galeria de produção)

Dado um catálogo de N_cat músicas pro Simsalabim:

1. Coletar K takes por música, idealmente cobrindo os 3 estilos. K=3–10.
2. Cada take passa pelo pipeline determinístico (sem aug) → embedding 256-d.
3. **Indexar todos os embeddings** (não fazer média!) em FAISS `IndexFlatIP`. Cada vetor tem tag `song_id`.

```python
import faiss
index = faiss.IndexFlatIP(256)
song_ids_gallery = []
for song in catalog:
    for take in song.takes[:K]:
        e = encoder(*preproc(take))
        index.add(e.cpu().numpy())
        song_ids_gallery.append(song.id)
```

**Por quê não medir o centroide e indexar só ele**: perde a variação intra-classe (refrão vs ponte vs estilo diferente). Sub-protótipos múltiplos = recall maior.

Adicionar música nova no catálogo = só rodar enrollment dela. Sem retreinar.

Se a galeria ficar > 50k vetores, troca por `IndexIVFFlat` ou `IndexHNSWFlat`.

---

# [11] Inferência (Simsalabim)

## 11.1 Pipeline runtime

```
mic → resample 16 kHz mono
    → VAD (descarta silêncio inicial)
    → janelas de 10 s, hop 5 s         (esperar acumular pelo menos 1 janela)
    → para cada janela:
        preproc determinístico (trim/LUFS/crop pad)
        mel + f0
        encoder → embedding 256-d
        FAISS top-K vizinhos
        guarda (song_id_k, similarity_k)
    → agrega por song_id:
        score = soma das similarities top-3 entre todas as janelas
    → top-1 = argmax score
    → se max_score < τ: "desconhecido"
```

Hop de 5 s = overlap de 50 %. Garante que uma frase melódica de 7 s sempre tenha pelo menos uma janela que a contém inteira.

## 11.2 Agregação

Três opções; recomendado começar com **soma top-3 por song**:

| Agregador | Como | Característica |
|---|---|---|
| `sum` | soma de **todas** as similaridades | sensível a outliers de match espúrio |
| `max` | pega o melhor match em qualquer janela | rápido mas barulhento |
| `sum_top_k` | soma das k=3 melhores similaridades | robusto, padrão recomendado |

## 11.3 Threshold τ — rejeição "música desconhecida"

Calibrado no val set:
- Pega todas as queries do val (que estão NO catálogo do val).
- Pega *outras* queries de músicas fora do val (use train ou test) — atuam como "música desconhecida".
- Plota ROC: τ varia, mede (FAR, FRR). Escolhe ponto operacional (EER, ou priorizando recall).

`τ` salvo junto com o checkpoint do encoder. Distribuição de scores varia por encoder.

---

# [12] Métricas de avaliação

Reportar no test set, com encoder e splits congelados:

| Métrica | Mede |
|---|---|
| **Top-1 accuracy** | identificação correta em primeiro lugar |
| **Top-5 accuracy** | está entre os 5 mais prováveis |
| **MRR** | mean reciprocal rank — qualidade do ranking |
| **mAP@10** | precisão média até 10 |
| **EER** | equal error rate (verificação 1:1) |
| **AUC ROC para rejeição** | qualidade do threshold de "desconhecido" |

Quebrar **toda** medição por:

- **Estilo do query** (cantar / cantarolar / assobiar) — diagnóstico do que precisa melhorar.
- **K-shot na galeria** (K=1, 3, 5, 10) — cobertura mínima por música.
- **Cross-style**: query em `cantar` vs galeria só com `assobiar`, etc. — pior caso típico.

---

# [13] Arquivos novos em `src/` e `scripts/`

```
src/
├── encoder.py           # MelEncoder, F0Encoder, TwoStreamEncoder
├── loss.py              # wrapper de SubCenterArcFaceLoss
├── splits.py            # geração e leitura de splits.json
├── train.py             # loop de treino (CLI)
├── enroll.py            # constrói FAISS gallery (CLI)
├── infer.py             # query → top-1 (CLI ou função)
└── eval.py              # métricas de retrieval

scripts/
├── compute_mel_stats.py # roda uma vez sobre train set, salva data/stats.json
├── make_splits.py       # gera data/splits.json
└── train_baseline.py    # ponto de entrada com config YAML
```

Configs novos:

```
configs/
├── preproc.yaml         # (existe)
├── model.yaml           # encoder dims, dropout, etc.
├── train.yaml           # lr, batch, epochs, schedule
└── infer.yaml           # janela, hop, top-k, threshold τ
```

Mais um item no `requirements.txt`: `pytorch-metric-learning`, `faiss-cpu` (ou `faiss-gpu` se quiser indexar enorme).

---

# Critério de "Parte 2 pronta"

A Parte 2 está completa quando:

1. **Smoke training**: `train.py` roda 3 epochs num subset minúsculo (5 músicas, 3 takes cada), loss desce monotônicamente, mAP de val no toy é > random baseline.
2. **Enrollment + inference**: dado um checkpoint qualquer, `enroll.py` constrói o FAISS, `infer.py` aceita um WAV arbitrário e devolve top-5 com similarities.
3. **Métricas reportadas**: `eval.py` roda no test set e imprime a tabela do item [12] quebrada por estilo e K-shot.
4. **Splits congelados**: `data/splits.json` commitado, com seed registrada.

Não exige que o modelo seja "bom" — só que o caminho inteiro de dado → embedding → busca → métrica esteja sólido. Treinar bem é função de (a) dataset crescer e (b) iteração de hiperparâmetros sobre essa fundação.
