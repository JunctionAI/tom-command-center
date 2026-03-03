#!/usr/bin/env python3
"""
AI Engineering Pipeline — Toolkit for building multi-agent systems.
Formalizes patterns from Tom's Command Center into reusable templates.
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class AgentTemplate:
    """Template for creating new agents in the system."""

    AGENT_MD_TEMPLATE = """# AGENT.md — {name}
## {description}

### IDENTITY
You are {name}, {identity}

### PERSONALITY
{personality}

### SCHEDULED TASK: {schedule}
{task_description}

### STANDING ORDERS
- Task 1
- Task 2

### SYSTEM CAPABILITIES
You can emit:
- [INSIGHT: category|content|evidence]
- [METRIC: name|value|context]
- [EVENT: type|SEVERITY|payload]
- [STATE UPDATE: info]
"""

    CONTEXT_TEMPLATE = """# STATE — {name}

## Current Status
[What's happening now]

## Key Metrics
- Metric 1: [value]
- Metric 2: [value]

## Recent Decisions
[Decisions made this week]

## Next Steps
[What's planned]
"""

    def __init__(self, name: str, description: str, schedule: str):
        self.name = name
        self.description = description
        self.schedule = schedule
        self.created_at = datetime.now().isoformat()

    def generate_agent_md(self, identity: str, personality: str, task_desc: str) -> str:
        """Generate AGENT.md from template."""
        return self.AGENT_MD_TEMPLATE.format(
            name=self.name,
            description=self.description,
            identity=identity,
            personality=personality,
            schedule=self.schedule,
            task_description=task_desc,
        )

    def generate_context_md(self, status: str, metrics: Dict, decisions: List[str]) -> str:
        """Generate CONTEXT.md from template."""
        metrics_str = "\n".join(f"- {k}: {v}" for k, v in metrics.items())
        decisions_str = "\n".join(f"- {d}" for d in decisions)

        return self.CONTEXT_TEMPLATE.format(name=self.name).replace(
            "[What's happening now]", status
        ).replace(
            "[Key Metrics]", metrics_str
        ).replace(
            "[Recent Decisions]", decisions_str
        )


class MultiAgentOrchestrator:
    """Framework for wiring multiple agents into a cohesive system."""

    def __init__(self, base_dir: Path):
        self.base_dir = base_dir
        self.agents_dir = base_dir / "agents"
        self.config_dir = base_dir / "config"

    def create_agent_folder_structure(self, agent_name: str) -> Dict[str, Path]:
        """Create standard folder structure for new agent."""
        agent_dir = self.agents_dir / agent_name
        structure = {
            "agent_dir": agent_dir,
            "skills": agent_dir / "skills",
            "playbooks": agent_dir / "playbooks",
            "intelligence": agent_dir / "intelligence",
            "state": agent_dir / "state",
        }

        for path in structure.values():
            path.mkdir(parents=True, exist_ok=True)

        logger.info(f"Created agent structure: {agent_dir}")
        return structure

    def wire_agent_to_config(
        self,
        agent_name: str,
        display_name: str,
        chat_id: str,
        schedule_cron: str,
        task_name: str,
    ) -> Dict:
        """Wire agent into telegram and schedule configs."""
        result = {
            "agent_name": agent_name,
            "display_name": display_name,
            "status": "success",
            "changes": [],
        }

        try:
            # Load configs
            telegram_path = self.config_dir / "telegram.json"
            schedules_path = self.config_dir / "schedules.json"

            with open(telegram_path) as f:
                telegram_config = json.load(f)

            with open(schedules_path) as f:
                schedules_config = json.load(f)

            # Add to telegram config
            telegram_config["chat_ids"][agent_name] = chat_id
            telegram_config["agent_names"][agent_name] = display_name
            result["changes"].append(f"Added to telegram.json: {agent_name}")

            # Add to schedules
            schedules_config["schedules"].append(
                {
                    "agent": agent_name,
                    "task": task_name,
                    "cron": schedule_cron,
                    "description": f"{display_name} scheduled task",
                }
            )
            result["changes"].append(f"Added to schedules.json: {schedule_cron}")

            # Save configs
            with open(telegram_path, "w") as f:
                json.dump(telegram_config, f, indent=2)

            with open(schedules_path, "w") as f:
                json.dump(schedules_config, f, indent=2)

            logger.info(f"Wired agent: {agent_name}")

        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

        return result

    def create_inter_agent_connection(
        self,
        source_agent: str,
        target_agent: str,
        trigger: str,
        data_format: str = "event",
    ) -> Dict:
        """Define how one agent triggers or feeds into another."""
        connection = {
            "source": source_agent,
            "target": target_agent,
            "trigger": trigger,  # e.g., "[EVENT: ...] marker"
            "data_format": data_format,  # "event", "file", "database"
            "created_at": datetime.now().isoformat(),
        }

        logger.info(f"Connection: {source_agent} → {target_agent}")
        return connection

    def validate_system_integrity(self) -> Dict:
        """Check system for wiring issues, duplicates, gaps."""
        result = {
            "timestamp": datetime.now().isoformat(),
            "agents_count": 0,
            "missing_configs": [],
            "orphaned_agents": [],
            "warnings": [],
        }

        try:
            # Load configs
            telegram_path = self.config_dir / "telegram.json"
            schedules_path = self.config_dir / "schedules.json"

            with open(telegram_path) as f:
                telegram_config = json.load(f)
            with open(schedules_path) as f:
                schedules_config = json.load(f)

            # List all agent folders
            agent_folders = [d.name for d in self.agents_dir.iterdir() if d.is_dir()]
            result["agents_count"] = len(agent_folders)

            # Check for missing configs
            for agent in agent_folders:
                if agent not in telegram_config.get("chat_ids", {}):
                    result["missing_configs"].append(f"{agent}: missing from telegram.json")

            # Check for orphaned agents in config
            for agent in telegram_config.get("chat_ids", {}):
                if agent not in agent_folders and agent != "scout":  # scout is special
                    result["orphaned_agents"].append(agent)

            # Check for unscheduled agents
            scheduled = {s["agent"] for s in schedules_config.get("schedules", [])}
            for agent in agent_folders:
                if agent not in scheduled and agent not in ["command-center", "strategic-advisor"]:
                    result["warnings"].append(f"{agent}: not in schedules (on-demand only)")

            logger.info(f"System integrity check: {result['agents_count']} agents")

        except Exception as e:
            result["error"] = str(e)

        return result


class PipelineDocumentation:
    """Generate documentation for the AI engineering pipeline."""

    @staticmethod
    def generate_architecture_doc() -> str:
        """Generate architecture overview."""
        return """# AI Engineering Pipeline Architecture

## Multi-Agent System Design

### Core Principles
1. **Specialization** — Each agent owns one domain
2. **Autonomy** — Agents run on their own schedule
3. **Context** — Full brain (AGENT.md + skills + state) before each response
4. **Communication** — Event bus + markers for inter-agent coordination
5. **Learning** — State files accumulate intelligence over time

### Agent Lifecycle
```
Load Identity (AGENT.md)
  ↓
Load Skills (domain expertise)
  ↓
Load State (current context)
  ↓
Load Playbooks (proven patterns)
  ↓
Receive Trigger (schedule or message)
  ↓
Execute Task
  ↓
Update State
  ↓
Emit Events/Markers
  ↓
Next Agent Reads Events
```

### Key Files
- **AGENT.md** — Identity, instructions, standing orders
- **skills/** — Domain expertise files
- **playbooks/** — Proven patterns with real results
- **state/CONTEXT.md** — Current situation, decisions, learning
- **intelligence/** — Research dumps, external data

### Wiring Points
- **telegram.json** — Maps agent to Telegram channel
- **schedules.json** — Cron schedules for each agent
- **orchestrator.py** — Main router + loader
- **event_bus.db** — Cross-agent communication

## Building a New Agent (Checklist)
- [ ] Create agent folder
- [ ] Write AGENT.md (identity)
- [ ] Add to telegram.json + schedules.json
- [ ] Add to orchestrator.py AGENT_DISPLAY
- [ ] Create state/CONTEXT.md
- [ ] Test locally before deploying
- [ ] Wire event subscriptions if needed
"""

    @staticmethod
    def generate_best_practices_doc() -> str:
        """Generate best practices guide."""
        return """# AI Engineering Pipeline — Best Practices

## Agent Design
- **Singular Focus** — One agent, one domain. Don't combine specializations.
- **Readable AGENT.md** — Future you should understand the brief in 2 minutes.
- **State Before Response** — Always read state first. Don't assume.
- **Marker Discipline** — Use [INSIGHT:], [EVENT:], [METRIC:] consistently.

## System Health
- **No Duplication** — Check BRIEFING_DOMAINS.md before creating an agent.
- **Event Subscriptions** — Only subscribe to events you actually use.
- **State Hygiene** — Update state after decisions. Don't let it stale.
- **Testing** — Test locally before deploying to Railway.

## Debugging
- **Check Logs** — orchestrator.log shows routing issues.
- **Verify Wiring** — Did you add to telegram.json AND schedules.json?
- **Load Order** — orchestrator.py must have the agent in AGENT_DISPLAY.
- **Chat ID** — Is the Telegram group ID correct? (Start with -)

## Scaling
- **Stagger Schedules** — Don't run all agents at once.
- **Use Events** — Don't poll. Emit [EVENT:] markers instead.
- **Archive State** — Keep state files < 1MB (split old decisions into archives).
- **Monitor API Calls** — Check orchestrator.log for API usage.
"""


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    print("\n=== AI ENGINEERING PIPELINE ===")
    print("\nDocumentation:")
    print(PipelineDocumentation.generate_architecture_doc()[:500] + "...")
    print(
        "\nBest Practices:",
        PipelineDocumentation.generate_best_practices_doc()[:500] + "...",
    )
