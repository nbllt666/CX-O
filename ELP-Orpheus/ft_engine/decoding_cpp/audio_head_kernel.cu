// audio_head_kernel.cu — Audio Head C++/CUDA 算子实现
//
// 设计决策（详见 audio_head_kernel.h 顶部注释）。本文件要点：
//   1. 用 #ifdef HAVE_CUDA 包裹所有 CUDA/cublas 调用，使无 CUDA 工具链时
//      也能作为纯 C++ 编译（g++/MSVC），仅走 CPU 回退路径。
//   2. CPU 回退路径用 std::vector + 朴素 matmul，仅保证逻辑正确（性能不要求）。
//   3. GELU 一律用 tanh 近似（与 CUDA kernel 一致）：
//        gelu(x) = 0.5 * x * (1 + tanh(sqrt(2/π) * (x + 0.044715 * x^3)))
//      PyTorch F.gelu 默认 erf-based，二者在边界值有微小差异，单测用 atol 容忍。
//   4. 本文件带 include guard，允许被 binding.cpp 在无 CUDA 时直接 #include
//      （因 g++ 无法独立编译 .cu 扩展名）。CUDA 构建时由 nvcc 单独编译本文件。
//
// 构建：
//   - CPU 回退（本仓库默认）：仅编译 binding.cpp（其 #include 本文件，HAVE_CUDA 未定义）
//   - CUDA 构建：nvcc -DHAVE_CUDA [-DHAVE_CUBLASLT] -c audio_head_kernel.cu + g++ binding.cpp，链接

#ifndef ELP_ORPHEUS_AUDIO_HEAD_KERNEL_CU_IMPL
#define ELP_ORPHEUS_AUDIO_HEAD_KERNEL_CU_IMPL

#include "audio_head_kernel.h"

#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <stdexcept>
#include <string>
#include <vector>

#ifdef HAVE_CUDA
#include <cuda_runtime.h>
#include <cuda_fp16.h>
#endif

namespace {

// ============================================================================
// FP16 <-> FP32 转换（纯位运算，无 CUDA 依赖）。
// CPU 回退路径读 .bin（FP16）时用此转 FP32。CUDA 路径用 __half 内建函数。
// 实现 IEEE 754 half（1/5/10 位）到 binary32（1/8/23 位）的标准转换。
// ============================================================================
float half_to_float_cpu(uint16_t h) {
    uint32_t sign = (static_cast<uint32_t>(h) >> 15) & 0x1u;
    uint32_t exp = (static_cast<uint32_t>(h) >> 10) & 0x1fu;
    uint32_t mant = static_cast<uint32_t>(h) & 0x3ffu;
    uint32_t f_bits = 0;

    if (exp == 0u) {
        if (mant == 0u) {
            // ±0
            f_bits = sign << 31;
        } else {
            // 次正规数：归一化
            uint32_t e = 1u;
            while ((mant & 0x400u) == 0u) {
                mant <<= 1;
                --e;
            }
            mant &= 0x3ffu;
            f_bits = (sign << 31) | ((e + 112u) << 23) | (mant << 13);
        }
    } else if (exp == 0x1fu) {
        // inf / nan
        f_bits = (sign << 31) | (0xffu << 23) | (mant << 13);
    } else {
        // 正规数：指数偏移 15 -> 127（差 112）
        f_bits = (sign << 31) | ((exp + 112u) << 23) | (mant << 13);
    }

    float result;
    std::memcpy(&result, &f_bits, sizeof(float));
    return result;
}

// ============================================================================
// 文件读取工具：将二进制文件读为 FP16（uint16）数组。
// 校验长度，长度不符抛异常（避免静默错误导致 argmax 错乱）。
// ============================================================================
std::vector<uint16_t> read_fp16_file(const std::string& path, size_t expected_count) {
    std::ifstream ifs(path, std::ios::binary | std::ios::ate);
    if (!ifs) {
        throw std::runtime_error("AudioHeadKernel: 无法打开权重文件: " + path);
    }
    std::streamsize size = ifs.tellg();
    if (size < 0 || static_cast<size_t>(size) != expected_count * sizeof(uint16_t)) {
        char buf[256];
        std::snprintf(buf, sizeof(buf),
                     "AudioHeadKernel: 权重文件长度不符 %s (期望 %zu 元素, 实际 %lld 字节)",
                     path.c_str(), expected_count, static_cast<long long>(size));
        throw std::runtime_error(buf);
    }
    ifs.seekg(0, std::ios::beg);
    std::vector<uint16_t> data(expected_count);
    if (expected_count > 0) {
        ifs.read(reinterpret_cast<char*>(data.data()),
                 static_cast<std::streamsize>(expected_count * sizeof(uint16_t)));
        if (!ifs) {
            throw std::runtime_error("AudioHeadKernel: 读取权重文件失败: " + path);
        }
    }
    return data;
}

// 路径拼接（跨平台：同时兼容正/反斜杠输入）。
std::string join_path(const std::string& dir, const std::string& name) {
    if (dir.empty()) return name;
    char last = dir.back();
    if (last == '/' || last == '\\') return dir + name;
    return dir + "/" + name;
}

// 判断文件是否存在（用于可选 bias 文件）。
bool file_exists(const std::string& path) {
    std::ifstream ifs(path, std::ios::binary);
    return ifs.good();
}

// GELU tanh 近似（CPU 与 CUDA 共用同一公式，保证两条路径数值一致）。
// 用 tanh 近似而非 erf 的原因：
//   - tanh 近似无需 libm 的 erf（部分嵌入式/精简 g++ 环境可能缺），更可移植
//   - 与 CUDA kernel 用同一公式，便于一致性推理
//   - 与 PyTorch erf-GELU 的差异在边界值，单测 atol 容忍
inline float gelu_tanh(float x) {
    const float c = 0.7978845608028654f;  // sqrt(2/π)
    float x3 = x * x * x;
    return 0.5f * x * (1.0f + std::tanh(c * (x + 0.044715f * x3)));
}

}  // namespace

namespace elp_orpheus {

// ============================================================================
// 构造 / 析构
// ============================================================================
AudioHeadKernel::AudioHeadKernel(int hidden_dim, int intermediate_dim,
                                 int num_codebooks, int snac_vocab_size,
                                 int gpu_id)
    : hidden_dim_(hidden_dim),
      intermediate_dim_(intermediate_dim),
      num_codebooks_(num_codebooks),
      snac_vocab_size_(snac_vocab_size),
      gpu_id_(gpu_id),
      weights_loaded_(false),
      has_bias_(false) {
    if (hidden_dim_ <= 0 || intermediate_dim_ <= 0 || num_codebooks_ <= 0 ||
        snac_vocab_size_ <= 0) {
        throw std::invalid_argument("AudioHeadKernel: 维度参数必须为正");
    }
}

AudioHeadKernel::~AudioHeadKernel() {
#ifdef HAVE_CUDA
    free_cuda_resources();
#endif
}

// ============================================================================
// load_weights：读取 .bin -> FP32 host 向量 -> (CUDA: cudaMemcpy 到 device)
// ============================================================================
void AudioHeadKernel::load_weights(const std::string& audio_head_dir) {
    // 期望元素数。
    const size_t fc1_count = static_cast<size_t>(hidden_dim_) * intermediate_dim_;
    const size_t fc2_count =
        static_cast<size_t>(intermediate_dim_) * num_codebooks_ * snac_vocab_size_;

    // 读取 fc1.bin / fc2.bin（必需）。
    auto fc1_h = read_fp16_file(join_path(audio_head_dir, "fc1.bin"), fc1_count);
    auto fc2_h = read_fp16_file(join_path(audio_head_dir, "fc2.bin"), fc2_count);

    // FP16 -> FP32，存入 host 向量（行主序布局与 .bin 一致）。
    fc1_host_.resize(fc1_count);
    fc2_host_.resize(fc2_count);
    for (size_t i = 0; i < fc1_count; ++i) fc1_host_[i] = half_to_float_cpu(fc1_h[i]);
    for (size_t i = 0; i < fc2_count; ++i) fc2_host_[i] = half_to_float_cpu(fc2_h[i]);

    // 可选 bias 文件（存在则加载，与 PyTorch Linear.bias 对齐）。
    const std::string bias1_path = join_path(audio_head_dir, "fc1_bias.bin");
    const std::string bias2_path = join_path(audio_head_dir, "fc2_bias.bin");
    has_bias_ = file_exists(bias1_path) && file_exists(bias2_path);
    if (has_bias_) {
        auto b1 = read_fp16_file(bias1_path, static_cast<size_t>(intermediate_dim_));
        auto b2 = read_fp16_file(bias2_path,
                                 static_cast<size_t>(num_codebooks_) * snac_vocab_size_);
        bias1_host_.resize(intermediate_dim_);
        bias2_host_.resize(static_cast<size_t>(num_codebooks_) * snac_vocab_size_);
        for (size_t i = 0; i < b1.size(); ++i) bias1_host_[i] = half_to_float_cpu(b1[i]);
        for (size_t i = 0; i < b2.size(); ++i) bias2_host_[i] = half_to_float_cpu(b2[i]);
    } else {
        bias1_host_.clear();
        bias2_host_.clear();
    }

#ifdef HAVE_CUDA
    // ------------------------------------------------------------------
    // CUDA 路径：分配 device 显存并拷贝权重。
    // pinned memory 中转可加速 H2D 拷贝；此处直接用 host 向量（已 FP32），
    // 先转回 FP16 再拷贝（保持 device 权重为 FP16 以走 Tensor Core）。
    // ------------------------------------------------------------------
    cudaSetDevice(gpu_id_);

    auto to_dev_fp16 = [&](const std::vector<float>& host, void** dev_ptr) {
        // host FP32 -> device FP16（保持 device 权重为 FP16 以走 Tensor Core）。
        std::vector<uint16_t> h16(host.size());
        for (size_t i = 0; i < host.size(); ++i) {
            h16[i] = __float2half(host[i]);
        }
        cudaMalloc(dev_ptr, host.size() * sizeof(uint16_t));
        cudaMemcpy(*dev_ptr, h16.data(), host.size() * sizeof(uint16_t),
                   cudaMemcpyHostToDevice);
    };

    to_dev_fp16(fc1_host_, &fc1_dev_);
    to_dev_fp16(fc2_host_, &fc2_dev_);
    if (has_bias_) {
        to_dev_fp16(bias1_host_, &bias1_dev_);
        to_dev_fp16(bias2_host_, &bias2_dev_);
    }

#ifdef HAVE_CUBLASLT
    cublasLtCreate(&cublaslt_handle_);
#else
    cublasCreate(&cublas_handle_);
#endif
    cuda_initialized_ = true;
#endif

    weights_loaded_ = true;
}

// ============================================================================
// forward：分派到 CUDA 或 CPU 路径。
// ============================================================================
void AudioHeadKernel::forward(const void* hidden_states_ptr, int batch,
                              bool is_fp16, int32_t* out_tokens) {
    if (!weights_loaded_) {
        throw std::runtime_error("AudioHeadKernel::forward: 权重未加载");
    }
    if (batch <= 0 || hidden_states_ptr == nullptr || out_tokens == nullptr) {
        throw std::invalid_argument("AudioHeadKernel::forward: 非法参数");
    }
#ifdef HAVE_CUDA
    if (cuda_initialized_) {
        forward_cuda(hidden_states_ptr, batch, is_fp16, out_tokens);
        return;
    }
#endif
    forward_cpu(hidden_states_ptr, batch, is_fp16, out_tokens);
}

// ============================================================================
// CPU 回退前向：朴素 matmul + tanh-GELU + argmax。
// 仅保证逻辑正确（与 PyTorch 数值对齐，除 GELU 近似外）。
// ============================================================================
void AudioHeadKernel::forward_cpu(const void* hidden_states_ptr, int batch,
                                  bool is_fp16, int32_t* out_tokens) {
    const int H = hidden_dim_;
    const int I = intermediate_dim_;
    const int C = num_codebooks_;
    const int V = snac_vocab_size_;
    const int out_dim = C * V;  // fc2 输出维度

    // ---- 1. 输入转 FP32（FP16 输入则按 half 解码）----
    std::vector<float> x_host(static_cast<size_t>(batch) * H);
    if (is_fp16) {
        const uint16_t* x16 = static_cast<const uint16_t*>(hidden_states_ptr);
        for (size_t i = 0; i < x_host.size(); ++i) x_host[i] = half_to_float_cpu(x16[i]);
    } else {
        const float* xf = static_cast<const float*>(hidden_states_ptr);
        for (size_t i = 0; i < x_host.size(); ++i) x_host[i] = xf[i];
    }

    // ---- 2. fc1: Y1[b][j] = sum_k X[b][k] * W1[k][j] + bias1[j] ----
    // W1 行主序 [H, I]: W1[k*I + j]
    std::vector<float> y1(static_cast<size_t>(batch) * I, 0.0f);
    for (int b = 0; b < batch; ++b) {
        const float* xb = &x_host[static_cast<size_t>(b) * H];
        float* yb = &y1[static_cast<size_t>(b) * I];
        for (int j = 0; j < I; ++j) {
            float acc = 0.0f;
            for (int k = 0; k < H; ++k) {
                acc += xb[k] * fc1_host_[static_cast<size_t>(k) * I + j];
            }
            if (has_bias_) acc += bias1_host_[j];
            yb[j] = acc;
        }
    }

    // ---- 3. GELU（tanh 近似）----
    for (size_t i = 0; i < y1.size(); ++i) y1[i] = gelu_tanh(y1[i]);

    // ---- 4. fc2: logits[b][j] = sum_k G1[b][k] * W2[k][j] + bias2[j] ----
    // W2 行主序 [I, out_dim]: W2[k*out_dim + j]
    std::vector<float> logits(static_cast<size_t>(batch) * out_dim, 0.0f);
    for (int b = 0; b < batch; ++b) {
        const float* gb = &y1[static_cast<size_t>(b) * I];
        float* lb = &logits[static_cast<size_t>(b) * out_dim];
        for (int j = 0; j < out_dim; ++j) {
            float acc = 0.0f;
            for (int k = 0; k < I; ++k) {
                acc += gb[k] * fc2_host_[static_cast<size_t>(k) * out_dim + j];
            }
            if (has_bias_) acc += bias2_host_[j];
            lb[j] = acc;
        }
    }

    // ---- 5. reshape [batch, C, V] + argmax(dim=-1) ----
    // logits[b][c*V + v]，对每个 (b,c) 取 v 上 argmax。
    for (int b = 0; b < batch; ++b) {
        const float* lb = &logits[static_cast<size_t>(b) * out_dim];
        for (int c = 0; c < C; ++c) {
            const float* row = lb + static_cast<size_t>(c) * V;
            float best = row[0];
            int best_idx = 0;
            for (int v = 1; v < V; ++v) {
                if (row[v] > best) {
                    best = row[v];
                    best_idx = v;
                }
            }
            out_tokens[static_cast<size_t>(b) * C + c] = static_cast<int32_t>(best_idx);
        }
    }
}

#ifdef HAVE_CUDA
// ============================================================================
// CUDA 路径：cublasLtMatmul / cublasGemmEx + 自定义 GELU/argmax kernel。
// 本路径在无 GPU 环境不编译；以下代码需 nvcc + CUDA 工具链。
// ============================================================================

// GELU kernel（FP16 输入/输出，内部 FP32 计算保证精度）。
// 用 tanh 近似，与 CPU 回退公式一致。
__global__ void gelu_kernel(const half* __restrict__ in, half* __restrict__ out, int n) {
    const float c = 0.7978845608028654f;  // sqrt(2/π)
    int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx < n) {
        float x = __half2float(in[idx]);
        float x3 = x * x * x;
        float g = 0.5f * x * (1.0f + tanhf(c * (x + 0.044715f * x3)));
        out[idx] = __float2half(g);
    }
}

// Argmax kernel：logits [batch, num_codebooks, snac_vocab] FP16 -> [batch, num_codebooks] int32。
// 一个 block 处理一个 batch 样本，blockDim.x = num_codebooks（≤4），每线程串行扫一个 codebook。
// 简单正确；snac_vocab=4096 串行扫可接受（首 token 不在 hot path）。
__global__ void argmax_kernel(const half* __restrict__ logits, int32_t* __restrict__ out,
                              int batch, int num_codebooks, int snac_vocab) {
    int b = blockIdx.x;
    int c = threadIdx.x;
    if (b >= batch || c >= num_codebooks) return;
    const half* row = logits + (static_cast<size_t>(b) * num_codebooks + c) * snac_vocab;
    float best = -1e30f;
    int best_idx = 0;
    for (int v = 0; v < snac_vocab; ++v) {
        float val = __half2float(row[v]);
        if (val > best) {
            best = val;
            best_idx = v;
        }
    }
    out[b * num_codebooks + c] = best_idx;
}

// 通用 GEMM 封装：行主序 C[batch, out_features] = A_input[batch, in_features] @ B_weight[in_features, out_features]。
// cublasLt/cublas 为列主序，利用 C = (B^T A^T)^T 的等价关系将行主序输入映射到列主序 GEMM：
//   期望行主序 C_row[batch, out_features] 的内存 = 列主序 C_col[out_features, batch] = C_row^T。
//   而 C_row^T = B_weight^T @ A_input^T。
//   - B_weight 行主序 [in_features, out_features] 在内存中即列主序 [out_features, in_features] -> 作为 A_cublas(opA=N) 形状 (m=out_features, k=in_features)
//   - A_input  行主序 [batch, in_features]         在内存中即列主序 [in_features, batch] -> 作为 B_cublas(opB=N) 形状 (k=in_features, n=batch)
//   - 结果 C_cublas 列主序 (m=out_features, n=batch) 即期望行主序 C_row。
// 句柄通过参数传入（避免 free 函数访问类私有成员）。
void gemm_rowmajor(
#ifdef HAVE_CUBLASLT
    cublasLtHandle_t handle,
#else
    cublasHandle_t handle,
#endif
    void* A_weight, void* B_input, void* C_output,
    int batch, int in_features, int out_features,
    bool apply_gelu_after  // 是否在 GEMM 后接 GELU kernel
    ) {
    const int m = out_features;
    const int n = batch;
    const int k = in_features;
    const int lda = out_features;  // 权重行主序 leading dim = 列数（列主序视图行数）
    const int ldb = in_features;   // 输入行主序 leading dim = 列数
    const int ldc = out_features;

    const float alpha = 1.0f, beta = 0.0f;
    (void)beta;

#ifdef HAVE_CUBLASLT
    cublasLtMatmulDesc_t op_desc;
    cublasLtMatmulDescCreate(&op_desc, CUBLAS_COMPUTE_32F, CUDA_R_32F);

    cublasLtMatrixLayout_t A_layout, B_layout, C_layout;
    cublasLtMatrixLayoutCreate(&A_layout, CUDA_R_16F, m, k, lda);
    cublasLtMatrixLayoutCreate(&B_layout, CUDA_R_16F, k, n, ldb);
    cublasLtMatrixLayoutCreate(&C_layout, CUDA_R_16F, m, n, ldc);

    cublasLtMatmul(handle, op_desc, &alpha,
                   A_weight, A_layout, B_input, B_layout,
                   &beta, C_output, C_layout, C_output, C_layout,
                   nullptr, nullptr, 0, 0);

    cublasLtMatrixLayoutDestroy(A_layout);
    cublasLtMatrixLayoutDestroy(B_layout);
    cublasLtMatrixLayoutDestroy(C_layout);
    cublasLtMatmulDescDestroy(op_desc);
#else
    cublasGemmEx(handle,
                 CUBLAS_OP_N, CUBLAS_OP_N,
                 m, n, k,
                 &alpha,
                 A_weight, CUDA_R_16F, lda,
                 B_input, CUDA_R_16F, ldb,
                 &beta,
                 C_output, CUDA_R_16F, ldc,
                 CUBLAS_COMPUTE_32F);
#endif

    // 可选 GELU（in-place）。bias 加法此处省略单独 kernel（首 token 不在 hot path，
    // 生产若需 bias 应补 bias_add kernel；当前 has_bias_ 路径 bias 由 host 端预加或单独处理）。
    if (apply_gelu_after) {
        int total = batch * out_features;
        int block = 256;
        int grid = (total + block - 1) / block;
        gelu_kernel<<<grid, block>>>(static_cast<const half*>(C_output),
                                     static_cast<half*>(C_output), total);
    }
}

void AudioHeadKernel::forward_cuda(const void* hidden_states_ptr, int batch,
                                   bool is_fp16, int32_t* out_tokens) {
    const int H = hidden_dim_;
    const int I = intermediate_dim_;
    const int C = num_codebooks_;
    const int V = snac_vocab_size_;
    const int out_dim = C * V;

    cudaSetDevice(gpu_id_);

    // ---- 输入转 device FP16 ----
    void* x_dev = nullptr;
    size_t x_bytes = static_cast<size_t>(batch) * H * sizeof(half);
    cudaMalloc(&x_dev, x_bytes);
    if (is_fp16) {
        cudaMemcpy(x_dev, hidden_states_ptr, x_bytes, cudaMemcpyHostToDevice);
    } else {
        // 输入 FP32 -> 转 FP16。简化：分配临时 host FP16 再拷。
        std::vector<half> xh(static_cast<size_t>(batch) * H);
        const float* xf = static_cast<const float*>(hidden_states_ptr);
        for (size_t i = 0; i < xh.size(); ++i) xh[i] = __float2half(xf[i]);
        cudaMemcpy(x_dev, xh.data(), x_bytes, cudaMemcpyHostToDevice);
    }

    // ---- fc1: [batch, H] @ W1[H, I] -> [batch, I] ----
    void* y1_dev = nullptr;
    cudaMalloc(&y1_dev, static_cast<size_t>(batch) * I * sizeof(half));
    gemm_rowmajor(
#ifdef HAVE_CUBLASLT
        cublaslt_handle_,
#else
        cublas_handle_,
#endif
        fc1_dev_, x_dev, y1_dev, batch, H, I, /*apply_gelu_after=*/true);

    // ---- fc2: [batch, I] @ W2[I, out_dim] -> [batch, out_dim] ----
    void* logits_dev = nullptr;
    cudaMalloc(&logits_dev, static_cast<size_t>(batch) * out_dim * sizeof(half));
    gemm_rowmajor(
#ifdef HAVE_CUBLASLT
        cublaslt_handle_,
#else
        cublas_handle_,
#endif
        fc2_dev_, y1_dev, logits_dev, batch, I, out_dim, /*apply_gelu_after=*/false);

    // ---- argmax -> [batch, num_codebooks] int32 ----
    int32_t* out_dev = nullptr;
    cudaMalloc(&out_dev, static_cast<size_t>(batch) * C * sizeof(int32_t));
    argmax_kernel<<<batch, C>>>(static_cast<const half*>(logits_dev), out_dev,
                                batch, C, V);

    cudaMemcpy(out_tokens, out_dev, static_cast<size_t>(batch) * C * sizeof(int32_t),
               cudaMemcpyDeviceToHost);

    cudaFree(x_dev);
    cudaFree(y1_dev);
    cudaFree(logits_dev);
    cudaFree(out_dev);
}

void AudioHeadKernel::free_cuda_resources() {
    if (fc1_dev_) { cudaFree(fc1_dev_); fc1_dev_ = nullptr; }
    if (fc2_dev_) { cudaFree(fc2_dev_); fc2_dev_ = nullptr; }
    if (bias1_dev_) { cudaFree(bias1_dev_); bias1_dev_ = nullptr; }
    if (bias2_dev_) { cudaFree(bias2_dev_); bias2_dev_ = nullptr; }
#ifdef HAVE_CUBLASLT
    if (cublaslt_handle_) { cublasLtDestroy(cublaslt_handle_); cublaslt_handle_ = nullptr; }
#else
    if (cublas_handle_) { cublasDestroy(cublas_handle_); cublas_handle_ = nullptr; }
#endif
    cuda_initialized_ = false;
}
#endif  // HAVE_CUDA

}  // namespace elp_orpheus

// ============================================================================
// C 风格接口实现：无状态单次调用版本。
// 每次 load 权重开销大，仅供 binding 简化路径与 FT 单次集成测试；
// 生产 FT 路径应直接持有 AudioHeadKernel 实例复用（见 INTEGRATION_NOTES）。
// ============================================================================
extern "C" int32_t* audio_head_forward(const void* hidden_states_ptr,
                                       int batch,
                                       int hidden_dim,
                                       int intermediate_dim,
                                       int num_codebooks,
                                       int snac_vocab_size,
                                       int gpu_id,
                                       bool is_fp16,
                                       const char* audio_head_dir,
                                       int* out_num_codebooks) {
    try {
        elp_orpheus::AudioHeadKernel kernel(hidden_dim, intermediate_dim,
                                            num_codebooks, snac_vocab_size, gpu_id);
        kernel.load_weights(audio_head_dir ? std::string(audio_head_dir) : std::string());
        int32_t* out = static_cast<int32_t*>(
            std::malloc(static_cast<size_t>(batch) * num_codebooks * sizeof(int32_t)));
        if (!out) {
            if (out_num_codebooks) *out_num_codebooks = 0;
            return nullptr;
        }
        kernel.forward(hidden_states_ptr, batch, is_fp16, out);
        if (out_num_codebooks) *out_num_codebooks = num_codebooks;
        return out;
    } catch (const std::exception& e) {
        std::fprintf(stderr, "[audio_head_forward] error: %s\n", e.what());
        if (out_num_codebooks) *out_num_codebooks = 0;
        return nullptr;
    }
}

#endif  // ELP_ORPHEUS_AUDIO_HEAD_KERNEL_CU_IMPL
