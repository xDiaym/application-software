#include <functional>
#include <future>
#include <iostream>
#include <ostream>
#include <queue>
#include <thread>
#include <type_traits>
#include <utility>
#include <vector>
#include <mutex>
#include <condition_variable>


class ThreadPool {
  using Task = std::move_only_function<void()>;
public:
  ThreadPool(std::size_t threads = std::thread::hardware_concurrency())
    : stop_(false) {
    for (std::size_t i = 0; i < threads; ++i) {
      workers_.push_back(std::thread([this]() {
        while (true) {
          Task task;

          {
            std::unique_lock lock(mutex_);
            cond_var_.wait(lock, [this]() { return stop_ || !queue_.empty(); });

            if (stop_ && queue_.empty())
              return;

            task = std::move(queue_.front());
            queue_.pop();
          }

          task();
        }
      }));
    }
  }

  template<typename Fn, typename ...Args> requires(std::is_invocable_v<Fn, Args...>)
  std::future<std::invoke_result_t<Fn, Args...>> Enqueue(Fn&& fn, Args&&... args) {
    using return_type = std::invoke_result_t<Fn, Args...>;
    auto task = std::packaged_task<return_type()>(
      std::bind(std::forward<Fn>(fn), std::forward<Args>(args)...)
    );

    std::future<return_type> future = task.get_future();
    {
      std::scoped_lock lock(mutex_);
      queue_.emplace([task = std::move(task)]() mutable { task(); });
    }
    cond_var_.notify_one();
    return future;
  }

  ~ThreadPool() {
    {
      std::unique_lock lock(mutex_);
      stop_ = true;
    }
    cond_var_.notify_all();

    for (auto& thread : workers_)
      thread.join();
  }

private:
  std::vector<std::thread> workers_;
  mutable std::mutex mutex_;
  std::condition_variable cond_var_;
  std::queue<Task> queue_;
  bool stop_;
};

int main() {
  ThreadPool tp;
  std::vector<int> nums = {5, 2, 3, 6, 1, 9, 7, 4, 8, 10};

  for (int i : nums) {
    tp.Enqueue([](int i) {
      std::this_thread::sleep_for(std::chrono::seconds(i));
      std::cout << i << ' ';
    }, i);
  }
}
