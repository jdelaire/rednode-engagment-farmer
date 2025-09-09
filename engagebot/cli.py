from __future__ import annotations

import json

import typer

from engagebot.adapters.base import ServiceAdapter
from engagebot.adapters.mock import MockAdapter
from engagebot.config import Settings, load_settings
from engagebot.controller import Controller
from engagebot.logging_setup import setup_logging
from engagebot.scheduler import run_schedule
from engagebot.strategy import RandomSampleStrategy, RecentFirstStrategy

app = typer.Typer(help="EngageBot - Sandbox Engagement CLI")


def _build_adapter(settings: Settings) -> ServiceAdapter:
    if settings.ADAPTER.lower() == "mock":
        return MockAdapter(settings)
    raise typer.BadParameter("Only ADAPTER='mock' is supported in this PoC.")


def _choose_strategy(name: str, seed: int):
    key = name.lower()
    if key in {"random", "randomsample", "randomsamplestrategy"}:
        return RandomSampleStrategy(seed)
    if key in {"recent", "recentfirst", "recentfirststrategy"}:
        return RecentFirstStrategy()
    raise typer.BadParameter("Unknown strategy. Choose 'random' or 'recent'.")


@app.callback()
def main(json_logs: bool = typer.Option(False, "--json-logs", help="Enable JSON logs")):
    setup_logging(json_logs=json_logs)


@app.command()
def login():
    """Login with the configured adapter and credentials (mock only)."""
    settings = load_settings()
    adapter = _build_adapter(settings)
    session = adapter.login(settings.USERNAME, settings.PASSWORD)
    typer.echo(json.dumps(session.model_dump(), indent=2, ensure_ascii=False))


@app.command()
def discover(tag: str | None = typer.Option(None, "--tag"), limit: int = typer.Option(10, "--limit")):
    settings = load_settings()
    adapter = _build_adapter(settings)
    posts = adapter.discover_posts(tag=tag or settings.DEFAULT_TAG, limit=limit)
    typer.echo(json.dumps([p.model_dump() for p in posts], indent=2, ensure_ascii=False, default=str))


@app.command()
def like(post_id: str = typer.Option(..., "--post-id"), dry_run: bool = typer.Option(True, "--dry-run")):
    settings = load_settings()
    adapter = _build_adapter(settings)
    session = adapter.login(settings.USERNAME, settings.PASSWORD)
    result = adapter.like_post(session, post_id, dry_run=dry_run)
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def follow(user_id: str = typer.Option(..., "--user-id"), dry_run: bool = typer.Option(True, "--dry-run")):
    settings = load_settings()
    adapter = _build_adapter(settings)
    session = adapter.login(settings.USERNAME, settings.PASSWORD)
    result = adapter.follow_user(session, user_id, dry_run=dry_run)
    typer.echo(result.model_dump_json(indent=2))


@app.command()
def comment(
    post_id: str = typer.Option(..., "--post-id"),
    text: str | None = typer.Option(None, "--text"),
    dry_run: bool = typer.Option(True, "--dry-run"),
):
    settings = load_settings()
    adapter = _build_adapter(settings)
    session = adapter.login(settings.USERNAME, settings.PASSWORD)
    result = adapter.comment(session, post_id, text=text or settings.DEFAULT_COMMENT_TEXT, dry_run=dry_run)
    typer.echo(result.model_dump_json(indent=2))


@app.command("run-once")
def run_once(
    tag: str | None = typer.Option(None, "--tag"),
    strategy: str = typer.Option("recent", "--strategy", help="recent|random"),
    dry_run: bool | None = typer.Option(None, "--dry-run"),
    limit: int | None = typer.Option(None, "--limit"),
):
    settings = load_settings()
    adapter = _build_adapter(settings)
    ctrl = Controller(adapter, settings)
    strat = _choose_strategy(strategy, settings.SEED)
    ctrl.run_once(strat, tag=tag, dry_run=dry_run, discover_limit=limit)


@app.command("run-schedule")
def run_schedule_cmd(
    cron: str | None = typer.Option(None, "--cron", help="crontab schedule like '*/30 * * * *'"),
    enable: bool = typer.Option(False, "--enable"),
    tag: str | None = typer.Option(None, "--tag"),
    strategy: str = typer.Option("recent", "--strategy", help="recent|random"),
):
    settings = load_settings()
    adapter = _build_adapter(settings)
    ctrl = Controller(adapter, settings)
    strat = _choose_strategy(strategy, settings.SEED)
    run_schedule(controller=ctrl, strategy=strat, settings=settings, cron=cron, enable=enable, tag=tag)

