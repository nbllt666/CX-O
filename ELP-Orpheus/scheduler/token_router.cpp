// token_router.cpp — C++ Token 路由，绕过 Python GIL
// 设计决策：纯 Python 调度器的 GIL 会导致毫秒级延迟毛刺，
// 将 LLM→TTS 的 token 路由逻辑下放到 C++ 层，彻底绕过 GIL。
//
// 核心思路：
//   - LLM 生产者线程通过 push_tokens() 写入 C++ 队列；
//   - TTS 消费者线程通过 pop_tokens() 阻塞读取；
//   - 关键路径上通过 py::call_guard<py::gil_scoped_release>() 释放 GIL，
//     使得 Python 其它线程（如音频渲染、网络收发）可并行执行，
//     避免被 GIL 抢占导致的毫秒级延迟毛刺。
//
// 编译：见 build_token_router.py
// 模块名：token_router（导入时 import token_router）

#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
#include <pybind11/stl.h>

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstring>
#include <mutex>
#include <queue>
#include <thread>
#include <vector>

namespace py = pybind11;

// 线程安全的 Token 路由队列：LLM 生产者线程写入，TTS 消费者线程读取，
// 全程不持有 Python GIL（通过 py::gil_scoped_release）。
//
// 为什么释放 GIL 能避免毛刺：
//   CPython 的 GIL 限制了同一时刻只有一个原生线程执行 Python 字节码。
//   当 LLM 推理（PyTorch/CUDA 内核）或 TTS 推理在 Python 调度器中排队
//   时，若调度逻辑在 Python 层做循环判断/拷贝，会长时间占用 GIL，
//   阻塞其它 Python 线程（音频采集、websocket 接收等），表现为几毫秒
//   甚至十几毫秒的延迟毛刺。把队列逻辑放到 C++ 层，并在调用入口处
//   释放 GIL，意味着 Python 调度线程进入 C++ 后立即放弃 GIL，让其它
//   Python 线程自由运行；C++ 队列使用 std::mutex + std::condition_variable
//   自行同步，不依赖 GIL，从而彻底消除由 GIL 引入的调度毛刺。
class TokenRouter {
public:
    explicit TokenRouter(size_t max_queue_size = 1024)
        : max_queue_size_(max_queue_size == 0 ? 1 : max_queue_size) {}

    // 生产者：LLM 线程写入 token（释放 GIL 后操作 C++ 队列）。
    // 释放 GIL 后，Python 其它线程（音频/网络/渲染）可同时运行，
    // 不会被本调用阻塞——这是消除毛刺的关键所在。
    void push_tokens(py::array_t<int32_t, py::array::c_style | py::array::forcecast> token_ids) {
        // 持有 GIL 读取 numpy 数组信息（request() 访问 Python 对象必须持有 GIL）。
        auto buf = token_ids.request();
        const int32_t* data_ptr = static_cast<int32_t*>(buf.ptr);
        const size_t n = static_cast<size_t>(buf.size);

        std::vector<int32_t> chunk;
        chunk.reserve(n);
        for (size_t i = 0; i < n; ++i) {
            chunk.push_back(data_ptr[i]);
        }

        // 释放 GIL 进入 C++ 临界区：标准库同步原语不依赖 GIL，
        // 队列满时阻塞等待不会卡住其它 Python 线程。
        bool finished_now = false;
        {
            py::gil_scoped_release gil_release;
            std::unique_lock<std::mutex> lock(mtx_);
            // 队列满时阻塞等待消费者腾出空间，避免无界堆积导致内存爆涨。
            cv_not_full_.wait(lock, [this]() {
                return queue_.size() < max_queue_size_ || finished_.load(std::memory_order_acquire);
            });
            finished_now = finished_.load(std::memory_order_acquire);
            if (!finished_now) {
                queue_.push(std::move(chunk));
                // 通知等待 pop 的消费者。
                cv_not_empty_.notify_one();
            }
        }
        // 重新持有 GIL 后抛出异常（pybind11 需 GIL 转 Python 异常）。
        if (finished_now) {
            throw std::runtime_error("TokenRouter: push_tokens called after mark_finished");
        }
    }

    // 消费者：TTS 线程读取 token 块（阻塞等待，释放 GIL）。
    // 阻塞等待期间不占用 GIL，让其它 Python 线程顺畅执行。
    py::array_t<int32_t> pop_tokens() {
        std::vector<int32_t> chunk;
        bool drained = false;
        {
            // 释放 GIL 进行阻塞等待，让其它 Python 线程并行运行。
            py::gil_scoped_release gil_release;
            std::unique_lock<std::mutex> lock(mtx_);
            cv_not_empty_.wait(lock, [this]() {
                return !queue_.empty() || finished_.load(std::memory_order_acquire);
            });

            // 队列空且已结束：标记 drained，随后在持有 GIL 时构造空数组返回。
            if (queue_.empty() && finished_.load(std::memory_order_acquire)) {
                drained = true;
            } else {
                chunk = std::move(queue_.front());
                queue_.pop();
                cv_not_full_.notify_one();
            }
        }
        // 此处已重新持有 GIL（gil_release 析构），可安全构造 Python 对象。
        if (drained) {
            py::array_t<int32_t> empty(0);
            return empty;
        }
        py::array_t<int32_t> result(chunk.size());
        auto r = result.request();
        if (!chunk.empty()) {
            std::memcpy(r.ptr, chunk.data(), chunk.size() * sizeof(int32_t));
        }
        return result;
    }

    // 非阻塞尝试读取。返回 numpy 数组或 None。
    // 调用方在 Python 层判断 is None，避免阻塞。
    // 注意：本方法不带 call_guard<py::gil_scoped_release>，
    // 因为返回 py::none()/array 切换需要 GIL；但内部临界区极短，
    // 仅一次 lock/unlock，不会造成可见毛刺。
    py::object try_pop_tokens() {
        std::vector<int32_t> chunk;
        {
            std::unique_lock<std::mutex> lock(mtx_);
            if (queue_.empty()) {
                // 队列空：返回 None 表示暂无数据（调用方自行结合 is_drained 判断是否流结束）。
                return py::none();
            }
            chunk = std::move(queue_.front());
            queue_.pop();
            cv_not_full_.notify_one();
        }

        py::array_t<int32_t> result(chunk.size());
        auto r = result.request();
        if (!chunk.empty()) {
            std::memcpy(r.ptr, chunk.data(), chunk.size() * sizeof(int32_t));
        }
        return result;
    }

    // 标记 LLM 流结束。此后不允许再 push，pop 在队列清空后返回空。
    void mark_finished() {
        {
            std::lock_guard<std::mutex> lock(mtx_);
            finished_.store(true, std::memory_order_release);
        }
        // 唤醒所有等待中的生产者与消费者，让它们看到 finished_ 状态并退出。
        cv_not_empty_.notify_all();
        cv_not_full_.notify_all();
    }

    // 是否已结束且队列为空。调用方据此判断是否结束 TTS 管线。
    bool is_drained() const {
        std::lock_guard<std::mutex> lock(mtx_);
        return finished_.load(std::memory_order_acquire) && queue_.empty();
    }

    // 当前队列长度（块数，不是 token 数）。
    size_t queue_size() const {
        std::lock_guard<std::mutex> lock(mtx_);
        return queue_.size();
    }

private:
    std::queue<std::vector<int32_t>> queue_;
    mutable std::mutex mtx_;
    // cv_not_empty_：队列由空变非空时唤醒消费者。
    std::condition_variable cv_not_empty_;
    // cv_not_full_：队列由满变非满时唤醒生产者。
    std::condition_variable cv_not_full_;
    size_t max_queue_size_;
    std::atomic<bool> finished_{false};
};

PYBIND11_MODULE(token_router, m) {
    m.doc() = "C++ Token Router for ELP-Orpheus FT engine (GIL-free).";

    py::class_<TokenRouter>(m, "TokenRouter")
        .def(py::init<size_t>(), py::arg("max_queue_size") = 1024)
        // push_tokens / pop_tokens：函数内部手动管理 GIL
        // （持有 GIL 访问 numpy 数组，释放 GIL 进行阻塞等待/入队）。
        // 不能用 call_guard<gil_scoped_release>：那会在整个函数体释放 GIL，
        // 导致 request() 与 py::array_t 构造（需要 GIL）崩溃。
        .def("push_tokens", &TokenRouter::push_tokens, py::arg("token_ids"))
        .def("pop_tokens", &TokenRouter::pop_tokens)
        .def("try_pop_tokens", &TokenRouter::try_pop_tokens)
        .def("mark_finished", &TokenRouter::mark_finished,
             py::call_guard<py::gil_scoped_release>())
        .def("is_drained", &TokenRouter::is_drained,
             py::call_guard<py::gil_scoped_release>())
        .def("queue_size", &TokenRouter::queue_size,
             py::call_guard<py::gil_scoped_release>());
}
