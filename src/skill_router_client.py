"""
Skill Router Client — HTTP client for the Skill Router service.

Talks to the Skill Router container (192.168.10.42:5099) to find relevant
skills via semantic search, then lazy-loads their SKILL.md content from disk.

Integrates with the existing SkillsManager index as a parallel enhancement:
the old full index stays, and this adds an [auto-detected relevant skills]
section with the actual content of the top-N matching skills.
"""
import logging
import os
from typing import List, Dict, Optional

import requests

logger = logging.getLogger(__name__)

SKILL_ROUTER_URL = os.getenv("SKILL_ROUTER_URL", "http://192.168.10.42:5099")
SKILL_ROUTER_ENABLED = os.getenv("SKILL_ROUTER_ENABLED", "true").lower() == "true"
SKILL_ROUTER_TIMEOUT = float(os.getenv("SKILL_ROUTER_TIMEOUT", "2.0"))

MAX_SKILL_CONTENTS = int(os.getenv("SKILL_ROUTER_MAX_SKILLS", "5"))


class SkillRouterClient:
    """Client for the Skill Router semantic search service."""

    def __init__(self, base_url: str = SKILL_ROUTER_URL):
        self.base_url = base_url.rstrip("/")
        self.enabled = SKILL_ROUTER_ENABLED
        self.timeout = SKILL_ROUTER_TIMEOUT

    def query(self, message: str, k: int = 10) -> List[Dict]:
        """
        Query the Skill Router for relevant skills.

        Args:
            message: The user's message to match against
            k: Max skills to return

        Returns:
            List of results [{name, score, preview, collection}, ...]
        """
        if not self.enabled:
            return []

        try:
            resp = requests.post(
                f"{self.base_url}/api/query",
                json={"query": message, "k": k},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()

            results = data.get("results", [])
            parsed = []
            for r in results:
                if r.get("collection") != "skills":
                    continue
                # id format: "skills:dev__add-new-route-odysseus:0"
                full_id = r.get("id", "")
                # Extract "dev__add-new-route-odysseus" from "skills:...:chunknum"
                name_part = full_id.split(":", 1)[-1] if ":" in full_id else full_id
                if ":" in name_part:
                    name_part = name_part.rsplit(":", 1)[0]
                # Split category__skill-name
                if "__" in name_part:
                    category, skill_name = name_part.split("__", 1)
                else:
                    category, skill_name = "", name_part
                parsed.append({
                    "name": skill_name,
                    "category": category,
                    "score": r.get("score", 0),
                    "preview": r.get("preview", "")[:200],
                })
            return parsed[:k]

        except requests.exceptions.ConnectionError:
            logger.debug("Skill Router unreachable — continuing without it")
            return []
        except requests.exceptions.Timeout:
            logger.debug("Skill Router timed out — continuing without it")
            return []
        except Exception as e:
            logger.debug(f"Skill Router query failed: {e}")
            return []

    def health(self) -> bool:
        """Quick health check."""
        try:
            resp = requests.get(f"{self.base_url}/health", timeout=1.0)
            return resp.status_code == 200
        except Exception:
            return False


_skill_router: Optional[SkillRouterClient] = None


def get_skill_router() -> SkillRouterClient:
    global _skill_router
    if _skill_router is None:
        _skill_router = SkillRouterClient()
    return _skill_router


def load_skill_md(name: str, category: str = "", data_dir: str = "/app/data") -> Optional[str]:
    """
    Load SKILL.md content from disk.
    
    Args:
        name: Skill name (e.g. "add-new-route-odysseus")
        category: Skill category (e.g. "dev", "system", "general")
        data_dir: Base data directory (default /app/data)
    
    Returns:
        SKILL.md content or None if not found
    """
    import os
    if category:
        path = os.path.join(data_dir, "skills", category, name, "SKILL.md")
    else:
        # Fallback: search all categories
        skills_root = os.path.join(data_dir, "skills")
        for cat in os.listdir(skills_root):
            p = os.path.join(skills_root, cat, name, "SKILL.md")
            if os.path.isfile(p):
                path = p
                break
        else:
            return None
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return None
