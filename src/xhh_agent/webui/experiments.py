"""Explicit fixed verification recipes; never executes a prompt as a command."""

import asyncio
import hashlib
import sys


async def execute(root, recipe):
    recipes = {
        "runtime": [sys.executable, "--version"],
        "project-tests": [sys.executable, "-m", "pytest", "-q"],
    }
    if recipe not in recipes:
        raise ValueError("请选择 runtime 或 project-tests 验证配方")
    process = await asyncio.create_subprocess_exec(
        *recipes[recipe], cwd=root, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
    )
    output = bytearray()

    async def collect():
        while chunk := await process.stdout.read(8192):
            output.extend(chunk)
            if len(output) > 1_000_000:
                raise ValueError("验证输出超过限制")
        await process.wait()

    try:
        await asyncio.wait_for(collect(), timeout=60)
    except BaseException:
        if process.returncode is None:
            process.kill()
        await process.wait()
        raise
    digest = hashlib.sha256(output).hexdigest()
    return {
        "kind": "experiment",
        "text": f"验证配方：{recipe}\n退出码：{process.returncode}\n日志：\n"
        + output[:24000].decode("utf-8", errors="replace"),
        "recipe": recipe,
        "command": recipes[recipe],
        "exit_code": process.returncode,
        "log_sha256": digest,
        "log_truncated": len(output) > 24000,
        "provenance": "executed_on_host",
        "verification": "命令实际执行；结论仅适用于该环境与配方",
    }
