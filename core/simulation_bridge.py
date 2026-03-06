"""
Market Simulator — Simulation Bridge

Bridges the conversational config (gathered by the conversation engine) to the
actual simulation pipeline (persona generation → interviews → analysis → report).

This module handles:
  - Converting the conversational JSON config into a full YAML config
  - Running the world model research
  - Orchestrating the full simulation pipeline
  - Streaming progress updates back to the calling interface
"""
import os
import json
import yaml
import asyncio
import logging
from typing import Dict, Any, Optional, Callable, Awaitable
from datetime import datetime

logger = logging.getLogger("market_sim.bridge")


class SimulationBridge:
    """
    Converts conversational config to simulation config and runs the pipeline.

    The bridge is interface-agnostic — it accepts a progress callback function
    that each interface (Slack, CLI, web) implements differently.
    """

    def __init__(self, base_output_dir: str = None):
        self.base_output_dir = base_output_dir or os.path.join(
            os.path.expanduser("~"), "market-simulation-agent", "output", "runs"
        )

    def build_config(self, conversational_config: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert the conversational JSON config into the full simulation config
        format expected by the engine.

        Args:
            conversational_config: The JSON config gathered from the conversation.

        Returns:
            A fully-resolved config dict ready for the simulation runner.
        """
        product_name = conversational_config.get("product_name", "Unknown Product")
        product_desc = conversational_config.get("product_description", "")
        target_market = conversational_config.get("target_market", "")
        assumptions = conversational_config.get("assumptions", [])
        questions = conversational_config.get("questions", [])
        persona_count = conversational_config.get("persona_count", 30)
        interview_turns = conversational_config.get("interview_turns", 6)

        # Build archetypes from the conversational config
        raw_archetypes = conversational_config.get("archetypes", {})
        archetypes = self._build_archetypes(raw_archetypes)

        # Create a timestamped output directory
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = "".join(c if c.isalnum() or c in "-_" else "_" for c in product_name[:50])
        run_dir = os.path.join(self.base_output_dir, f"sim_{safe_name}_{timestamp}")
        os.makedirs(run_dir, exist_ok=True)

        # Build the config dict
        config = {
            "product_name": product_name,
            "product_description": product_desc,
            "target_market": target_market,
            "assumptions": assumptions,
            "questions": questions,
            "llm_model": "gemini-2.5-flash",
            "persona_count": persona_count,
            "interview_turns": interview_turns,
            "interaction_context": "warm_demo",
            "persona_concurrency": 10,
            "interview_concurrency": 5,
            "archetypes": archetypes,
            "disposition_weights": None,  # Use defaults
            "context_dir": run_dir,
            "world_model_path": None,
            "transcripts_path": None,
            "customer_list_path": None,
            "output_dir": run_dir,
        }

        # Save the conversational config for reference
        config_path = os.path.join(run_dir, "conversational_config.json")
        with open(config_path, "w") as f:
            json.dump(conversational_config, f, indent=2)
        logger.info("Saved conversational config to: %s", config_path)

        # Also save as YAML for reference
        yaml_config = {
            "product": {
                "name": product_name,
                "description": product_desc,
                "target_market": target_market,
            },
            "assumptions": assumptions,
            "questions": questions,
            "settings": {
                "persona_count": persona_count,
                "interview_turns": interview_turns,
                "llm_model": "gemini-2.5-flash",
                "interaction_context": "warm_demo",
            },
            "archetypes": {
                k: {
                    "name": v.get("name", k),
                    "description": v.get("description", ""),
                    "behaviors": v.get("behaviors", []),
                    "buying_triggers": v.get("buying_triggers", []),
                    "common_objections": v.get("common_objections", []),
                    "skepticism_range": v.get("skepticism_range", [3, 7]),
                    "typical_weight": v.get("typical_weight", 1.0 / max(len(archetypes), 1)),
                }
                for k, v in archetypes.items()
            },
            "output_dir": "output",
        }
        yaml_path = os.path.join(run_dir, "config.yaml")
        with open(yaml_path, "w") as f:
            yaml.dump(yaml_config, f, default_flow_style=False, sort_keys=False)
        logger.info("Saved YAML config to: %s", yaml_path)

        return config

    def _build_archetypes(self, raw_archetypes: Dict[str, Any]) -> Dict[str, Any]:
        """
        Convert conversational archetypes into the full archetype format
        expected by the simulation engine.

        The conversational config may have simplified archetypes (just name,
        description, percentage). This method enriches them with the behavioral
        fields the engine needs.
        """
        from config import DEFAULT_ARCHETYPES

        if not raw_archetypes:
            logger.info("No custom archetypes provided — using defaults")
            return DEFAULT_ARCHETYPES

        archetypes = {}
        for key, archetype in raw_archetypes.items():
            # Normalize the key
            safe_key = key.lower().replace(" ", "_").replace("-", "_")

            # Get percentage and convert to weight
            pct = archetype.get("percentage", 100 / max(len(raw_archetypes), 1))
            weight = pct / 100.0

            # Determine skepticism based on archetype name/description
            name = archetype.get("name", key)
            desc = archetype.get("description", "")
            skepticism = self._infer_skepticism(name, desc)

            archetypes[safe_key] = {
                "name": name,
                "description": desc,
                "behaviors": archetype.get("behaviors", [
                    f"Evaluates products from the perspective of a {name}",
                    "Considers practical implementation challenges",
                    "Weighs cost against perceived value",
                ]),
                "buying_triggers": archetype.get("buying_triggers", [
                    "Clear ROI demonstration",
                    "Peer recommendations",
                    "Easy onboarding process",
                ]),
                "common_objections": archetype.get("common_objections", [
                    "We already have a process for this",
                    "How is this different from what we use today?",
                    "What's the implementation timeline?",
                ]),
                "skepticism_range": skepticism,
                "typical_weight": weight,
            }

        return archetypes

    def _infer_skepticism(self, name: str, description: str) -> list:
        """Infer a skepticism range based on archetype name/description."""
        combined = (name + " " + description).lower()

        # High skepticism keywords
        if any(w in combined for w in ["skeptic", "critic", "resistant", "conservative", "enterprise"]):
            return [7, 10]
        # Medium-high
        elif any(w in combined for w in ["executive", "vp", "director", "budget", "decision"]):
            return [5, 8]
        # Medium
        elif any(w in combined for w in ["manager", "lead", "team"]):
            return [4, 7]
        # Lower
        elif any(w in combined for w in ["early adopter", "innovator", "enthusiast", "champion"]):
            return [2, 5]
        # Default medium
        else:
            return [3, 7]

    async def run_simulation(
        self,
        config: Dict[str, Any],
        progress_callback: Optional[Callable[[str], Awaitable[None]]] = None,
    ) -> Dict[str, Any]:
        """
        Run the full simulation pipeline.

        Args:
            config: The fully-resolved simulation config.
            progress_callback: Async function to call with progress updates.
                Each interface implements this differently (Slack posts to channel,
                CLI prints to stdout, web pushes to websocket).

        Returns:
            A dict with the simulation results and output paths.
        """
        async def update(msg: str):
            if progress_callback:
                try:
                    await progress_callback(msg)
                except Exception as e:
                    logger.error("Progress callback failed: %s", e)
            logger.info("Progress: %s", msg)

        output_dir = config["output_dir"]
        results = {"output_dir": output_dir, "success": False}

        try:
            # Step 1: World Model
            await update(":earth_americas: *Building world model...* Researching the market landscape.")
            from engines.research_engine import ensure_world_model
            world_model = ensure_world_model(config)
            config["_generated_world_model"] = world_model
            await update(":white_check_mark: World model complete.")

            # Step 2: Persona Generation
            await update(":busts_in_silhouette: *Generating personas...* Creating realistic buyer profiles.")
            from engines.persona_engine import generate_personas
            personas = await generate_personas(config, world_model)
            if not personas:
                await update(":x: Failed to generate personas. Check the logs.")
                results["error"] = "Persona generation failed"
                return results
            await update(f":white_check_mark: Generated {len(personas)} personas.")

            # Save audience summary
            audience_path = os.path.join(output_dir, "audience_summary.md")
            self._save_audience_summary(personas, audience_path)

            # Step 3: Interviews
            await update(f":speech_balloon: *Running interviews...* Interviewing {len(personas)} personas ({config['interview_turns']} turns each).")
            from engines.interview_engine import run_interviews
            interviews = await run_interviews(config, personas)
            successful = [i for i in interviews if i]
            await update(f":white_check_mark: Completed {len(successful)}/{len(personas)} interviews.")

            # Save transcripts
            transcripts_path = os.path.join(output_dir, "transcripts.md")
            self._save_transcripts(interviews, transcripts_path)

            # Step 4: Analysis
            await update(":bar_chart: *Analyzing results...* Synthesizing insights from all interviews.")
            from engines.analysis_engine import analyze_results
            analysis = await analyze_results(config, interviews, world_model)
            await update(":white_check_mark: Analysis complete.")

            # Save analysis outputs
            if analysis.get("report"):
                report_path = os.path.join(output_dir, "report.md")
                with open(report_path, "w", encoding="utf-8") as f:
                    f.write(analysis["report"])
                results["report_path"] = report_path

            if analysis.get("quantitative"):
                quant_path = os.path.join(output_dir, "quantitative_summary.json")
                with open(quant_path, "w", encoding="utf-8") as f:
                    json.dump(analysis["quantitative"], f, indent=2)
                results["quantitative_path"] = quant_path

            if analysis.get("insights"):
                insights_path = os.path.join(output_dir, "insights.json")
                with open(insights_path, "w", encoding="utf-8") as f:
                    json.dump(analysis["insights"], f, indent=2)
                results["insights_path"] = insights_path

            results["success"] = True
            results["personas_count"] = len(personas)
            results["interviews_count"] = len(successful)
            results["transcripts_path"] = transcripts_path
            results["audience_path"] = audience_path

            await update(
                f":tada: *Simulation complete!* {len(successful)} interviews analyzed. "
                f"Generating final report..."
            )

            return results

        except Exception as e:
            logger.error("Simulation failed: %s", e, exc_info=True)
            await update(f":x: Simulation failed: {str(e)[:200]}")
            results["error"] = str(e)
            return results

    def _save_audience_summary(self, personas: list, path: str):
        """Save a summary of the generated personas."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Audience Summary\n\n")
                f.write(f"**Total Personas:** {len(personas)}\n\n")
                for i, p in enumerate(personas, 1):
                    name = p.get("name", f"Persona {i}")
                    role = p.get("role", "Unknown")
                    archetype = p.get("archetype", "Unknown")
                    f.write(f"## {i}. {name}\n")
                    f.write(f"- **Role:** {role}\n")
                    f.write(f"- **Archetype:** {archetype}\n")
                    if p.get("company"):
                        f.write(f"- **Company:** {p['company']}\n")
                    if p.get("background"):
                        f.write(f"- **Background:** {p['background'][:200]}\n")
                    f.write("\n")
        except Exception as e:
            logger.error("Failed to save audience summary: %s", e)

    def _save_transcripts(self, interviews: list, path: str):
        """Save interview transcripts to a Markdown file."""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("# Interview Transcripts\n\n")
                for i, interview in enumerate(interviews, 1):
                    if not interview:
                        continue
                    persona = interview.get("persona", {})
                    name = persona.get("name", f"Persona {i}")
                    f.write(f"---\n\n## Interview {i}: {name}\n\n")
                    for turn in interview.get("turns", []):
                        role = turn.get("role", "unknown")
                        content = turn.get("content", "")
                        if role == "interviewer":
                            f.write(f"**Interviewer:** {content}\n\n")
                        else:
                            f.write(f"**{name}:** {content}\n\n")
        except Exception as e:
            logger.error("Failed to save transcripts: %s", e)
