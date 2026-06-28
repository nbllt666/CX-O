// binding.cpp — pybind11 绑定，模块名 audio_head_cpp
//
// 设计决策：
//   1. GIL 管理：参考 scheduler/token_router.cpp 的风格——函数内部手动管理 GIL，
//      不用 py::call_guard<py::gil_scoped_release>。原因：request() 访问 numpy 数组、
//      构造 py::array_t 输出都需要持有 GIL；若用 call_guard 在整个函数体释放 GIL，
//      request()/数组构造会崩溃。故：持有 GIL 做 numpy 桥接，释放 GIL 做 matmul/argmax。
//   2. 输入 dtype 兼容：接收任意 numpy 数组（float32 / float16），用 buffer format
//      字符串判别（"f"=float32, "e"=float16/numpy half）。比 py::array_t<float> 模板派发
//      更灵活（pybind11 无原生 py::float16 类型）。
//   3. CPU 构建路径：当未定义 HAVE_CUDA 时，#include "audio_head_kernel.cu" 直接内联
//      实现（g++ 无法独立编译 .cu 扩展名）。CUDA 构建时由 nvcc 编译 .cu，binding.cpp
//      仅 include 头文件。
//
// 模块导出：
//   class AudioHeadCpp:
//       __init__(hidden_dim=3072, intermediate_dim=1024, num_codebooks=4,
//                snac_vocab_size=4096, gpu_id=1)
//       load_weights(dir: str) -> None
//       forward(hidden_states: np.ndarray) -> np.ndarray[int32]  shape [batch, num_codebooks]
//   audio_head_cpp_available() -> bool  （CPU 回退恒 True；CUDA 路径需 HAVE_CUDA）
//   HAS_CUDA: bool                （编译期是否启用 CUDA）

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

#include <cstdint>
#include <stdexcept>
#include <string>

#include "audio_head_kernel.h"

// CPU 回退构建：内联 .cu 实现（无 nvcc 时唯一编译入口）。
// CUDA 构建（nvcc + g++ 分别编译）不内联，避免重复定义。
#if !defined(HAVE_CUDA)
#include "audio_head_kernel.cu"
#endif

namespace py = pybind11;

namespace {

// 编译期是否启用 CUDA（供 Python 侧查询）。
constexpr bool kHasCuda =
#ifdef HAVE_CUDA
    true;
#else
    false;
#endif

}  // namespace

// ============================================================================
// AudioHeadCpp：AudioHeadKernel 的 pybind11 包装类。
// 持有一个 AudioHeadKernel 实例，复用其权重（避免每次 forward 重新 load）。
// ============================================================================
class AudioHeadCppBinding {
public:
    AudioHeadCppBinding(int hidden_dim, int intermediate_dim, int num_codebooks,
                       int snac_vocab_size, int gpu_id)
        : kernel_(hidden_dim, intermediate_dim, num_codebooks, snac_vocab_size, gpu_id) {}

    // 加载权重：释放 GIL 进行文件 IO + cudaMemcpy。
    void load_weights(const std::string& dir) {
        // dir 为 std::string（已从 py::str 拷贝），释放 GIL 安全。
        py::gil_scoped_release gil_release;
        kernel_.load_weights(dir);
    }

    // 前向：hidden_states [batch, hidden_dim] float32/float16 -> [batch, num_codebooks] int32。
    py::array_t<int32_t> forward(py::object hidden_states_obj) {
        // ---- 持有 GIL：numpy 桥接 ----
        // forcecast：非 C-contiguous 输入自动拷贝为连续（保证指针可直接读）。
        py::array hs = py::array::ensure(
            hidden_states_obj, py::array::c_style | py::array::forcecast);
        if (hs.ndim() != 2) {
            throw std::runtime_error(
                "AudioHeadCpp.forward: 期望输入 2D [batch, hidden_dim]，实际 ndim=" +
                std::to_string(hs.ndim()));
        }
        auto buf = hs.request();
        const int batch = static_cast<int>(buf.shape[0]);
        const int hidden = static_cast<int>(buf.shape[1]);
        if (hidden != kernel_.hidden_dim()) {
            throw std::runtime_error(
                "AudioHeadCpp.forward: 输入 hidden_dim=" + std::to_string(hidden) +
                " 与 kernel hidden_dim=" + std::to_string(kernel_.hidden_dim()) + " 不匹配");
        }

        // 判别输入 dtype（numpy buffer format 字符）。
        //   "f" = float32, "e" = float16, "d" = float64（暂不支持）。
        bool is_fp16 = false;
        if (buf.format == "e") {
            is_fp16 = true;
        } else if (buf.format == "f") {
            is_fp16 = false;
        } else {
            throw std::runtime_error(
                "AudioHeadCpp.forward: 仅支持 float32('f')/float16('e')，实际 format='" +
                buf.format + "'");
        }

        const void* data_ptr = buf.ptr;

        // ---- 持有 GIL：预分配输出数组（numpy 数组构造需 GIL）----
        const int num_codebooks = kernel_.num_codebooks();
        py::array_t<int32_t> out({batch, num_codebooks});
        auto out_buf = out.request();
        int32_t* out_ptr = static_cast<int32_t*>(out_buf.ptr);

        // ---- 释放 GIL：matmul + GELU + argmax（纯 C++/CUDA，不碰 Python 对象）----
        // hs / out 的 numpy 缓冲在函数作用域内有效，data_ptr/out_ptr 在释放 GIL 期间稳定。
        {
            py::gil_scoped_release gil_release;
            kernel_.forward(data_ptr, batch, is_fp16, out_ptr);
        }
        // gil_release 析构重新持有 GIL，安全返回 py::array。
        return out;
    }

    int num_codebooks() const { return kernel_.num_codebooks(); }
    int hidden_dim() const { return kernel_.hidden_dim(); }
    int intermediate_dim() const { return kernel_.intermediate_dim(); }
    int snac_vocab_size() const { return kernel_.snac_vocab_size(); }
    bool weights_loaded() const { return kernel_.weights_loaded(); }

private:
    elp_orpheus::AudioHeadKernel kernel_;
};

PYBIND11_MODULE(audio_head_cpp, m) {
    m.doc() = "Audio Head C++/CUDA operator for ELP-Orpheus "
              "(CPU fallback + optional CUDA).";

    py::class_<AudioHeadCppBinding>(m, "AudioHeadCpp")
        .def(py::init<int, int, int, int, int>(),
             py::arg("hidden_dim") = 3072,
             py::arg("intermediate_dim") = 1024,
             py::arg("num_codebooks") = 4,
             py::arg("snac_vocab_size") = 4096,
             py::arg("gpu_id") = 1)
        // load_weights / forward：函数内部手动管理 GIL
        // （持有 GIL 访问 numpy 数组，释放 GIL 做 matmul/argmax）。
        // 不能用 call_guard<gil_scoped_release>：那会在整个函数体释放 GIL，
        // 导致 request() 与 py::array_t 构造崩溃（参考 token_router.cpp）。
        .def("load_weights", &AudioHeadCppBinding::load_weights, py::arg("dir"))
        .def("forward", &AudioHeadCppBinding::forward, py::arg("hidden_states"))
        .def_property_readonly("num_codebooks", &AudioHeadCppBinding::num_codebooks)
        .def_property_readonly("hidden_dim", &AudioHeadCppBinding::hidden_dim)
        .def_property_readonly("intermediate_dim", &AudioHeadCppBinding::intermediate_dim)
        .def_property_readonly("snac_vocab_size", &AudioHeadCppBinding::snac_vocab_size)
        .def_property_readonly("weights_loaded", &AudioHeadCppBinding::weights_loaded);

    // audio_head_cpp_available：CPU 回退恒 True（总有纯 C++ 路径）；
    // CUDA 路径需 #ifdef HAVE_CUDA，Python 侧据此选择是否期望 GPU 加速。
    m.def("audio_head_cpp_available", []() -> bool { return true; },
          "返回 audio_head_cpp 模块是否可用（CPU 回退恒为 True）。");

    // 编译期常量：是否启用了 CUDA 路径。
    m.attr("HAS_CUDA") = py::bool_(kHasCuda);
}
