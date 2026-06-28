// audio_head_kernel.h — Audio Head C++/CUDA 算子声明
//
// 设计决策（核心）：
//   1. 为什么把 Audio Head 从 PyTorch 下沉到 C++/CUDA：
//      Python 实现虽迭代快，但每次推理都要走 PyTorch dispatcher（~毫秒级开销），
//      且占 GIL。在 FT 引擎（C++）的 hot path 末尾，再回到 Python 跑两层 Linear
//      会引入跨语言 + GIL 毛刺。下沉为 C++/CUDA 后，可在 FT 的 decoding.cpp 内
//      就地调用，零拷贝消费 hidden_states，首 token 延迟降至亚毫秒。
//      Python 实现保留为 fallback（无 CUDA / 未编译 C++ 扩展时）。
//   2. 同时支持 CUDA 与纯 CPU 两条路径：
//      - CUDA 路径：cublasLtMatmul（Ampere Tensor Core FP16）+ 自定义 GELU/argmax kernel
//      - CPU 路径：std::vector + 朴素 matmul，仅用于无 GPU 环境下的逻辑验证与单测
//      用 #ifdef HAVE_CUDA 包裹所有 CUDA 调用，保证无 CUDA 工具链时仍可编译可单测。
//   3. 权重布局：fc1.bin 按 [hidden_dim, intermediate_dim]（行主序，即 PyTorch
//      fc1.weight 的转置）存储，使 GEMM 直接做 X @ W（无需运行时转置）；
//      fc2.bin 同理按 [intermediate_dim, num_codebooks*snac_vocab_size] 存储。
//      权重一律 FP16（Ampere Tensor Core 最优）；CPU 路径读取后转 FP32 计算。
//   4. bias：spec 仅强制要求 fc1.bin/fc2.bin。为与 PyTorch AudioHead（Linear 含 bias）
//      数值对齐以支持 bit-exact 单测，本实现额外读取可选 fc1_bias.bin/fc2_bias.bin
//      （存在则加 bias，不存在则 bias=0），既不破坏 spec 又保证可对齐。
//
// 与 audio_head/audio_head.py:AudioHead 的数值契约：
//   forward 等价于 PyTorch:
//     x = F.gelu(fc1(hidden_states))        # [batch, intermediate]
//     logits = fc2(x)                        # [batch, num_codebooks*snac_vocab]
//     logits = logits.view(batch, num_codebooks, snac_vocab)
//     return logits.argmax(dim=-1)           # [batch, num_codebooks] int32
//   唯一允许的数值差异：GELU 近似方式不同（CUDA/CPU 回退用 tanh 近似，
//   PyTorch F.gelu 默认 erf-based），在边界值可能翻转 argmax，单测用 atol 容忍。

#ifndef ELP_ORPHEUS_AUDIO_HEAD_KERNEL_H
#define ELP_ORPHEUS_AUDIO_HEAD_KERNEL_H

#include <cstdint>
#include <string>
#include <vector>

// ============================================================================
// CUDA 相关头文件仅在 HAVE_CUDA 定义时引入。
// 这样无 CUDA 工具链的纯 C++ 编译器（g++/MSVC）也能编译本头文件。
// ============================================================================
#ifdef HAVE_CUDA
#include <cuda_runtime.h>
#ifdef HAVE_CUBLASLT
#include <cublasLt.h>
#else
#include <cublas_v2.h>
#endif
#endif

namespace elp_orpheus {

// AudioHeadKernel：Audio Head 的 C++/CUDA 算子封装。
//
// 生命周期：
//   1. 构造（仅记录维度配置，不分配显存）
//   2. load_weights(dir)：从目录读取 fc1.bin/fc2.bin（FP16）到显存/内存
//   3. forward(hidden, batch, out)：就地计算，输出 [batch, num_codebooks] int32
//
// 线程安全：非线程安全（与 FT 解码的单线程调用模型一致；多线程需上层加锁）。
class AudioHeadKernel {
public:
    // 构造：仅记录维度，不分配。
    // 默认参数与 PyTorch AudioHead 默认值一致（Llama-3B: hidden=3072, intermediate=1024,
    // num_codebooks=4, snac_vocab=4096, gpu_id=1）。
    AudioHeadKernel(int hidden_dim = 3072,
                    int intermediate_dim = 1024,
                    int num_codebooks = 4,
                    int snac_vocab_size = 4096,
                    int gpu_id = 1);

    // 析构：释放显存/句柄（CUDA 路径）。
    ~AudioHeadKernel();

    // 禁止拷贝（持有 GPU/大块资源，拷贝语义易出错）。
    AudioHeadKernel(const AudioHeadKernel&) = delete;
    AudioHeadKernel& operator=(const AudioHeadKernel&) = delete;

    // 从目录加载权重。
    // 必需文件：
    //   fc1.bin : FP16, shape [hidden_dim, intermediate_dim]（行主序）
    //   fc2.bin : FP16, shape [intermediate_dim, num_codebooks*snac_vocab_size]
    // 可选文件（存在则加 bias，与 PyTorch Linear.bias 对齐）：
    //   fc1_bias.bin : FP16, shape [intermediate_dim]
    //   fc2_bias.bin : FP16, shape [num_codebooks*snac_vocab_size]
    // CUDA 路径：pinned memory -> cudaMemcpy2Device；CPU 路径：存为 FP32 vector。
    void load_weights(const std::string& audio_head_dir);

    // 前向：就地计算首个 SNAC token。
    //   hidden_states_ptr : 指向 [batch, hidden_dim] 的输入。
    //                        dtype 由 is_fp16 入参指示（void* 以兼容 float/half）。
    //   batch             : batch size
    //   is_fp16           : 输入是否为 FP16（True=half，False=float32）
    //   out_tokens        : 输出缓冲，shape [batch * num_codebooks]，行主序
    //                       （out_tokens[b*num_codebooks + c] 为第 b 个样本第 c 个 codebook 的 token）
    void forward(const void* hidden_states_ptr, int batch, bool is_fp16,
                 int32_t* out_tokens);

    // 仅用于单测：返回内部是否已加载权重。
    bool weights_loaded() const { return weights_loaded_; }

    int hidden_dim() const { return hidden_dim_; }
    int intermediate_dim() const { return intermediate_dim_; }
    int num_codebooks() const { return num_codebooks_; }
    int snac_vocab_size() const { return snac_vocab_size_; }

private:
    int hidden_dim_;
    int intermediate_dim_;
    int num_codebooks_;
    int snac_vocab_size_;
    int gpu_id_;
    bool weights_loaded_;
    bool has_bias_;

    // ----------------------------------------------------------------------
    // CPU 回退路径的权重存储（FP32）。
    // 始终保留：即使 CUDA 路径也会先把权重读到这里（作为 pinned-memory 来源），
    // CPU 路径直接用它们做 matmul。存储布局与 .bin 一致（行主序）：
    //   fc1_host_[k*intermediate + j]   = W1[k][j]  (k in [0,hidden), j in [0,intermediate))
    //   fc2_host_[k*out_dim + j]        = W2[k][j]  (out_dim = num_codebooks*snac_vocab)
    //   bias1_host_[j], bias2_host_[j]
    // ----------------------------------------------------------------------
    std::vector<float> fc1_host_;   // [hidden_dim * intermediate_dim], FP32
    std::vector<float> fc2_host_;   // [intermediate_dim * (num_codebooks*snac_vocab_size)], FP32
    std::vector<float> bias1_host_; // [intermediate_dim] or empty
    std::vector<float> bias2_host_; // [num_codebooks*snac_vocab_size] or empty

    // CPU 路径前向实现（朴素 matmul + tanh 近似 GELU + argmax）。
    void forward_cpu(const void* hidden_states_ptr, int batch, bool is_fp16,
                     int32_t* out_tokens);

#ifdef HAVE_CUDA
    // CUDA 路径资源（仅 HAVE_CUDA 时存在）。
    void* fc1_dev_ = nullptr;       // device FP16 权重
    void* fc2_dev_ = nullptr;
    void* bias1_dev_ = nullptr;     // device FP16 bias（has_bias_ 时非空）
    void* bias2_dev_ = nullptr;
    bool cuda_initialized_ = false;

#ifdef HAVE_CUBLASLT
    cublasLtHandle_t cublaslt_handle_ = nullptr;
#else
    cublasHandle_t cublas_handle_ = nullptr;
#endif

    void forward_cuda(const void* hidden_states_ptr, int batch, bool is_fp16,
                      int32_t* out_tokens);
    void free_cuda_resources();
#endif
};

}  // namespace elp_orpheus

// ============================================================================
// C 风格接口：供 binding.cpp 调用，屏蔽 AudioHeadKernel 的构造细节。
// 用 C 接口的原因：binding.cpp 仅做 numpy<->C 桥接，不关心 kernel 内部状态；
// C 接口签名稳定，便于 FT 上游 decoding.cpp 直接链接调用（见 INTEGRATION_NOTES）。
//
// 返回：指向 out_tokens 缓冲的指针（调用方拥有，需 free）。
//      *out_num_codebooks 写入 num_codebooks（供 binding 构造输出 shape）。
//   返回 nullptr 表示失败。
// ============================================================================

#ifdef __cplusplus
extern "C" {
#endif

// 单次前向的 C 接口：内部会构造/复用 kernel。
// 注意：本接口为无状态单次调用版本（每次重新 load 权重开销大，仅供 binding 简化路径）。
// FT 上游应直接持有 AudioHeadKernel 实例复用（见 INTEGRATION_NOTES）。
int32_t* audio_head_forward(const void* hidden_states_ptr,
                            int batch,
                            int hidden_dim,
                            int intermediate_dim,
                            int num_codebooks,
                            int snac_vocab_size,
                            int gpu_id,
                            bool is_fp16,
                            const char* audio_head_dir,
                            int* out_num_codebooks);

#ifdef __cplusplus
}
#endif

#endif  // ELP_ORPHEUS_AUDIO_HEAD_KERNEL_H
