#include "grid.hpp"

#include <cstddef>
#include <cstdio>
#include <cstring>

#include <sys/socket.h>
#include <sys/types.h>
#include <netinet/in.h>
#include <unistd.h>

int main() {
  Params p;

  int sock = socket(AF_INET, SOCK_STREAM, 0);
  if (sock < 0) {
    perror("socket");
    return -1;
  }

  sockaddr_in addr, client_addr;
  memset(&addr, 0, sizeof(addr));
  addr.sin_family = AF_INET;
  addr.sin_port = htons(1449);
  addr.sin_addr.s_addr = htonl(INADDR_ANY);
  if (bind(sock, (sockaddr*)&addr, sizeof(addr)) < 0) {
    perror("bind");
    return -1;
  }

  if (listen(sock, 1) < 0) {
    perror("listen");
    return -1;
  }

  while (true) {
    socklen_t len;
    int fd = accept(sock, (sockaddr*)&client_addr, &len);
    if (fd < 0) {
      perror("accept");
      return -1;
    }

    if (read(fd, &p, sizeof(p)) < 0) {
      perror("read");
      return -1;
    }

    printf("alpha = %f, t = %f, num_cpus = %zu\n", p.alpha, p.t, p.num_threads);

    Grid g(
      p,
      [&](auto x, auto y) {
        return x == -1 || x == p.columns
            || y == -1 || y == p.rows
            || (y >= 30 && y <= 60 && x <= 30);
      },
      [&](std::vector<Value>& v) {
        for (auto y = 0; y < 30; ++y)
          v[y * p.columns] = 1.0;
      },
      [&](auto x, auto y) -> Coords {
        // bounding box
        if (x == -1) return {1, 0};
        if (x == p.columns) return {-1, 0};
        if (y == -1) return {0, 1};
        if (y == p.rows) return {0, -1};

        // box inside
        if (x == 30 && y >= 30 && y <= 60) return {1, 0};
        if (x <= 30 && y == 30) return {0, -1};
        if (x <= 30 && y == 60) return {0, 1};

        return {0, 0};
      }
    );

    const auto result = std::move(g).run("out.dat");

    send(fd, &result.wall_time, sizeof(result.wall_time), 0);

    const char* data = reinterpret_cast<const char*>(result.heatmap.data());
    const std::size_t size = result.heatmap.size() * sizeof(Value);
    for(std::size_t i = 0; i < size; i += 4096)
      send(fd, data + i, std::min(size - i, 4096ul), 0);

    close(fd);
  }

  close(sock);
  return 0;
}
