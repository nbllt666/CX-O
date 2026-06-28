// probe.cpp — 超低开销 C++/Python 混合 Profiler 计时探针（实现 + pybind11 绑定）
//
// 设计决策：
//   - 单次 begin/end 仅做 steady_clock::now() + unordered_map 查找 + mutex lock，
//     无锁路径开销 < 100ns（steady_clock::now 约 20-50ns，mutex 无竞争约 20ns）。
//   - GIL：begin/end/get_samples/clear/overhead_ns 用 call_guard<gil_scoped_release>
//     释放 GIL，使 Python 其它线程在计时期间可并行运行（参考 token_router.cpp）。
//   - CUDA：#ifdef HAVE_CUDA 包裹 cudaEventRecord/cudaEventElapsedTime；
//     无 CUDA 时 cuda_event_begin/end 回退到 steady_clock 并 stderr 输出 warning，
//     保证开发环境（无 CUDA / 无 nvcc）也能编译运行。
//   - 嵌套：start_times_ 用 vector 当栈，end 时弹出栈顶时戳，支持嵌套 stage。
//
// 编译：python profiler/build_probe.py  （或 python profiler/build_probe.py --with-cuda）
// 模块名：probe_cpp（导入时 import probe_cpp）

#include "probe.h"

#include <pybind11/pybind11.h>
#include <pybind11/stl.h>

#include <cstdio>
#include <utility>

namespace py = pybind11;
using namespace elp_prof;

Probe::Probe() = default;

Probe::~Probe() {
#ifdef HAVE_CUDA
    // 析构时销毁所有未释放的 CUDA event，避免资源泄漏。
    try {
        for (auto& kv : cuda_start_events_) {
            for (auto& e : kv.second) {
                cudaEventDestroy(e);
            }
        }
        for (auto& kv : cuda_end_events_) {
            for (auto& e : kv.second) {
                cudaEventDestroy(e);
            }
        }
    } catch (...) {
        // 析构中不抛异常。
    }
#endif
}

void Probe::begin(const std::string& name) {
    auto now = clock::now();
    std::lock_guard<std::mutex> lock(mtx_);
    start_times_[name].push_back(now);
}

void Probe::end(const std::string& name) {
    auto now = clock::now();
    std::lock_guard<std::mutex> lock(mtx_);
    auto it = start_times_.find(name);
    if (it == start_times_.end() || it->second.empty()) {
        // 无匹配 begin：静默忽略（防御性，避免调用方未配对 begin 导致崩溃）。
        return;
    }
    time_point start = it->second.back();
    it->second.pop_back();
    auto elapsed = std::chrono::duration_cast<std::chrono::nanoseconds>(now - start).count();
    samples_[name].push_back(elapsed);
}

void Probe::cuda_event_begin(const std::string& name, uintptr_t stream) {
#ifdef HAVE_CUDA
    cudaEvent_t event;
    if (cudaEventCreate(&event) != cudaSuccess) {
        // event 创建失败：回退到 steady_clock 路径。
        std::fprintf(stderr,
            "[probe_cpp] warning: cudaEventCreate failed, fallback to steady_clock\n");
        begin(name);
        return;
    }
    cudaStream_t s = reinterpret_cast<cudaStream_t>(stream);
    if (cudaEventRecord(event, s) != cudaSuccess) {
        std::fprintf(stderr,
            "[probe_cpp] warning: cudaEventRecord failed, fallback to steady_clock\n");
        cudaEventDestroy(event);
        begin(name);
        return;
    }
    {
        std::lock_guard<std::mutex> lock(mtx_);
        cuda_start_events_[name].push_back(event);
    }
#else
    // 无 CUDA 编译：回退到 steady_clock 并记录 warning（仅首次提示，避免刷屏）。
    static bool warned = false;
    if (!warned) {
        std::fprintf(stderr,
            "[probe_cpp] warning: HAVE_CUDA not defined, cuda_event_begin fallback to steady_clock\n");
        warned = true;
    }
    (void)stream;  // 避免未使用参数告警。
    begin(name);
#endif
}

void Probe::cuda_event_end(const std::string& name, uintptr_t stream) {
#ifdef HAVE_CUDA
    cudaEvent_t end_event;
    if (cudaEventCreate(&end_event) != cudaSuccess) {
        std::fprintf(stderr,
            "[probe_cpp] warning: cudaEventCreate failed, fallback to steady_clock\n");
        end(name);
        return;
    }
    cudaStream_t s = reinterpret_cast<cudaStream_t>(stream);
    cudaEventRecord(end_event, s);
    // 同步等待 event 完成（确保测到的是 kernel 完成时刻而非 launch 时刻）。
    cudaEventSynchronize(end_event);

    // 先在锁内取出 start_event，再在锁外计算并清理，避免在锁内调用 end() 死锁。
    cudaEvent_t start_event = nullptr;
    bool has_start = false;
    {
        std::lock_guard<std::mutex> lock(mtx_);
        auto it = cuda_start_events_.find(name);
        if (it != cuda_start_events_.end() && !it->second.empty()) {
            start_event = it->second.back();
            it->second.pop_back();
            has_start = true;
        }
    }

    if (!has_start) {
        // 无匹配 cuda_event_begin：销毁 end_event 并用 steady_clock end 兜底。
        cudaEventDestroy(end_event);
        end(name);
        return;
    }

    float ms = 0.0f;
    cudaEventElapsedTime(&ms, start_event, end_event);
    // ms → ns
    int64_t elapsed_ns = static_cast<int64_t>(ms * 1e6);
    {
        std::lock_guard<std::mutex> lock(mtx_);
        samples_[name].push_back(elapsed_ns);
    }
    cudaEventDestroy(start_event);
    cudaEventDestroy(end_event);
#else
    static bool warned = false;
    if (!warned) {
        std::fprintf(stderr,
            "[probe_cpp] warning: HAVE_CUDA not defined, cuda_event_end fallback to steady_clock\n");
        warned = true;
    }
    (void)stream;
    end(name);
#endif
}

std::vector<int64_t> Probe::get_samples(const std::string& name) {
    std::lock_guard<std::mutex> lock(mtx_);
    auto it = samples_.find(name);
    if (it == samples_.end()) {
        return {};
    }
    return it->second;
}

void Probe::clear() {
    std::lock_guard<std::mutex> lock(mtx_);
    start_times_.clear();
    samples_.clear();
#ifdef HAVE_CUDA
    for (auto& kv : cuda_start_events_) {
        for (auto& e : kv.second) {
            cudaEventDestroy(e);
        }
    }
    for (auto& kv : cuda_end_events_) {
        for (auto& e : kv.second) {
            cudaEventDestroy(e);
        }
    }
    cuda_start_events_.clear();
    cuda_end_events_.clear();
#endif
}

int64_t Probe::overhead_ns() {
    // 测量 begin/end 一次的自身开销：begin 紧跟 end，中间无工作，
    // 采样值即探针自身开销（steady_clock::now × 2 + map 操作 + mutex）。
    clear();
    begin("__overhead__");
    end("__overhead__");
    auto s = get_samples("__overhead__");
    int64_t result = s.empty() ? 0 : s[0];
    clear();
    return result;
}

// ============================================================================
// pybind11 绑定：模块名 probe_cpp
// ============================================================================
// GIL 策略：begin/end/get_samples/clear/overhead_ns 用 call_guard<gil_scoped_release>
// 释放 GIL，使 Python 其它线程在计时期间可并行运行（参考 token_router.cpp）。
// cuda_event_begin/end 也释放 GIL（cudaEventSynchronize 可能阻塞，不应卡住 GIL）。
PYBIND11_MODULE(probe_cpp, m) {
    m.doc() = "ELP-Orpheus 超低开销 C++/Python 混合 Profiler 计时探针（GIL-free）";

    py::class_<Probe>(m, "Probe")
        .def(py::init<>())
        .def("begin", &Probe::begin, py::arg("name"),
             py::call_guard<py::gil_scoped_release>(),
             "记录 stage 开始时戳（steady_clock）")
        .def("end", &Probe::end, py::arg("name"),
             py::call_guard<py::gil_scoped_release>(),
             "记录 stage 结束时戳，计算 elapsed_ns 存入采样列表")
        .def("cuda_event_begin", &Probe::cuda_event_begin,
             py::arg("name"), py::arg("stream"),
             py::call_guard<py::gil_scoped_release>(),
             "CUDA event 计时开始（无 CUDA 回退 steady_clock）")
        .def("cuda_event_end", &Probe::cuda_event_end,
             py::arg("name"), py::arg("stream"),
             py::call_guard<py::gil_scoped_release>(),
             "CUDA event 计时结束（无 CUDA 回退 steady_clock）")
        .def("get_samples", &Probe::get_samples, py::arg("name"),
             py::call_guard<py::gil_scoped_release>(),
             "返回某 stage 的所有采样（ns）")
        .def("clear", &Probe::clear,
             py::call_guard<py::gil_scoped_release>(),
             "清空所有采样")
        .def("overhead_ns", &Probe::overhead_ns,
             py::call_guard<py::gil_scoped_release>(),
             "测量 begin/end 一次的自身开销（ns，应 < 100ns）");
}
