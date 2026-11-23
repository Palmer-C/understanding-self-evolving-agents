"""检查真实模型后端的本机配置，默认只检查配置。

用法：
    python experiments/lab/check_backend.py
    python experiments/lab/check_backend.py --probe     # 向配置的服务发送一次可能计费的请求
"""

import argparse
import sys
from pathlib import Path

if __package__:
    from .backends import BackendUnavailable, OpenAIChatBackend
else:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from backends import BackendUnavailable, OpenAIChatBackend


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    options = parser.add_mutually_exclusive_group()
    options.add_argument("--probe", action="store_true", help="发送一次真实模型请求，可能产生费用")
    options.add_argument("--no-probe", action="store_true", help="只检查配置（默认）")
    parser.add_argument("--model", help="检查指定模型，默认使用本机配置")
    args = parser.parse_args(argv)
    try:
        backend = OpenAIChatBackend(model=args.model, max_retries=0, timeout=60.0)
        if not args.probe:
            print(f"BACKEND_READY model={backend.model} base={backend.base_url} probe=skipped")
            return 0

        reply = backend.generate([{"role": "user", "content": "Reply with the single word: ok"}])
        if not reply.text.strip():
            print("BACKEND_UNREADY reason=empty_reply")
            return 1
        print(f"BACKEND_READY model={backend.model} base={backend.base_url} probe=ok "
              f"prompt_tokens={reply.prompt_tokens}")
        return 0
    except BackendUnavailable as exc:
        print(f"BACKEND_UNREADY reason={exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
