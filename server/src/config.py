"""設定ファイル (YAML) の読み込み。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, List, Optional

import yaml


@dataclass
class PathsConfig:
    vault_dir: Path
    db_path: Path
    log_dir: Path


@dataclass
class LivesyncConfig:
    cli_command: str
    timeout_sec: int


@dataclass
class GoogleConfig:
    credentials_file: Path
    token_file: Path
    scopes: List[str]


@dataclass
class LocksConfig:
    timeout_sec: int = 600
    retry_interval_sec: int = 10
    max_retry: int = 6


@dataclass
class ZabbixConfig:
    enabled: bool = False
    server: str = ""
    host: str = ""
    item_count: str = ""
    item_log: str = ""


@dataclass
class VerifyConfig:
    webhook_url: str = ""
    zabbix: ZabbixConfig = field(default_factory=ZabbixConfig)


@dataclass
class LoggingConfig:
    level: str = "INFO"


@dataclass
class Config:
    paths: PathsConfig
    livesync: LivesyncConfig
    google: GoogleConfig
    locks: LocksConfig
    verify: VerifyConfig
    logging: LoggingConfig

    @classmethod
    def load(cls, path: Optional[str] = None) -> "Config":
        target = Path(path or os.environ.get("GTODO_CONFIG", "config/config.yaml"))
        if not target.is_absolute():
            target = (Path.cwd() / target).resolve()
        with target.open("r", encoding="utf-8") as fp:
            raw: Any = yaml.safe_load(fp) or {}
        return cls.from_dict(raw)

    @classmethod
    def from_dict(cls, raw: dict) -> "Config":
        paths_raw = raw.get("paths") or {}
        livesync_raw = raw.get("livesync") or {}
        google_raw = raw.get("google") or {}
        locks_raw = raw.get("locks") or {}
        verify_raw = raw.get("verify") or {}
        zabbix_raw = (verify_raw.get("zabbix") or {})
        logging_raw = raw.get("logging") or {}

        return cls(
            paths=PathsConfig(
                vault_dir=Path(paths_raw["vault_dir"]),
                db_path=Path(paths_raw["db_path"]),
                log_dir=Path(paths_raw.get("log_dir", "logs")),
            ),
            livesync=LivesyncConfig(
                cli_command=livesync_raw.get("cli_command", "livesync-cli"),
                timeout_sec=int(livesync_raw.get("timeout_sec", 300)),
            ),
            google=GoogleConfig(
                credentials_file=Path(google_raw.get("credentials_file", "credentials.json")),
                token_file=Path(google_raw.get("token_file", "token.json")),
                scopes=list(google_raw.get("scopes", ["https://www.googleapis.com/auth/tasks"])),
            ),
            locks=LocksConfig(
                timeout_sec=int(locks_raw.get("timeout_sec", 600)),
                retry_interval_sec=int(locks_raw.get("retry_interval_sec", 10)),
                max_retry=int(locks_raw.get("max_retry", 6)),
            ),
            verify=VerifyConfig(
                webhook_url=str(verify_raw.get("webhook_url", "")),
                zabbix=ZabbixConfig(
                    enabled=bool(zabbix_raw.get("enabled", False)),
                    server=str(zabbix_raw.get("server", "")),
                    host=str(zabbix_raw.get("host", "")),
                    item_count=str(zabbix_raw.get("item_count", "")),
                    item_log=str(zabbix_raw.get("item_log", "")),
                ),
            ),
            logging=LoggingConfig(
                level=str(logging_raw.get("level", "INFO")).upper(),
            ),
        )
