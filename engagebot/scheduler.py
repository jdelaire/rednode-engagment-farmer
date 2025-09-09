from __future__ import annotations

import time

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from engagebot.config import Settings
from engagebot.controller import Controller
from engagebot.logging_setup import get_logger


def run_schedule(
    controller: Controller,
    strategy,
    *,
    settings: Settings,
    cron: str | None = None,
    enable: bool = False,
    tag: str | None = None,
) -> None:
    logger = get_logger("scheduler")
    if not enable:
        logger.info("Schedule disabled. Pass --enable to start the scheduler.")
        print("Schedule disabled. Pass --enable to start the scheduler.")
        return

    cron_expr = cron or settings.SCHEDULE_CRON
    scheduler = BackgroundScheduler()

    scheduler.add_job(
        lambda: controller.run_once(
            strategy, tag=tag or settings.DEFAULT_TAG, dry_run=settings.DRY_RUN
        ),
        CronTrigger.from_crontab(cron_expr),
        name="engagebot_run_once",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=30,
    )

    scheduler.start()
    logger.info("Scheduler started with cron: %s", cron_expr)
    print(f"Scheduler started with cron: {cron_expr}")

    # Keep the process alive until interrupted
    try:
        while True:
            time.sleep(1.0)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")
        scheduler.shutdown()

