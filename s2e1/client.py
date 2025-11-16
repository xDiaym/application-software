import asyncio
import contextlib
import sys

CRLF = "\r\n"


class Client:
    def __init__(self) -> None:
        self._last_channel: str | None = None
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None

    def _format_irc_message(self, line: str) -> str:
        """Format IRC messages to look like a real IRC client."""
        if not line:
            return ""

        # Parse IRC message format: [:prefix] COMMAND [params] [:trailing]

        if line.startswith(":"):
            # Has prefix
            prefix_end = line.find(" ")
            if prefix_end == -1:
                return f"< {line}"

            prefix = line[1:prefix_end]  # Remove leading :
            rest = line[prefix_end + 1:]  # Everything after space

            parts = rest.split(" ", 1)
            command = parts[0]
            params = parts[1] if len(parts) > 1 else ""

            # Extract nickname from prefix (format: !nickname)
            nick = prefix[1:] if prefix.startswith("!") else prefix

            # Handle different message types
            if command == "PRIVMSG":
                if not params:
                    return f"< {prefix} PRIVMSG"
                msg_parts = params.split(" :", 1)
                if len(msg_parts) < 2:
                    return f"< {prefix} PRIVMSG {params}"
                channel, message = msg_parts[0], msg_parts[1]
                return f"<{channel}> {nick}: {message}"

            elif command == "JOIN":
                channel = params.split()[0] if params else "unknown"
                return f"*** {nick} has joined {channel}"

            elif command == "QUIT":
                reason = params.split(" :", 1)[1] if " :" in params else "Client quit"
                return f"*** {nick} has quit ({reason})"

            else:
                return f"< {prefix} {command} {params}"

        else:
            # No prefix - server message
            parts = line.split(" ", 1)
            command = parts[0]
            params = parts[1] if len(parts) > 1 else ""

            if command == "REGD":
                return f"*** Registered and authenticated as: {params}"

            elif command == "LOGIN":
                return f"*** Logged in as: {params}"

            elif command == "ERR":
                return f"*** ERROR: {params}"

            else:
                return f"< {command} {params}"

    async def _handle_server(self) -> None:
        assert self._reader is not None
        try:
            while True:
                binary = await self._reader.readline()
                if not binary:
                    break
                line = binary.decode().rstrip()
                formatted = self._format_irc_message(line)
                print(formatted)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            print(f"Server error: {e}")

    async def _handle_stdin(self) -> None:
        """Read from stdin without using connect_read_pipe (Windows-safe)."""
        loop = asyncio.get_running_loop()

        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)

                if not line:
                    break

                line = line.rstrip()

                if not line:
                    continue

                command, *args = line.split(" ")

                if command == "/reg":
                    if len(args) >= 2:
                        nick, password = args[0], args[1]
                        await self._send(f"REG {nick} {password}")
                    else:
                        print("Usage: /reg <nick> <password>")

                elif command == "/login":
                    if len(args) >= 2:
                        nick, password = args[0], args[1]
                        await self._send(f"LOGIN {nick} {password}")
                    else:
                        print("Usage: /login <nick> <password>")

                elif command == "/msg":
                    if len(args) >= 2:
                        self._last_channel = args[0]
                        text = " ".join(args[1:])
                        await self._send(f"PRIVMSG {self._last_channel} :{text}")
                    else:
                        print("Usage: /msg <channel> <text>")

                elif command == "/join":
                    if len(args) >= 1:
                        channel = args[0]
                        self._last_channel = channel
                        await self._send(f"JOIN {channel}")
                    else:
                        print("Usage: /join <channel>")

                elif command == "/quit":
                    quit_message = " ".join(args) if args else "Client quit"
                    await self._send(f"QUIT :{quit_message}")
                    break

                else:
                    if self._last_channel is not None:
                        await self._send(f"PRIVMSG {self._last_channel} :{line}")
                    else:
                        print("connect to channel first")

            except asyncio.CancelledError:
                break
            except Exception as e:
                print(f"Input error: {e}")
                break

    async def _send(self, line: str) -> None:
        assert self._writer is not None
        self._writer.write(f"{line}{CRLF}".encode())
        await self._writer.drain()

    async def run(self, host: str, port: int = 6667) -> None:
        try:
            self._reader, self._writer = await asyncio.open_connection(host, port)
            print(f"Connected to {host}:{port}")
            print("Please authenticate first: /reg <nick> <password> or /login <nick> <password>")

            server_task = asyncio.create_task(self._handle_server())
            stdin_task = asyncio.create_task(self._handle_stdin())

            done, pending = await asyncio.wait(
                {server_task, stdin_task},
                return_when=asyncio.FIRST_COMPLETED
            )

            for task in pending:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        except ConnectionRefusedError:
            print("ERROR: Could not connect to server. Make sure server is running!")
        except Exception as e:
            print(f"ERROR: {e}")
        finally:
            if self._writer:
                self._writer.close()
                await self._writer.wait_closed()


def main() -> int:
    client = Client()
    asyncio.run(client.run("127.0.0.1"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
