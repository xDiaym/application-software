#include <cassert>
#include <chrono>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <iostream>
#include <fstream>
#include <ostream>
#include <limits>
#include <vector>
#include <concepts>
#include <utility>

#include <omp.h>

using Value = float;
using Coord = std::int64_t;
using Coords = std::pair<Coord, Coord>;

template <typename T>
concept Predicate = requires (T t, Coord x) {
  { t(x, x) } -> std::convertible_to<Value>;
};

template <typename T>
concept BoundaryFunc = requires (T t, std::vector<Value>& v) {
  t(v);
};

template <typename T>
concept VectorFieldFunc = requires (T t, Coord x) {
  { t(x, x) } -> std::convertible_to<std::pair<Coord, Coord>>;
};

inline void save(const std::string& path, const std::vector<std::vector<Value>>& history) {
  std::ofstream ofs(path, std::ios::out | std::ios::binary);
  for (const auto& v : history)
    for (const auto i : v)
      ofs << i;
}

struct Params {
  Value alpha;
  Value dt, dx, dy;
  std::size_t rows, columns;
  Value t;
  std::size_t sample_rate;
  std::size_t num_threads;
};

struct Result {
  std::vector<Value> heatmap;
  std::chrono::system_clock::duration wall_time;
};

template <
  Predicate IsWallFn,
  BoundaryFunc BoundaryFn,
  VectorFieldFunc WallNormalFn
>
class Grid {
public:
  Grid(Params p, IsWallFn&& is_wall, BoundaryFn&& boundary, WallNormalFn&& wall)
    : is_wall(std::forward<IsWallFn>(is_wall))
    , boundary(std::forward<BoundaryFn>(boundary))
    , wall_normal(std::forward<WallNormalFn>(wall))
    , params(p)
    , u(p.rows * p.columns, 0.0)
    , u_new(p.rows * p.columns, 0.0) {
      assert(p.rows > 1);
      assert(p.columns > 1);
      if (p.alpha * p.dt / (p.dx * p.dx) + p.alpha * p.dt / (p.dy * p.dy) > 1)
        std::clog << "WARN: check convergence\n";

      omp_set_num_threads(params.num_threads);
    }


  void step() {
    boundary(u);

    #pragma omp parallel for
    for (std::int64_t y = 0; y < params.rows; ++y) {
      for (std::int64_t x = 0; x < params.columns; ++x) {
        if (is_wall(x, y)) [[unlikely]]
          continue;

        auto dudx2 = (at(x+1, y) - 2*at(x, y) + at(x-1, y)) / (params.dx * params.dx);
        auto dudy2 = (at(x, y+1) - 2*at(x, y) + at(x, y-1)) / (params.dy * params.dy);
        u_new[y * params.columns + x] = at(x, y) + params.dt * params.alpha * (dudx2 + dudy2);
      }
    }

    std::swap(u, u_new);
  }

  Result run(const std::string& path) && {
    const std::size_t n = std::floor(params.t / params.dt);

    const auto start = std::chrono::steady_clock::now();
    for (auto i = 0ull; i < n; ++i) {
      step();
      if (params.sample_rate != std::numeric_limits<std::size_t>::max() && i % params.sample_rate == 0)
        history.push_back(u);
    }
    const auto dur = std::chrono::steady_clock::now() - start;

    save(path, history);
    return { .heatmap = std::move(u), .wall_time = dur };
  }

protected:
  const Value& at(std::int64_t x, std::int64_t y) const {
    if (is_wall(x, y)) [[unlikely]] {
      const auto[nx, ny] = wall_normal(x, y);
      x += nx, y += ny;
    }
    return u[y * params.columns + x];
  }

protected:
  IsWallFn is_wall;
  BoundaryFn boundary;
  WallNormalFn wall_normal;
  Params params;
  std::vector<Value> u, u_new;
  std::vector<std::vector<Value>> history;
};
