// probe.h — 超低开销 C++/Python 混合 Profiler 计时探针（头文件）
//
// 设计决策：
//   - 现有 scripts/run_e2e.py 用 time.perf_counter() 手工分阶段计时，stages 字典
//     手工赋值，开销高且不可复用。本模块用 C++ steady_clock 实现超低开销探针，
//     单次 begin/end 仅做 steady_clock::now() + unordered_map 查找。
//   - GIL：begin/end/get_samples 通过 pybind11 call_guard<gil_scoped_release>
//     释放 GIL，使 Python 其它线程（音频采集/网络收发）在计时期间可并行运行，
//     避免被 GIL 抢占导致的毫秒级延迟毛刺（参考 token_router.cpp 的 GIL 策略）。
//   - CUDA：用 #ifdef HAVE_CUDA 包裹 cudaEventRecord/cudaEventElapsedTime，
//     无 CUDA 时 cuda_event_begin/end 回退到 steady_clock 并记录 warning，
//     保证开发环境（无 CUDA）也能正常编译运行。
//   - 嵌套：每个 stage 的开始时戳用 vector 当栈，支持嵌套 stage 不互相干扰。
//
// 编译：见 build_probe.py
// 模块名：probe_cpp（导入时 import probe_cpp）

#pragma once

#include <chrono>
#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

// HAVE_CUDA 由编译命令行 -DHAVE_CUDA=1 注入（见 build_probe.py）。
// 无 CUDA 环境下不包含 cuda_runtime.h，保证可编译。
#ifdef HAVE_CUDA
#include <cuda_runtime.h>
#endif

namespace elp_prof {

// 超低开销计时探针：记录 begin/end 时戳，计算 elapsed_ns 存入内部 map。
//
// 为什么用 steady_clock：单调递增，不受系统时间调整影响，适合测量耗时。
// 为什么用 unordered_map：O(1) 平均查找，begin/end 热路径开销极低。
// 为什么用 mutex：concurrent_runner 并发 4 流可能共享同一 Probe，需线程安全；
// 无竞争时 mutex lock/unlock 开销极小（~20ns），不影响 < 100ns 目标。
class Probe {
public:
    Probe();
    ~Probe();

    // 记录 stage 开始时戳（压入该 stage 的开始时戳栈，支持嵌套）。
    void begin(const std::string& name);

    // 记录 stage 结束时戳，计算 elapsed_ns 并存入采样列表。
    void end(const std::string& name);

    // CUDA event 计时开始：cudaEventRecord 到指定 stream。
    // 无 CUDA 时回退到 steady_clock（与 begin 等价）并记录 warning。
    void cuda_event_begin(const std::string& name, uintptr_t stream);

    // CUDA event 计时结束：cudaEventSynchronize + cudaEventElapsedTime。
    // 无 CUDA 时回退到 steady_clock（与 end 等价）并记录 warning。
    void cuda_event_end(const std::string& name, uintptr_t stream);

    // 返回某 stage 的所有采样（ns）。无该 stage 时返回空 vector。
    std::vector<int64_t> get_samples(const std::string& name);

    // 清空所有采样与开始时戳栈。
    void clear();

    // 测量 begin/end 一次的自身开销（ns）：begin 紧跟 end，中间无工作，
    // 采样值即探针自身开销（steady_clock::now() × 2 + map 操作）。
    int64_t overhead_ns();

private:
    using clock = std::chrono::steady_clock;
    using time_point = clock::time_point;

    std::mutex mtx_;
    // 每个 stage 的开始时戳栈（vector 当栈用，支持嵌套 stage）。
    std::unordered_map<std::string, std::vector<time_point>> start_times_;
    // 每个 stage 的已采样耗时列表（ns）。
    std::unordered_map<std::string, std::vector<int64_t>> samples_;

#ifdef HAVE_CUDA
    // CUDA event 栈：与 start_times_ 对应，用于 cuda_event_begin/end。
    std::unordered_map<std::string, std::vector<cudaEvent_t>> cuda_start_events_;
    std::unordered_map<std::string, std::vector<cudaEvent_t>> cuda_end_events_;
#endif
};

} // namespace elp_prof
