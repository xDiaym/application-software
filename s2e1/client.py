import asyncio
import contextlib
import sys

CRLF = "\r\n"


class Client:
    def __init__(self) -> None:
        self._last_channel: str | None = None

    def _format_irc_message(self, line: str) -> str:
        """Format IRC messages to look like a real IRC client."""
        if not line:
            return ""
        
        # Parse IRC message format: [:prefix] COMMAND [args] [:trailing]
        parts = line.split(" ", 2)
        if len(parts) < 2:
            return f"< {line}"
        
        # Extract prefix (sender info)
        prefix = ""
        command = parts[0]
        args = parts[1] if len(parts) > 1 else ""
        
        # Check if first part is a prefix (starts with :)
        if command.startswith(":"):
            prefix = command[1:]  # Remove the :
            if len(parts) > 1:
                command = parts[1]
                args = parts[2] if len(parts) > 2 else ""
            else:
                return f"< {line}"
        
        # Extract nickname from prefix (format: !nickname)
        nick = prefix[1:] if prefix.startswith("!") else prefix
        
        # Handle different message types
        if command == "PRIVMSG":
            if not args:
                return f"< {prefix} PRIVMSG"
            # Split channel and message
            msg_parts = args.split(" :", 1)
            if len(msg_parts) < 2:
                return f"< {prefix} PRIVMSG {args}"
            channel, message = msg_parts[0], msg_parts[1]
            return f"<{channel}> {nick}: {message}"
        
        elif command == "JOIN":
            channel = args.split()[0] if args else "unknown"
            return f"*** {nick} has joined {channel}"
        
        elif command == "QUIT":
            reason = args.split(" :", 1)[1] if " :" in args else "Client quit"
            return f"*** {nick} has quit ({reason})"
        
        elif command == "REGD":
            return f"*** Registered: {args}"
        
        else:
            # Default formatting for other messages
            if prefix:
                return f"{prefix} {command} {args}"
            else:
                return f"{command} {args}"

    async def _handle_server(self) -> None:
        while True:  # not self._reader.at_eof():
            try:
                binary = await self._reader.readline()
            except asyncio.CancelledError:
                break
            if not binary:
                break
            line = binary.decode().rstrip()
            formatted = self._format_irc_message(line)
            print(formatted)

    async def _handle_stdin(self) -> None:
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        srp = asyncio.StreamReaderProtocol(reader)
        await loop.connect_read_pipe(lambda: srp, sys.stdin)

        while True:
            try:
                line = (await reader.readline()).decode().rstrip()
            except asyncio.CancelledError:
                break
            if not line:
                break  # TODO quit

            command, *args = line.split(" ")
            if command == "/msg":
                self._last_channel = args[0]
                text = " ".join(args[1:])
                await self._send(f"PRIVMSG {self._last_channel} :{text}")
            elif command == "/reg":
                if len(args) >= 2:
                    nick, password = args[0], args[1]
                    await self._send(f"REG {nick} {password}")
                else:
                    print("Usage: /reg <nick> <password>")
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

    async def _send(self, line: str) -> None:
        self._writer.write(f"{line}{CRLF}".encode())
        await self._writer.drain()

    async def run(self, host: str, port: int = 6667) -> None:
        self._reader, self._writer = await asyncio.open_connection(host, port)

        server_task = asyncio.create_task(self._handle_server())
        stdin_task = asyncio.create_task(self._handle_stdin())

        _done, pending = await asyncio.wait(
            {server_task, stdin_task}, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


def main() -> int:
    client = Client()
    asyncio.run(client.run("127.0.0.1"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
