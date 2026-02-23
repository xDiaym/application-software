#include <cassert>
#include <cctype>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <optional>
#include <vector>
#include <concepts>
#include <utility>
#include <ostream>
#include <fstream>

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
concept VectorFieldFunc = requires (T t, Coord x) {  // TODO: rename
  { t(x, x) } -> std::convertible_to<std::pair<Coord, Coord>>;
};

struct Params {
  Value alpha;
  Value dt, dx, dy;
  std::size_t rows, columns;
  Value t;
  std::size_t sample_rate;
};

void save(const std::vector<std::vector<Value>>& v, const std::string& path) {
  std::ofstream fs(path, std::ios::out | std::ios::binary);
  for (const auto& u : v) {
    fs.write(reinterpret_cast<const char*>(u.data()), u.size() * sizeof(Value));
  }
}

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
        std::clog << "WARN: converge\n";
    }

  void step() {
    boundary(u);

    #pragma omp parallel for
    for (std::int64_t y = 1; y < params.rows - 1; ++y) {
      for (std::int64_t x = 1; x < params.columns - 1; ++x) {
        if (is_wall(x, y)) [[unlikely]]
          continue;

        auto dudx2 = (at(x+1, y) - 2*at(x, y) + at(x-1, y)) / (params.dx * params.dx);
        auto dudy2 = (at(x, y+1) - 2*at(x, y) + at(x, y-1)) / (params.dy * params.dy);
        u_new[y * params.columns + x] = at(x, y) + params.dt * params.alpha * (dudx2 + dudy2);
      }
    }

    std::swap(u, u_new);
  }

  void run(const std::string& path) {
    const std::size_t n = std::floor(params.t / params.dt);
    for (auto i = 0ull; i < n; ++i) {
      step();
      if (i % params.sample_rate == 0) history.push_back(u);
    }

    save(history, path);
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

int main() {
  Params p{
    1, 1e-3, 1e-1, 1e-1,
    102, 102,
    200,
    100
  };

  Grid g(
    p,
    [&](auto x, auto y) {
      return x == 0 || x == p.columns - 1
          || y == 0 || y == p.rows - 1
          || (y >= 30 && y <= 60 && x <= 30);
    },
    [&](std::vector<Value>& v) {
      for (auto y = 1; y < 30; ++y)
        v[y * p.columns + 1] = 1.0;
    },
    [&](auto x, auto y) -> Coords {
      // bounding box
      if (x == 0) return {1, 0};
      if (x == p.columns - 1) return {-1, 0};
      if (y == 0) return {0, 1};
      if (y == p.rows - 1) return {0, -1};

      // box inside
      if (x == 30 && y >= 30 && y <= 60) return {1, 0};
      if (x <= 30 && y == 30) return {0, -1};
      if (x <= 30 && y == 60) return {0, 1};

      return {0, 0};
    }
  );

  g.run("out.dat");
}
