import asyncio
import logging
import socket
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("server")

PORT = 8080
HOST = "0.0.0.0"
MESSAGE_SIZE_BYTES = 1 << 10


async def handle_request(client: socket.socket) -> None:
    loop = asyncio.get_event_loop()
    while True:
        bytes = await loop.sock_recv(client, MESSAGE_SIZE_BYTES)
        if not bytes:
            logger.info("sock %s disconnected", client.getpeername())
            break
        message = bytes.decode("utf-8")
        logger.info("sock %s: %s", client.getpeername(), message)
        await loop.sock_sendall(client, bytes)


async def serve() -> None:
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(8)
    server.setblocking(False)
    logger.info("server running at %s:%d", HOST, PORT)

    loop = asyncio.get_event_loop()
    while True:
        client, _addr = await loop.sock_accept(server)
        loop.create_task(handle_request(client))


def main() -> int:
    asyncio.run(serve())
    return 0

if __name__ == "__main__":
    sys.exit(main())