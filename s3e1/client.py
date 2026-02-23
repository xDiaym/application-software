#!/usr/bin/env python3
import socket
import struct
from datetime import timedelta

import click
import numpy as np
import matplotlib.pyplot as plt

# using Value = float;
# struct Params {
#   Value alpha;
#   Value dt, dx, dy;
#   std::size_t rows, columns;
#   Value t;
#   std::size_t sample_rate;
#   std::size_t num_threads;
# };
Params = struct.Struct("@ffffQQfQQ")

Lx, Ly = 100, 100

def call_tool(alpha: float, t: float, num_threads: int, port: int) -> tuple[timedelta, np.ndarray]:
    params = Params.pack(
        alpha, # 1.0
        1e-3, 1e-1, 1e-1,
        Lx, Ly,
        t,  # 200.0
        100,
        num_threads,
    )

    sock = socket.socket(family=socket.AF_INET, type=socket.SOCK_STREAM)
    sock.connect(("127.0.0.1", port))

    sock.send(params)

    heatmap = bytearray()
    while True:
        res = sock.recv(4096)
        if not res:
            break
        heatmap.extend(res)

    sock.close()

    assert len(heatmap) >= 8
    wall_time, = struct.unpack("@Q", heatmap[:8])
    dt = timedelta(microseconds=wall_time / 1000)

    T = np.frombuffer(heatmap[8:], dtype=np.float32).reshape((Lx, Ly))
    return dt, T

@click.group()
def client() -> None:
    pass


@client.command("compare")
def compare() -> None:
    t_omp = np.array([(n, call_tool(1.0, 200.0, n, 1449)[0].total_seconds()) for n in range(1, 17, 2)])
    plt.plot(t_omp[:, 0], t_omp[:, 1], label='OpenMP')
    plt.title(r'Solution time for: 100x100, 0.1x0.1, dt=1e-3, t=200, $\alpha=1.0$')
    plt.xlabel('threads, #')
    plt.ylabel('Time, s')
    plt.legend()
    plt.savefig("plot.png")

    click.echo("file saved: plog.png")


# TODO: area size
@client.command("compute")
@click.argument("alpha", type=float)
@click.argument("t", type=float)
def compute(alpha: float, t: float) -> None:
    _, T = call_tool(alpha, t, 12, 1449)
    # TODO Info
    plt.imsave("heatmap.png", T)

    click.echo("file saved: heatmap.png")

if __name__ == "__main__":
    client()