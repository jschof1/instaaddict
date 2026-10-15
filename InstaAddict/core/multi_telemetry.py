import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class MultiAccountTelemetryAggregator:
    """
    Centralized telemetry aggregation engine that ingests per-account session records,
    Dogfood optimization recommendations, and performance latencies, generating
    comparative fleet analytics and automated multi-tenant tuning recommendations.
    """

    def __init__(self, accounts: List[str], accounts_base_dir: str = "accounts", log_dir: str = "logs/orchestrator"):
        self.accounts = [u.lstrip("@").strip() for u in accounts]
        self.accounts_base_dir = accounts_base_dir
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

    def collect_account_telemetry(self, username: str) -> Dict[str, Any]:
        """Reads local sessions.json and tuning_suggestions.json for a single account."""
        acc_dir = os.path.join(self.accounts_base_dir, username)
        sessions_path = os.path.join(acc_dir, "sessions.json")
        tuning_path = os.path.join(acc_dir, "tuning_suggestions.json")

        sessions_data = []
        if os.path.exists(sessions_path):
            try:
                with open(sessions_path, "r", encoding="utf-8") as f:
                    sessions_data = json.load(f)
            except Exception as e:
                logger.debug(f"Failed to read sessions.json for {username}: {e}")

        tuning_data = {}
        if os.path.exists(tuning_path):
            try:
                with open(tuning_path, "r", encoding="utf-8") as f:
                    tuning_data = json.load(f)
            except Exception as e:
                logger.debug(f"Failed to read tuning_suggestions.json for {username}: {e}")

        # Compute aggregate KPIs
        total_likes = 0
        total_follows = 0
        total_comments = 0
        total_watched = 0
        total_crashes = 0
        total_sessions = len(sessions_data)

        for s in sessions_data:
            if isinstance(s, dict):
                total_likes += s.get("totalLikes", 0)
                tf = s.get("totalFollowed", {})
                total_follows += sum(tf.values()) if isinstance(tf, dict) else (tf if isinstance(tf, int) else 0)
                total_comments += s.get("totalComments", 0)
                total_watched += s.get("totalWatched", 0)
                total_crashes += s.get("total_crashes", 0)

        return {
            "username": username,
            "total_sessions": total_sessions,
            "metrics": {
                "total_likes": total_likes,
                "total_follows": total_follows,
                "total_comments": total_comments,
                "total_watched": total_watched,
                "total_crashes": total_crashes,
            },
            "tuning": tuning_data,
        }

    def aggregate_fleet_telemetry(self) -> Dict[str, Any]:
        """Aggregates telemetry across all configured accounts."""
        per_account = {}
        fleet_totals = {
            "total_likes": 0,
            "total_follows": 0,
            "total_comments": 0,
            "total_watched": 0,
            "total_crashes": 0,
            "total_sessions": 0,
        }

        for username in self.accounts:
            data = self.collect_account_telemetry(username)
            per_account[username] = data
            m = data["metrics"]
            fleet_totals["total_likes"] += m["total_likes"]
            fleet_totals["total_follows"] += m["total_follows"]
            fleet_totals["total_comments"] += m["total_comments"]
            fleet_totals["total_watched"] += m["total_watched"]
            fleet_totals["total_crashes"] += m["total_crashes"]
            fleet_totals["total_sessions"] += data["total_sessions"]

        return {
            "generated_at": datetime.now().isoformat(),
            "fleet_totals": fleet_totals,
            "accounts": per_account,
        }

    def generate_fleet_report(self) -> Tuple[str, str]:
        """
        Generates markdown fleet report and JSON telemetry payload.
        Returns: (markdown_path, json_path)
        """
        data = self.aggregate_fleet_telemetry()
        json_path = os.path.join(self.log_dir, "fleet_telemetry.json")
        md_path = os.path.join(self.log_dir, "fleet_report.md")

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        totals = data["fleet_totals"]
        md_lines = [
            "# InstaAddict-AI Fleet Telemetry Report",
            f"\n**Generated**: {data['generated_at']}",
            f"\n## 1. Fleet Overview",
            f"- **Managed Accounts**: {len(self.accounts)}",
            f"- **Total Sessions**: {totals['total_sessions']}",
            f"- **Total Likes**: {totals['total_likes']}",
            f"- **Total Follows**: {totals['total_follows']}",
            f"- **Total Comments**: {totals['total_comments']}",
            f"- **Total Watched**: {totals['total_watched']}",
            f"- **Total Crashes**: {totals['total_crashes']}",
            "\n## 2. Per-Account Performance Breakdown",
            "| Account | Sessions | Likes | Follows | Comments | Watched | Crashes |",
            "|---|---|---|---|---|---|---|",
        ]

        for u, acc_data in data["accounts"].items():
            m = acc_data["metrics"]
            md_lines.append(
                f"| @{u} | {acc_data['total_sessions']} | {m['total_likes']} | {m['total_follows']} | {m['total_comments']} | {m['total_watched']} | {m['total_crashes']} |"
            )

        with open(md_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines) + "\n")

        logger.info(f"Generated fleet report at {md_path}")
        return md_path, json_path

    def apply_tuning_and_restart(self, username: str, orchestrator: Any) -> bool:
        """
        Applies dogfood tuning for an account and automatically reboots the child process
        so that modified configuration is loaded fresh into memory (GAP-10).
        """
        clean_user = username.lstrip("@").strip()
        logger.info(f"Applying auto-tuning recommendations for @{clean_user}...")

        try:
            from InstaAddict.core.dogfood import DogfoodOptimizer
            optimizer = DogfoodOptimizer(clean_user)
            optimizer.analyze()
            optimizer.apply_tuning()
            # If recommendations were generated, log and reboot process
            logger.info(f"Dogfood optimization applied for @{clean_user}. Rebooting child process (GAP-10)...")
            if orchestrator and hasattr(orchestrator, "restart_account"):
                return orchestrator.restart_account(clean_user, delay_seconds=2.0)
            return True
        except Exception as e:
            logger.error(f"Failed to apply tuning and restart @{clean_user}: {e}")
            return False
