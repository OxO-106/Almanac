## Takeaways

### GQA: Training Generalized Multi-Query Transformer Models from Multi-Head Checkpoints
**In class**
-   **Problem**: Autoregressive inference is bottlenecked by memory bandwidth due to loading keys and values (KV cache) for every token.
-   **Solution**: Grouped Query Attention (GQA) shares key-value heads across groups of query heads, reducing KV cache size compared to Multi-Head Attention (MHA).
-   **Conversion Method**: Existing MHA checkpoints can be converted to GQA by mean-pooling the K and V heads within each group.
-   **Training Strategy**: Do not train from scratch; fine-tune the converted model for a small fraction of original pre-training steps (approx. 5%) to recover quality.
-   **Performance**: Uptrained GQA achieves quality close to MHA with speed comparable to Multi-Query Attention (MQA).
-   **Sweet Spot**: ~8 groups is often optimal; too few groups hurt quality, too many increase cache size back towards MHA levels.

**From the paper**
-   **Compute Cost**: Uptraining takes approximately 600 TPUv3 chip-days, which is only 5% of the original pre-training compute.
-   **Mean Pooling Superiority**: Mean pooling K and V heads outperforms random initialization or single-head selection for conversion.
-   **Architecture**: GQA generalizes MQA; if groups $g=h$, it is MHA; if $g=1$, it is MQA; intermediate $1 < g < h$ is GQA.
-   **Evaluation**: Tested on summarization (CNN/Daily Mail), translation (WMT), and QA (TriviaQA) using T5-XXL models.
-   **Limitations**: Evaluated only on encoder-decoder models (T5), not decoder-only architectures; no comparison to scratch-trained GQA models.

### Native Sparse Attention: Hardware-Aligned and Natively Trainable Sparse Attention
**In class**
-   **Solution**: Native Sparse Attention (NSA) is natively trainable and hardware-aligned, using a dynamic hierarchical strategy.
-   **Mechanism**: Combines coarse-grained token compression, fine-grained blockwise selection of continuous blocks, and a dedicated sliding window for local context.
-   **Training**: The sparsity pattern is learned end-to-end during pretraining, ensuring the model adapts to the sparse architecture rather than being applied post-hoc.
-   **Hardware**: Uses Triton kernels designed to balance arithmetic intensity across training, prefilling, and decoding phases.

**From the paper**
-   **Speedups**: At 64k context length, NSA achieves a 9.0x speedup in forward propagation and 6.0x in backward propagation during training; 11.6x decoding speedup compared to Full Attention.
-   **Quality**: Outperforms Full Attention on LongBench (avg score 0.469, +0.032 gain) and maintains perfect retrieval accuracy on 64k needle-in-a-haystack tests.
-   **Reasoning**: The reasoning variant (NSA-R) outperforms Full Attention-R on AIME by +0.075 accuracy at 8k context.
-   **Blockwise Selection**: Processes continuous token blocks to minimize memory access overhead compared to token-granular approaches.
-   **Limitations**: Evaluation primarily on A100 GPUs; ensuring consistent block selection across GQA/MQA groups requires specific coordination.

### Gated Delta Networks: Improving Mamba2 with Delta Rule
**In class**
-   **Problem**: Linear Transformers struggle with long-context retrieval due to memory collisions and inefficient forgetting. Mamba2 degrades beyond 2K sequences due to uniform decay; DeltaNet cannot rapidly clear outdated information.
-   **Solution**: Gated DeltaNet combines adaptive gating (for rapid erasure) and the delta update rule (for targeted updates).
-   **Mechanism**: Uses an adaptive scaling factor $\alpha_t$ for decay and a delta update $\beta_t$ for modifications, preventing superposition of information.
-   **Training**: Developed a chunkwise training algorithm optimized for modern hardware, enabling parallel training of linear RNNs.
-   **Hybrid Models**: Combines Gated DeltaNet layers with sliding window attention or Mamba2 layers to achieve both improved training efficiency and superior task performance.

**From the paper**
-   **Performance**: Maintains near-perfect retention beyond 2K sequences on S-NIAH, whereas Mamba2 degrades significantly; achieves lowest overall perplexity among RNN models on long-context benchmarks.
-   **Throughput**: Throughput matches DeltaNet; hybrid models achieve higher throughput than pure recurrent layers.
-   **Memorization**: The delta rule demonstrates superior memorization of complex patterns (e.g., UUIDs) compared to uniform decay.
-   **Architecture**: Combines adaptive decay and targeted delta updates in a parallel training algorithm extending WY representation.
-   **Limitations**: Pure linear RNNs lag behind Flash-Attention Transformers on short-context retrieval; instruction alignment issues affect short contexts.

### Kimi Linear: An Expressive, Efficient Attention Architecture
*Not presented in class; from the paper.*

**From the paper**
-   **Architecture**: Introduces Kimi Delta Attention (KDA), an expressive linear attention module extending Gated DeltaNet with finer-grained channel-wise gating.
-   **Hybrid Design**: Combines KDA with Multi-Head Latent Attention (MLA) in a 3:1 layerwise ratio to balance retrieval capability with speed.
-   **Efficiency**: Reduces KV cache usage by up to 75% compared to full attention; achieves up to 6× decoding throughput for 1M context length.
-   **Scale**: Pretrained on 1.4 trillion tokens with 3B activated parameters and 48B total parameters.
-   **Performance**: Outperforms full MLA with a sizeable margin across short/long context and RL tasks (RULER: 84.3).

## Comparison

| Paper | Problem Targeted | Core Idea | What it Saves | What it Costs / Trade-offs | Training Method | Main Result | Main Limitation |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **GQA** | KV cache bandwidth bottleneck in autoregressive decoding. | Grouped Query Attention: Share KV heads across groups of query heads. | KV cache size (reduced to $1/g$ of MHA). | Quality drops if not fine-tuned; requires conversion from MHA checkpoint. | Convert MHA checkpoint via mean-pooling, then fine-tune 5% compute. | Quality close to MHA with MQA-like speed. | Evaluated only on encoder-decoder (T5); no scratch-trained GQA comparison. |
| **NSA** | $O(N^2)$ complexity and memory bandwidth for long-context decoding. | Native Sparse Attention: Dynamic hierarchical sparsity (compression, selection, window) trained end-to-end. | Computation and memory traffic (9x-11x speedup at 64k). | Requires hardware-aligned kernels; block selection coordination needed for GQA/MQA. | End-to-end training from scratch with learned sparsity patterns. | Outperforms Full Attention on LongBench; perfect needle-in-haystack retrieval. | Evaluated primarily on A100 GPUs; specific kernel tuning may be needed for other architectures. |
| **Gated DeltaNet** | Memory collisions and inefficient forgetting in linear RNNs/SSMs. | Gated Delta Rule: Adaptive gating + delta updates for targeted memory modification. | Computation (linear complexity); improves long-context retrieval over Mamba2/DeltaNet. | Pure linear RNNs lag on short context; requires hybrid models for optimal throughput. | Chunkwise parallel training algorithm optimized for hardware. | Near-perfect retention beyond 2K sequences; lowest perplexity among RNNs. | Struggles with exact copying/short-context retrieval without MLA hybrid component. |
| **Kimi Linear** | Quadratic scaling of softmax attention and limited expressivity of linear attention. | Kimi Delta Attention (KDA) + Hybrid Architecture (3:1 KDA/MLA ratio). | KV cache usage (75% reduction); decoding throughput (6x at 1M context). | Optimal hybrid ratio requires tuning; pure linear struggles without MLA. | Pretrained on 1.4T tokens with identical recipe to full attention baselines. | Outperforms full MLA and matches/exceeds full attention quality. | Pure linear attention lacks exact copying capability without MLA hybrid. |

## Connections

-   GQA generalizes Multi-Query Attention (MQA) and is a specific case of Grouped Query Attention where the number of groups equals the number of heads; this relationship is stated in class.
-   Native Sparse Attention (NSA) uses a dynamic hierarchical strategy that combines coarse-grained compression with fine-grained selection, a concept discussed as an alternative to fixed sparse patterns in class.
-   Gated DeltaNet improves upon Mamba2 and DeltaNet by combining gating and delta rules; this builds on the linear attention concepts introduced in class.
-   Kimi Linear extends Gated DeltaNet by introducing channel-wise gating (KDA) and hybridizing it with MLA; this is stated in the paper's abstract.
-   NSA and GQA both aim to reduce KV cache size, but NSA does so via sparsity while GQA does so via sharing; this comparison is made in class.
-   Hybrid models combining linear layers (like Gated DeltaNet) with attention layers are discussed as a way to achieve optimal throughput in class and in the Gated DeltaNet paper.

## Background

### From class
-   **Self-Attention Mechanics**: Each token computes Query ($Q$), Key ($K$), and Value ($V$) vectors. The attention score is $Softmax(Q \cdot K^T / \sqrt{d})$. The output is the weighted sum of Values.
-   **Multi-Head Attention (MHA)**: Uses $h$ independent heads, each with its own $Q, K, V$ matrices. Every head has its own KV cache, leading to high memory usage during decoding.
-   **KV Cache Bottleneck**: In autoregressive generation, previous tokens' $K$ and $V$ are cached to avoid recomputation. For long sequences (e.g., 64k), the cache size becomes large (~5GB), making inference memory-bandwidth bound rather than compute-bound.
-   **Multi-Query Attention (MQA)**: All heads share a single set of $K$ and $V$. Reduces cache size significantly but degrades quality due to limited expressiveness.
-   **Linear Attention**: Transforms the quadratic attention mechanism into a linear one by removing the softmax or using associative properties, allowing state maintenance ($S_t$) instead of full matrix multiplication.
-   **Chunkwise Training**: A method to parallelize linear RNNs (like Mamba) by computing states at checkpoints and combining them, avoiding the sequential dependency of standard recurrent forms during training.

### From the papers
-   **GQA**: The number of groups $g$ is a hyperparameter where $1 < g < h$. Mean pooling K and V heads is superior to random initialization for conversion.
-   **NSA**: Uses a dynamic hierarchical strategy with three branches: Compression (summarizes blocks), Selection (picks relevant blocks), and Sliding Window (local context). The sparsity pattern is learned end-to-end.
-   **Gated DeltaNet**: Introduces the Gated Delta Rule where $\alpha_t$ controls decay and $\beta_t$ controls updates, solving memory collision issues in linear RNNs.
-   **Kimi Linear**: Uses Diagonal-Plus-LowRank (DPLR) transition matrices for hardware efficiency and channel-wise gating in KDA to improve expressivity over scalar gating.

## Questions
- **Q** (a student, 4:57): Why is the specific priority palette designed this way, and what is the relationship between it and other words?
  - **A** (the presenter): The presenter explains that queries ask how important tokens are, keys answer that importance, and values represent the token's attributes, with the product of query and key determining the attention weight.
  - **From the paper** (GQA, 4 Related Work): The paper states that the design achieves a tradeoff between decoder quality and inference time by reducing memory bandwidth overhead from loading keys and values, which is the primary expense for long inputs. It notes that other works group attention heads for efficiency but do not focus specifically on the key-value heads that determine this overhead.
- **Q** (a student, 6:38): How do we know how important a token is?
  - **A** (the presenter): The presenter explains that the metrics are learned during training via backpropagation to minimize loss, adjusting weights toward an optimal goal.
- **Q** (a student, 7:16): Is the value matrix supposed to be for one A time, or is that not what we're doing with the word embeddings since they already encode the tokens?
  - **A** (the presenter): The presenter clarifies that values are a hidden representation multiplied by a projection layer, representing a different format of information or attributes rather than the raw token itself.
- **Q** (a student, 13:31): Why isolate groups in terms of keeping a key for the group, rather than just keeping the size of the number of keys and having them all map to that?
  - **A** (the presenter): The presenter explains that a one-to-one mapping keeps the computational graph simple and chaotic-free, whereas a many-to-one mapping would make the graph chaotic as the model grows, and the current design maximizes expressiveness per token.
  - **From the paper** (GQA, 2.2 Grouped-query attention): The paper explains that an intermediate number of groups creates a model with higher quality than MQA but faster than MHA, representing a favorable trade-off. It states that GQA allows keeping the same proportional decrease in bandwidth and capacity as model size increases, unlike MQA which represents a more aggressive cut.
- **Q** (a student, 21:23): Is this method basically a way to cut down the VRAM memory footprint during inference time, and what are the trade-offs regarding pre-training computation?
  - **A** (the presenter): The presenter confirms the method reduces inference cost but requires conversion from MHA checkpoints rather than training from scratch, as training MQA from scratch leads to worse performance, though GQA can be trained from scratch with some trials.
  - **From the paper** (GQA, 1 Introduction): The paper confirms the method reduces memory bandwidth overhead from loading keys and values, which is most important for generating longer sequences. It notes that checkpoints with multihead attention can be uptrained to use MQA with a small fraction of original training compute, presenting a cost-effective method.
- **Q** (a student, 29:13): Can you explain a little more about how global attention works in general?
  - **A** (the presenter): The presenter explains that global attention involves specific tokens that are always looked at, similar to a window but fixed, and serves as a summary of information for the model.
- **Q** (a student, 30:55): Is the global tokens part a superset of the dynamic attention, or do we not actually pick blocks smartly but just use fixed patterns?
  - **A** (the presenter): The presenter clarifies that global attention is a fixed pattern where tokens summarize information, whereas dynamic attention involves selecting blocks based on scores, and global attention is part of the dynamic mechanism.
- **Q** (a student, 34:25): Why is the design parameter D smaller than alpha and D equals L, given that we cannot want to break some information if that matters?
  - **A** (the presenter): The presenter explains that the design minimizes the chance of breaking related information into separate blocks, ensuring that connections are preserved during the compression and selection process.
- **Q** (a student, 36:43): How do we get the rates of the selection block when the compression block is larger than the selection block, given that attention scores are based on the smaller compression blocks?
  - **A** (the presenter): The presenter explains that the rates are calculated by summing the scores of the overlapping compression blocks that fall within the selection block, accounting for overlaps where blocks are covered multiple times.
- **Q** (a student, 41:35): Why is the attention mechanism called Native Sparse Attention and how does it relate to hardware co-design?
  - **A** (the presenter): They co-design the algorithms and the hardware, which is why they call it NSA. There is a section in the paper describing their redesign of the hardware.
  - **From the paper** (Native Sparse Attention, 1. Introduction): The paper introduces NSA as a Natively trainable Sparse Attention architecture that integrates hierarchical token modeling. It states that NSA introduces a hardware-aligned system to optimize blockwise sparse attention for Tensor Core utilization and memory access, ensuring balanced arithmetic intensity.
- **Q** (a student, 45:07): How can Top-K be trained if it is not differentiable and cannot calculate variance?
  - Not answered in class.
- **Q** (a student, 57:07): Is the explanation of computing states at checkpoints clear?
  - **A** (the presenter): The explanation is clear; the method computes states at checkpoints rather than for every single token position.
- **Q** (a student, 57:29): How is the transformation done in the FixStates Visual Model?
  - **A** (the presenter): The transformation involves a gate dot idea, which is a combination of Mamba and trying to get more efficient following design partition.
- **Q** (a student, 61:41): Why split queries into chunks instead of using reverse K and reverse tension for memory savings?
  - **A** (the presenter): The causal mask matrix M cannot be easily computed in quadratic time and space for the parallel form, which is why the chunking method is necessary.

## Summary

The lecture on October 5, 2026, focused on efficient attention mechanisms and architectures designed to overcome the memory bandwidth bottlenecks of standard Transformers during long-context autoregressive inference. The session began with a detailed review of Multi-Head Attention (MHA) and the KV cache problem, where the instructor explained that decoding speed is limited by the need to load large key-value caches for every generated token. To address this, the class examined **GQA** (Grouped Query Attention), presented as a practical solution that shares key-value heads across groups of query heads. The instructor highlighted a specific "recipe" for converting existing MHA checkpoints into GQA models by mean-pooling K and V matrices and fine-tuning for only 5% of the original compute, achieving quality close to MHA with speeds comparable to Multi-Query Attention (MQA).

The discussion then shifted to **Native Sparse Attention (NSA)**, which tackles the $O(N^2)$ complexity of full attention through a natively trainable, hardware-aligned approach. Unlike methods that apply sparsity post-training, NSA learns sparse patterns end-to-end using a dynamic hierarchical strategy involving token compression, blockwise selection, and sliding windows. The class noted its substantial speedups (up to 11x) at long context lengths while maintaining or exceeding the quality of full attention models. Following this, the lecture introduced **Gated Delta Networks**, a linear RNN architecture that improves upon Mamba2 and DeltaNet by combining adaptive gating with delta updates to solve memory collision issues in long-context retrieval. The instructor explained the chunkwise training algorithm that enables hardware-efficient parallelization for these linear models. Finally, the class briefly touched upon **Kimi Linear**, which was not presented but noted as a hybrid architecture extending Gated DeltaNet with channel-wise gating and MLA components to achieve high efficiency and performance at massive scales (1M context). The overarching conclusion was that no single attention mechanism is optimal; modern architectures increasingly rely on hybrid designs, hardware-aware training, and efficient conversion strategies to balance expressivity, speed, and memory constraints.