"""分批提交 scripts/add_partitions_20260702_03.json 到 DataWorks。

每批 ≤100 条 ALTER（合并成一条 scriptContent），调 bff_client.execute_sql 拿
jobCode，再 wait_job 轮询完成；任一批失败立即停，已完成的批写进度到
scripts/add_partitions_progress.json。

使用方式：
    uv run python scripts/run_add_partitions.py            # 默认从头部开始
    uv run python scripts/run_add_partitions.py --resume   # 从上次进度继续
    uv run python scripts/run_add_partitions.py --batch-size 80
    uv run python scripts/run_add_partitions.py --dry-run  # 不调 API，只打印
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from dataworks_agent.api_clients.bff_client import DataWorksClient

SCRIPT_DIR = Path(__file__).resolve().parent
PLAN_PATH = SCRIPT_DIR / "add_partitions_20260702_03.json"
PROGRESS_PATH = SCRIPT_DIR / "add_partitions_progress.json"
REPORT_PATH = SCRIPT_DIR / "add_partitions_report.json"


def chunked(items: list, size: int) -> list[list]:
    return [items[i : i + size] for i in range(0, len(items), size)]


async def _wait_with_retry(client: DataWorksClient, job: str,
                            first_round: int = 60, second_round: int = 60,
                            interval: int = 3) -> bool:
    """首轮用 first_round×interval；首轮返回 False 时再跑 second_round 复核，
    避免 RUNNING 被 180s 窗口误判成失败（DDL 在 MC 上排队偶尔 >3min）。"""
    ok = await client.wait_job(job, max_retry=first_round, interval=interval)
    if ok:
        return True
    if client.last_error:
        # 真有 errorMessage，立即认定失败
        return False
    # last_error 为空但超时 → RUNNING 但没收到 end=True，再等一轮
    print(f"  [poll]   首轮超时（无 errorMessage），进入复核阶段 +{second_round * interval}s")
    return await client.wait_job(job, max_retry=second_round, interval=interval)


def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        return json.loads(PROGRESS_PATH.read_text(encoding="utf-8"))
    return {"completed_batches": [], "failed_batch": None}


def save_progress(progress: dict) -> None:
    PROGRESS_PATH.write_text(
        json.dumps(progress, ensure_ascii=False, indent=2), encoding="utf-8"
    )


async def run(batch_size: int, resume: bool, dry_run: bool) -> int:
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    alters = plan["plan"]
    progress = load_progress() if resume else {"completed_batches": [], "failed_batch": None}
    done_batches = set(progress["completed_batches"])

    batches = chunked(alters, batch_size)
    total = len(alters)
    started_batches = len(done_batches)

    print(f"plan={total} alters, batch_size={batch_size}, batches={len(batches)}, "
          f"resume={resume}, dry_run={dry_run}, already_done_batches={started_batches}")

    if dry_run:
        for idx, batch in enumerate(batches, 1):
            head = batch[0]
            tail = batch[-1]
            print(f"  [dry-run] batch {idx}: {len(batch)} alters, "
                  f"{head['table']} ({head['dt']}/{head['ht']}) → "
                  f"{tail['table']} ({tail['dt']}/{tail['ht']})")
        return 0

    client = DataWorksClient()
    summary = {"started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
               "batch_size": batch_size, "batches": []}

    try:
        for idx, batch in enumerate(batches, 1):
            if idx in done_batches:
                print(f"  [skip] batch {idx}/{len(batches)} already done")
                continue

            script = "\n".join(item["sql"] for item in batch)
            print(f"  [submit] batch {idx}/{len(batches)}  ({len(batch)} alters, "
                  f"{len(script)} chars)")

            job = await client.execute_sql(script)
            if not job:
                progress["failed_batch"] = idx
                save_progress(progress)
                print(f"  [FAIL] execute_sql 返回 None: {client.last_error}")
                summary["batches"].append({"idx": idx, "size": len(batch),
                                            "status": "submit_failed",
                                            "error": client.last_error})
                json.dump(summary, REPORT_PATH.open("w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
                return 1

            print(f"  [poll]   batch {idx} jobCode={job}")
            ok = await _wait_with_retry(client, job)
            if not ok:
                progress["failed_batch"] = idx
                save_progress(progress)
                err = client.last_error
                print(f"  [FAIL] job {job}: {err}")
                summary["batches"].append({"idx": idx, "size": len(batch),
                                            "job_code": job, "status": "job_failed",
                                            "error": err})
                json.dump(summary, REPORT_PATH.open("w", encoding="utf-8"),
                          ensure_ascii=False, indent=2)
                return 1

            progress["completed_batches"].append(idx)
            save_progress(progress)
            summary["batches"].append({"idx": idx, "size": len(batch),
                                        "job_code": job, "status": "ok"})
            print(f"  [OK]    batch {idx} done")

        summary["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        summary["status"] = "all_done"
        json.dump(summary, REPORT_PATH.open("w", encoding="utf-8"),
                  ensure_ascii=False, indent=2)
        print("ALL DONE")
        return 0
    finally:
        await client.close()


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--batch-size", type=int, default=100,
                   help="每批 ALTER 数量（默认 100，按 DataWorks IDE 通道经验值）")
    p.add_argument("--resume", action="store_true", help="从 add_partitions_progress.json 继续")
    p.add_argument("--dry-run", action="store_true", help="只打印批次，不调 API")
    args = p.parse_args()

    if args.batch_size < 1 or args.batch_size > 100:
        print("ERROR: --batch-size 必须在 1..100 之间", file=sys.stderr)
        return 2

    return asyncio.run(run(args.batch_size, args.resume, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
